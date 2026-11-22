# Code Genesis Capability

## When to Use

Activate this capability when the user asks to:
- Generate a software project from natural language requirements
- Create a web application, backend service, or full-stack project
- Build a demo or prototype with frontend and backend
- Scaffold a project with proper architecture and dependencies

## Async Tools (Recommended)

### Tool: `submit_code_genesis_task`

Starts code generation in the background. Returns immediately with a `task_id`.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | -- | Natural language description of the project |
| `config_path` | string | no | bundled | Path to code_genesis config directory |
| `output_dir` | string | no | auto | Directory for generated code |
| `workflow` | string | no | `standard` | `standard` (7-stage) or `simple` (4-stage) |

**Returns:**
```json
{
  "task_id": "a1b2c3d4",
  "status": "running",
  "output_dir": "/path/to/output/code_genesis_20260407_143000",
  "message": "Code genesis task a1b2c3d4 started..."
}
```

### Tool: `check_code_genesis_progress`

Polls the status and counts generated files.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `task_id` | string | yes | The task_id from submit_code_genesis_task |

**Returns (running):**
```json
{
  "task_id": "a1b2c3d4",
  "task_type": "code_genesis",
  "status": "running",
  "created_at": "2026-04-07T14:30:00",
  "query": "Create a todo app...",
  "output_dir": "/path/to/output/code_genesis_20260407_143000",
  "workflow": "standard",
  "total_files": 15,
  "file_types": {".py": 5, ".tsx": 8, ".json": 2},
  "log_tail": "..."
}
```

**Returns (terminal):**
```json
{
  "task_id": "a1b2c3d4",
  "task_type": "code_genesis",
  "status": "completed",
  "created_at": "2026-04-07T14:30:00",
  "completed_at": "2026-04-07T15:00:00",
  "total_files": 25,
  "file_types": {".py": 8, ".tsx": 12, ".json": 5}
}
```

Status values: `running`, `completed`, `failed`, `cancelled`. When terminal,
includes `completed_at`; when `failed`, includes `error`.

### Tool: `get_code_genesis_result`

Retrieves the file tree and key file contents.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `task_id` | string | yes | -- | The task_id from submit_code_genesis_task |
| `max_chars` | integer | no | 50000 | Max characters for key file contents |

**Returns (on completion):**
```json
{
  "task_id": "a1b2c3d4",
  "status": "completed",
  "output_dir": "/path/to/output",
  "file_tree": "├── src/\n│   ├── App.tsx\n...",
  "total_files": 25,
  "file_types": {".py": 8, ".tsx": 12, ".json": 5},
  "key_files": [{"path": "README.md", "content": "..."}]
}
```

**Returns (still running):**
```json
{
  "task_id": "a1b2c3d4",
  "status": "running",
  "message": "Code generation is still in progress. Files generated so far: 15."
}
```

**Returns (failed):**
```json
{
  "task_id": "a1b2c3d4",
  "status": "failed",
  "error": "..."
}
```

## SOP Workflow

### Step 1: Understand Requirements

Clarify with the user:
- What type of project (web app, CLI tool, API service, etc.)
- Technology preferences (React, Vue, Python, Node.js, etc.)
- Key features needed

### Step 2: Submit the Task

```
submit_code_genesis_task(
    query="Create a todo app with React frontend, Express backend, and SQLite database",
    workflow="standard"
)
```

Tell the user:
> "I've started generating the project (ID: a1b2c3d4). This typically takes
> 10-30 minutes as it goes through architecture design, code generation with
> LSP validation, and runtime refinement."

### Step 3: Monitor Progress

```
check_code_genesis_progress(task_id="a1b2c3d4")
```

Report: "15 files generated so far (5 Python, 8 TypeScript, 2 JSON)."

### Step 4: Retrieve Results

```
get_code_genesis_result(task_id="a1b2c3d4")
```

Present the file tree and key files (README, package.json, main entry points).

## Sync Tool: `code_genesis`

Synchronous version that blocks until code generation completes. **Not
recommended for MCP clients** — prefer the async trio.

**Estimated Duration:** descriptor `hours`; typical wall-clock 10–30 minutes.

### Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | -- | Natural language description of the project |
| `config_path` | string | no | bundled | Path to code_genesis config directory |
| `output_dir` | string | no | auto | Directory for generated code |
| `workflow` | string | no | `standard` | `standard` (7-stage) or `simple` (4-stage) |

### Returns

On success:

```json
{
  "status": "completed",
  "output_dir": "/path/to/output/code_genesis_20260407_143000",
  "total_files": 25,
  "file_types": {".py": 8, ".tsx": 12, ".json": 5}
}
```

On failure:

```json
{
  "status": "failed",
  "output_dir": "/path/to/output/code_genesis_20260407_143000",
  "error": "..."
}
```

## Workflow Modes

| Mode | Stages | Best For |
|------|--------|----------|
| `standard` | 7 (user story, architect, file design, file order, install, coding, refine) | Production-quality projects |
| `simple` | 4 (reduced pipeline) | Quick prototypes, simpler projects |

## Output Structure

```
output_dir/
├── src/              # Source code
├── public/           # Static assets (web projects)
├── package.json      # Dependencies (Node.js projects)
├── requirements.txt  # Dependencies (Python projects)
├── README.md         # Project documentation
└── ...
```

## Prerequisites

### Capability descriptor (declared)

The MCP capability declares **`OPENAI_API_KEY`** as its only static
`requires.env` entry. This is the LLM credential needed to run the workflow.

### Runtime project prerequisites (not in descriptor)

- **Docker** must be installed for sandboxed code execution.
- Build the sandbox image first:
  `bash projects/code_genesis/tools/build_sandbox_image.sh` — path is relative
  to the **ms-agent repository root** and is unavailable when only the skill
  package is copied into another agent host.

## Notes

- The 7-stage workflow produces higher quality code with LSP validation
  and dependency resolution, but takes longer.
- The simple workflow is faster but may produce less polished output.
- Generated code runs inside a Docker container for security isolation.
- If the task fails, check the `error` field. Common causes: missing Docker
  image, API key issues, or overly complex requirements.
