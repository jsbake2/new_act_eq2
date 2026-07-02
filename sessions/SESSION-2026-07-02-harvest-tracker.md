# Session 2026-07-02 — Harvest tracker

Added a **Harvest** tab that tracks resource gathering live and from past logs,
with a per-item bar table, a by-category pie/donut, and a rare counter.

## What shipped

### Backend
- **`eq2act/harvest.py`** (new) — `HarvestTracker`:
  - `HARVEST_RE` matches `You <verb> [a] <qty> \aITEM <id> <id>:<name>\/a from the <node>.`
    Verbs: gather/mine/acquire/forage/trap/fell/chop/fish/net/catch/collect
    (+ past-tense `\w*` tail: gathered/mined/…). Handles the `acquire a 1 …`
    article form for dens.
  - `RARE_RE` = `You have found a rare item!` — attributed to the immediately
    preceding harvested item (rare line prints on the next tick).
  - Verb→category map (Gathering/Mining/Trapping/Foraging/Foresting/Fishing/Collecting).
  - Rolls up per item {qty, actions, rares, category, node}; `snapshot()` returns
    sorted items + category totals + grand totals. `merge()` for past-log import.
  - Persists per character to `data/harvests.json` (same pattern as roster.json).
- **`engine.py`** — owns a `HarvestTracker`, feeds every log line to it on the hot
  path (gated on `harvest_enabled`), throttled broadcast (`{"type":"harvest"}`,
  0.5s) + throttled save (10s). Load/save on character switch. New methods:
  `harvest_snapshot()`, `clear_harvests()`, `import_harvests(path, me, start, end)`.
- **`server.py`** — `GET /api/harvest`, `POST /api/harvest/import`,
  `POST /api/harvest/clear`.
- **`config.py`** — `harvest_enabled: True` default.

### Frontend
- **index.html** — new `Harvest` tab + view: stat strip (character / total /
  actions / unique / rares), by-category donut, past-log import panel (char +
  datetime range + quick ranges), full-width per-item bar table.
- **app.js** — `loadHarvest()`, donut + table renderers (reuse `EQChart.drawDonut`
  + `.dps-row/.dps-bar`), live-tracking checkbox → POST settings, Clear button,
  import handler. SSE `harvest` events refresh only when the tab is active.
  Also added **deep-link hash tabs** (`#harvest` etc.) — used for headless QA and
  a nice bonus.

## Verified (curl against the live systemd service)
- Import Trailmix whole log → 10,348 harvested, 39 items, 197 rares, cats
  Mining/Gathering/Trapping. Robskin 81 rares, Furyflatulence 97.
- Live feed of a synthetic `gather` + `rare` line → item row qty=7, rares=1,
  correct category/node.
- Clear resets + persists empty; re-import repopulates.
- Rotation handling is inherited from the shared tailer hot path (see below).

## Log rotation finding (user asked)
EQ2 does **not** rotate or overwrite logs — it appends to one
`eq2log_<Char>.txt` forever. Confirmed: Robskin's single 24 MB file spans
Jun 9 → Jul 1 (3 weeks); no `.1/.old/archive` artifacts in the logs dir.
- **Live:** `tailer.py` already survives manual truncation/rotation — it detects
  an inode change or size-shrink and reopens from the top (lines ~85-96). Harvest
  rides the same `feed_line` path, so it's covered for free.
- **Limitation:** if a player *manually* archives an old log (rename to
  `.txt.1` or move to another folder), `discover.py` only globs `eq2log_*.txt`
  in the logs dir, so the UI import picker won't list it. The `/api/harvest/import`
  and `/api/import` endpoints already accept an explicit `path`, so a future
  "browse for a log file" field would expose archived logs. Not built yet.

## Log archiving (added same session)
Second feature: cap the ever-growing EQ2 log and read rolled-off data transparently.

