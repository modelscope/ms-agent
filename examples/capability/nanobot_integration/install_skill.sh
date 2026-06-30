#!/usr/bin/env bash
# Install ms-agent skill into nanobot's workspace skills directory
# so the agent knows *when* and *how* to use each MCP tool.
#
# Usage:
#   ./install_skill.sh                                  # uses default paths
#   NANOBOT_WORKSPACE=~/my-ws ./install_skill.sh        # custom workspace

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SKILL_SRC="$REPO_ROOT/ms-agent-skills"

NANOBOT_WORKSPACE="${NANOBOT_WORKSPACE:-$HOME/.nanobot/workspace}"
SKILL_DST="$NANOBOT_WORKSPACE/skills/ms-agent"

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
echo "  1. Merge config.json into ~/.nanobot/config.json"
echo "  2. Start nanobot:  nanobot agent"
echo "  3. Test:  python3 test_mcp_tools.py --list"
