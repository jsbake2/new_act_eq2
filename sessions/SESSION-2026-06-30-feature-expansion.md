# Session 2026-06-27 → 06-30 — feature expansion, GitHub, installer

Continuation of the EQ2ACT build. The previous file
(`SESSION-2026-06-26-initial-build.md`) covers the initial build + first
real-log validation. This file captures **everything after that**, which is most
of the current feature set. NOTE: the git history was later squashed into one
clean commit for GitHub, so this file is the detailed record of what/why.

## TL;DR current state

- EQ2ACT is a zero-dependency Python (stdlib) + vanilla-JS web dashboard combat
  tracker for EQ2. Runs at `http://127.0.0.1:8777`.
- **Pushed to GitHub:** `git@github.com:jsbake2/new_act_eq2.git` (public),
  `main` branch, squashed to a single clean commit + an installer commit.
- **Installable** by friends via `./install.sh` (zero questions).
- All 25 unit tests pass. Validated against the real install repeatedly.

## How to run (important: harness can't host it)

Long-lived servers launched from inside an AI/agent session get **reaped**
(signal 16). The server itself is fine — it must run in a **real terminal**:

```bash
cd ~/repos/new_act_eq2
./run.sh              # auto-detects & follows the most-recently-active character
./run.sh Paraphoin    # or pin a character
python -m eq2act --no-browser   # long form
```

When I (the agent) needed it running to test, I used the Bash tool with
`run_in_background: true` **and** `dangerouslyDisableSandbox: true` — the sandbox
blocks both binding a long-lived socket and sustained reads of `/mnt/games3`
(throws SIGSTKFLT/exit 144). Read-only short commands also need
`dangerouslyDisableSandbox: true` to touch `/mnt/games3`.

## Environment facts

- EQ2 install: `/mnt/games3/SteamLibrary/steamapps/common/EverQuest 2/logs/Wuoshi/`
- Characters seen: Paraphoin, Trailmix, Robskin, Furyflatulence, Cruelst,
  Foxyman, Jenskin, Paraphon. Real groupmates seen: Prax, Trailmix, Torzax,
  Lantik, Ahanu, Healary, Konarn, etc.
- Desktop: **COSMIC** on **Wayland** (greetd/cosmic-greeter); `xclip` present via
  XWayland (clipboard works), `wl-clipboard` not installed.
- `gh` CLI is logged in as **jsbake2**; SSH to GitHub works.

## Features added this stretch (with implementing files)

**Auto-detect & live following** (`discover.py`, `__main__.py`, `engine.py`)
- Launch with no args → finds the logs dir and tails the most-recently-written
  `eq2log_*.txt`; `LatestLogWatcher` auto-switches when you log in on another
  character. `char_from_path()` derives `me` from the filename.
- `engine.switch_character()` resets the GroupTracker for the new char and
  warm-loads its saved allies; `__main__.do_switch` repoints the tailer.

**Historical range import** (`engine.import_range`, `/api/import`, Settings UI)
- Parse any date/time window of any character's log into browsable fights.
- UI: Settings → "Parse past combat": character dropdown, from/to datetime,
  quick ranges (Tonight/Today/Last 2h/Whole log). After parsing it jumps to the
  Dashboard and auto-opens the biggest fight (UX fix — list lives on Dashboard).

**Live character switching from UI** (`/api/switch`, `/api/characters`, top-bar
dropdown). `●` marks a character whose log is active now.

**Keep last fight on screen** (`encounter.py` `last_closed`, `engine.live_summary`)
- When combat ends the dashboard keeps showing that fight (◆ LAST) until a new
  one starts. Was previously snapping to IDLE.

**Pastable parse rework + auto-copy** (`pastable.py`, `clipboard.py`, engine)
- Format (per request):
  ```
  <mob>: <raid dps> dps | max hit <MOB's max hit> (<dur>)
  Group max hit: <max> by <who> (<ability>)
  1. <member>: <dps> dps
  ```
  Line-1 max hit is the **mob's** biggest hit (incoming); line-2 is the group's.
- `clipboard.py` copies to OS clipboard (wl-copy/xclip/xsel/pbcopy/clip).
- Auto-copy on fight end, **gated** by `autocopy_min_seconds` (default 30) +
  `autocopy_min_damage`, with `autocopy_enabled` toggle (Settings UI). Keeps
  trash kills from spamming the clipboard. Manual "Copy parse" always works.

**Per-fight drill-down popup — ⊞ Breakdown** (`web/`, `charts.drawDonut`)
- Click a member → donut of where their damage came from + per-skill bars
  (total, %, hits, crit%, max, avg). Heal entries excluded from the damage donut.

**ACT-aligned classification & encounter-end** (`group.py`, `encounter.py`)
- Researched ACT's real algorithm (see below). Key change: **a name with a space
  is a mob** (`a fierce badger`, `Vicathyra the Weaver`, `Brother Shen`); single
  capitalised token = player; relationship graph + heal network + co-combat
  resolve the rest. No `/whogroup` required.
