"""Pipecat Voice bot with multi-transport support.

This bot supports multiple transport layers:
- WebRTC for direct browser clients
- Daily for production video/audio rooms  
- WebSocket for telephony (Twilio)

Required AI services:
- Deepgram (Speech-to-Text)
- OpenAI (LLM)
- Cartesia (Text-to-Speech)

Run the bot using:
    For browser client:
        uv run bot.py
    For Daily rooms:
        uv run bot.py -t daily
    For Twilio:
        uv run bot.py -t twilio -x your_ngrok.ngrok.io
"""

import os
import aiohttp
from dotenv import load_dotenv
from loguru import logger
from typing import Optional
import time
import uuid

from pipecat.runner.types import RunnerArguments, SmallWebRTCRunnerArguments, DailyRunnerArguments
from pipecat.runner.utils import create_transport, parse_telephony_websocket
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.network.small_webrtc import SmallWebRTCTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
from pipecat.transports.daily.transport import DailyTransport, DailyParams
from pipecat.transports.daily.utils import DailyRESTHelper, DailyRoomParams, DailyRoomProperties
from pipecat.serializers.twilio import TwilioFrameSerializer

from pipeline import NudgePipeline, get_transport_params

load_dotenv(override=True)

print("🚀 Starting Pipecat bot...")


async def create_webrtc_transport(args: SmallWebRTCRunnerArguments) -> Optional[BaseTransport]:
    """Create WebRTC transport for browser clients."""
    transport_params = get_transport_params()
    return SmallWebRTCTransport(
        webrtc_connection=args.webrtc_connection,
        params=transport_params
    )

async def create_twilio_transport(args: RunnerArguments) -> Optional[BaseTransport]:
    """Create WebSocket transport for Twilio telephony."""
    transport_type, call_data = await parse_telephony_websocket(args.websocket)
    logger.info(f"Auto-detected transport: {transport_type}")

    # Create Twilio-specific serializer
    serializer = TwilioFrameSerializer(
        stream_sid=call_data["stream_id"],
        call_sid=call_data["call_id"],
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
    )

    vad_analyzer = get_transport_params().vad_analyzer
    # Configure WebSocket transport with Twilio parameters
    return FastAPIWebsocketTransport(
        websocket=args.websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=vad_analyzer,  # Reuse VAD config
            serializer=serializer,
        ),
    )

async def create_daily_room_and_token() -> tuple[str, str, str]:
    """Create a new Daily room and return room_url, token, and room_name."""
    async with aiohttp.ClientSession() as session:
        daily_helper = DailyRESTHelper(
            daily_api_key=os.getenv("DAILY_API_KEY"),
            daily_api_url=os.getenv("DAILY_API_URL", "https://api.daily.co/v1"),
            aiohttp_session=session
        )
        
        # Create room optimized for 1:1 voice-only sessions (5-minute limit)
        room_params = DailyRoomParams(
            privacy="public",
            properties=DailyRoomProperties(
                exp=time.time() + (5 * 60),  # 5 minutes from now
                eject_at_room_exp=True,  # Remove participants when room expires
                max_participants=2,  # 1:1 session (user + bot)
                enable_chat=False,  # Voice-only, no text chat
                enable_prejoin_ui=False,  # Direct join
                start_video_off=True,  # Audio-only bot
                start_audio_off=False,  # Audio should be on
                enable_recording=None,  # No recording needed
                enable_transcription_storage=False,  # Using Deepgram instead
                enable_emoji_reactions=False,  # No visual elements
                geo="us-east-1"  # Optimize for your primary user base
            )
        )
        
        # Create the room
        room = await daily_helper.create_room(room_params)
        logger.info(f"Created Daily room: {room.name} (expires in 5 minutes for 1:1 session)")
        
        # Get a token for the bot (5-minute session)
        token = await daily_helper.get_token(room.url, expiry_time=5 * 60)  # 5 minutes
        
        return room.url, token, room.name

async def delete_daily_room(room_name: str) -> bool:
    """Delete a Daily room by name."""
    async with aiohttp.ClientSession() as session:
        daily_helper = DailyRESTHelper(
            daily_api_key=os.getenv("DAILY_API_KEY"),
            daily_api_url=os.getenv("DAILY_API_URL", "https://api.daily.co/v1"),
            aiohttp_session=session
        )
        
        try:
            await daily_helper.delete_room_by_name(room_name)
            logger.info(f"Successfully deleted Daily room: {room_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete Daily room {room_name}: {e}")
            return False

