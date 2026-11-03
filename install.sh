#!/bin/sh
# install.sh — set up (or repair) open-browser-use on this Mac. Idempotent.
#
#   1. browser-harness itself (the max1874 fork, branch max) as a uv tool
#   2. ~/.local/bin/{browser-harness,bh-agent-chrome} -> this repo's bin/
#   3. agent_helpers.py (focus patch, session groups) -> browser-harness config
#   4. data collection off (telemetry, recordings, version check)
#   5. the skill, into every agent skill directory that exists
#
# Re-run after `uv tool upgrade browser-harness` (it replaces the bin/ shim)
# and after moving this repo (every link points into it).

set -eu

REPO="$(cd "$(dirname "$0")" && pwd -P)"
BH_SRC="${BH_SRC:-$HOME/.local/share/browser-harness}"
BH_TOOL="$HOME/.local/share/uv/tools/browser-harness"
BIN="$HOME/.local/bin"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/browser-harness"

# --- 1. browser-harness ----------------------------------------------------
# The fork carries two small daemon patches (docs/design.md, "The fork");
# upstream stays reachable as the `upstream` remote for rebases.
if [ ! -d "$BH_SRC/.git" ]; then
  git clone -b max https://github.com/max1874/browser-harness.git "$BH_SRC"
  git -C "$BH_SRC" remote add upstream https://github.com/browser-use/browser-harness.git
fi
if [ ! -x "$BH_TOOL/bin/browser-harness" ]; then
  # --editable: the tool follows the clone, so `git pull` there is the update.
  uv tool install --python 3.12 --editable "$BH_SRC"
fi

# --- 2-3. links into this repo --------------------------------------------
mkdir -p "$BIN" "$CONFIG/agent-workspace"
ln -sfn "$REPO/bin/browser-harness" "$BIN/browser-harness"
ln -sfn "$REPO/bin/bh-agent-chrome" "$BIN/bh-agent-chrome"
ln -sfn "$REPO/agent_helpers.py" "$CONFIG/agent-workspace/agent_helpers.py"
echo "linked: $BIN/browser-harness, $BIN/bh-agent-chrome, agent_helpers.py -> $REPO"

# --- 4. data collection off --------------------------------------------------
# Telemetry is on by default and sends scripts and their output verbatim; the
# version check phones home on every run. A far-future fetched_at keeps it quiet.
"$BIN/browser-harness" telemetry disable >/dev/null
"$BIN/browser-harness" recordings disable >/dev/null
version=$("$BH_TOOL/bin/python3" -c "import importlib.metadata as m; print(m.version('browser-harness'))")
printf '{"tag":"%s","fetched_at":99999999999}\n' "$version" > "$CONFIG/version-cache.json"
echo "data collection: off"

# --- 5. skill -----------------------------------------------------------------
# SKILL.md is copied, never linked: Claude Code and Codex both skip a skill whose
# SKILL.md is a symlink, silently (the directory itself may be one).
for dir in ${BH_SKILL_DIRS:-"$HOME/.claude/skills" "$HOME/.codex/skills"}; do
  [ -d "$dir" ] || continue
  mkdir -p "$dir/browser-harness"
  cp "$REPO/skill/browser-harness/SKILL.md" "$dir/browser-harness/SKILL.md"
  ln -sfn "$BH_SRC/interaction-skills" "$dir/browser-harness/interaction-skills"
  echo "skill: $dir/browser-harness"
done
