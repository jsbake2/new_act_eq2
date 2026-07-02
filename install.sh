#!/usr/bin/env bash
#
# EQ2ACT one-shot installer — zero questions.
#
#   git clone git@github.com:jsbake2/new_act_eq2.git
#   cd new_act_eq2
#   ./install.sh
#
# It will: install prerequisites (asks for sudo once), auto-find your EQ2 log
# folder, configure itself, start as a background service, and print the URL.
#
set -uo pipefail

BOLD="$(printf '\033[1m')"; DIM="$(printf '\033[2m')"; GRN="$(printf '\033[32m')"
YEL="$(printf '\033[33m')"; RED="$(printf '\033[31m')"; CYN="$(printf '\033[36m')"
RST="$(printf '\033[0m')"
say()  { printf "%s\n" "${CYN}::${RST} $*"; }
ok()   { printf "%s\n" "${GRN} ✓${RST} $*"; }
warn() { printf "%s\n" "${YEL} !${RST} $*"; }
die()  { printf "%s\n" "${RED} ✗ $*${RST}" >&2; exit 1; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE" || die "cannot cd to script dir"

[ "${EUID:-$(id -u)}" -eq 0 ] && die "Run as your normal user (it will sudo when needed), not as root."

echo
echo "${BOLD}  EQ2ACT installer${RST}  ${DIM}— $HERE${RST}"
echo "  ----------------------------------------------"

# ── 1. Python ────────────────────────────────────────────────────────────────
PY="$(command -v python3 || command -v python || true)"

# ── 2. Detect package manager + the clipboard tool to install ────────────────
SESSION="${XDG_SESSION_TYPE:-}"
[ -z "$SESSION" ] && { [ -n "${WAYLAND_DISPLAY:-}" ] && SESSION=wayland || SESSION=x11; }
CLIP_PKGS=()
[ "$SESSION" = "wayland" ] && CLIP_PKGS+=(wl-clipboard) || CLIP_PKGS+=(xclip)

install_pkgs() {
  local pm="" ; local pkgs=("$@")
  if   command -v pacman  >/dev/null; then pm=pacman
  elif command -v apt-get >/dev/null; then pm=apt
  elif command -v dnf     >/dev/null; then pm=dnf
  elif command -v zypper  >/dev/null; then pm=zypper
  else warn "no known package manager — skipping prereq install"; return 0; fi
  say "Installing prerequisites via ${BOLD}$pm${RST} (sudo)…"
  case "$pm" in
    pacman) sudo pacman -S --needed --noconfirm "${pkgs[@]}" ;;
    apt)    sudo apt-get update -qq && sudo apt-get install -y "${pkgs[@]}" ;;
    dnf)    sudo dnf install -y "${pkgs[@]}" ;;
    zypper) sudo zypper -n install "${pkgs[@]}" ;;
  esac
}

# python package name differs per distro; clipboard pkgs as detected
PYPKG=python3; command -v pacman >/dev/null && PYPKG=python
install_pkgs "$PYPKG" "${CLIP_PKGS[@]}" || warn "prereq install had issues (continuing)"

PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || die "Python is required but was not found after install."
ok "Python: $($PY --version 2>&1)"
command -v wl-copy >/dev/null && ok "clipboard: wl-copy"
command -v xclip   >/dev/null && ok "clipboard: xclip"

# ── 3. Find the EQ2 logs folder, fully automatically ─────────────────────────
say "Searching for your EverQuest II log folder…"
SEARCH_ROOTS=("$HOME" /mnt /media "/run/media/$USER" /run/media /opt /games)
# add Steam library roots from libraryfolders.vdf (covers extra drives)
for vdf in \
  "$HOME/.steam/steam/steamapps/libraryfolders.vdf" \
  "$HOME/.local/share/Steam/steamapps/libraryfolders.vdf" \
  "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/libraryfolders.vdf"; do
  [ -f "$vdf" ] || continue
  while IFS= read -r p; do
    [ -d "$p/steamapps/common" ] && SEARCH_ROOTS+=("$p/steamapps/common")
  done < <(grep -oE '"path"[[:space:]]+"[^"]+"' "$vdf" | sed -E 's/.*"path"[[:space:]]+"([^"]+)"/\1/')
done

# de-dup existing roots
declare -A seen; ROOTS=()
for r in "${SEARCH_ROOTS[@]}"; do
  [ -d "$r" ] || continue; rp="$(realpath -m "$r")"
  [ -n "${seen[$rp]:-}" ] && continue; seen[$rp]=1; ROOTS+=("$rp")
done

# find the most recently written eq2log_*.txt under any root
NEWEST="$(find "${ROOTS[@]}" -maxdepth 10 -type f -iname 'eq2log_*.txt' \
            -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)"

LOG_DIR=""
if [ -n "$NEWEST" ]; then
  d="$(dirname "$NEWEST")"
  # logs may live in .../logs/ or .../logs/<Server>/ — normalise to the logs dir
  [ "$(basename "$(dirname "$d")")" = "logs" ] && d="$(dirname "$d")"
  LOG_DIR="$d"
  ok "Found logs: ${BOLD}$LOG_DIR${RST}"
  ok "Character logs: $(find "$LOG_DIR" -maxdepth 2 -iname 'eq2log_*.txt' 2>/dev/null | wc -l) file(s)"
