"""
This module contains the base functions and classes for the MCP client.
"""

import json
import os
from typing import List, Type, TypedDict, Annotated

from langchain.tools.base import BaseTool, ToolException
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph.graph import CompiledGraph
from langgraph.prebuilt import create_react_agent
from langchain.chat_models import init_chat_model
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from pydantic import BaseModel
from jsonschema_pydantic import jsonschema_to_pydantic
from langgraph.graph import add_messages
from langgraph.managed import IsLastStep

CONFIG_FILE = 'mcp-server-config.json'


class AgentState(TypedDict):
    """Defines the state of the agent in terms of messages and other properties."""
    messages: Annotated[list[BaseMessage], add_messages]
    is_last_step: IsLastStep
    today_datetime: str
    remaining_steps: int


def create_mcp_tool(
        tool_schema: types.Tool,
        server_params: StdioServerParameters
) -> BaseTool:
    """Create a LangChain tool from MCP tool schema.

    This function generates a new LangChain tool based on the provided MCP tool schema
    and server parameters. The tool's behavior is defined within the McpTool inner class.

    :param tool_schema: The schema of the tool to be created.
    :param server_params: The server parameters needed by the tool for operation.
    :return: An instance of a newly created mcp tool.
    """

    # Convert the input schema to a Pydantic model for validation
    input_model = jsonschema_to_pydantic(tool_schema.inputSchema)

    class McpTool(BaseTool):
        """McpTool class represents a tool that can execute operations asynchronously."""

        # Tool attributes from the schema
        name: str = tool_schema.name
        description: str = tool_schema.description
        args_schema: Type[BaseModel] = input_model
        mcp_server_params: StdioServerParameters = server_params

        def _run(self, **kwargs):
            """Synchronous execution is not supported."""
            raise NotImplementedError("Only async operations are supported")

        async def _arun(self, **kwargs):
            """Run the tool asynchronously with provided arguments."""
            async with stdio_client(self.mcp_server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()  # Initialize the session
                    result = await session.call_tool(self.name, arguments=kwargs)
                    if result.isError:
                        # Raise an exception if there is an error in the tool call
                        raise ToolException(result.content)
                    return result.content  # Return the result if no error

    return McpTool()


async def convert_mcp_to_langchain_tools(server_params: List[StdioServerParameters]) -> List[BaseTool]:
    """Convert MCP tools to LangChain tools."""
    print(f"Converting tools from {len(server_params)} server parameters")
    langchain_tools = []
    # Retrieve tools from each server and add to the list
    for i, server_param in enumerate(server_params):
        print(f"Processing server {i+1}/{len(server_params)}: {server_param.command}")
        tools = await get_mcp_tools(server_param)
        print(f"Retrieved {len(tools)} tools from server {i+1}")
        langchain_tools.extend(tools)

    print(f"Total tools converted: {len(langchain_tools)}")
    return langchain_tools


async def get_mcp_tools(server_param: StdioServerParameters) -> List[BaseTool]:
    """Asynchronously retrieves and converts tools from a server using specified parameters"""
    mcp_tools = []
    print(f"Connecting to MCP server: {server_param.command} {' '.join(server_param.args)}")

    async with stdio_client(server_param) as (read, write):
        print("Connection established, creating client session")
        async with ClientSession(read, write) as session:
            print("Initializing session...")
            await session.initialize()  # Initialize the session
            print("Retrieving tools list...")
            tools: types.ListToolsResult = await session.list_tools()  # Retrieve tools from the server
            print(f"Found {len(tools.tools)} tools available on server")
            # Convert each tool to LangChain format and add to list
            for tool in tools.tools:
                print(f"Converting tool: {tool.name}")
                mcp_tools.append(create_mcp_tool(tool, server_param))

    print(f"Completed tool conversion, returning {len(mcp_tools)} tools")
    return mcp_tools


def is_json(string):
    """Check if a string is a valid JSON."""
    try:
        json.loads(string)
        return True
    except ValueError:
        return False


def load_server_config() -> dict:
    """Load server configuration from available config files."""
    # Load server configuration from the config file
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)  # Load server configuration
    raise FileNotFoundError(f"Could not find config file {CONFIG_FILE}")


def create_server_parameters(server_config: dict) -> List[StdioServerParameters]:
    """Create server parameters from the server configuration."""
    server_parameters = []
    # Create server parameters for each server configuration
    for config in server_config["mcpServers"].values():
        server_parameter = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env={**config.get("env", {}), "PATH": os.getenv("PATH")}
        )
        # Add environment variables from the system if not provided
        for key, value in server_parameter.env.items():
            if len(value) == 0 and key in os.environ:
                server_parameter.env[key] = os.getenv(key)
        server_parameters.append(server_parameter)
    return server_parameters


def initialize_model(llm_config: dict):
    """Initialize the language model using the provided configuration."""
    api_key = llm_config.get("api_key")
    base_url = llm_config.get("base_url")
    # Initialize the language model with the provided configuration
    init_args = {
        "model": llm_config.get("model", "gpt-4o-mini"),
        "model_provider": llm_config.get("provider", "openai"),
        "temperature": llm_config.get("temperature", 0),
        "streaming": True,
    }
    # Add API key if provided
    if api_key:
        init_args["api_key"] = api_key
    # Add base URL if provided
    if base_url:
        init_args["base_url"] = base_url
    return init_chat_model(**init_args)


def create_chat_prompt(client: str, server_config: dict) -> ChatPromptTemplate:
    """Create chat prompt template from server configuration."""
    system_prompt = server_config.get("systemPrompt", "")
    if client == "rest":
        pass  # Removed JSON-only output instruction to allow natural language responses
    return ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user", "{messages}"),
        ("placeholder", "{agent_scratchpad}"),
    ])


async def create_agent_executor(client: str) -> CompiledGraph:
    """Create an agent executor for the specified client."""
    print("Loading server configuration...")
    server_config = load_server_config()  # Load server configuration
    print(f"Server config loaded: {len(server_config.keys())} keys found")
    
    print("Creating server parameters...")
    server_params = create_server_parameters(server_config)  # Create server parameters
    print(f"Server parameters created: {len(server_params)} servers configured")
    
    print("Converting MCP tools to LangChain tools...")
    langchain_tools = await convert_mcp_to_langchain_tools(server_params)  # Convert MCP tools to LangChain tools
    print(f"Converted {len(langchain_tools)} tools successfully")

    print("Initializing Model...")
    model = initialize_model(server_config.get("llm", {}))  # Initialize the language model
    print(f"Model initialized: {model.__class__.__name__}")
    
    print("Creating chat prompt...")
    prompt = create_chat_prompt(client, server_config)  # Create chat prompt template
    print(f"Prompt created for client: {client}")

    print("Building agent executor...")
    agent_executor = create_react_agent(
        model,
        langchain_tools,
        state_schema=AgentState,
        state_modifier=prompt,
    )
    print("Agent executor created successfully")

    return agent_executor
