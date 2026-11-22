# LSP Code Server Capability

## When to Use

Activate these tools when the user asks to:
- Validate or check code for errors
- Verify that generated code compiles correctly
- Run diagnostics on a project directory
- Check imports, type errors, or syntax issues
- Iteratively fix code by checking after each edit

## Supported Languages

| Language | File Extensions | LSP Backend |
|---|---|---|
| TypeScript/JavaScript | .ts, .tsx, .js, .jsx, .mjs, .cjs | typescript-language-server |
| Python | .py | pyright-langserver |
| Java | .java | jdtls (Eclipse JDT Language Server) |

Runtime prerequisites are **checked at invoke time** per the `language`
parameter — they are not declared as static descriptor `requires.bins`:

| `language` | Preflight check | Install hint |
|---|---|---|
| `python` | `pyright-langserver` on `$PATH` | `pip install pyright` (or `npm install -g pyright`) |
| `typescript` | `npx` on `$PATH` | Install Node.js/npm and `typescript-language-server` plus `typescript` locally or globally |
| `java` | `jdtls` on `$PATH` or a supported standard install path | `brew install jdtls` (or download Eclipse JDT Language Server) |

TypeScript packages are resolved by the existing `npx` backend; a global
`typescript-language-server` binary is not required. Start from the project
directory when using project-local dependencies. Preflight does not download
packages or guarantee a successful language-server startup.

A missing prerequisite produces an actionable `{"error": "..."}` message;
errors from the language server can still occur after preflight.

## Tool: `lsp_check_directory`

**Granularity:** Component
**Estimated Duration:** 1-5 minutes (depends on project size)

Opens matching files in a directory for LSP indexing. Directory-wide diagnostic
collection is currently disabled in the SDK; an empty `diagnostics` list does
not mean the project has no errors.

### Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `directory` | string | yes | Path to directory (relative to workspace or absolute) |
| `language` | string | yes | One of: `typescript`, `python`, `java` |

### Example

```
lsp_check_directory(directory="src/", language="typescript")
```

The wrapper returns `{"result": "..."}`, where `result` is a JSON-encoded
indexing summary, for example:
```json
{
  "directory": "src/",
  "language": "typescript",
  "file_count": 42,
  "diagnostics": [],
  "files_indexed": 42,
  "status": "indexed"
}
```

## Tool: `lsp_update_and_check`

**Granularity:** Tool (atomic)
**Estimated Duration:** seconds

Updates a single file with new content and returns LSP diagnostics.
The LSP server instance is reused across calls, making repeated checks
on the same project very efficient.

### Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `file_path` | string | yes | Path to the file (relative or absolute) |
| `content` | string | yes | The updated file content to validate |
| `language` | string | yes | One of: `typescript`, `python`, `java` |

### Example

```
lsp_update_and_check(
    file_path="src/utils/helpers.ts",
    content="export function add(a: number, b: number): number {\n  return a + b;\n}\n",
    language="typescript"
)
```

## SOP: Code Generation with Validation

Use this workflow when generating code that must be correct:

### Step 1: Generate the Code

Write the code using standard file tools.

### Step 2: Index the Project

```
lsp_check_directory(directory="src/", language="typescript")
```

### Step 3: Check Changed Files

1. Call `lsp_update_and_check` with each changed file's content.
2. Inspect the returned diagnostics and fix the source file with a file-editing tool.
3. Submit the corrected content for another check. The LSP call updates its
   in-memory document; it does not save the file to disk.

### Step 4: Run Project Checks

Run the project's compiler, type checker, or tests for final verification.
Directory indexing alone is not a substitute for these checks.

## Skipped Files

The LSP server automatically skips config files that often produce
false positives:
- vite.config.ts/js, webpack.config.js/ts
- rollup.config.js/ts, next.config.js/ts
- tsconfig.json, jsconfig.json
- package.json, pom.xml, build.gradle

## Notes

- The first call for a language starts the LSP server (adds 1-3 seconds).
  Subsequent calls reuse the running server and are much faster.
- Backend availability is checked per `language` at invoke time (see table above).
