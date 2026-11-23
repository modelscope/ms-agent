# Agent Hub

Agent Hub reuses instructions, skills, and memory across frameworks. It identifies, converts, merges, and synchronizes assets; it does not transplant another framework's entire runtime into MS-Agent.

## Inspect local assets

Install MS-Agent first, then run from the repository root. This example creates synthetic, non-sensitive assets in a separate `mktemp` directory without reading or changing your everyday Agent home.

```bash
DEMO="$(mktemp -d)"
mkdir -p "$DEMO/source/skills/greeting"
printf '# Instructions\nOnly greet the user.\n' > "$DEMO/source/AGENTS.md"
printf '%s\n' '---' 'name: greeting' 'description: Say hello without tools.' '---' '# Greeting' 'Reply with Hello.' > "$DEMO/source/skills/greeting/SKILL.md"
ms-agent agent status -f ms-agent --local-dir "$DEMO/source"
```

Expected: the test instructions and `greeting` skill are listed. To try your own assets, use a copy under `source` and remove credentials and private content first.

Use a dedicated test copy rather than your everyday agent home. `--local-dir` selects the root explicitly. Choose framework names from the current CLI's supported list.

## Preview conversion

```bash
env -u TRY_EXP_FRAMEWORKS ms-agent agent convert --from-framework ms-agent --target-framework qwenpaw \
  --local-dir "$DEMO/source" --out-dir "$DEMO/converted" --dry-run
```

Expected: a conversion plan targeting QwenPaw. `--dry-run` does not write the destination, upload assets, or start watchers. The default frameworks are `ms-agent` and `qwenpaw`; Hermes requires `TRY_EXP_FRAMEWORKS=true`. Preview mode does not bypass that check.

Review destination paths, asset types, and conflicts before removing `--dry-run`. Frameworks differ in format, fields, and scope. Successful conversion does not guarantee identical runtime behavior.

## Upload, download, and synchronization

| Operation | Review |
| --- | --- |
| upload | Repository, visibility, credentials, file inventory |
| download | Destination, conversion, merge, backups |
| watch | Continuous watching, remote pull, process shutdown |
| backups / restore | Backup source, restore target, overwrite risk |

Upload repository visibility can default to public. Inspect `--dry-run` output and choose visibility deliberately. Do not upload secrets, personal files, or memory without authorization. Hub account credentials are distinct from model API keys.

## Verify the destination

Check instruction meaning, complete skill resources, and memory scope, then run a small task in the target framework. Resolve conflicts through backups and diffs rather than unconditionally overwriting user content.

Keep `$DEMO` to inspect the source files, or remove only that directory after confirming it belongs to this example. Do not clear the original Agent home.

Next: [Skills](skills.md), [Memory](memory.md), [CLI reference](../development/cli-reference.md). Implementation: `agent_hub/`, `cli/agent.py`.
