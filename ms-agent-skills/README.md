# ms-agent Capability Gateway Skill

A **single** Agent Skill package (`name: ms-agent`) that teaches host agents
how to use the ms-agent Capability Gateway over MCP.

This directory is **not** auto-scanned by ms-agent’s in-process skill runtime
under its repo-root name. Install it into a skill tree (see below), or rely on
the copy bundled into `ms_agent/skills/ms-agent/` when installing from a wheel.

## Contents

```
ms-agent-skills/
├── SKILL.md                 # Frontmatter + Capability Index (30 MCP tools)
├── README.md                # This file
├── references/              # Per-capability SOPs (9 modules)
└── scripts/
    ├── check_ms_agent.py              # Health check
    ├── validate_capability_index.py   # Index ↔ registry drift check
    └── install_into_ms_agent.sh       # Install into ~/.ms_agent/skills/ms-agent
```

## Install for external hosts

```bash
# nanobot / OpenClaw / Hermes — see examples/capability/*/install_skill.sh
bash examples/capability/nanobot_integration/install_skill.sh
```

Configure the MCP server:

```bash
python -m ms_agent.capabilities.mcp_server
```

## Install for ms-agent itself

```bash
bash ms-agent-skills/scripts/install_into_ms_agent.sh
# → $MS_AGENT_HOME/skills/ms-agent  (default ~/.ms_agent/skills/ms-agent)
```

Or declare a config source without copying:

```yaml
skills:
  sources:
    - type: local
      path: /path/to/ms-agent/ms-agent-skills
```

When loaded by SkillLoader, `skill_id` equals the **directory name**
(`ms-agent` after install scripts; `ms-agent-skills` if the repo folder is
referenced directly).

## Validate

Run from the repository root:

```bash
python ms-agent-skills/scripts/check_ms_agent.py
python ms-agent-skills/scripts/validate_capability_index.py
```

## Docs

- English: [docs/en/Components/CapabilityGateway.md](../docs/en/Components/CapabilityGateway.md)
- Chinese: [docs/zh/Components/capability-gateway.md](../docs/zh/Components/capability-gateway.md)
- Integration examples: [examples/capability/](../examples/capability/)
