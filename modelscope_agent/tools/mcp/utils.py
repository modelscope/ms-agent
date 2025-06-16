import os

def fix_json_brackets(json_str):
    # 初始化堆栈和结果字符串
    stack = []
    result = []

    # 遍历字符串中的每个字符
    for char in json_str:
        if char in '{[':
            # 如果是开括号，压入堆栈并添加到结果中
            stack.append(char)
            result.append(char)
        elif char in '}]':
            # 如果是闭括号
            if not stack:
                # 如果堆栈为空，说明缺少开括号，跳过这个闭括号
                continue

            # 检查括号是否匹配
            if (char == '}' and stack[-1] == '{') or (char == ']'
                                                      and stack[-1] == '['):
                # 括号匹配，弹出堆栈并添加到结果中
                stack.pop()
                result.append(char)
            else:
                # 括号不匹配，跳过这个闭括号
                continue
        else:
            # 其他字符直接添加到结果中
            result.append(char)

    # 处理堆栈中剩余的开括号
    while stack:
        # 为每个未匹配的开括号添加对应的闭括号
        open_bracket = stack.pop()
        result.append('}' if open_bracket == '{' else ']')

    return ''.join(result)


def parse_mcp_config(mcp_config: dict, enabled_mcp_servers: list = None):
    mcp_servers = {}
    for server_name, server in mcp_config.get('mcpServers', {}).items():
        if server.get('type', '') in [
                'stdio', ''
        ] or (enabled_mcp_servers is not None
              and server_name not in enabled_mcp_servers):
            continue
        new_server = {**server}
        new_server['transport'] = server.get('type', )
        del new_server['type']
        if server.get('env'):
            env = {'PYTHONUNBUFFERED': '1', 'PATH': os.environ.get('PATH', '')}
            env.update(server['env'])
            new_server['env'] = env
        mcp_servers[server_name] = new_server
    return {'mcpServers': mcp_servers}


def merge_mcp_config(mcp_config1, mcp_config2):
    return {
        'mcpServers': {
            **mcp_config1.get('mcpServers', {}),
            **mcp_config2.get('mcpServers', {})
        }
    }