async def create_daily_transport(args: DailyRunnerArguments) -> Optional[BaseTransport]:
    """Create Daily transport for Daily clients."""
    transport_params = get_transport_params()
    
    # Create Daily-specific parameters optimized for 1:1 voice sessions
    daily_params = DailyParams(
        api_url=os.getenv("DAILY_API_URL", "https://api.daily.co/v1"),
        api_key=os.getenv("DAILY_API_KEY", ""),
        audio_in_enabled=transport_params.audio_in_enabled,
        audio_out_enabled=transport_params.audio_out_enabled,
        vad_analyzer=transport_params.vad_analyzer,
        turn_analyzer=transport_params.turn_analyzer,
        transcription_enabled=False,  # We handle transcription separately with Deepgram
        camera_out_enabled=False,     # Audio-only bot - no video
        microphone_out_enabled=True,  # Bot needs to speak
        audio_in_user_tracks=False    # Single audio stream for 1:1 session
    )
    
    return DailyTransport(
        room_url=args.room_url,
        token=args.token,
        bot_name="Nudge",
        params=daily_params
    )


async def bot(runner_args: RunnerArguments):
    """Main bot entry point supporting multiple transport types."""
    transport = None
    sample_rates = (16000, 16000)  # Default for WebRTC
    user_id = None
    room_name = None  # Track room name for cleanup
    
    # Extract user_id and session_id from runner_args if available
    session_id = None
    if hasattr(runner_args, 'body') and runner_args.body:
        user_id = runner_args.body.get('user_id')
        session_id = runner_args.body.get('session_id')
        logger.info(f"Extracted from runner_args - user_id: {user_id}, session_id: {session_id}")

    # If no session_id provided, generate a unique one
    if not session_id:
        session_id = f"session_{uuid.uuid4().hex[:8]}"
        logger.info(f"Generated session_id: {session_id}")

    try:
        # Select transport based on runner arguments type
        if isinstance(runner_args, SmallWebRTCRunnerArguments):
            transport = await create_webrtc_transport(runner_args)
        elif isinstance(runner_args, DailyRunnerArguments):
            # For Daily, we need to create a room first if it doesn't exist
            if not runner_args.room_url or not runner_args.token:
                logger.info("Creating new Daily room for session")
                room_url, token, room_name = await create_daily_room_and_token()
                # Update runner_args with the new room info
                runner_args.room_url = room_url
                runner_args.token = token
            else:
                # Extract room name from existing URL for cleanup
                from urllib.parse import urlparse
                room_name = urlparse(runner_args.room_url).path[1:]
                
            transport = await create_daily_transport(runner_args)
            # Use 16kHz for Silero VAD compatibility (Silero only supports 8kHz or 16kHz)
            # Daily transport will handle resampling internally as needed
            sample_rates = (16000, 16000)
        elif hasattr(runner_args, 'websocket'):  # Telephony WebSocket
            transport = await create_twilio_transport(runner_args)
            sample_rates = (8000, 8000)  # Twilio uses 8kHz
        else:
            logger.error(f"Unsupported runner arguments type: {type(runner_args)}")
            return

        if transport is None:
            logger.error("Failed to create transport")
            return

        # Initialize and run pipeline with appropriate sample rates, user_id, and session_id
        pipeline = NudgePipeline(
            transport,
            user_id=user_id,
            session_id=session_id,
            room_name=room_name,  # Pass room name for cleanup
            audio_in_sample_rate=sample_rates[0],
            audio_out_sample_rate=sample_rates[1]
        )
        await pipeline.run(runner_args)
        
    except Exception as e:
        logger.error(f"Error in bot execution: {e}")
        raise
    finally:
        # Clean up Daily room if we created one
        if room_name and isinstance(runner_args, DailyRunnerArguments):
            logger.info(f"Cleaning up Daily room: {room_name}")
            await delete_daily_room(room_name)


if __name__ == "__main__":
    from pipecat.runner.run import main
    main()