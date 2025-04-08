"""
This module contains the REST API client for the MCP servers.
"""
import json
import traceback
from datetime import datetime

from fastapi import FastAPI, HTTPException, Body
from typing import List, Dict, Any

from langchain_core.messages import HumanMessage, AIMessageChunk
from langgraph.graph.graph import CompiledGraph
from starlette.responses import StreamingResponse

from mcp_client.base import (
    load_server_config,
    create_server_parameters,
    convert_mcp_to_langchain_tools,
    create_agent_executor,
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
        agent_executor_rest = await create_agent_executor("rest")
        user_message = input_message.get("message", "")
        streaming = input_message.get("streaming", False)  # Check if streaming is enabled
        if not user_message:
            raise HTTPException(status_code=400, detail="Message content is required")

        input_messages = {
            "messages": [HumanMessage(content=user_message)],
            "is_last_step": True,
            "today_datetime": datetime.now().isoformat(),

        }
        if streaming is False:
            response = await query_response_without_streaming(input_messages, agent_executor_rest)
            return _process_json_response(response)
        else:
            async def event_stream():
                async for message_chunk in query_response_with_streaming(input_messages, agent_executor_rest):
                    yield message_chunk  # Stream the message chunk

            return StreamingResponse(event_stream(), media_type="text/plain",
                                     headers={"Transfer-Encoding": "chunked"})
    except Exception as e:
        error_trace = traceback.format_exc()
        print(error_trace)
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}")

def remove_json_wrappers(input_string):
    # Check if the string starts with ```json and ends with ```
    if input_string.startswith("```json") and input_string.endswith("```"):
        return input_string[7:-3].strip()  # Remove the ```json and ``` and strip leading/trailing spaces
    return input_string  # Return as-is if no ```json wrapper is found

# Helper function to process JSON responses
def _process_json_response(response_content: str) -> Any:
    response_content = remove_json_wrappers(response_content)
    return json.loads(response_content) if is_json(response_content) else response_content


# Helper function to handle single response
def _handle_single_response(output: str) -> Dict[str, Any]:
    return {"responses": _process_json_response(output)}


async def query_response_with_streaming(input_messages: Dict[str, Any], agent_executor: CompiledGraph):
    """Query the assistant for a response and stream the response."""
    try:
        async for chunk in agent_executor.astream(
                input_messages,
                stream_mode=["messages", "values"]
        ):
            # Process the chunk and append the response to the collected response

            content = process_message_chunk(chunk)

            if content:
                # Stream the content directly
                if isinstance(content, list):  # Handle multiple messages
                    for item in content:
                        message_chunk = _process_message_chunk(item)
                        # print(message_chunk)
                        yield message_chunk  # Stream the message chunk
                else:  # Handle single message
                    message_chunk = _process_message_chunk(content)
                    yield message_chunk  # Stream the message chunk
    except Exception as e:
        error_trace = traceback.format_exc()
        print(error_trace)
        print(f"Error processing messages: {e}")
        yield ""

async def query_response_without_streaming(input_messages: Dict[str, Any], agent_executor: CompiledGraph):
    """Query the assistant for a response and send a single response."""
    try:
        # Collect all chunks into a list
        collected_responses = []

        async for chunk in agent_executor.astream(
                input_messages,
                stream_mode=["messages", "values"]
        ):
            # Process the chunk and append the response to the collected response
            content = process_message_chunk(chunk)

            if content:
                if isinstance(content, list):  # Handle multiple messages
                    for item in content:
                        message_chunk = _process_message_chunk(item)
                        collected_responses.append(message_chunk.replace("\n", ""))
                else:  # Handle single message
                    message_chunk = _process_message_chunk(content)
                    collected_responses.append(message_chunk.replace("\n", ""))

        # Join all collected responses and return as a single response
        return "".join(collected_responses)

    except Exception as e:
        error_trace = traceback.format_exc()
        print(error_trace)
        print(f"Error processing messages: {e}")
        return ""


def process_message_chunk(message_chunk) -> str:
    """Process the message chunk and print the content."""
    if isinstance(message_chunk, tuple) and message_chunk[0] == "messages":
        chunk = message_chunk[1][0]
        if isinstance(chunk, AIMessageChunk):
            return chunk.content  # Get the content of the message chunk
    return ""


def _process_message_chunk(content) -> str:
    """Process the message chunk and extract plain text"""

    print("\n--- DEBUG: Raw content received in _process_message_chunk ---")
    print(content)

    def extract_plain_text(value, max_depth=5):
        """Recursively extract plain text from nested JSON strings"""
        try:
            if max_depth <= 0:
                return str(value)
            # If dict, collect all string values recursively
            if isinstance(value, dict):
                # Special case: if dict has 'joke' key, return it directly
                if 'joke' in value:
                    return extract_plain_text(value['joke'], max_depth - 1)
                # Otherwise, concatenate all values
                texts = []
                for v in value.values():
                    texts.append(extract_plain_text(v, max_depth - 1))
                return "\n\n".join(texts).strip()
            # If string, check if it looks like JSON
            if isinstance(value, str):
                stripped = value.strip()
                if (stripped.startswith("{") and stripped.endswith("}")) or \
                   (stripped.startswith('{"') and stripped.endswith("}")):
                    import json
                    try:
                        data = json.loads(stripped)
                        return extract_plain_text(data, max_depth - 1)
                    except Exception:
                        return value  # Not valid JSON, return as is
                else:
                    return value
            # If bytes, decode
            if isinstance(value, bytes):
                return value.decode('utf-8', errors='ignore')
            # Else, convert to string
            return str(value)
        except Exception:
            return str(value)

    try:
        # First extraction
        text = None
        if isinstance(content, dict) and 'text' in content:
            text = extract_plain_text(content['text'])
        else:
            text = extract_plain_text(content)

        # Additional flattening: if still JSON-like, parse again
        import json
        for _ in range(3):  # up to 3 extra attempts
            stripped = text.strip()
            if (stripped.startswith("{") and stripped.endswith("}")) or \
               (stripped.startswith('{"') and stripped.endswith("}")):
                try:
                    data = json.loads(stripped)
                    # Special case: if dict has 'joke' key, extract it
                    if isinstance(data, dict) and 'joke' in data:
                        text = extract_plain_text(data['joke'])
                        break
                    else:
                        text = extract_plain_text(data)
                except Exception:
                    break  # not valid JSON, stop
            else:
                break  # plain text, stop

        print("--- DEBUG: Final extracted text ---")
        print(text)
        return text
    except Exception:
        return str(content)
