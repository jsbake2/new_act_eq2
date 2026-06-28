#!/usr/bin/env bash
# Launch the EQ2ACT dashboard. Run this in your OWN terminal (not through an
# agent) so the server stays alive while you play.
#
#   ./run.sh                 # uses config/settings.json (Trailmix, live log)
#   ./run.sh Robskin         # override character (auto-finds its log)
#   ./run.sh Robskin /path/to/eq2log_Robskin.txt   # explicit log path
#
# Then open http://127.0.0.1:8777 in a browser. Keep the tab open for dings.

cd "$(dirname "$0")" || exit 1

LOGDIR="/mnt/games3/SteamLibrary/steamapps/common/EverQuest 2/logs/Wuoshi"
CHAR="${1:-}"
LOG="${2:-}"

ARGS=()
if [[ -n "$CHAR" ]]; then
  ARGS+=(--me "$CHAR")
  if [[ -z "$LOG" ]]; then LOG="$LOGDIR/eq2log_${CHAR}.txt"; fi
fi
if [[ -n "$LOG" ]]; then ARGS+=(--log "$LOG"); fi

exec python3 -m eq2act "${ARGS[@]}"
