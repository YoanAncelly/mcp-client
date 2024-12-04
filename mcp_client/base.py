"""
This module contains the base functions and classes for the MCP client.
"""

import json
import os
from typing import List, Type, TypedDict, Annotated

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool, ToolException
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph.graph import CompiledGraph
from langgraph.graph import add_messages
from langgraph.managed import IsLastStep

from langgraph.prebuilt import create_react_agent
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from pydantic import BaseModel
from jsonschema_pydantic import jsonschema_to_pydantic
from langchain.chat_models import init_chat_model

CONFIG_FILE = 'mcp-server-config.json'


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


class AgentState(TypedDict):
    """Defines the state of the agent in terms of messages and other properties."""
    messages: Annotated[list[BaseMessage], add_messages]
    is_last_step: IsLastStep
    today_datetime: str


async def convert_mcp_to_langchain_tools(server_params: List[StdioServerParameters]) -> List[BaseTool]:
    """Convert MCP tools to LangChain tools"""
    langchain_tools = []

    for server_param in server_params:
        tools = await get_mcp_tools(server_param)
        langchain_tools.extend(tools)

    return langchain_tools


async def get_mcp_tools(server_param: StdioServerParameters) -> List[BaseTool]:
    """
    Asynchronously retrieves and converts tools from a server using specified parameters.

    Args:
        server_param (StdioServerParameters): Parameters that specify which server to connect to.

    Returns:
        List[BaseTool]: A list of tools converted into the LangChain format.

    This function establishes a connection to a specified server using the given parameters,
    initializes a session, and retrieves the list of available tools. Each tool is then
    converted to the LangChain format and added to a list, which is returned upon completion.
    """
    mcp_tools = []

    async with stdio_client(server_param) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()  # Initialize the session
            tools: types.ListToolsResult = await session.list_tools()  # Retrieve tools from the server
            # Convert each tool to LangChain format and add to list
            for tool in tools.tools:
                mcp_tools.append(create_mcp_tool(tool, server_param))

    return mcp_tools


def load_server_config() -> dict:
    """Load server configuration from available config files."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)  # Load server configuration
    raise FileNotFoundError(f"Could not find config file {CONFIG_FILE}")


def create_server_parameters(server_config: dict) -> List[StdioServerParameters]:
    """Create server parameters from the server configuration."""
    server_parameters = []
    # Iterate over each server configuration
    for config in server_config["mcpServers"].values():
        server_parameter = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env={**config.get("env", {}), "PATH": os.getenv("PATH")}
        )
        # Update environment variables from the system environment
        for key, value in server_parameter.env.items():
            # If the value is empty and the key is in the system environment
            if len(value) == 0 and key in os.environ:
                server_parameter.env.update({key: os.getenv(key)})  # Update the value with the system environment value
        # Add the server parameter to the list
        server_parameters.append(server_parameter)
    return server_parameters


def initialize_model(llm_config: dict):
    """Initialize the language model using the provided configuration."""
    return init_chat_model(
        model=llm_config.get("model", "gpt-4o-mini"),
        model_provider=llm_config.get("provider", "openai"),
        api_key=llm_config.get("api_key"),
        temperature=llm_config.get("temperature", 0)
    )


def create_chat_prompt(server_config: dict) -> ChatPromptTemplate:
    """Create chat prompt template from server configuration."""
    return ChatPromptTemplate.from_messages([
        ("system", server_config["systemPrompt"]),
        ("placeholder", "{messages}")
    ])


async def initialise_tools() -> CompiledGraph:
    """
    Initializes tools for the server.

    This asynchronous function performs the initialization of various tools and configurations required by the server. It loads the server configuration, creates server parameters, and converts them into LangChain tools. It also initializes the model and creates a chat prompt and a reactive agent executor.

    Returns:
        CompiledGraph: A compiled graph of the agent executor.
    """
    server_config = load_server_config()
    server_params = create_server_parameters(server_config)
    langchain_tools = await convert_mcp_to_langchain_tools(server_params)

    model = initialize_model(server_config.get("llm", {}))
    prompt = create_chat_prompt(server_config)

    agent_executor = create_react_agent(
        model,
        langchain_tools,
        state_schema=AgentState,
        state_modifier=prompt,
    )
    return agent_executor
