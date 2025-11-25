---
slug: Installation
title: Installation
description: Ms-Agent Installation Guide
---

# Installation

## Wheel Package Installation

You can install using pip:

```shell
pip install ms-agent
```

## Source Code Installation

```shell
# pip install git+https://github.com/modelscope/ms-agent.git

git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
```

If using DeepResearch or CodeScratch, there may be additional dependencies. Please install according to the corresponding README documentation.

## Images

It is recommended to use ModelScope's [official LLM images](https://modelscope.cn/docs/intro/environment-setup#%E6%9C%80%E6%96%B0%E9%95%9C%E5%83%8F).

## Runtime Environment

MS-Agent runs using LLM API, so only a CPU environment is required.

| Environment | Requirements |
|-------------|--------------|
| python      | \>=3.11      |
