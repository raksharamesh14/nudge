

from langchain_core.tools import tool  # Import tool decorator
from langchain_mongodb.vectorstores import (
    MongoDBAtlasVectorSearch,
)  # Import necessary class
#from langchain_voyageai import VoyageAIEmbeddings
from langchain_openai import OpenAIEmbeddings
from langgraph.store.mongodb.base import (
    MongoDBStore,
    VectorIndexConfig,
)  # Import MongoDBStore

from dotenv import load_dotenv
from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.prebuilt import create_react_agent
from langmem import create_manage_memory_tool
from openai import OpenAI
# from pymongo import MongoClient

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

from loguru import logger
import os

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

#logger.debug(f"Connecting to: {MONGODB_URI}")

# Create a new client and connect to the server
client = MongoClient(MONGODB_URI, server_api=ServerApi('1'))
# Send a ping to confirm a successful connection
try:
    client.admin.command('ping')
    logger.info("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    logger.error(e)

# client = MongoClient(MONGODB_URI)


db = client["memories"]
collection = db["memory_store"]

logger.info("Creating store..")
# Create store directly
store = MongoDBStore(
    collection=collection,
    index_config=VectorIndexConfig(
        fields=None,
        filters=None,
        dims=1536,
        embed=OpenAIEmbeddings(
            model="text-embedding-3-small"
        ),  # Pass an instance of OpenAIEmbeddings
    ),
    auto_index_timeout=70,
)

checkpointer = MongoDBSaver(
    client, db_name="memories", collection_name="thread_checkpoints"
)

def prompt(state, store):
    """Prepare the messages for the LLM by injecting memories."""
    memories = store.search(
        ("memories",),
        query=state["messages"][-1].content,
    )
    logger.info(f"Memories: {memories}")
    system_msg = f"""You are a helpful assistant that has access to memory

## Memories

<memories>
{memories}
</memories>

"""
    return [{"role": "system", "content": system_msg}, *state["messages"]]


# 3. Create the agent with the memory tool
agent = create_react_agent(
    "openai:gpt-4o-mini",
    prompt=lambda state: prompt(state, store),  # Pass the store to the prompt function
    tools=[
        create_manage_memory_tool(namespace=("memories",)),
    ],
    store=store,
    checkpointer=checkpointer,
)


config = {"configurable": {"thread_id": "thread-a"}}

response = agent.invoke(
    {
        "messages": [
            {
                "role": "user",
                "content": "Remember I am vegan. I like beaches and dancing. Once I went to Rome and loved the food!"
            }
        ]
    },
    config=config,
)
logger.info("Response 1: " + response["messages"][-1].content)


response = agent.invoke(
    {
        "messages": [
            {"role": "user", "content": "Help me plan a trip aligned with what I like."}
        ]
    },
    config=config,
)
logger.info("Response 2: " + response["messages"][-1].content)