# Do a website!

This repository is designed for complex code generation work, primarily targeting two types of projects: frontend React projects and native JavaScript projects.

The codebase contains three YAML configuration files:

- **workflow.yaml** - The entry configuration file for code generation; the command line automatically detects this file's existence
- **agent.yaml** - Configuration file used for generating React projects, referenced by workflow.yaml
- **native.yaml** - Configuration file for native JS projects; can be used by manually modifying the `config:` field in workflow.yaml to run support for native JS projects

This project needs to be used together with ins-agent.

## Running Commands

First install ins-agent:
```shell
pip install ins -U
```

Then run:
```shell
# use with native.yaml
ins run --config ins/coding --modelscope_api_key xxx --trust_remote_code true
# use with agent.yaml
ins run --config ins/coding --openai_api_key xxx --trust_remote_code true
```

The modelscope_api_key can be obtained from the [https://www.modelscope.cn/my/myaccesstoken](https://www.modelscope.cn/my/myaccesstoken) page.

After the command starts, simply describe a requirement to generate code. The code will be output to the "output" folder in the current directory by default.

## Architecture Principles

The workflow is defined in workflow.yaml and follows a two-phase approach:

**Design & Coding Phase:**
1. A user query is given to the architecture
2. The architecture produces PRD (Product Requirements Document) & module design
3. Optional: An architecture reviewer does one round of review, and the architecture reproduces the PRD and module design
4. The architecture starts several programmer tasks to finish the coding jobs
5. The Design & Coding phase completes when all coding jobs are done

**Refine Phase:**
1. The first three messages are carried to the refine phase (system, query, and architecture design)
2. Building begins (in this case, npm install & npm run build); error messages are incorporated into the process
3. The refiner distributes tasks to programmers to read files and collect information (these tasks do no coding)
4. The refiner creates a fix plan with the information collected from the tasks
5. The refiner distributes tasks to fix the problems
6. After all problems are resolved (or exceed 20 problems), users can input additional requirements, and the refiner will analyze and update the code accordingly

This system appears to be an automated code generation and refinement tool that can create complete web applications based on natural language descriptions, with built-in error detection and fixing capabilities.

## Developer guide

各模块作用：

- workflow.yaml 入口配置文件，用于描述整个workflow的运行流程。你可以添加一些其他的流程，比如代码review等
- agent.yaml/native_js.yaml workflow中每个Agent的配置文件，该文件在第一个Agent中被加载，会传递给后续的流程
- config_handler.py 控制workflow每个Agent的config修改，例如，对Architecture、Refiner、Worker等不同场景动态修改需要加载的callbacks和tools
- codes/arch_review_callback.py 架构review的callback，原理是在Architecture产出架构后使用另一个角色进行review，主要针对模块划分不全面、工具输入不正确等场景
  * 这个callback仅对235B模型生效，因为该模型尺寸较小，增加review过程有助于产出更高质量的架构设计
- codes/artifact_callback.py 代码存储callback，本项目中所有的代码都用下面的格式：

    ```js:js/index.js
    ... code ...
    ```
  js/index.js会用于文件存储，该callback会解析一个任务中的所有符合该格式的代码块并存储为文件。
  在本项目中，一个worker可以写入多个文件，这是因为讲代码编写分为不同的簇，可以让关系更紧密的模块一同编写，这样bug更少。
- codes/coding_callback.py 该callback会在`split_to_sub_task`工具调用前将每个任务的system添加几个必要字段：
    * 项目的完整设计
    * 代码规范（目前固定插入前端规范）
    * 代码生成格式
- codes/eval_callback 自动编译npm（开发者如果使用其他语言，也可以将这里修改为其他编译方式）并交给Refiner进行检查和修复：
    * Refiner会先根据错误分析可能受影响的文件，并使用`split_to_sub_task`分配任务收集信息
    * Refiner根据收集的信息重新分配fix任务，用`split_to_sub_task`进行修复
