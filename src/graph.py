"""Memory management using Langgraph with MongoDB integration.

This module implements the memory management system using Langgraph for orchestration.
It integrates with MongoDB for persistent memory storage and retrieval.
"""

import os
from typing import AsyncGenerator, Dict, List, TypedDict

import yaml
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import OpenAIEmbeddings
from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent
from langgraph.store.mongodb.base import MongoDBStore, VectorIndexConfig
from langmem import create_manage_memory_tool
from loguru import logger
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

load_dotenv()


def load_prompts() -> Dict[str, str]:
    """Load system prompts from YAML config."""
    config_path = os.path.join(os.path.dirname(__file__), "config", "prompts.yaml")
    with open(config_path, "r") as f:
        prompts = yaml.safe_load(f)
    return prompts.get("system", {})


class ChatState(TypedDict):
    """State maintained between conversation turns."""
    messages: List[Dict]  # Current conversation session's messages
    current_input: str    # Latest user input
    current_output: str   # Latest system output
    session_id: str      # Unique session identifier
    user_id: str         # Unique user identifier


class Graph:
    """Simplified memory management graph using Langgraph with MongoDB."""
    
    def __init__(self, default_user_id: str = "test_user", default_session_id: str = "test_session"):
        # Load prompts from YAML
        self.prompts = load_prompts()
        
        # Set default IDs for testing
        self.default_user_id = default_user_id
        self.default_session_id = default_session_id
        logger.info(f"Initialized Graph with default user_id: {default_user_id}, session_id: {default_session_id}")
        
        # Initialize MongoDB connection
        self.mongodb_uri = os.getenv("MONGODB_URI")
        if not self.mongodb_uri:
            raise ValueError("MONGODB_URI environment variable is required")
            
        self.client = MongoClient(self.mongodb_uri, server_api=ServerApi('1'))
        
        # Test connection
        try:
            self.client.admin.command('ping')
            logger.info("Successfully connected to MongoDB!")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
        
        # Setup database and collections
        self.db = self.client["memories"]
        self.collection = self.db["memory_store"]
        
        # Create MongoDB store for vector search
        self.store = MongoDBStore(
            collection=self.collection,
            index_config=VectorIndexConfig(
                fields=None,
                filters=None,
                dims=1536,
                embed=OpenAIEmbeddings(model="text-embedding-3-small"),
            ),
            auto_index_timeout=70,
        )
        
        # Create checkpointer for conversation state
        self.checkpointer = MongoDBSaver(
            self.client, 
            db_name="memories", 
            collection_name="thread_checkpoints"
        )
        
        # Create the agent with memory tool
        self.agent = create_react_agent(
            "openai:gpt-4o-mini",
            prompt=self._create_prompt,
            tools=[create_manage_memory_tool(namespace=("memories",))],
            store=self.store,
            checkpointer=self.checkpointer,
        )
        
    def _create_prompt(self, state):
        """Create prompt with memory injection from vector store."""
        # Get the latest user message for memory search
        latest_message = state["messages"][-1] if state["messages"] else None
        
        memories = ""
        if latest_message:
            # Handle both dict and object message formats
            query_text = ""
            if isinstance(latest_message, dict):
                query_text = latest_message.get("content", "")
            elif hasattr(latest_message, 'content'):
                query_text = latest_message.content
            
            if query_text:
                # Search for relevant memories
                memory_results = self.store.search(
                    ("memories",),
                    query=query_text,
                )
                logger.info(f"Found {len(memory_results)} relevant memories")
                
                if memory_results:
                    memories = "\n".join([str(memory) for memory in memory_results])
        
        # Use the memory_enhanced prompt template from YAML
        system_msg = self.prompts.get("memory_enhanced", "").format(memories=memories)
        logger.info(f"System message: {system_msg}")
        return [{"role": "system", "content": system_msg}, *state["messages"]]

    async def process_message(self, message: str, session_id: str = None, user_id: str = None) -> str:
        """Process a message through the simplified memory graph.
        
        Args:
            message: The user's input message
            session_id: Unique identifier for the conversation session (optional, uses default if None)
            user_id: Unique identifier for the user (optional, uses default if None)
            
        Returns:
            The system's response
        """
        # Use default IDs if not provided
        if user_id is None:
            user_id = self.default_user_id
        if session_id is None:
            session_id = self.default_session_id
        
        logger.info(f"Processing message with user_id: {user_id}, session_id: {session_id}")
            
        # Create thread ID that combines user and session for proper isolation
        thread_id = f"{user_id}_{session_id}"
        
        config = {"configurable": {"thread_id": thread_id}}
        
        try:
            # Invoke the agent with the user message
            response = self.agent.invoke(
                {"messages": [{"role": "user", "content": message}]},
                config=config,
            )
            
            # Extract the response content
            if response and "messages" in response and response["messages"]:
                logger.info(f"Response: {response['messages'][-1].content}")
                return response["messages"][-1].content
            else:
                logger.warning("No response generated from agent")
                return "I'm sorry, I didn't understand that. Could you please rephrase?"
                
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return "I'm experiencing some technical difficulties. Please try again."

    async def stream_message(self, message: str, session_id: str = None, user_id: str = None) -> AsyncGenerator[str, None]:
        """Stream a message response through the memory graph.
        
        Args:
            message: The user's input message
            session_id: Unique identifier for the conversation session (optional, uses default if None)
            user_id: Unique identifier for the user (optional, uses default if None)
            
        Yields:
            Token chunks from the LLM response
        """
        # Use default IDs if not provided
        if user_id is None:
            user_id = self.default_user_id
        if session_id is None:
            session_id = self.default_session_id
            
        logger.info(f"Streaming message with user_id: {user_id}, session_id: {session_id}")
            
        # Create thread ID that combines user and session for proper isolation
        thread_id = f"{user_id}_{session_id}"
        
        config = {"configurable": {"thread_id": thread_id}}
        
        try:
            # Stream the agent response
            async for chunk in self.agent.astream(
                {"messages": [{"role": "user", "content": message}]},
                config=config,
            ):
                logger.info(f"Streaming chunk: {chunk}")
                # Extract content from streaming chunks
                if "agent" in chunk and "messages" in chunk["agent"]:
                    messages = chunk["agent"]["messages"]
                    if messages:
                        last_message = messages[-1]
                        content = None
                        
                        # Handle different message formats
                        if hasattr(last_message, 'content'):
                            content = last_message.content
                        elif isinstance(last_message, dict) and last_message.get('content'):
                            content = last_message['content']
                            
                        if content:
                            logger.info(f"Extracted content: {content}")
                            yield content
                        
        except Exception as e:
            logger.error(f"Error streaming message: {e}")
            yield "I'm experiencing some technical difficulties. Please try again."
