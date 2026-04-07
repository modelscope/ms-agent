#!/usr/bin/env bash
# Install ms-agent skill into nanobot's workspace skills directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MS_AGENT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SKILL_SRC="$MS_AGENT_ROOT/ms-agent-skills"

NANOBOT_WORKSPACE="${NANOBOT_WORKSPACE:-$HOME/.nanobot/workspace}"
SKILL_DST="$NANOBOT_WORKSPACE/skills/ms-agent"

if [ ! -d "$SKILL_SRC" ]; then
    echo "ERROR: ms-agent-skills not found at $SKILL_SRC"
    exit 1
fi

mkdir -p "$SKILL_DST"

cp -r "$SKILL_SRC/SKILL.md" "$SKILL_DST/"
cp -r "$SKILL_SRC/references" "$SKILL_DST/" 2>/dev/null || true
cp -r "$SKILL_SRC/scripts" "$SKILL_DST/" 2>/dev/null || true

echo "Installed ms-agent skill to: $SKILL_DST"
echo ""
echo "Contents:"
find "$SKILL_DST" -type f | sort | while read -r f; do
    echo "  $f"
done
echo ""
echo "nanobot will now discover this skill automatically on next startup."
