#!/usr/bin/env bash
# Install the ms-agent skill into OpenClaw's workspace so the agent
# knows *when* and *how* to use each MCP tool.
#
# Usage:
#   ./install_skill.sh                           # uses default paths
#   OPENCLAW_WORKSPACE=~/my-ws ./install_skill.sh  # custom workspace

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SKILL_SRC="$REPO_ROOT/ms-agent-skills"

OPENCLAW_WORKSPACE="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}"
SKILL_DST="$OPENCLAW_WORKSPACE/skills/ms-agent"

if [ ! -d "$SKILL_SRC" ]; then
    echo "ERROR: ms-agent-skills/ not found at $SKILL_SRC" >&2
    exit 1
fi

mkdir -p "$SKILL_DST"

cp "$SKILL_SRC/SKILL.md" "$SKILL_DST/"
cp -r "$SKILL_SRC/references" "$SKILL_DST/" 2>/dev/null || true
cp -r "$SKILL_SRC/scripts" "$SKILL_DST/" 2>/dev/null || true

echo "Installed ms-agent skill to $SKILL_DST"
echo ""
echo "Next steps:"
echo "  1. Merge openclaw_mcp_config.json into ~/.openclaw/openclaw.json"
echo "  2. Restart the OpenClaw gateway:  openclaw gateway start"
echo "  3. Test:  openclaw agent --agent main --message 'List your MCP tools'"
