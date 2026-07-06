#!/usr/bin/env bash
# Install the ms-agent skill into Hermes Agent's skills directory
# so the agent knows *when* and *how* to use each MCP tool.
#
# Usage:
#   ./install_skill.sh                          # uses default paths
#   HERMES_SKILLS=~/my-skills ./install_skill.sh  # custom skills dir

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SKILL_SRC="$REPO_ROOT/ms-agent-skills"

HERMES_SKILLS="${HERMES_SKILLS:-$HOME/.hermes/skills}"
SKILL_DST="$HERMES_SKILLS/ms-agent"

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
echo "  1. Merge hermes_mcp_config.yaml into ~/.hermes/config.yaml"
echo "  2. Restart Hermes:  hermes chat"
echo "  3. Test:  hermes chat -q 'What ms-agent MCP tools do you have?'"
