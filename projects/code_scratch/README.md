# Do a Website!

This is a development version of code generation. We hope you can play happily with this code. It can do:

* Complex code generation work, especially React frontend and Node.js backend tasks
* A high success rate of generation
* Free development of your own code generation workflows, fitting your scenario

The codebase contains three YAML configuration files:

- **workflow.yaml** - The entry configuration file for code generation; the command line automatically detects this file's existence
- **agent.yaml** - Configuration file used for generating code projects, referenced by workflow.yaml

This project needs to be used together with ms-agent.

## Running Commands

1. Clone this repo:

  ```shell
  git clone https://github.com/modelscope/ms-agent
  cd ms-agent
  ```

2. Prepare python environment (python>=3.10) with conda:

  ```shell
  conda create -n code_scratch python==3.11
  conda activate code_scratch
  pip install -r ./requirements.txt
  ```

3. Prepare npm environment, following https://nodejs.org/en/download. If you are using Mac, using Homebrew is recommended: https://formulae.brew.sh/formula/node

Make sure your installation is successful:

```shell
npm --version
```

Make sure the npm installation is successful, or the npm install/build/dev will fail and cause an infinite loop.

4. Run:

```shell
PYTHONPATH=. openai_api_key=your-api-key openai_base_url=your-api-url python ms_agent/cli/cli.py run --config projects/code_scratch --query 'make a demo website' --trust_remote_code true
```

The code will be output to the `output` folder in the current directory by default.

## Architecture Principles

The workflow is defined in workflow.yaml and follows a two-phase approach:

**Design & Coding Phase:**
1. A user query is given to the architecture
2. The architecture produces a PRD (Product Requirements Document) & module design
3. The architecture starts several tasks to finish the coding jobs
4. The Design & Coding phase completes when all coding jobs are done

**Refine Phase:**
1. The first three messages are carried to the refine phase (system, query, and architecture design)
2. Building begins (in this case, npm install & npm run dev/build); error messages are incorporated into the process
3. The refiner distributes tasks to programmers to read files and collect information (these tasks do no coding)
4. The refiner creates a fix plan with the information collected from the tasks
5. The refiner distributes tasks to fix the problems
6. After all problems are resolved, users can input additional requirements, and the refiner will analyze and update the code accordingly

## Developer Guide

Function of each module:

- **workflow.yaml** - Entry configuration file used to describe the entire workflow's running process. You can add other processes
- **agent.yaml** - Configuration file for each Agent in the workflow. This file is loaded in the first Agent and passed to subsequent processes
- **config_handler.py** - Controls config modifications for each Agent in the workflow, for example, dynamically modifying callbacks and tools that need to be loaded for different scenarios like Architecture, Refiner, Worker, etc.
- **callbacks/artifact_callback.py** - Code storage callback. All code in this project uses the following format:

    ```js:js/index.js
    ... code ...
    ```
  js/index.js is used for file storage. This callback parses all code blocks matching this format in a task and stores them as files.
  In this project, a worker can write multiple files because code writing is divided into different clusters, allowing more closely related modules to be written together, resulting in fewer bugs.
- **callbacks/coding_callback.py** - This callback adds several necessary fields to each task's system before the `split_to_sub_task` tool is called:
    * Complete project design
    * Code standards (currently fixed to insert frontend standards)
    * Code generation format
- **callbacks/eval_callback** - Automatically compiles npm (developers using other languages can also modify this to other compilation methods) and hands it to the Refiner for checking and fixing:
    * The Refiner first analyzes files that might be affected based on errors and uses `split_to_sub_task` to assign tasks for information collection
    * The Refiner redistributes fix tasks based on collected information, using `split_to_sub_task` for repairs

## Human Evaluation

After all writing and compiling is finished, an input will be shown to enable human feedback:

1. Please run both frontend and backend with `npm run dev` to start the website
2. Check website problems and give error feedback from:
   * The backend console
   * The browser console
   * Page errors
3. After the website runs normally, you can adjust the website, add new features, or refactor something
4. If you find the token cost is huge or there's an infinite loop, stop it at any time. The project serves as a cache in ~/.cache/modelscope/hub/workflow_cache
5. Feel free to optimize the code and bring new ideas
