# EQ2ACT — Advanced Combat Tracker for EverQuest II

A from-scratch combat-log parser and **live web dashboard** for EQ2, in the spirit
of ACT. Zero external dependencies — pure Python standard library on the backend,
vanilla JS + canvas on the front. It tails your EQ2 log, parses combat in real
time, shows a Grafana-style live DPS dashboard, figures out your group + pets
automatically, dings configurable regex notifications, lets you drill into every
fight (and whole zones) by skill, and copies a pastable group parse to your
clipboard when a fight ends.

See [`docs/dashboard.txt`](docs/dashboard.txt) for a layout sketch.

## Features

- **Real-time log parsing** using the line grammar from ACT's official EQ2 plugin
  (auto-attack, abilities, crits, multi/flurry/AOE, DoT ticks, heals, wards, power
  refresh, misses, deaths, unattributed/falling damage). Handles 64-bit client
  number formats (`270,333,864`, `270.3M`, `17.7B`).
- **Automatic group / ally detection — no `/whogroup` needed.** Uses ACT's
  approach: `YOU` is the seed, a name with a space is a mob
  (`a fierce badger`, `Vicathyra the Weaver`), single-token names are players,
  and the rest is resolved from the attacker/victim relationship graph + the
  heal network + co-combat. Pets fold onto their owner (angle-form
  `Gnasher<Maergoth's tiger>` and possessive-form `Torzax's aqueous swarm`).
  Each character's allies persist for a warm start. Modes: `solo`, `group`,
  `raid`, `all`.
- **ACT-style encounter splitting.** A fight ends when every engaged mob is dead
  (per-kill, so XP grinds split into real pulls), with an inactivity timeout as
  fallback. Multi-mob pulls stay one encounter until all adds die. The last fight
  stays on screen until a new one replaces it.
- **Per-fight drill-down (⊞ Breakdown).** Click any group member to see a donut of
  where their damage came from, plus per-skill bars (total, %, hits, crit%, max,
  avg). See exactly what everyone's damage is built from.
- **Zone awareness + whole-zone / combined parses.** Reads `You have entered
  <zone>` (and seeds the current zone on attach by scanning the log). Fights are
  grouped by zone; **parse zone** rolls up a whole zone, or tick any fights and
  **Combine** them — the merged result renders like a single fight (table, chart,
  breakdown, paste).
- **Pastable parse + auto-copy.** When a fight ends it copies an ACT-style parse
  to your system clipboard (`xclip`/`wl-copy`/`xsel`/`pbcopy`), gated by a
  configurable minimum fight length so trash kills don't spam it.
- **Regex notification triggers.** Define dings in a UI; match against log text,
  play a sound (ding/alarm/chime), optionally speak via TTS, with per-trigger
  cooldowns and a built-in regex tester.
- **Auto-follow the active character.** Launch with no arguments and it tails the
  most-recently-written `eq2log_*.txt` and switches automatically when you log in
  on someone else. A top-bar dropdown switches manually.
- **History.** Finished fights persist to SQLite and are selectable from the
  dashboard; a date/time range importer re-parses past sessions.

## Install (one shot, zero questions)

On CachyOS / Arch (any desktop), with Steam + EQ2 installed:

```bash
git clone https://github.com/jsbake2/new_act_eq2.git
cd new_act_eq2
./install.sh           # (or: bash install.sh)
```

The installer auto-detects your package manager and session type, installs
prerequisites (Python + the right clipboard tool — asks for sudo once), finds your
EverQuest II log folder automatically, configures itself, starts EQ2ACT as a
background service that auto-starts on login, and **prints the dashboard URL**
(default `http://127.0.0.1:8777`). Then just run `/log on` in game.

> Use `bash install.sh`, not `sh install.sh` — it relies on bash features.

## Quick start (manual / dev)

```bash
# 1. In EQ2, turn logging on:   /log on
#    (creates  <EQ2 install>/logs/eq2log_<YourCharacter>.txt )

# 2. Run it IN YOUR OWN TERMINAL (Python 3.9+, no pip install needed):
./run.sh                 # auto-detects & follows the active character's log
./run.sh Robskin         # or pin a character (auto-finds its log)

#    …or the long form:
python -m eq2act --me YourCharacter --log "/path/to/logs/eq2log_YourCharacter.txt"

# 3. Open  http://127.0.0.1:8777  in a browser. Keep the tab open for dings.
```

> Run it in a normal terminal so the server stays up while you play. Trigger
> dings play in the browser tab — keep it open.

CLI flags (all optional — everything is also editable in the web UI):

| flag | meaning |
|------|---------|
| `--log PATH`     | path to your `eq2log_<Character>.txt` |
| `--me NAME`      | your character name (expands `YOU`/`YOUR`) |
| `--mode MODE`    | `solo` \| `group` \| `raid` \| `all` |
| `--port N`       | dashboard port (default 8777) |
| `--from-start`   | replay the whole log on launch instead of live-only |
| `--no-browser`   | don't auto-open the browser |

With no `--log`/`--me`, EQ2ACT auto-detects the logs folder and follows the
most-recently-active character.

## How it fits together

```
 EQ2 log file ──► tailer ──► engine ──► parser ──► CombatEvent
                              │                        │
                              ├─ triggers (regex ding) │
                              ├─ group (who's my side) │
                              └─ encounter manager ◄────┘
                                     │  fights, per-second buckets, rollups
                                     ▼
                       HTTP server (REST + Server-Sent Events)
                                     │
                                     ▼
                        web dashboard (charts, tables, breakdown)
```

Module map (`eq2act/`):

| file | role |
|------|------|
| `parser.py`    | log line → `CombatEvent` (ACT-derived regexes, pet folding) |
| `group.py`     | ally/enemy classification, roster, pet ownership |
| `encounter.py` | per-kill fight splitting, aggregation, chart buckets, zones |
| `aggregate.py` | merge fights into one summary (whole-zone / combine) |
| `triggers.py`  | regex notification engine |
| `tailer.py`    | `tail -f` the log, survives rotation |
| `discover.py`  | find the logs dir / latest log; live character following |
| `storage.py`   | SQLite fight history |
| `clipboard.py` | cross-platform clipboard copy |
| `pastable.py`  | the chat-pastable parse string |
| `engine.py`    | wires it all + broadcasts to the UI |
| `server.py`    | stdlib HTTP + SSE + static |
| `web/`         | the dashboard (html/css/js/canvas) |

## Configuration

- `config/settings.json` — log path/dir, character, mode, timeout, port, paste &
  auto-copy options.
- `config/triggers.json` — your notification triggers (edited from the UI).
- `data/fights.db`, `data/roster.json` — saved fights & learned allies (git-ignored).

## Tests

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

Covers number parsing, every combat line type, pet crediting, ally detection,
encounter splitting, solo-mode filtering, and the pastable parse, against a
synthetic sample log.

## Notes on accuracy

Parser regexes are ported from ACT's `ACT_English_Parser.cs` and validated against
real EQ2 logs (137k+ events, ~0 missed combat lines). Make sure your in-game
**Filters** (Ctrl+O → Filters) are set to *Show* for the combat/heal text you want
logged — that's the #1 cause of "missing" parse data. For a strict 6-person group
filter inside a raid, type `/whogroup` in game.

## License

Personal project — do what you like with it.
