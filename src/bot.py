"""Pipecat Voice bot with multi-transport support.

This bot supports both WebRTC for browser clients and WebSocket for telephony.

Required AI services:
- Deepgram (Speech-to-Text)
- OpenAI (LLM)
- Cartesia (Text-to-Speech)

Run the bot using:
    For browser client:
        uv run bot.py
    For Twilio:
        uv run bot.py -t twilio -x your_ngrok.ngrok.io
"""

import os
from dotenv import load_dotenv
from loguru import logger
from typing import Optional

from pipecat.runner.types import RunnerArguments, SmallWebRTCRunnerArguments
from pipecat.runner.utils import create_transport, parse_telephony_websocket
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.network.small_webrtc import SmallWebRTCTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
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


async def bot(runner_args: RunnerArguments):
    """Main bot entry point supporting multiple transport types."""
    transport = None
    sample_rates = (16000, 16000)  # Default for WebRTC

    # Select transport based on runner arguments type
    if isinstance(runner_args, SmallWebRTCRunnerArguments):
        transport = await create_webrtc_transport(runner_args)
    elif hasattr(runner_args, 'websocket'):  # Telephony WebSocket
        transport = await create_twilio_transport(runner_args)
        sample_rates = (8000, 8000)  # Twilio uses 8kHz
    else:
        logger.error(f"Unsupported runner arguments type: {type(runner_args)}")
        return

    if transport is None:
        logger.error("Failed to create transport")
        return

    # Initialize and run pipeline with appropriate sample rates
    pipeline = NudgePipeline(
        transport,
        audio_in_sample_rate=sample_rates[0],
        audio_out_sample_rate=sample_rates[1]
    )
    await pipeline.run(runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main
    main()