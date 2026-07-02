#!/usr/bin/env bash
# Launch the EQ2ACT dashboard. Run this in your OWN terminal (not through an
# agent) so the server stays alive while you play.
#
#   ./run.sh                 # auto-discovers your logs + follows the active char
#   ./run.sh Robskin         # override character (auto-finds its log)
#   ./run.sh Robskin /path/to/eq2log_Robskin.txt   # explicit log path
#
# Then open http://127.0.0.1:8777 in a browser. Keep the tab open for dings.

cd "$(dirname "$0")" || exit 1

CHAR="${1:-}"
LOG="${2:-}"

# derive the logs dir from your config if present; otherwise the app
# auto-discovers it (standard Steam paths + any configured log_dir).
LOGDIR="$(python3 -c 'import json;print(json.load(open("config/settings.json")).get("log_dir",""))' 2>/dev/null || true)"

ARGS=()
if [[ -n "$CHAR" ]]; then
  ARGS+=(--me "$CHAR")
  if [[ -z "$LOG" && -n "$LOGDIR" && -f "$LOGDIR/eq2log_${CHAR}.txt" ]]; then
    LOG="$LOGDIR/eq2log_${CHAR}.txt"
  fi
fi
if [[ -n "$LOG" ]]; then ARGS+=(--log "$LOG"); fi

exec python3 -m eq2act "${ARGS[@]}"
