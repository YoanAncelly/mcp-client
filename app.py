"""
This module contains the REST API client for the MCP servers.
"""
from fastapi import FastAPI, HTTPException, Body
from datetime import datetime
from typing import List, Dict, Any
from langchain_core.messages import HumanMessage, AIMessageChunk, AIMessage
from langgraph.graph.graph import CompiledGraph

from mcp_client.base import (
    load_server_config,
    create_server_parameters,
    convert_mcp_to_langchain_tools,
    initialise_tools
)

app = FastAPI()

@app.get("/tools")
async def list_tools() -> List[str]:
    """List available tools from the server."""
    try:
        server_config = load_server_config()
        server_params = create_server_parameters(server_config)
        langchain_tools = await convert_mcp_to_langchain_tools(server_params)
        return [tool.name for tool in langchain_tools]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching tools: {str(e)}")


@app.post("/chat")
async def handle_chat(input_message: Dict[str, Any] = Body(...)):
    """Handle chat messages."""
    try:
        langchain_tools = await initialise_tools()
        user_message = input_message.get("message", "")
        if not user_message:
            raise HTTPException(status_code=400, detail="Message content is required")

        input_messages = {
            "messages": [HumanMessage(content=user_message)],
            "today_datetime": datetime.now().isoformat(),
        }
        response = await query_response(input_messages, langchain_tools)
        # Just return the last message content, not the entire response,
        # please change this if you want to stream the response to UI
        if response.get("responses") and len(response.get("responses")) > 0:
            # Get the last message content
            last_element = response.get("responses")[-1]
            # Return the content of the last message
            return last_element["message"].content

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}")


async def query_response(input_messages: Dict[str, Any], agent_executor: CompiledGraph) -> Dict[str, Any]:
    """Processes responses asynchronously for given input messages using an agent executor."""
    try:
        responses = []
        async for chunk in agent_executor.astream(
                input_messages,
                stream_mode=["messages", "values"]
        ):
            message = process_chunk(chunk)
            # Only process tool calls, not other types of messages
            # please change this if you want to stream the response to UI
            if message["type"] in ("unknown_tool_call", "tool_calls"):
                responses.append(process_chunk(chunk))
        return {"responses": responses}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error querying response: {str(e)}")


def process_chunk(chunk):
    """Process a data chunk."""
    if isinstance(chunk, tuple) and chunk[0] == "messages":
        return process_message_chunk(chunk[1][0])
    elif isinstance(chunk, dict) and "messages" in chunk:
        return {"type": "final", "message": "Final chunk processed"}
    elif isinstance(chunk, tuple) and chunk[0] == "values":
        return process_tool_calls(chunk[1]['messages'][-1])
    return {"type": "unknown", "chunk": chunk}


def process_message_chunk(message_chunk):
    """Process a message chunk."""
    if isinstance(message_chunk, AIMessageChunk):
        return {"type": "message_chunk", "content": message_chunk.content}
    return {"type": "unknown_message_chunk", "chunk": message_chunk}


def process_tool_calls(message):
    """Process tool calls."""
    if isinstance(message, AIMessage) and message.tool_calls:
        return {"type": "tool_calls", "tool_calls": message.tool_calls}
    return {"type": "unknown_tool_call", "message": message}


@app.get("/")
def root():
    return {"message": "Welcome to the MCP REST API"}
