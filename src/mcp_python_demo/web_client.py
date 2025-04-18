import streamlit as st
import asyncio
from client import MCPClient
import nest_asyncio
import anyio

# 启用嵌套事件循环支持
nest_asyncio.apply()

def get_event_loop():
    """获取或创建事件循环"""
    if not hasattr(st.session_state, 'event_loop'):
        st.session_state.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(st.session_state.event_loop)
    return st.session_state.event_loop

async def safe_cleanup(client):
    """安全地清理客户端资源"""
    try:
        await client.cleanup()
    except RuntimeError as e:
        if "Attempted to exit cancel scope" in str(e):
            # 如果是SSE客户端，需要特殊处理
            if hasattr(client, 'exit_stack'):
                for cm in client.exit_stack._exit_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(cm[1].__call__):
                            await cm[1](None, None, None)
                    except Exception:
                        pass
    except Exception as e:
        print(f"Cleanup error: {e}")

def main():
    st.set_page_config(page_title="MCP Client Web UI", page_icon="🤖", layout="wide")
    st.title("🤖 MCP Client Web Interface")
    
    # 侧边栏配置
    with st.sidebar:
        st.header("配置")
        agent = st.text_input("Agent URL/Path", value="http://127.0.0.1:8000")
        if st.button("连接"):
            st.session_state.ws_connected = True
            st.session_state.messages = []
            # 初始化 MCP 客户端
            try:
                if not hasattr(st.session_state, 'mcp_client'):
                    loop = get_event_loop()
                    st.session_state.mcp_client = MCPClient()
                    if agent.endswith(('.py', '.js')):
                        loop.run_until_complete(st.session_state.mcp_client.connect_to_server(agent))
                    else:
                        loop.run_until_complete(st.session_state.mcp_client.connect_to_sse_server(f"{agent}/sse"))
                    st.success("成功连接到服务器！")
            except Exception as e:
                st.error(f"连接失败: {str(e)}")
                if hasattr(st.session_state, 'mcp_client'):
                    del st.session_state.mcp_client
    
    # 主界面
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # 显示聊天历史
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
    
    # 输入框
    if prompt := st.chat_input("输入您的问题"):
        if not hasattr(st.session_state, 'mcp_client'):
            st.error("请先连接到服务器！")
            return
            
        # 添加用户消息
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
        
        # 添加助手响应
        with st.chat_message("assistant"):
            with st.spinner("思考中..."):
                try:
                    loop = get_event_loop()
                    # 处理查询
                    response = loop.run_until_complete(st.session_state.mcp_client.process_query(prompt))
                    st.write(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                except Exception as e:
                    st.error(f"错误: {str(e)}")

    # 添加断开连接按钮
    with st.sidebar:
        if hasattr(st.session_state, 'mcp_client'):
            if st.button("断开连接"):
                try:
                    loop = get_event_loop()
                    loop.run_until_complete(safe_cleanup(st.session_state.mcp_client))
                except Exception as e:
                    print(f"Disconnect error: {e}")
                finally:
                    del st.session_state.mcp_client
                    if hasattr(st.session_state, 'event_loop'):
                        del st.session_state.event_loop
                    st.success("已断开连接！")
                    st.rerun()

if __name__ == "__main__":
    main() 