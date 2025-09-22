
# To run the ms-agent chat with mcp tools, let's take the newspaper example as an instance:

## Step1: Installation
# pip install ms-agent -U
# pip install -U llama-index-core llama-index-embeddings-huggingface llama-index-llms-openai llama-index-llms-replicate

## Step2: Configuration & Run
export TAVILY_API_KEY=xxx-xxx    # Replace with your `Tavily` API key
ms-agent run --modelscope_api_key ms-xxx-xxx --config ms-agent/newspaper --trust_remote_code true

# Refer to: https://modelscope.cn/models/ms-agent/newspaper/summary
