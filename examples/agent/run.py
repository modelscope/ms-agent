"""
This file is used to show a basic python usage of LLMAgent
The next code will do the following:
1. Read default yaml config file
2. Read a mcp.json file to connect to mcp servers
3. Run LLMAgent to finish the user request

This loop is a simplified version of ModelScope mcp-playground:
https://modelscope.cn/mcp/playground
"""
import asyncio
import os
import sys

from ms_agent import LLMAgent
from ms_agent.config import Config

path = os.path.dirname(os.path.abspath(__file__))
# ms_agent/agent/agent.yaml
# The system of the config will help LLM to make a better analysis and plan
agent_config = os.path.join(path, '..', '..', 'ms_agent', 'agent',
                            'agent.yaml')
# TODO change the mcp.json to a real path:
# https://www.modelscope.cn/mcp/servers/@amap/amap-maps
mcp_config = os.path.join(path, 'mcp.json')


async def run_query(query: str):
    config = Config.from_task(agent_config)
    # TODO change to your real api key https://modelscope.cn/my/myaccesstoken
    config.llm.modelscope_api_key = '<your-modelscope-api-here>'
    engine = LLMAgent(config=config, mcp_server_file=mcp_config)

    _content = ''
    generator = await engine.run(query, stream=True)
    async for _response_message in generator:
        new_content = _response_message[-1].content[len(_content):]
        # sys.stdout.write(new_content)
        # sys.stdout.flush()
        _content = _response_message[-1].content
    sys.stdout.write('\n')
    """
    Here shows the output result:
    针对针对该需求，该需求，我进行了详细拆解我进行了详细拆解和规划，需要按照如下和规划，需要按照如下步骤来解决问题：
    步骤来解决问题：
    1. 首先1. 首先，我需要获取，我需要获取杭州西湖的经纬度坐标杭州西湖的经纬度坐标，这样才能进行后续，这样才能进行后续的周边搜索。
    2的周边搜索。
    2. 然后. 然后，使用西湖经纬，使用西湖经纬度坐标作为中心度坐标作为中心点，搜索其点，搜索其周边的咖啡厅信息周边的咖啡厅信息。
    首先我应当选择`。
    首先我应当选择`amap-maps:mapsamap-maps:maps_geo`工具，_geo`工具，由于该工具可以由于该工具可以将结构化地址转换将结构化地址转换为经纬度坐标，为经纬度坐标，该工具的入该工具的入参需要地址信息和参需要地址信息和城市信息。
    城市信息。
    [INFO:ms_agent] [Agent-default] [tool_calling]:
    [INFO:ms_agent] [Agent-default] {
    [INFO:ms_agent] [Agent-default]     "id": "call_e169184377ca447b9bca56",
    [INFO:ms_agent] [Agent-default]     "index": 0,
    [INFO:ms_agent] [Agent-default]     "type": "function",
    [INFO:ms_agent] [Agent-default]     "arguments": {
    [INFO:ms_agent] [Agent-default]         "address": "杭州西湖",
    [INFO:ms_agent] [Agent-default]         "city": "杭州"
    [INFO:ms_agent] [Agent-default]     },
    [INFO:ms_agent] [Agent-default]     "tool_name": "amap-maps:maps_geo"
    [INFO:ms_agent] [Agent-default] }
    [INFO:ms_agent] [Agent-default] {
    [INFO:ms_agent] [Agent-default]   "return": [
    [INFO:ms_agent] [Agent-default]     {
    [INFO:ms_agent] [Agent-default]       "country": "中国",
    [INFO:ms_agent] [Agent-default]       "province": "浙江省",
    [INFO:ms_agent] [Agent-default]       "city": "杭州市",
    [INFO:ms_agent] [Agent-default]       "citycode": "0571",
    [INFO:ms_agent] [Agent-default]       "district": "西湖区",
    [INFO:ms_agent] [Agent-default]       "street": [],
    [INFO:ms_agent] [Agent-default]       "number": [],
    [INFO:ms_agent] [Agent-default]       "adcode": "330106",
    [INFO:ms_agent] [Agent-default]       "location": "120.130396,30.259242",
    [INFO:ms_agent] [Agent-default]       "level": "区县"
    [INFO:ms_agent] [Agent-default]     }
    [INFO:ms_agent] [Agent-default]   ]
    [INFO:ms_agent] [Agent-default] }
    [INFO:ms_agent] [Agent-default] [usage] prompt_tokens: 1970, completion_tokens: 142
      "adcode": "330106",
          "location": "120.130396,30.259242",
          "level": "区县"
        }
      ]
    }[INFO:ms_agent] [Agent-default] [assistant]:
    我仔细仔细查看查看了工具了工具返回值，该返回值，该工具返回了杭州工具返回了杭州西湖的经纬度坐标西湖的经纬度坐标为"120为"120.1303.130396,30.96,30.259242259242"，符合我的"，符合我的要求。接下来我要求。接下来我需要使用该坐标作为中心需要使用该坐标作为中心点，调用周边点，调用周边搜索工具查询附近的搜索工具查询附近的咖啡厅。
    咖啡厅。
    [INFO:ms_agent] [Agent-default] [tool_calling]:
    [INFO:ms_agent] [Agent-default] {
    [INFO:ms_agent] [Agent-default]     "id": "call_ce4455cbe24e4aa7beed0d",
    [INFO:ms_agent] [Agent-default]     "index": 0,
    [INFO:ms_agent] [Agent-default]     "type": "function",
    [INFO:ms_agent] [Agent-default]     "arguments": {
    [INFO:ms_agent] [Agent-default]         "keywords": "咖啡厅",
    [INFO:ms_agent] [Agent-default]         "location": "120.130396,30.259242",
    [INFO:ms_agent] [Agent-default]         "radius": "1000"
    [INFO:ms_agent] [Agent-default]     },
    [INFO:ms_agent] [Agent-default]     "tool_name": "amap-maps:maps_around_search"
    [INFO:ms_agent] [Agent-default] }
    [INFO:ms_agent] [Agent-default] {
    [INFO:ms_agent] [Agent-default]   "pois": [
    [INFO:ms_agent] [Agent-default]     {
    [INFO:ms_agent] [Agent-default]       "id": "B0J06ZG937",
    [INFO:ms_agent] [Agent-default]       "name": "暇意咖啡",
    [INFO:ms_agent] [Agent-default]       "address": "曙光路156号(西湖区社会治理中心旁边)",
    [INFO:ms_agent] [Agent-default]       "typecode": "050500",
    [INFO:ms_agent] [Agent-default]       "photos": {
    [INFO:ms_agent] [Agent-default]         "title": [],
    [INFO:ms_agent] [Agent-default]         "url": "https://aos-comment.amap.com/B0J06ZG937/comment/content_media_external_images_media_1000089702_ss__1727324447444_96663809.jpg"
    [INFO:ms_agent] [Agent-default]       }
    [INFO:ms_agent] [Agent-default]     },
    [INFO:ms_agent] [Agent-default]     {
    [INFO:ms_agent] [Agent-default]       "id": "B0KBZS654B",
    [INFO:ms_agent] [Agent-default]       "name": "瑞幸咖啡(东山弄店)",
    [INFO:ms_agent] [Agent-default]       "address": "外东山弄86号西湖·东山集1层左边",
    [INFO:ms_agent] [Agent-default]       "typecode": "050500",
    [INFO:ms_agent] [Agent-default]       "photos": {
    [INFO:ms_agent] [Agent-default]         "title": [],
    [INFO:ms_agent] [Agent-default]         "url": "https://aos-comment.amap.com/B0KBZS654B/comment/9cad79f14fc01a19b9cdd4fb2e6f23aa_2048_2048_80.jpg"
    [INFO:ms_agent] [Agent-default]       }
    [INFO:ms_agent] [Agent-default]     },
                                        ... ignored some results ...
                                        ]
    [INFO:ms_agent] [Agent-default] [assistant]:
    我仔细仔细查看查看了工具了工具返回值，该返回值，该工具返回了杭州西湖工具返回了杭州西湖周边的多个咖啡厅信息周边的多个咖啡厅信息，包括名称、地址和，包括名称、地址和部分图片链接。部分图片链接。以下是部分推荐：
    以下是部分推荐：
    1. **暇意咖啡1. **暇意咖啡**
      **
       地址：曙光 地址：曙光路156号(路156号(西湖区社会治理中心旁边西湖区社会治理中心旁边)
       ![)
       ![图片](https://aos图片](https://aos-comment.amap.com/B-comment.amap.com/B0J060J06ZG937ZG937/comment/content_media_external/comment/content_media_external_images_media_10_images_media_100008900089702_ss702_ss__172__17273244732444744447444_9666_966638093809.jpg)
    2..jpg)
    2. **瑞幸咖啡( **瑞幸咖啡(东山弄店)**东山弄店)**
       地址：
       地址：外东山弄外东山弄86号西湖86号西湖·东山集·东山集1层左边
    1层左边
       ![图片](https://   ![图片](https://aos-comment.amap.com/Baos-comment.amap.com/B0KBZS60KBZS654B/comment54B/comment/9cad79/9cad79f14fcf14fc01a1901a19b9cddb9cdd4fb2e64fb2e6f23aaf23aa_2048__2048_2048_82048_80.jpg)
    3. **0.jpg)
    3. **星巴克(黄龙体育星巴克(黄龙体育中心店)**
      中心店)**
       地址：黄龙路 地址：黄龙路1号主体育场西1号主体育场西区W120区域区W120区域A4入口
       ![A4入口
       ![图片](http://store图片](http://store.is.autonavi.com.is.autonavi.com/showpic/1d/showpic/1d4aa4c4aa4c29bb729bb7e3360e33604e8614e861e8a1e8a1fa3c35fa3c35)
    4. **浅)
    4. **浅弄咖啡(玉古路弄咖啡(玉古路)**
       地址)**
       地址：玉古路5：玉古路58-1号8-1号(青芝坞(青芝坞内)
      内)
       ![图片](https://aos ![图片](https://aos-comment.amap.com/B-comment.amap.com/B0FFFYU80FFFYU863/comment/af63/comment/af517a26517a26cc6bff90abcc6bff90ab9eee439eee4331360bc31360bc7_207_2048_20448_2048_80.jpg)
    8_80.jpg)
    这些咖啡厅都这些咖啡厅都位于西湖附近，可以根据位于西湖附近，可以根据个人喜好和需求个人喜好和需求选择前往。选择前往。
    [INFO:ms_agent] [Agent-default] [usage] prompt_tokens: 4850, completion_tokens: 410
    >>>
    """ # noqa
    return _content


if __name__ == '__main__':
    query = '帮我找一下杭州西湖附近的咖啡厅'
    asyncio.run(run_query(query))
