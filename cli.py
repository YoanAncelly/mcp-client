"""
This module contains the Cli client for the MCP servers.
"""
import asyncio
import os
import sys
import traceback
from typing import Dict, Any
from langchain.agents import AgentExecutor
from langchain_core.messages import HumanMessage, AIMessage

from mcp_client.base import (
    load_server_config,
    create_server_parameters,
    convert_mcp_to_langchain_tools,
    create_agent_executor
)


async def list_tools() -> None:
    """List available tools from the server."""
    server_config = load_server_config()
    server_params = create_server_parameters(server_config)
    langchain_tools = await convert_mcp_to_langchain_tools(server_params)

    for tool in langchain_tools:
        print(f"{tool.name}")


async def handle_chat_mode():
    """Handle chat mode for the LangChain agent."""
    print("\nInitializing chat mode...")
    agent_executor_cli = await create_agent_executor("cli")
    print("\nInitialized chat mode...")

    # Maintain a chat history of messages
    chat_history = []

    # Start the chat loop
    while True:
        try:
            user_message = input("\nYou: ").strip()
            if user_message.lower() in ["exit", "quit"]:
                print("Exiting chat mode.")
                break
            if user_message.lower() in ["clear", "cls"]:
                os.system("cls" if sys.platform == "win32" else "clear")
                chat_history = []
                continue

            # Append the user's message to the chat history
            chat_history.append(HumanMessage(content=user_message))

            input_messages = {
                "messages": chat_history
            }
            # Query the assistant and get a fully formed response
            assistant_response = await query_response(input_messages, agent_executor_cli)

            # Append the assistant's response to the history
            chat_history.append(AIMessage(content=assistant_response))
        except Exception as e:
            error_trace = traceback.format_exc()
            print(error_trace)
            print(f"\nError processing message: {e}")
            continue


async def query_response(input_messages: Dict[str, Any], agent_executor: AgentExecutor) -> str:
    """Query the assistant for a response"""
    collected_response = []
    try:
        async for chunk in agent_executor.astream_events(input=input_messages, version="v2"):
            if chunk["event"] == "on_chat_model_stream":
                content = chunk["data"]["chunk"].content
                if content:
                    # Print and accumulate the content
                    if isinstance(content, list):  # Handle multiple messages
                        for item in content:
                            message_chunk = process_message_chunk(item)
                            collected_response.append(message_chunk)
                    else:  # Handle single message
                        message_chunk = process_message_chunk(content)
                        collected_response.append(message_chunk)
            elif chunk["event"] == "on_tool_start":  # Print tool start and end events
                print("--")
                print(f"Starting tool: {chunk['name']} with inputs: {chunk['data'].get('input')}")
            elif chunk["event"] == "on_tool_end":  # Print tool start and end events
                print(f"Done tool: {chunk['name']}")
                print("--")

        print("")  # Ensure a newline after the conversation ends
        return "".join(collected_response)
    except Exception as e:
        error_trace = traceback.format_exc()
        print(error_trace)
        print(f"Error processing messages: {e}")
        return ""


def process_message_chunk(content) -> str:
    """Process the message chunk and print the content"""
    if 'text' in content:  # Check if the content is a message
        print(content['text'], end="", flush=True)
        return content['text']
    elif isinstance(content, str):  # Check if the content is a string
        print(content, end="", flush=True)
        return content
    return ""


async def interactive_mode():
    """Run the CLI in interactive mode."""
    print("\nWelcome to the Interactive MCP Command-Line Tool")
    print("Type 'help' for available commands or 'chat' to start chat or 'quit' to exit")

    while True:
        try:
            command = input(">>> ").strip() # Get user input
            if not command:
                continue
            should_continue = await handle_command(command) # Handle the command
            if not should_continue:
                return
        except KeyboardInterrupt:
            print("\nUse 'quit' or 'exit' to close the program")
        except EOFError:
            break
        except Exception as e:
            print(f"\nError: {e}")


async def handle_command(command: str):
    """ Handle specific commands dynamically."""
    try:
        if command == "list-tools":
            print("\nFetching Tools List...\n")
            # Implement list-tools logic here
            await list_tools()
        elif command == "chat":
            print("\nEntering chat mode...")
            await handle_chat_mode()
            # Implement chat mode logic here
        elif command in ["quit", "exit"]:
            print("\nGoodbye!")
            return False
        elif command == "clear":
            if sys.platform == "win32":
                os.system("cls")
            else:
                os.system("clear")
        elif command == "help":
            print("\nAvailable commands:")
            print("  list-tools    - Display available tools")
            print("  chat          - Enter chat mode")
            print("  clear         - Clear the screen")
            print("  help          - Show this help message")
            print("  quit/exit     - Exit the program")
        else:
            print(f"\nUnknown command: {command}")
            print("Type 'help' for available commands")
    except Exception as e:
        print(f"\nError executing command: {e}")

    return True


def main() -> None:
    """ Entry point for the script."""


asyncio.run(interactive_mode())  # Run the main asynchronous function

if __name__ == "__main__":
    main()  # Execute the main function when script is run directly
