# Agent Hub

Agent Hub reuses instructions, skills, and memory across frameworks. It identifies, converts, merges, and synchronizes assets; it does not transplant another framework's entire runtime into MS-Agent.

## Inspect local assets

```bash
ms-agent agent --help
ms-agent agent status -f ms-agent --local-dir ./demo-agent-home
```

Use a dedicated test copy rather than your everyday agent home. `--local-dir` selects the root explicitly. Choose framework names from the current CLI's supported list.

## Preview conversion

```bash
ms-agent agent convert --from-framework ms-agent --target-framework hermes \
  --local-dir ./demo-agent-home --out-dir ./converted-agent --dry-run
```

Review destination paths, asset types, and conflicts before removing dry-run. Frameworks differ in format, fields, and scope. Successful conversion does not guarantee identical runtime behavior.

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

Next: [Skills](skills.md), [Memory](memory.md), [CLI reference](../development/cli-reference.md). Implementation: `agent_hub/`, `cli/agent.py`.