- **`eq2act/archive.py`** (new):
  - `rotate()` = **copytruncate** — copy live log to
    `<dir>/eq2log_<Char>__<firstEpoch>-<lastEpoch>.txt`, then `truncate(0)` the
    original in place. Rename won't work (EQ2 holds an append fd → keeps writing
    to the moved inode); truncation makes the game's next append land at 0.
  - `scan_span()` (head+tail 256KB scan for first/last epoch), `list_archives()`,
    `logs_for_range()` (archives overlapping [start,end] + live log, ordered),
    `prune()` (delete archives whose last-epoch is older than N days).
- **`engine.py`**:
  - `maybe_rotate()` from `tick()` (outside the lock, self-throttled 15s): rolls
    only when `archive_enabled` AND size ≥ cap AND **no fight is live** (waits for
    a combat lull → never interrupts a fight). Also prunes each pass.
  - `rotate_now()` (manual), `_prune_archives()`, `archive_info()`.
  - `import_range()`/`import_harvests()` now take `character=` and span
    archives+live via `_range_logs()` (explicit `path=` still = single file).
- **`discover.py`** — `_all_logs()` now excludes `eq2act_archive/` + archive-named
  files (`__<epoch>-<epoch>.txt`), so archives never appear as a live character or
  get followed by the latest-log watcher. **Important fix** — without it the
  `logs/*/eq2log_*.txt` glob would have slurped archives.
- **`server.py`** — `GET /api/archive`, `POST /api/archive/rotate`.
- **`config.py`** — `archive_enabled=False` (opt-in — it truncates a game file),
  `archive_max_mb=50`, `archive_dir=""` (→ `<logs>/eq2act_archive`),
  `archive_retention_days=0` (0 = keep forever).
- **UI** — Settings › “Log archiving”: enable toggle, size cap, retention days,
  folder, live-size readout (turns red near the cap), **Archive now** button,
  archive list. SSE `archived` event → toast. Import hint notes ranges span
  archives. Deep-link hash tabs already added above.

Defaults are **safe/off** — I did NOT enable auto-roll on your real logs. Turn it
on in Settings when you want it. Verified end-to-end on synthetic + temp-copied
real logs: roll → correct span name → live truncated → import pulls fights AND
harvests from archive+live in one pass; archive excluded from char list.

## Analytics rework + theme picker (same session, later)
- **Two data bugs fixed in `harvest.py`:** (1) the `forest` verb was missing, so
  all wood harvesting (1600+ lines) was dropped; (2) rare attribution was
  *backwards* — the rare is the item on the line AFTER the "found a rare" banner
  (oak root, alkaline loam, severed bone…), not the common item before it. Rares
  now surface as their own line items; the 197 attributed rares reconcile exactly
  with the 197 banner lines. `snapshot()` now pre-groups by node + category
  (qty/pulls/rares + nested items), reports `total_pulls`/`unique_nodes`, and
  flags per-item `is_rare`. Renamed item `actions`→`pulls` (load() tolerates old).
- **Harvest tab is now a configurable pivot:** Group by Node|Category|Item ×
  Measure by Quantity|Pulls|Rares, Pie/Bars toggle, collapsible group rows with
  per-item breakdown bars, Rares-only filter, expand/collapse all. Grouping is
  done client-side from the flat `items` list for flexibility.
- **Theme picker:** 7 themes (Midnight default, Neon, Cyber Teal, Synthwave,
  Aurora, Solar, Frost-light) as `body[data-theme]` CSS-variable sets incl.
  `--chart-1..12`. `charts.js` now reads colors/ink from CSS vars
  (`EQChart.refreshPalette()` on switch) so canvas charts restyle too. Selector
  in the top bar, persisted to `localStorage["eq2act_theme"]`.
- **Cloudflare / act.jsb-emr.us: dropped** by the user — it's a local app reading
  local logs, so a public URL wouldn't help others (they run it locally). Not built.

## Not done / possible next
- Arbitrary-file picker for import (archived logs).
- Harvest-rate over time (harvests/hr) chart; per-zone harvest breakdown
  (would need to thread zone into `HarvestTracker.feed`).
- Fuel/refined-item tracking, or vendor value estimates.
