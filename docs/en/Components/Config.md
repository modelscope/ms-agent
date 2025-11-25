---
slug: Config
title: Config & Parameters
description: Ms-Agent Configuration & Parameters
---

# Config

MS-Agent uses a yaml file for configuration management, typically named `agent.yaml`, which allows different scenarios to read different configuration files. The specific fields contained in this file are:

## Type Configuration

> Optional

```yaml
# type: codeagent
type: llmagent
```

Identifies the agent type corresponding to this configuration, supporting two types: `llmagent` and `codeagent`. Default is `llmagent`. If the yaml contains a code_file field, code_file takes priority.

## Custom Code

> Optional, used when customizing LLMAgent

```yaml
code_file: custom_agent
```

An external agent class can be used, which needs to inherit from `LLMAgent`. Several methods can be overridden. If code_file has a value, the `type` field does not take effect.

## LLM Configuration

> Required

```yaml
llm:
  # Large model service backend
  service: modelscope
  # Model id
  model: Qwen/Qwen3-235B-A22B-Instruct-2507
  # Model api_key
  modelscope_api_key:
  # Model base_url
  modelscope_base_url: https://api-inference.modelscope.cn/v1
```

## Inference Configuration

> Required

```yaml
generation_config:
  # The following fields are all standard parameters of OpenAI SDK, you can also configure other parameters supported by OpenAI here.
  top_p: 0.6
  temperature: 0.2
  top_k: 20
  stream: true
  extra_body:
    enable_thinking: false
```

## system and query

> Optional, but system is recommended

```yaml
prompt:
  # LLM system, if not passed, the default `you are a helpful assistant.` is used
  system:
  # LLM initial query, usually not needed
  query:
```

## callbacks

> Optional, recommended

```yaml
callbacks:
  # User input callback, this callback automatically waits for user input after assistant reply
  - input_callback
```

## Tool Configuration

> Optional, recommended

```yaml
tools:
  # Tool name
  file_system:
    # Whether it is mcp
    mcp: false
    # Excluded functions, can be empty
    exclude:
      - create_directory
      - write_file
  amap-maps:
    mcp: true
    type: sse
    url: https://mcp.api-inference.modelscope.net/xxx/sse
    exclude:
      - map_geo
```

For the complete list of supported tools and custom tools, please refer to [here](./Tools.md)

## Others

> Optional, configure as needed

```yaml
# Automatic conversation rounds, default is 20 rounds
max_chat_round: 9999

# Tool call timeout, in seconds
tool_call_timeout: 30000

# Output artifact directory
output_dir: output

# Help information, usually appears after runtime errors
help: |
  A commonly use config, try whatever you want!
```

## config_handler

To facilitate customization of config at the beginning of tasks, MS-Agent has built a mechanism called `ConfigLifecycleHandler`. This is a callback class, and developers can add such a configuration in the yaml file:

```yaml
handler: custom_handler
```

This means there is a custom_handler.py file at the same level as the yaml file, and the class in this file inherits from `ConfigLifecycleHandler`, with two methods:

```python
def task_begin(self, config: DictConfig, tag: str) -> DictConfig:
    return config
def task_end(self, config: DictConfig, tag: str) -> DictConfig:
    return config
```

`task_begin` takes effect when the LLMAgent class is constructed, and in this method you can make some modifications to the config. This mechanism is helpful if downstream tasks in your workflow will inherit the yaml configuration from upstream. It's worth noting the `tag` parameter, which passes in the name of the current LLMAgent, making it convenient to distinguish the current workflow node.


## Command Line Configuration

In addition to yaml configuration, MS-Agent also supports several additional command line parameters.

- query: Initial query, this query has higher priority than prompt.query in yaml
- config: Configuration file path, supports modelscope model-id
- trust_remote_code: Whether to trust external code. If a configuration contains some external code, this parameter needs to be set to true for it to take effect
- load_cache: Continue conversation from historical messages. Cache will be automatically stored in the `output` configuration. Default is `False`
- mcp_server_file: Can read an external mcp tool configuration, format is:
    ```json
    {
      "mcpServers": {
        "amap-maps": {
          "type": "sse",
          "url": "https://mcp.api-inference.modelscope.net/..."
        }
      }
    }
    ```

> Any configuration in agent.yaml can be passed in with new values via command line, and also supports reading from environment variables with the same name (case insensitive), for example `--llm.modelscope_api_key xxx-xxx`.
