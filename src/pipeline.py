"""Shared pipeline logic for Nudge bot.

This module contains the core pipeline implementation that can be used
across different transport layers (WebRTC, Twilio, etc.).
"""

import os
import uuid
import asyncio
from typing import Dict, List, Optional

import yaml
from loguru import logger
from pipecat.frames.frames import TextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.audio.turn.smart_turn.local_smart_turn_v2 import LocalSmartTurnAnalyzerV2
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams

from interface import Processor
from pipecat.runner.types import RunnerArguments, DailyRunnerArguments
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams


def get_transport_params() -> TransportParams:
    """Get transport parameters with VAD and Smart Turn configuration."""
    
    using_turn_detection = True
    # Responsive VAD with turn detection - force 16kHz sample rate for Silero compatibility
    vad_analyzer = SileroVADAnalyzer(
                params=VADParams(
                    confidence=0.7,      # Minimum confidence for voice detection
                    start_secs=0.2,      # Time to wait before confirming speech start
                    stop_secs=0.15 if using_turn_detection else 0.6,      # Faster stop with Smart Turn
                    min_volume=0.3,      # Lower threshold to detect softer speech
                ),
                sample_rate=16000    # Force 16kHz sample rate - Silero VAD only supports 8kHz or 16kHz
    )
    
    # local models directory
    model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "smart-turn-v2")
    
    turn_analyzer = LocalSmartTurnAnalyzerV2(
        smart_turn_model_path=model_path,
        params=SmartTurnParams(
            stop_secs=1.0,
            pre_speech_ms=0.0,
            max_duration_secs=8.0
        )
    )
    return TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        vad_analyzer=vad_analyzer,
        turn_analyzer=turn_analyzer
    )

class NudgePipeline:
    """Core pipeline implementation for Nudge bot."""
    def __init__(
        self,
        transport: BaseTransport,
        user_id: str = None,
        session_id: str = None,
        room_name: Optional[str] = None,
        audio_in_sample_rate: int = 16000,
        audio_out_sample_rate: int = 16000,
    ):
        self.transport = transport
        self.user_id = user_id
        self.session_id = session_id
        self.room_name = room_name  # For Daily room cleanup
        self.audio_in_sample_rate = audio_in_sample_rate
        self.audio_out_sample_rate = audio_out_sample_rate
        #self.prompts = load_prompts()
        self._session_timeout_task = None  # Track timeout task
        
        # Initialize services
        self.stt = DeepgramSTTService(
            api_key=os.getenv("DEEPGRAM_API_KEY"),
            language="en-US",
            interim_results=True,
            smart_format=True,
            endpointing=True,
            keepalive = True
        )
        self.tts = CartesiaTTSService(
            api_key=os.getenv("CARTESIA_API_KEY"),
            #voice_id="78ab82d5-25be-4f7d-82b3-7ad64e5b85b2",  # Savannah
            voice_id="00a77add-48d5-4ef6-8157-71e5437b282d"
        )
        # Note: LLM handling is now done in the graph_processor

        # Initialize memory processor with user context
        if self.user_id is None:
            self.user_id = "anonymous_user"
        if self.session_id is None:
            self.session_id = f"session_{uuid.uuid4().hex[:8]}"
        
        self.graph_processor = Processor(user_id=self.user_id, session_id=self.session_id)

        # Initialize RTVI
        self.rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    def create_pipeline(self) -> Pipeline:
        """Create the core processing pipeline."""
        return Pipeline(
            [
                self.transport.input(),  # Transport user input
                self.rtvi,  # RTVI processor
                self.stt,  # Speech-to-Text
                self.graph_processor,  # main conversation processor logic
                self.tts,  # Text-to-Speech
                self.transport.output()  # Transport bot output
            ]
        )

    def create_task(self) -> PipelineTask:
        """Create pipeline task with appropriate parameters."""
        return PipelineTask(
            self.create_pipeline(),
            params=PipelineParams(
                allow_interruptions=True,
                audio_in_sample_rate=self.audio_in_sample_rate,
                audio_out_sample_rate=self.audio_out_sample_rate,
                enable_metrics=True,
                enable_usage_metrics=True,
                report_only_initial_ttfb=True
            ),
            observers=[RTVIObserver(self.rtvi)],
        )

    async def setup_handlers(self, task: PipelineTask, runner_args: RunnerArguments):
        """Set up event handlers for the transport based on transport type."""
        
        # Daily transport uses RTVI events for proper handshake
        if isinstance(runner_args, DailyRunnerArguments):
            await self._setup_daily_handlers(task)
        else:
            await self._setup_direct_handlers(task)
    
    async def _setup_daily_handlers(self, task: PipelineTask):
        """Set up Daily-specific RTVI event handlers."""
        
        @self.rtvi.event_handler("on_client_ready")
        async def on_client_ready(rtvi):
            logger.info("Daily client ready - starting conversation")
            await rtvi.set_bot_ready()  # Confirm readiness to client
            
            # Start 5-minute session timeout
            self._session_timeout_task = asyncio.create_task(
                self._handle_session_timeout(task, 5 * 60)  # 5 minutes
            )

        @self.transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info(f"Daily client disconnected")
            # Cancel timeout task
            if self._session_timeout_task:
                self._session_timeout_task.cancel()
            # Room cleanup is handled in bot.py finally block
            await task.cancel()
    
    async def _setup_direct_handlers(self, task: PipelineTask):
        """Set up direct connection handlers for WebRTC and telephony."""
        
        @self.transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info(f"Client connected")
            logger.info(f"SESSION ID: {self.session_id} | USER ID: {self.user_id}")
            # Wait for user speech; avoid enqueueing a greeting to prevent self-response

        @self.transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info(f"Client disconnected")
            await task.cancel()

    async def _handle_session_timeout(self, task: PipelineTask, timeout_seconds: int):
        """Handle automatic session timeout for 1:1 voice sessions."""
        try:
            await asyncio.sleep(timeout_seconds)
            logger.info(f"Session timeout reached ({timeout_seconds}s). Ending conversation gracefully.")
            
            # Send a polite goodbye message
            goodbye_message = "Our 5-minute session is ending. Thank you for chatting with me today. Take care!"
            await task.queue_frames([TextFrame(text=goodbye_message)])
            # Wait a moment for the goodbye to be spoken
            await asyncio.sleep(3)
            # End the session
            await task.cancel()
            
        except asyncio.CancelledError:
            # Timeout was cancelled (user disconnected early)
            logger.info("Session timeout cancelled (user disconnected early)")
        except Exception as e:
            logger.error(f"Error in session timeout handler: {e}")
    
    async def run(self, runner_args: RunnerArguments):
        """Run the pipeline."""
        task = self.create_task()
        await self.setup_handlers(task, runner_args)
        
        runner = PipelineRunner(
            handle_sigint=getattr(runner_args, 'handle_sigint', False)
        )
        await runner.run(task)