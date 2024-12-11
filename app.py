"""
This module contains the REST API client for the MCP servers.
"""
import json
import traceback

from fastapi import FastAPI, HTTPException, Body
from typing import List, Dict, Any

from langchain.agents import AgentExecutor
from langchain_core.messages import HumanMessage
from starlette.responses import StreamingResponse

from mcp_client.base import (
    load_server_config,
    create_server_parameters,
    convert_mcp_to_langchain_tools,
    initialise_tools,
    is_json
)

# Constants
HTTP_500_ERROR_MESSAGE = "Error querying response"

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
        error_trace = traceback.format_exc()
        print(error_trace)
        raise HTTPException(status_code=500, detail=f"Error fetching tools: {str(e)}")


@app.post("/chat")
async def handle_chat(input_message: Dict[str, Any] = Body(...)):
    """Handle chat messages."""
    try:
        langchain_tools = await initialise_tools("rest")
        user_message = input_message.get("message", "")
        streaming = input_message.get("streaming", False)
        if not user_message:
            raise HTTPException(status_code=400, detail="Message content is required")

        input_messages = {
            "messages": [HumanMessage(content=user_message)],
        }
        if streaming is False:
            response = await query_response_without_streaming(input_messages, langchain_tools)
            return response
        else:
            async def event_stream():
                async for message_chunk in query_response_with_streaming(input_messages, langchain_tools):
                    yield message_chunk
            return StreamingResponse(event_stream(), media_type="application/json", headers={"Transfer-Encoding": "chunked"})
    except Exception as e:
        error_trace = traceback.format_exc()
        print(error_trace)
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}")


# Helper function to process JSON responses
def _process_json_response(response_content: str) -> Any:
    return json.loads(response_content) if is_json(response_content) else response_content


# Helper function to handle single response
def _handle_single_response(output: str) -> Dict[str, Any]:
    return {"responses": _process_json_response(output)}


# Helper function to handle multiple responses
def _handle_multiple_responses(output: List[Dict[str, str]]) -> Dict[str, Any]:
    responses = []
    for response_chunk in output:
        responses.append(_process_json_response(response_chunk["text"]))
    return {"responses": responses}


# Main function
async def query_response_without_streaming(input_messages: Dict[str, Any], agent_executor: AgentExecutor) -> Dict[
    str, Any]:
    """Query the assistant for a full response without streaming."""
    try:
        # Invoke the agent executor and fetch the response
        response = await agent_executor.ainvoke(input=input_messages)
        output = response.get("output")  # Extract "output" from the response

        if isinstance(output, str):
            # Handle single response
            return _handle_single_response(output)
        elif isinstance(output, list):
            # Handle multiple responses
            return _handle_multiple_responses(output)
        else:
            # Fallback case - no response found
            return {"responses": "No response found"}
    except Exception as error:
        # Handle exceptions gracefully with an HTTP 500 error
        error_trace = traceback.format_exc()
        print(error_trace)
        raise HTTPException(status_code=500, detail=f"{HTTP_500_ERROR_MESSAGE}: {str(error)}")


async def query_response_with_streaming(input_messages: Dict[str, Any], agent_executor: AgentExecutor):
    """Query the assistant for a response and stream the response."""
    try:
        async for chunk in agent_executor.astream_events(input=input_messages, version="v2"):
            if chunk["event"] == "on_chat_model_stream":
                content = chunk["data"]["chunk"].content
                if content:
                    # Stream the content directly
                    if isinstance(content, list):  # Handle multiple messages
                        for item in content:
                            message_chunk = _process_message_chunk(item)
                            yield message_chunk
                    else:  # Handle single message
                        message_chunk = _process_message_chunk(content)
                        yield message_chunk
    except Exception as e:
        error_trace = traceback.format_exc()
        print(error_trace)
        print(f"Error processing messages: {e}")
        yield ""


def _process_message_chunk(content) -> str:
    """Process the message chunk and print the content"""
    if 'text' in content:  # Check if the content is a message
        return content['text']
    elif isinstance(content, str):  # Check if the content is a string
        return content
    return ""
