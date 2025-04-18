import asyncio
import os
import json
from typing import Optional
from contextlib import AsyncExitStack
import asyncclick as click

from openai import OpenAI  
from dotenv import load_dotenv
 
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

 
# 加载 .env 文件，确保 API Key 受到保护
load_dotenv()
 

class MCPClient:
    def __init__(self):
        """初始化 MCP 客户端"""
        self.exit_stack = AsyncExitStack()
        self.openai_api_key = os.getenv("ZHIPU_API_KEY")
        self.base_url = os.getenv("ZHIPU_BASE_URL")
        self.model = os.getenv("ZHIPU_MODEL")
        
        if not all([self.openai_api_key, self.base_url, self.model]):
            raise ValueError("❌ 请在 .env 文件中设置所有必要的环境变量")
            
        self.client = OpenAI(api_key=self.openai_api_key, base_url=self.base_url)
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.messages = []  # 用于存储会话历史记录
 
    async def connect_to_server(self, server_script_path: str):
        """连接到 MCP 服务器并列出可用工具"""
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("服务器脚本必须是 .py 或 .js 文件")
        command = "python"if is_python else"node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path, "--transport", "stdio"],
            env=None
        )
 
        # 启动 MCP 服务器并建立通信
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
 
        await self.session.initialize()
 
        # 列出 MCP 服务器上的工具
        response = await self.session.list_tools()
        tools = response.tools
        print("\n已连接到服务器，支持以下工具:", [tool.name for tool in tools])   


    async def connect_to_sse_server(self, server_url: str):
        """使用SSE连接到 MCP 服务器并列出可用工具"""
        sse_transport = await self.exit_stack.enter_async_context(sse_client(url=server_url))
        self.sse, self.write = sse_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.sse, self.write))

        await self.session.initialize()
 
        # 列出 MCP 服务器上的工具
        response = await self.session.list_tools()
        tools = response.tools
        print("\n已连接到服务器，支持以下工具:", [tool.name for tool in tools])      
        
    async def process_query(self, query: str) -> str:
        """
        使用大模型处理查询并调用可用的 MCP 工具 (Function Calling)
        """
        # 将用户的查询添加到历史记录中
        self.messages.append({"role": "user", "content": query})
        
        # 列出可用工具
        response = await self.session.list_tools()
        available_tools = [{
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema
            }
        } for tool in response.tools]
        
        # 让模型处理查询
        response = self.client.chat.completions.create(
            model=self.model,            
            messages=self.messages,
            tools=available_tools     
        )
        
        # 处理模型的响应
        content = response.choices[0]
        while content.finish_reason == "tool_calls":
            tool_call = content.message.tool_calls[0]
            # 如果模型建议工具调用，执行它们
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            
            # 执行工具
            result = await self.session.call_tool(tool_name, tool_args)
            # print(f"\n\n[Calling tool {tool_name} with args {tool_args}]\n\n")
            
            # 将工具调用和结果添加到消息中
            # self.messages.append(content.message.model_dump())
            self.messages.append({
                "role": "tool",
                "content": result.content[0].text,
                "tool_call_id": tool_call.id,
            })
            
            # 将更新后的消息发送回模型以进一步处理
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=available_tools
            )
            content = response.choices[0]
        
        # 将模型的响应添加到历史记录中
        self.messages.append({"role": "assistant", "content": content.message.content})
        
        return content.message.content
    
    async def chat_loop(self):
        """运行交互式聊天循环"""
        print("\n🤖 MCP 客户端已启动！输入 'quit' 退出")
        self.messages = []  # 初始化会话历史记录

        while True:
            try:
                query = input("\n🙎 你: ").strip()
                if query.lower() == 'quit':
                    break
                
                response = await self.process_query(query)  # 发送用户输入到 OpenAI API
                print(f"\n🤖 AI: {response}")
 
            except Exception as e:
                print(f"\n⚠️ 发生错误: {str(e)}")
 
    async def cleanup(self):
        """清理资源"""
        await self.exit_stack.aclose()


@click.command()
@click.option("--agent", default="http://127.0.0.1:8000")
async def main(agent):
    client = MCPClient()
    try:
        # Check if agent is a file path (.py or .js) or network address
        is_file_path = agent.endswith(('.py', '.js'))
        is_network_address = agent.startswith(('http://', 'https://'))
        
        if is_file_path:
            await client.connect_to_server(agent)
        elif is_network_address:
            await client.connect_to_sse_server(f"{agent}/sse")
        else:
            raise ValueError("Agent must be either a file path (.py/.js) or a network address (http(s)://)")
            
        await client.chat_loop()
    finally:
        await client.cleanup()
 
if __name__ == "__main__":
    asyncio.run(main())