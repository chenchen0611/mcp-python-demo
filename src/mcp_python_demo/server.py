import json
import click
import httpx
import os
from typing import Any
from mcp.server.fastmcp import FastMCP
from zhipuai import ZhipuAI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 初始化 MCP 服务器
mcp = FastMCP("MCPServer", host="127.0.0.1", port=8000)

# API 配置
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY")
zhipu_client = ZhipuAI(api_key=ZHIPU_API_KEY)

# 腾讯地图 API 配置
API_BASE = os.getenv("TENCENT_MAP_API_BASE")
API_KEY = os.getenv("TENCENT_MAP_API_KEY")

# 验证必要的环境变量
if not all([ZHIPU_API_KEY, API_BASE, API_KEY]):
    raise ValueError("请确保在 .env 文件中设置了所有必要的环境变量")

async def fetch_weather(adcode: str, search_type: str = "now") -> dict[str, Any] | None:
    """
    从 腾讯地图 API 获取中国城市天气信息，需要先获取要查询的位置的行政区划代码
    :param adcode: 要查询的行政区划代码，可支持市级和区/县级
    :param search_type: 查询天气类型，取值：now[默认] 实时天气预报 future 未来天气预报，获取当天和未来3天的天气信息
    :return: 天气数据字典
    """
    params = {
        "key": API_KEY,
        "adcode": adcode,
        "type": search_type
    }
    headers = {"User-Agent": "weather-app/1.0"}
 
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(API_BASE+"weather/v1/", params=params, headers=headers, timeout=1.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP 错误: {e.response.status_code}"}
        except Exception as e:
            return {"error": f"请求失败: {str(e)}"}
 
def format_weather(data: dict[str, Any] | str) -> str:
    """
    格式化天气查询结果。
    :param data: 天气数据（可以是字典或 JSON 字符串）
    :return: 天气信息查询结果
    """
    # 如果传入的是字符串，则先转换为字典
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception as e:
            return f"无法解析天气数据: {e}"
 
    # 如果数据中包含错误信息，直接返回错误提示
    if data['status'] != 0:
        return f"⚠️ {data['message']}"
 
    # 获取天气
    weather_info = data['result']

    return weather_info
 
async def fetch_adcode(keyword: str) -> dict[str, Any] | None:
    """
    从 腾讯地图 API 获取行政区划代码。
    :param keyword: 要查询的行政区划名称，可支持市级和区/县级，只输出最后一级就可以，例如要查询济南槐荫则keyword="槐荫"
    :return: 行政区划数据字典
    """
    params = {
        "key": API_KEY,
        "keyword": keyword,
    }
    headers = {"User-Agent": "adcode-app/1.0"}
 
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(API_BASE+"district/v1/search", params=params, headers=headers, timeout=1.0)
            response.raise_for_status()
            return response.json()  # 返回字典类型
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP 错误: {e.response.status_code}"}
        except Exception as e:
            return {"error": f"请求失败: {str(e)}"}
 
def format_adcode(data: dict[str, Any] | str) -> str:
    """
    格式化行政区划代码查询结果。
    :param data: 天气数据（可以是字典或 JSON 字符串）
    :return: 格式化的行政区划代码查询结果
    """
    # 如果传入的是字符串，则先尝试转换为字典
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            return f"无法解析天气数据: {e}"

    # 检查数据是否包含错误信息
    if data.get('status') != 0:
        return f"⚠️ {data.get('message', '未知错误')}"

    # 整理结果数据
    adcode_info = data.get('result', [])
    if not adcode_info:
        return "解析行政区划代码数据失败，请查询对应区域是否存在行政区划代码，若不存在可进一步查询对应区域的上级行政区，例如济南市高新区查询不到可直接查询济南市"

    # 提取并返回行政区划代码和地址
    result = [{"adcode": item[0]["id"], "address": item[0]["address"]} for item in adcode_info]
    return result
 
    

@mcp.tool()
async def query_weather(adcode: str, search_type: str = "now") -> str:
    """
    获取中国城市天气信息。必须要先获取要查询的行政区划代码，然后再调用此方法。
    :param adcode: 要查询的行政区划代码
    :param search_type: 查询天气类型，取值：now[默认] 实时天气预报 future 未来天气预报，获取当天和未来3天的天气信息
    :return: 获取的天气信息
    """
    data = await fetch_weather(adcode, search_type)
    return format_weather(data)


@mcp.tool()
async def query_adcode(region_name: str) -> str:
    """
    获取行政区划代码，然后供下游任务使用
    :param keyword: 要查询的行政区划名称，可支持市级和区/县级，例如要查询济南槐荫则region_name="槐荫"
    :return: 行政区划数据代码
    """
    data = await fetch_adcode(region_name)
    return format_adcode(data)

@mcp.tool()
async def web_search(search_query: str, search_engine: str = "search_std") -> str:
    """
    使用智谱AI进行网络搜索，返回相关的标题、链接和内容。
    :param search_query: 搜索查询内容
    :param search_engine: 搜索引擎类型，默认为 search_std
    :return: 搜索结果的格式化字符串
    """
    try:
        response = zhipu_client.web_search.web_search(
            search_engine=search_engine,
            search_query=search_query
        )
        
        # 格式化搜索结果
        results = []
        for result in response.search_result:
            formatted_result = {
                "标题": result.title,
                "链接": result.link if result.link else "无链接",
                "内容": result.content
            }
            results.append(formatted_result)
        return json.dumps(results, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return f"搜索失败: {str(e)}"

@click.command()
@click.option("--transport", default="sse")
def main(transport: str):
    if transport == "stdio":
        import logging
        logging.getLogger().setLevel(logging.WARNING)
    mcp.run(transport=transport)

if __name__ == "__main__":
    main()