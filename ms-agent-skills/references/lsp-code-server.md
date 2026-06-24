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

## Tool: `lsp_check_directory`

**Granularity:** Component
**Estimated Duration:** 1-5 minutes (depends on project size)

Scans all matching files in a directory and returns diagnostics.

### Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `directory` | string | yes | Path to directory (relative to workspace or absolute) |
| `language` | string | yes | One of: `typescript`, `python`, `java` |

### Example

```
lsp_check_directory(directory="src/", language="typescript")
```

Returns a summary like:
```
Checked 42 files in src/
  src/components/App.tsx:15 - error TS2304: Cannot find name 'useState'
  src/utils/api.ts:8 - error TS2307: Cannot find module 'axios'
Total: 2 errors, 0 warnings
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

### Step 2: Validate with LSP

```
lsp_check_directory(directory="src/", language="typescript")
```

### Step 3: Fix Errors Iteratively

For each error reported:
1. Read the error message and file location
2. Fix the issue in the source
3. Validate the fix with `lsp_update_and_check` on the changed file
4. Repeat until no errors remain

### Step 4: Final Full Check

Run `lsp_check_directory` one more time to confirm all issues are resolved.

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
- For Python, `pyright-langserver` must be installed
  (`npm install -g pyright` or `pip install pyright`).
- For TypeScript, `typescript-language-server` must be installed
  (`npm install -g typescript-language-server typescript`).
- For Java, Eclipse JDT Language Server must be available.
