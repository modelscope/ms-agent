# Copyright (c) Alibaba, Inc. and its affiliates.
import argparse
import asyncio
import os

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.config import Config
from ms_agent.utils import strtobool
from ms_agent.workflow.chain_workflow import ChainWorkflow

from modelscope import snapshot_download

if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument(
        '--config_dir_or_id',
        required=False,
        type=str,
        default=None,
        help='The directory or the repo id of the config file')
    arg_parser.add_argument(
        '--trust_remote_code',
        required=False,
        type=str,
        default='false',
        help=
        'Trust the code belongs to the config file, set this if you trust the code'
    )
    arg_parser.add_argument(
        '--load_cache',
        required=False,
        type=str,
        default='true',
        help=
        'Load previous step histories from cache, this is useful when a query fails '
        'and retry')
    arg_parser.add_argument(
        '--mcp_server_file',
        required=False,
        type=str,
        default=None,
        help='An extra mcp server file.')
    args, _ = arg_parser.parse_known_args()
    if not args.config_dir_or_id:
        dir_name = os.path.dirname(__file__)
        args.config_dir_or_id = os.path.join(dir_name, 'agent.yaml')
        args.trust_remote_code = 'true'
    if not os.path.exists(args.config_dir_or_id):
        args.config_dir_or_id = snapshot_download(args.config_dir_or_id)
    args.trust_remote_code: bool = strtobool(args.trust_remote_code)  # noqa
    args.load_cache = strtobool(args.load_cache)

    config = Config.from_task(args.config_dir_or_id)
    if Config.is_workflow(config):
        engine = ChainWorkflow(
            config=config,
            trust_remote_code=args.trust_remote_code,
            load_cache=args.load_cache,
            mcp_server_file=args.mcp_server_file)
    else:
        engine = LLMAgent(
            config=config,
            trust_remote_code=args.trust_remote_code,
            load_cache=args.load_cache,
            mcp_server_file=args.mcp_server_file)

    query = ('编写一个专门售卖圣诞礼物品类的电商为网站，包含前后端，前端的商品、用户等都使用后端ajax接口实现。'
             '后端使用node.js，且不需要连接中间件，使用json文件作为数据库即可'
             )  # input('>>>Please input the query:')
    asyncio.run(engine.run(query))
