"""Shared pipeline logic for Nudge bot.

This module contains the core pipeline implementation that can be used
across different transport layers (WebRTC, Twilio, etc.).
"""

import os
from typing import Dict, List

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
from pipecat.runner.types import RunnerArguments
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams


def get_transport_params() -> TransportParams:
    """Get transport parameters with VAD and Smart Turn configuration."""
    
    using_turn_detection = True
    # Responsive VAD with turn detection
    vad_analyzer = SileroVADAnalyzer(
                params=VADParams(
                    confidence=0.7,      # Minimum confidence for voice detection
                    start_secs=0.2,      # Time to wait before confirming speech start
                    stop_secs=0.2 if using_turn_detection else 0.8,      # Shorter stop time when using Smart Turn
                    min_volume=0.6,      # Minimum volume threshold
                )
    )
    turn_analyzer = LocalSmartTurnAnalyzerV2(
        smart_turn_model_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "smart-turn-v2"),
        params=SmartTurnParams(
            stop_secs=2.0,
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


def load_prompts() -> Dict[str, str]:
    """Load system prompts from YAML config."""
    config_path = os.path.join(os.path.dirname(__file__), "config", "prompts.yaml")
    with open(config_path, "r") as f:
        prompts = yaml.safe_load(f)
    return prompts.get("system", {})


class NudgePipeline:
    """Core pipeline implementation for Nudge bot."""
    def __init__(
        self,
        transport: BaseTransport,
        user_id: str = None,
        audio_in_sample_rate: int = 16000,
        audio_out_sample_rate: int = 16000,
    ):
        self.transport = transport
        self.user_id = user_id
        self.audio_in_sample_rate = audio_in_sample_rate
        self.audio_out_sample_rate = audio_out_sample_rate
        self.prompts = load_prompts()
        
        # Initialize services
        self.stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))
        self.tts = CartesiaTTSService(
            api_key=os.getenv("CARTESIA_API_KEY"),
            #voice_id="78ab82d5-25be-4f7d-82b3-7ad64e5b85b2",  # Savannah
            voice_id="00a77add-48d5-4ef6-8157-71e5437b282d"
        )
        # Note: LLM handling is now done in the graph_processor

        # Initialize memory processor with user context
        self.graph_processor = Processor()

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
                report_only_initial_ttfb=True,
                # start_metadata={
                #     "conversation_id": self.graph_processor._session_id,
                #     "session_data": {
                #         "user_id": self.graph_processor._user_id,
                #         "start_time": datetime.now().isoformat()
                #     }
                # }
            ),
            observers=[RTVIObserver(self.rtvi)],
        )

    async def setup_handlers(self, task: PipelineTask):
        """Set up event handlers for the transport."""
        
        @self.transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info(f"Client connected")
            # Generate greeting directly through our memory processor
            greeting_prompt = self.prompts.get("greeting", "Say hello and introduce yourself.")
            
            # Get the processor and generate greeting response
            if hasattr(self.graph_processor, 'graph'):
                try:
                    # Generate greeting using the memory system
                    greeting_response = await self.graph_processor.graph.process_message(
                        message=greeting_prompt,
                        session_id=self.graph_processor._session_id,
                        user_id=self.graph_processor._user_id
                    )
                    # Queue the greeting response as text for TTS
                    await task.queue_frames([TextFrame(text=greeting_response)])
                except Exception as e:
                    logger.error(f"Error generating greeting: {e}")
                    # Fallback to simple greeting
                    await task.queue_frames([TextFrame(text="Hello! I'm Nudge, your reflection companion. How are you doing today?")])

        @self.transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info(f"Client disconnected")
            await task.cancel()

    async def run(self, runner_args: RunnerArguments):
        """Run the pipeline."""
        task = self.create_task()
        await self.setup_handlers(task)
        
        runner = PipelineRunner(
            handle_sigint=False
        )
        await runner.run(task)