- Pets: fold angle-form (`Gnasher<Maergoth's tiger>`) AND possessive-form
  (`Torzax's aqueous swarm`, lowercase tail = pet) onto the owner, labelled
  `(pet)`. Canonicalise `/invite` names (adoration → Adoration).
- Encounter ends per **mob death** (all engaged mobs dead → complete), with an
  idle timeout fallback. Multi-mob pulls track every engaged mob (incl. ones hit
  only by a not-yet-classified ally via `looks_like_player`) so pulls don't split
  early. `engaged`/`active_enemies`/`completed`/`complete_ts` on Fight,
  `COMPLETE_GRACE = 1.5s`.
- **Warm-start persistence:** each character's allies saved to
  `data/roster.json` (`engine._load_roster/_save_roster`).

**Whole-zone & multi-fight combine** (`aggregate.py`, `/api/aggregate`, zones)
- `aggregate.combine()` merges N fight details into one summary in the SAME shape
  → table/chart/breakdown/paste all work on it unchanged. Per-second buckets are
  laid end-to-end for a continuous combat-time chart.
- Zone tracking: parse `You have entered <zone>.`; tag each Fight; `zone` column
  in SQLite (with migration). `prime_from_log()` scans the existing log on attach
  and on character switch to seed the **current zone** (fixes "Unknown zone" when
  attaching mid-session — this is how ACT "just knows" the zone).
- UI: Fights list grouped by zone; checkboxes → **Combine** selected; **Whole
  zone** / per-zone **⊕ parse** buttons; 📍 zone shown in the top bar with a
  **parse zone** button. Combined view shows as ⊕ COMBINED; server caches the
  last aggregate so Copy parse / detail work on it.

## ACT research findings (drove the design)

- **Encounter end** = `cbKillEnd` (end when an ally kills its target) +
  `cbIdleEnd` (inactivity timeout fallback). No HP tracking; uses the death line.
  Multi-mob: ends when the last linked enemy dies AND no hostile activity within
  the timeout. We implemented exactly this.
- **Ally/enemy**: ACT does **not** use `/whogroup`; it infers from the
  attacker/victim relationship graph + the documented **"space in name = mob"**
  heuristic. EQ2 player tokens in the combat log are a single capitalised word.
- **Encounter locking is opt-in** (`/lock`); encounters are open by default — so
  "anyone hitting my mob = my group" is NOT strictly guaranteed (see limitation).

## Data / API / config quick reference

- Endpoints: `/api/status` (now includes `zone`), `/api/live`, `/api/fights`
  (now include `zone`), `/api/fights/{id}`, `/api/fights/{id}/paste`,
  `/api/fights/{id}/delete`, `/api/characters`, `/api/switch`, `/api/import`,
  `/api/aggregate` (`{ids:[...]}` or `{zone:"..."}`), `/api/triggers`(+test),
  `/api/settings`, `/api/control/{end,clear}`, `/events` (SSE), `/api/feed`.
- SSE message types: `live`, `fight_closed`, `trigger`, `paste`.
- Config keys (`config/settings.json`): log_path, log_dir, me, mode, encounter_timeout,
  from_start, host, port, paste_title, paste_top, autocopy_enabled,
  autocopy_min_seconds, autocopy_min_damage.
- Git-ignored runtime: `data/fights.db`, `data/roster.json`.

## Known limitations (be honest about these)

- **Group vs raid vs zone-mates:** without `/whogroup`, co-combat detection
  captures "everyone fighting your mobs," which is usually your group but can
  over-include in raids/contested/open-world (EQ2 encounters are open by default).
  Reliable strict group = type `/whogroup` once, or use `solo` mode.
- Single-word named bosses (`Drayek`) look like players for the first hit or two
  until the graph flips them (converges fast).
- `players`/roster accumulates across a long session (per-fight display is still
  correct since only actual combatants show).
- In-game **Filters** (Ctrl+O) must Show combat/heal text or it's not logged.

## Open / offered, NOT yet built

- **Heal-network-biased group mode**: treat heal-network + roster as the real
  group and pure co-combatants as a separate "others in zone" bucket, so group
  parses stay clean in raids without `/whogroup`. (Offered; user hasn't said go.)
- Healing/threat breakdown tab (data captured, UI not surfaced).
- Always-on-top compact overlay.
- Live zone DPS total in header; auto-clear fights on zone change.
- "Combine all" shortcut; inline zone sub-totals in the list.

## Resume checklist

1. `cd ~/repos/new_act_eq2 && ./run.sh` (real terminal) → open the printed URL.
2. `git status` clean; remote `origin` = github jsbake2/new_act_eq2 (public).
3. Tests: `python -m unittest discover -s tests -p 'test_*.py'` (25, all pass).
4. If group detection feels loose in a raid → consider the heal-network-bias TODO
   or tell users to `/whogroup`.