else
  warn "Couldn't find an eq2log_*.txt yet."
  warn "In game, run ${BOLD}/log on${RST} once, then re-run ./install.sh"
  warn "(You can also set the log folder later in the dashboard Settings tab.)"
fi

# ── 4. Configure (no questions) ──────────────────────────────────────────────
say "Writing configuration…"
"$PY" - "$LOG_DIR" <<'PY'
import json, os, sys
cfgdir = os.path.join(os.getcwd(), "config"); os.makedirs(cfgdir, exist_ok=True)
path = os.path.join(cfgdir, "settings.json")
example = os.path.join(cfgdir, "settings.example.json")
# start from the shipped example so every default (incl. new keys) is present
defaults = {"log_path":"","log_dir":"","me":"You","mode":"group",
            "encounter_timeout":12.0,"from_start":False,"host":"127.0.0.1",
            "port":8777,"paste_title":"EQ2ACT","paste_top":6,
            "autocopy_enabled":True,"autocopy_min_seconds":30.0,"autocopy_min_damage":0,
            "harvest_enabled":True,"archive_enabled":False,"archive_max_mb":50,
            "archive_dir":"","archive_retention_days":0}
try:
    with open(example) as f: defaults.update(json.load(f))
except Exception: pass
data = dict(defaults)
try:                                   # keep any existing local tweaks
    with open(path) as f: data.update(json.load(f))
except Exception: pass
log_dir = sys.argv[1] if len(sys.argv) > 1 else ""
if log_dir: data["log_dir"] = log_dir
data["log_path"] = ""      # let it auto-follow the most-recent character
data["me"] = "You"
for k, v in defaults.items(): data.setdefault(k, v)
with open(path, "w") as f: json.dump(data, f, indent=2)
print("  port", data["port"])
PY
ok "Config written to config/settings.json"

PORT="$("$PY" -c 'import json;print(json.load(open("config/settings.json")).get("port",8777))')"
URL="http://127.0.0.1:${PORT}"

# ── 5. Run it — prefer a systemd user service so it stays up ──────────────────
start_via_systemd() {
  command -v systemctl >/dev/null || return 1
  systemctl --user show-environment >/dev/null 2>&1 || return 1
  local unit="$HOME/.config/systemd/user"; mkdir -p "$unit"
  cat > "$unit/eq2act.service" <<EOF
[Unit]
Description=EQ2ACT — EverQuest II combat tracker dashboard
After=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$HERE
ExecStart=$PY -m eq2act --no-browser
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
  # pass the graphical session env through so server-side clipboard works
  systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY XDG_RUNTIME_DIR 2>/dev/null || true
  systemctl --user daemon-reload
  systemctl --user enable --now eq2act.service >/dev/null 2>&1 || return 1
  # keep it running across logouts/reboots (sudo)
  sudo loginctl enable-linger "$USER" >/dev/null 2>&1 || true
  return 0
}

start_via_nohup() {
  pkill -f "python.* -m eq2act" 2>/dev/null || true
  sleep 0.5
  nohup "$PY" -m eq2act --no-browser >"$HERE/data/eq2act.out" 2>&1 &
  disown || true
}

mkdir -p "$HERE/data"
say "Starting EQ2ACT…"
if start_via_systemd; then
  ok "Running as a systemd user service (auto-starts on login)."
  RUNMODE="systemctl --user {status|restart|stop} eq2act"
else
  warn "systemd user service unavailable — starting in the background instead."
  start_via_nohup
  RUNMODE="re-run ./install.sh to restart"
fi

# ── 6. Wait until it answers, then print the URL ─────────────────────────────
say "Waiting for the dashboard to come up…"
up=0
for _ in $(seq 1 20); do
  if command -v curl >/dev/null && curl -fsS -o /dev/null "$URL/api/status" 2>/dev/null; then up=1; break; fi
  if command -v wget >/dev/null && wget -q -O /dev/null "$URL/api/status" 2>/dev/null; then up=1; break; fi
  sleep 0.5
done

echo
echo "  ${BOLD}══════════════════════════════════════════════${RST}"
if [ "$up" = 1 ]; then
  echo "  ${GRN}${BOLD}EQ2ACT is running.${RST}"
else
  echo "  ${YEL}${BOLD}EQ2ACT started${RST} (still warming up)."
fi
echo
echo "      Open:  ${BOLD}${CYN}${URL}${RST}"
echo
echo "  ${DIM}• In EQ2, type  /log on  once so combat is logged.${RST}"
echo "  ${DIM}• It auto-follows whichever character is currently playing.${RST}"
echo "  ${DIM}• Keep the browser tab open for notification sounds.${RST}"
echo "  ${DIM}• Manage:  ${RUNMODE}${RST}"
echo "  ${BOLD}══════════════════════════════════════════════${RST}"
echo

# best-effort: open it in their browser
( command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1 & ) || true
exit 0
