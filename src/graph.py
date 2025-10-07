"""Memory management using Langgraph with MongoDB integration.

This module implements the memory management system using Langgraph for orchestration.
It integrates with MongoDB for persistent memory storage and retrieval.
"""


import os
from typing import AsyncGenerator, Dict, List, Optional, TypedDict

import yaml
from dotenv import load_dotenv
from typing import Annotated
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph.message import add_messages
from langchain_core.runnables.config import RunnableConfig
from langchain_openai import OpenAIEmbeddings
from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langchain_anthropic import ChatAnthropic
from langmem import ReflectionExecutor, create_memory_store_manager
from langmem import create_manage_memory_tool, create_search_memory_tool
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import create_react_agent
from langgraph.store.mongodb.base import MongoDBStore, VectorIndexConfig

from loguru import logger
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

load_dotenv()

def load_prompts() -> Dict[str, str]:
    """Load system prompts from YAML config."""
    config_path = os.path.join(os.path.dirname(__file__), "prompts", "prompts.yaml")
    with open(config_path, "r") as f:
        prompts = yaml.safe_load(f)
    return prompts.get("system", {})

class ChatState(TypedDict):
    """State maintained between conversation turns."""
    messages: Annotated[list, add_messages] # Current conversation session's messages

model = ChatAnthropic(model="claude-3-haiku-20240307", temperature=0)

class Graph:
    """Simplified memory management graph using Langgraph with MongoDB."""
    
    def __init__(self):
        # Load prompts from YAML
        self.prompts = load_prompts()
        logger.info("Initializing global Graph instance")
        
        # # Create MongoDB store for vector search
        use_mongodb = os.getenv("USE_MONGODB", "true").lower() == "true"
        if use_mongodb:
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
            
            ##Setup database and collections
            self.db = self.client["memories"]
            self.collection = self.db["memory_store"]
            
            ##Create checkpointer for conversation state
            self.checkpointer = MongoDBSaver(
                self.client, 
                db_name="memories", 
                collection_name="thread_checkpoints"
            )
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

        else:
            self.checkpointer = MemorySaver()
            self.store = InMemoryStore(
                index={
                    "dims": 1536,
                    "embed": "openai:text-embedding-3-small"
                }
            )

        # Initialize LangMem tools for autonomous memory management/search
        namespace = ("memories", "{user_id}")
        self.manage_memory_tool = create_manage_memory_tool(
            namespace=namespace,
            store=self.store,
        )
        self.search_memory_tool = create_search_memory_tool(
            namespace=namespace,
            store=self.store,
        )

        
    def get_agent(self, user_id: str):
        """Create a react agent with the memory tools"""
        return create_react_agent(
                #"openai:gpt-4o-mini",
                "anthropic:claude-3-haiku-20240307",
                prompt=self._create_prompt,
                tools=[self.manage_memory_tool, self.search_memory_tool],
                store=self.store,
                checkpointer=self.checkpointer,
            )
        
    def _create_prompt(self, state, config: RunnableConfig):
        """Create prompt with memory injection from vector store."""
        prompt = self.prompts.get("draft_2", "")
        messages = [SystemMessage(content=prompt)] + state["messages"]
        return messages

    async def process_message(self, message: str, session_id: str, user_id: str) -> str:
        """Process a message through the simplified memory graph.
        
        Args:
            message: The user's input message
            session_id: Unique identifier for the conversation session
            user_id: Unique identifier for the user
            
        Returns:
            The system's response
        """
        logger.info(f"Processing message with user_id: {user_id}, session_id: {session_id}")
        # Include user_id in config for proper memory isolation
        config = {"configurable": {"thread_id": session_id, "user_id": user_id}}
        
        try:
            # Get user-specific agent for isolated memory operations
            agent = self.get_agent(user_id)
            
            # Invoke the agent with the user message, including user_id for memory isolation
            response = agent.invoke(
                {"messages": [HumanMessage(content=message)]},
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

    async def stream_message(self, message: str, session_id: str, user_id: str) -> AsyncGenerator[str, None]:
        """Stream a message response through the memory graph.
        
        Args:
            message: The user's input message
            session_id: Unique identifier for the conversation session
            user_id: Unique identifier for the user
            
        Yields:
            Token chunks from the LLM response
        """
        logger.info(f"Streaming message with user_id: {user_id}, session_id: {session_id}")
        config = {"configurable": {"thread_id": session_id, "user_id": user_id}}
        
        try:
            # Get user-specific agent for isolated memory operations
            agent = self.get_agent(user_id)
            
            # Stream the agent response with user_id for memory isolation
            async for chunk in agent.astream(
                {"messages": [HumanMessage(content=message)]},
                config=config,
            ):
                logger.info(f"Streaming response: {chunk}")
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
                            
                        # Suppress assistant text when a tool_use is present in the same chunk
                        if isinstance(content, list):
                            has_tool_use = any(
                                isinstance(part, dict) and part.get('type') == 'tool_use'
                                for part in content
                            )
                            if has_tool_use:
                                # Do not yield any text yet; wait for tool result and next agent message
                                continue

                        if content:
                            logger.info(f"Extracted content: {content}")
                            yield content
                        
        except Exception as e:
            logger.error(f"Error streaming message: {e}")
            yield "I'm experiencing some technical difficulties. Please try again."


# Global Graph instance
_graph_instance: Optional[Graph] = None

def get_graph() -> Graph:
    """Get the global Graph instance, initializing it if needed."""
    global _graph_instance
    if _graph_instance is None:
        logger.info("Initializing global Graph instance")
        _graph_instance = Graph()
        logger.info("Global Graph instance initialized successfully")
    return _graph_instance


if __name__ == "__main__":
    import asyncio

    async def _run():
        graph = get_graph()
        session_id = "2"
        user_id = "1"
        while True:
            message = input("Enter a message: ")
            if message == "exit":
                break
            logger.info(f"Processing message: {message}")
            async for chunk in graph.stream_message(message, session_id, user_id):
                logger.info(f"RESPONSE: {chunk}")
            print()

    asyncio.run(_run())