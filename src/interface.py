"""PipeCat integration with LangGraph orchestrator.

This module implements a custom FrameProcessor following PipeCat's official documentation
patterns for handling frames and streaming responses through our memory-enhanced system.
"""

import uuid
from typing import Dict

from loguru import logger

from graph import Graph

from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.frames.frames import (
    Frame, 
    TextFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame
)

class Processor(FrameProcessor):
    """Custom FrameProcessor that integrates LangGraph memory management with PipeCat pipeline.
    
    This processor follows PipeCat's official documentation patterns for custom frame processors.
    It handles LLM message frames and streams responses using our MongoDB-backed memory system.
    """

    def __init__(self, user_id: str = "test_user", session_id: str = "test_session", **kwargs):
        super().__init__(**kwargs)
        self.graph = Graph(default_user_id=user_id, default_session_id=session_id)
        self._session_id = session_id
        self._user_id = user_id
        logger.info(f"Initialized LangGraph processor with user_id: {self._user_id}, session_id: {self._session_id}")
        
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # call parent class process_frame
        await super().process_frame(frame, direction) 
        
        # Handle text frames from STT - custom logic to handle LLM response through langgraph nodes
        if isinstance(frame, TextFrame) and direction == FrameDirection.DOWNSTREAM:
            logger.info(f"Processing text frame: {frame.text}")
            # Signal response start
            await self.push_frame(LLMFullResponseStartFrame(), direction)
            # Stream response through our memory-enhanced graph
            await self._stream_langgraph_response(frame.text, direction)
            # Signal response end  
            await self.push_frame(LLMFullResponseEndFrame(), direction)
            # Don't forward the original TextFrame since we handled it
            return
        
        # Forward all other frames through the pipeline
        await self.push_frame(frame, direction)
    
    async def _stream_langgraph_response(self, message: str, direction: FrameDirection):
        """Stream response from LangGraph with proper error handling."""
        token_buffer = ""
        
        try:
            # Stream response through our memory-enhanced graph
            async for token in self.graph.stream_message(
                message=message,
                session_id=self._session_id,
                user_id=self._user_id
            ):
                token_buffer += token
                
                # Send chunks when we have complete words/phrases for better TTS
                if token_buffer.endswith((' ', '.', '!', '?', ',', '\n')) or len(token_buffer) > 50:
                    if token_buffer.strip():
                        logger.debug(f"Streaming text chunk: {token_buffer.strip()}")
                        await self.push_frame(TextFrame(text=token_buffer.strip()), direction)
                        token_buffer = ""
                        
            # Send any remaining content
            if token_buffer.strip():
                logger.debug(f"Final text chunk: {token_buffer.strip()}")
                await self.push_frame(TextFrame(text=token_buffer.strip()), direction)
                
        except Exception as e:
            logger.error(f"Error in LangGraph streaming: {e}")
            
            # Fallback to non-streaming response
            try:
                logger.info(f"Fallback processing (non-streaming): {message}")
                response = await self.graph.process_message(
                    message=message,
                    session_id=self._session_id,
                    user_id=self._user_id
                )
                await self.push_frame(TextFrame(text=response), direction)
            except Exception as fallback_e:
                logger.error(f"Fallback processing also failed: {fallback_e}")
                await self.push_frame(
                    TextFrame(text="I'm experiencing technical difficulties. Please try again."), 
                    direction
                )
    
    def set_user_id(self, user_id: str):
        """Update the user ID for this processor."""
        self._user_id = user_id
        logger.info(f"Updated user_id to: {user_id}")
    
    def get_session_info(self) -> Dict[str, str]:
        """Get current session information."""
        return {
            "user_id": self._user_id,
            "session_id": self._session_id
        }