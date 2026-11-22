# CodeGenesis

CodeGenesis turns natural-language requirements into software projects through requirements, design, dependency ordering, coding, and validation stages. It is a domain workflow built on MS-Agent, not another general chat interface. Generated software still needs tests and human review.

## Two workflows

```{mermaid}
flowchart TD
 A[User stories] --> B[Architecture]
 B --> C[File design]
 C --> D[Dependency ordering]
 D --> E[Environment setup]
 E --> F[Coding]
 F --> G[Refinement and validation]
```

The standard seven-stage workflow produces explicit design artifacts. The four-stage alternative combines planning into “orchestrator → install → code → refine” for prototypes. Neither guarantees production-ready results in one run.

Topological ordering organizes file dependencies; LSP/runtime feedback supports fixes. Directory LSP calls currently index files, so empty diagnostics do not prove correctness. Run the generated project's compiler, type checker, and tests.

## Prepare the environment

Complete [source installation](../get-started/quick-start.md), then from the repository root:

```bash
pip install -e '.[code]'
npm --version
```

Configure available models/endpoints in every node's `llm` section. The supplied YAMLs mainly use OpenAI-compatible services and can read `OPENAI_API_KEY`. Do not update only the first node.

Keeping the default sandbox configuration requires Docker and its image:

```bash
bash projects/code_genesis/tools/build_sandbox_image.sh
```

Inspect the build script and Docker setup before running it. Local execution changes isolation boundaries; see [Execution environments](../core/execution-environments.md).

## Run and inspect output

```bash
ms-agent run --config projects/code_genesis/workflow.yaml \
  --query 'Build a simple todo website; design it before implementing' \
  --output_dir ./codegen-output --trust_remote_code true
```

For the shorter workflow, use `projects/code_genesis/simple_workflow.yaml`. Custom Python nodes require trusted-code permission. An explicit output directory avoids mixing tasks. Existing project YAMLs also set `./output`; that is not the base SDK default.

Review designs, file lists, code, and validation before refinement/deployment. Preserve artifacts and check cache settings before rerunning rather than overwriting an existing project blindly.

## Editing and deployment boundaries

`file_system.edit_file` currently performs exact `old_string/new_string` replacement. Legacy handlers may read `tools.file_system.edit_file_config` when exposing editing tools; setting `diff_model` does not establish that Morph is used.

EdgeOne deployment uses a configured MCP tool and requires separate credentials/authorization. The initial example does not deploy automatically. Review content and public exposure before publishing.

See the [project directory](https://github.com/modelscope/ms-agent/tree/main/projects/code_genesis) for designs, examples, and configurations. Related: [Workflows](../core/workflows.md), [Tools](../core/tools.md).
