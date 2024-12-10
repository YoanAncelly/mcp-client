"""
This module contains the REST API client for the MCP servers.
"""
import json
import traceback

from fastapi import FastAPI, HTTPException, Body
from typing import List, Dict, Any

from langchain.agents import AgentExecutor
from langchain_core.messages import HumanMessage

from mcp_client.base import (
    load_server_config,
    create_server_parameters,
    convert_mcp_to_langchain_tools,
    initialise_tools
)

app = FastAPI()


@app.get("/")
def root():
    """Root endpoint."""
    return {"message": "Welcome to the MCP REST API"}


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
        langchain_tools = await initialise_tools("rest")
        user_message = input_message.get("message", "")
        if not user_message:
            raise HTTPException(status_code=400, detail="Message content is required")

        input_messages = {
            "messages": [HumanMessage(content=user_message)],
        }
        response = await query_response(input_messages, langchain_tools)
        return response
    except Exception as e:
        error_trace = traceback.format_exc()
        print(error_trace)
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}")


def is_json(string):
    try:
        json.loads(string)
        return True
    except ValueError:
        return False


async def query_response(input_messages: Dict[str, Any], agent_executor: AgentExecutor) -> Dict[str, Any]:
    """Processes responses asynchronously for given input messages using an agent executor."""
    try:
        response = await agent_executor.ainvoke(input=input_messages)
        responses: list[Any] = []
        if isinstance(response.get("output"), str):  # Single response
            if is_json(response.get("output")):
                return {"responses": json.loads(response.get("output"))}
            else:
                return {"responses": response.get("output")}
        elif isinstance(response.get("output"), list):  # Multiple responses
            for chunk in response.get("output"):
                if is_json(chunk["text"]):
                    responses.append(json.loads(chunk["text"]))
                else:
                    responses.append(chunk["text"])
            return {"responses": responses}
        else:
            return {"responses": "No response found"}
    except Exception as e:
        error_trace = traceback.format_exc()
        print(error_trace)
        raise HTTPException(status_code=500, detail=f"Error querying response: {str(e)}")
