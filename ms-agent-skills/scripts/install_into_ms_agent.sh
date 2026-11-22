#!/usr/bin/env bash
# Install the ms-agent Capability Gateway skill into ms-agent's own skill tree
# so the in-process SkillCatalog / SkillLoader can discover it.
#
# Destination (override with MS_AGENT_HOME):
#   $MS_AGENT_HOME/skills/ms-agent   (default: ~/.ms_agent/skills/ms-agent)
#
# Usage:
#   ./install_into_ms_agent.sh
#   MS_AGENT_HOME=/custom/home ./install_into_ms_agent.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_SRC="$(cd "$SCRIPT_DIR/.." && pwd)"

MS_AGENT_HOME="${MS_AGENT_HOME:-${HOME}/.ms_agent}"
SKILL_DST="${MS_AGENT_HOME}/skills/ms-agent"

if [ ! -f "$SKILL_SRC/SKILL.md" ]; then
    echo "ERROR: SKILL.md not found at $SKILL_SRC" >&2
    exit 1
fi

mkdir -p "$SKILL_DST/references" "$SKILL_DST/scripts"
cp "$SKILL_SRC/SKILL.md" "$SKILL_DST/"
cp -R "$SKILL_SRC/references/." "$SKILL_DST/references/"
cp -R "$SKILL_SRC/scripts/." "$SKILL_DST/scripts/"

echo "Installed Capability Gateway skill to: $SKILL_DST"
echo ""
echo "ms-agent will discover it via \$MS_AGENT_HOME/skills (skill_id: ms-agent)."
echo "Alternatively, add a config source without installing:"
echo ""
echo "  skills:"
echo "    sources:"
echo "      - type: local"
echo "        path: $SKILL_SRC"
echo ""
