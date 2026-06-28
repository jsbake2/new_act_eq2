# Session 2026-06-26 — initial build of EQ2ACT

Goal (from the captain): build an ACT-for-EQ2 from scratch that parses the combat
log, produces a pastable group parse, tracks **only my group + pets**, dings
regex-configured notifications, and shows a live Grafana-style dashboard (web page
on the box is fine instead of a Python GUI). Turn the dir into a repo; track
milestones in session files; no permission prompts.

## Decisions

- **Web dashboard, not a Python GUI.** Satisfies "always up", "grafana style
  charts", and cross-platform notifications better. Browser tab = notification
  surface (Web Audio ding + SpeechSynthesis TTS).
- **Zero external dependencies.** Backend is stdlib `http.server`
  (ThreadingHTTPServer) + **Server-Sent Events** for live push; SQLite for
  history. No pip install, no wheel-availability risk on Python 3.14. SSE chosen
  over WebSockets because the live feed is one-directional (server → browser) and
  SSE needs no extra library.
- **Parser regexes ported verbatim from ACT's `ACT_English_Parser.cs`** (the
  official EQ2 plugin). Researched first via a subagent — confirmed line wrapper
  `(epoch)[Www Mmm DD HH:MM:SS YYYY] msg`, the `[\d,.KMBTQ]+` amount class for the
  64-bit client, pet token `Name<Owner's class>`, and roster commands.
- **Group filtering** = learn roster from `/whogroup` `/whoraid` `/con` + group
  join/leave lines; pets fold to owner; outsiders excluded from *my* parse.
  Default mode `group`. Verified: a Randomstranger hitting the same mob is dropped
  from the friendly parse.

## What got built (milestone)

Full vertical slice, all working and tested:

- `eq2act/parser.py` — line → CombatEvent (damage/heal/ward/refresh/miss/death,
  crits, multi, multi-element, pets, YOU/YOUR expansion).
- `eq2act/group.py` — roster + pet ownership + 4 tracking modes + side filtering.
- `eq2act/encounter.py` — fight splitting on inactivity timeout, per-combatant
  rollups, per-second buckets for the stacked chart, fight auto-naming.
- `eq2act/triggers.py` — regex ding engine w/ cooldowns, JSON-persisted, UI CRUD.
- `eq2act/tailer.py` — `tail -f` with rotation/truncation handling, thread.
- `eq2act/storage.py` — SQLite fight history.
- `eq2act/pastable.py` — ACT-style chat-pastable ranked parse.
- `eq2act/engine.py` + `server.py` + `__main__.py` — wiring, REST + SSE, CLI.
- `web/` — dark Grafana-style dashboard: stat strip, stacked DPS-over-time canvas
  chart, per-combatant bars with click-to-expand abilities, enemy panel,
  selectable fight history, triggers config tab w/ regex tester, settings tab w/
  live roster view, pastable-parse modal, toast + sound + TTS notifications.
- `tests/` — 23 unit tests + synthetic `eq2log_Gaptia.txt`. All green.

## Verified end-to-end

Started the server, fed the sample log via `/api/feed`:
- 2 fights split correctly (badger, Brother Shen) across a 35s gap.
- Fight 1 friendly total = 32,857 (outsider's 99,999 correctly excluded).
- Pet damage folded into Maergoth.
- Pastable parse rendered: `EQ2ACT | Brother Shen | 5s | 17.97B dmg (3.59B dps)`.

## Open / future ideas

- Healing & threat parse tabs (data is already captured; UI not surfaced yet).
- Hit/miss avoidance %, parse upload/share, overlay-style always-on-top window.
- Auto-detect `me` from the log filename; file-picker for the log path in-UI
  (browser sandbox makes true picking hard — currently a path field + restart).
- Encounter merge/split controls in the UI.

## Update — validated against the real EQ2 install

Found the live install at `/mnt/games3/SteamLibrary/.../EverQuest 2/logs/Wuoshi/`
(chars: Robskin, Furyflatulence, Paraphoin, Cruelst, Trailmix…).

- Ran the parser over real logs: **137,125 events from Robskin's 245k lines, 0
  missed combat lines** after fixes.
- Fixed a real ordering bug ("X is hit by Trap for N" mis-parsed), bare-apostrophe
  possessives, unattributed/falling damage, and added heal-network player
  detection + bidirectional enemy inference so traps/bosses don't pollute the
  group parse. Confirmed on the Paraphoin raid session (12 real players detected,
  62 enemies incl. bosses+traps).
- Delivered a tonight's-combat rundown for Paraphoin (06-25 20:47→22:15).
- **Harness limitation found:** long-lived background servers launched from
  inside the agent get reaped (signal 16). The server is proven working; the
  durable path is `./run.sh` in the user's own terminal. Added run.sh + settings.
