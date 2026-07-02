/* EQ2ACT dashboard front-end. Vanilla JS, talks REST + SSE to the local engine. */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const fmt = EQChart.fmt;

  let selectedId = "live";     // "live" or a numeric fight id
  let currentZone = "";
  let liveSummary = null;
  let detailCache = {};
  let settings = {};
  let expanded = {};           // combatant name -> skills open?
  let lastChartKey = "";

  /* ---------------- networking ---------------- */
  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(path + " -> " + r.status);
    return r.json();
  }
  const post = (path, body) =>
    api(path, { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body || {}) });

  /* ---------------- tabs ---------------- */
  function activateTab(name) {
    $$(".tab").forEach((x) => x.classList.toggle("active", x.dataset.tab === name));
    $$(".view").forEach((x) => x.classList.remove("active"));
    const v = $("#" + name); if (v) v.classList.add("active");
    if (name === "triggers") loadTriggers();
    if (name === "settings") loadSettings();
    if (name === "harvest") loadHarvest();
  }
  $$(".tab").forEach((t) => t.addEventListener("click", () => {
    activateTab(t.dataset.tab);
    try { history.replaceState(null, "", "#" + t.dataset.tab); } catch {}
  }));

  /* ---------------- SSE ---------------- */
  let refreshQueued = false;
  function connectSSE() {
    const es = new EventSource("/events");
    es.onopen = () => $("#connDot").classList.add("on");
    es.onerror = () => $("#connDot").classList.remove("on");
    es.onmessage = (e) => {
      let msg; try { msg = JSON.parse(e.data); } catch { return; }
      if (msg.type === "trigger") return fireTrigger(msg);
      if (msg.type === "paste") { firePaste(msg); return queueRefresh(); }
      if (msg.type === "harvest") { if (harvestActive()) queueHarvest(); return; }
      if (msg.type === "archived") { fireArchived(msg); return; }
      if (msg.type === "live" || msg.type === "fight_closed") queueRefresh();
    };
  }
  function queueRefresh() {
    if (refreshQueued) return;
    refreshQueued = true;
    setTimeout(() => { refreshQueued = false; refreshAll(); }, 150);
  }

  /* ---------------- refresh ---------------- */
  async function refreshAll() {
    try {
      liveSummary = await api("/api/live");
      const status = await api("/api/status");
      $("#modeBadge").textContent = status.settings.mode || "group";
      currentZone = status.zone || "";
      $("#zoneLabel").textContent = currentZone || "—";
      loadCharacters(status.settings.me);
      renderHistory();
      renderCurrentSelection();
      renderRoster(status.group);
    } catch (e) { /* offline */ }
  }

  function currentSummary() {
    if (selectedId === "live") return liveSummary;
    const d = detailCache[selectedId];
    return d ? d.summary : null;
  }
  function currentChart() {
    if (selectedId === "live") return liveSummary ? liveSummary.chart : null;
    const d = detailCache[selectedId];
    return d ? d.chart : null;
  }

  async function selectFight(id) {
    selectedId = id;
    if (id !== "live" && !detailCache[id]) {
      try { detailCache[id] = await api("/api/fights/" + id); } catch {}
    }
    renderHistory();
    renderCurrentSelection();
  }

  function renderCurrentSelection() {
    const s = currentSummary();
    renderStrip(s);
    renderTable(s);
    renderEnemies(s);
    renderChart();
  }

  /* ---------------- stat strip ---------------- */
  function renderStrip(s) {
    if (!s) return;
    $("#fightName").textContent = s.name || "No active fight";
    $("#fightDur").textContent = durStr(s.duration || 0);
    $("#raidDps").textContent = fmt(s.raid_dps || 0);
    $("#totalDmg").textContent = fmt(s.total_damage || 0);
    let pill;
    if (selectedId === "combo") pill = '<span class="pill last">⊕ COMBINED</span>';
    else if (selectedId !== "live") pill = '<span class="pill idle">SAVED</span>';
    else if (s.active) pill = '<span class="pill live">● LIVE</span>';
    else if (s.last) pill = '<span class="pill last">◆ LAST</span>';
    else pill = '<span class="pill idle">IDLE</span>';
    $("#liveState").innerHTML = pill;
  }

  /* ---------------- dps table ---------------- */
  function renderTable(s) {
    const el = $("#dpsTable");
    if (!s || !s.combatants || !s.combatants.length) {
      el.innerHTML = '<div class="muted" style="padding:14px">No combatants yet.</div>';
      $("#tableSub").textContent = "";
      return;
    }
    const max = s.combatants[0].damage || 1;
    $("#tableSub").textContent = s.combatants.length + " tracked";
    el.innerHTML = "";
    s.combatants.forEach((c, i) => {
      const row = document.createElement("div");
      row.className = "dps-row";
      const col = EQChart.colorFor(i);
      const w = Math.max(2, (c.damage / max) * 100);
      row.innerHTML =
        `<div class="dps-bar" style="width:${w}%;background:${col}"></div>` +
        `<div class="dps-rank">${i + 1}</div>` +
        `<div class="dps-name">${esc(c.name)}` +
          (c.is_friend ? "" : '<span class="tag">?</span>') + `</div>` +
        `<div class="dps-dps">${fmt(c.dps)}</div>` +
        `<div class="dps-amt">${fmt(c.damage)}</div>` +
        `<div class="dps-pct">${c.pct.toFixed(1)}%</div>`;
      row.addEventListener("click", () => {
        expanded[c.name] = !expanded[c.name];
        renderTable(currentSummary());
      });
      el.appendChild(row);
      const sk = document.createElement("div");
      sk.className = "skills" + (expanded[c.name] ? " open" : "");
      sk.innerHTML = (c.skills || []).slice(0, 12).map((s) =>
        `<div class="skill-row"><span class="sn">${esc(s.name)}</span>` +
        `<span class="mono">${fmt(s.total)}</span>` +
        `<span class="mono">${s.hits} hits</span>` +
        `<span class="mono">${s.crit_pct.toFixed(0)}% crit · max ${fmt(s.max_hit)}</span></div>`
      ).join("") || '<div class="muted">no abilities</div>';
      el.appendChild(sk);
    });
  }

  function renderEnemies(s) {
    const el = $("#enemyTable");
    const en = (s && s.enemies) || [];
    if (!en.length) { el.innerHTML = '<div class="muted" style="padding:8px">—</div>'; return; }
    el.innerHTML = en.slice(0, 8).map((c) =>
      `<div class="dps-row"><div class="dps-name">${esc(c.name)}` +
      (c.deaths ? ' <span class="tag" style="color:var(--bad)">☠</span>' : "") +
      `</div><div class="dps-amt">${fmt(c.damage_taken)} taken</div></div>`
    ).join("");
  }

  /* ---------------- chart ---------------- */
  function renderChart() {
    const chart = currentChart();
    const s = currentSummary();
    $("#chartTitle").textContent = "DPS over time";
    $("#chartSub").textContent = s ? (s.name || "") : "";
    const legend = EQChart.drawStacked($("#dpsChart"),
      chart || { seconds: [], series: {} }, { height: 240 });
    $("#chartLegend").innerHTML = (legend || []).map((l) =>
      `<span class="lg"><span class="sw" style="background:${l.color}"></span>${esc(l.name)}</span>`
    ).join("");
  }
  // redraw on resize
  window.addEventListener("resize", () => renderChart());

  /* ---------------- history (with multi-select + zone grouping) ---------------- */
  let comboSel = new Set();      // ids selected for combine
  let lastFightList = [];
  async function renderHistory() {
    let fights;
    try { fights = await api("/api/fights"); } catch { return; }
    lastFightList = fights;
    const el = $("#histList");
    el.innerHTML = "";
    let lastZone = null;
    fights.forEach((f) => {
      const id = f.live ? "live" : f.id;
      const zone = f.zone || "Unknown zone";
      if (zone !== lastZone) {
        const zh = document.createElement("div");
        zh.className = "zone-head";
        zh.innerHTML = `<span>${esc(zone)}</span>` +
          `<button class="btn tiny ghost zoneparse" data-zone="${escA(f.zone || "")}">⊕ parse</button>`;
        el.appendChild(zh);
        lastZone = zone;
      }
      const item = document.createElement("div");
      item.className = "hist-item" + (String(id) === String(selectedId) ? " sel" : "") +
        (f.live ? " live" : "");
      item.innerHTML =
        `<div class="hi-top"><span class="hi-name">` +
        `<input type="checkbox" class="hi-check" data-cid="${id}" ${comboSel.has(String(id)) ? "checked" : ""}>` +
        `${esc(f.name || "Unknown")}` +
        (f.live ? ' <span class="pill live" style="font-size:9px">LIVE</span>' : "") +
        `</span><span class="hi-dps">${fmt(f.raid_dps || 0)}</span></div>` +
        `<div class="hi-sub"><span>${durStr(f.duration || 0)} · ${fmt(f.total_damage || 0)}</span>` +
        (f.live ? "" : `<span class="del" data-del="${f.id}">✕</span>`) + `</div>`;
      item.addEventListener("click", (e) => {
        if (e.target.dataset.cid !== undefined) {   // checkbox toggled
          e.stopPropagation();
          const cid = e.target.dataset.cid;
          if (e.target.checked) comboSel.add(cid); else comboSel.delete(cid);
          updateComboBar();
          return;
        }
        if (e.target.dataset.del) {
          e.stopPropagation();
          post("/api/fights/" + e.target.dataset.del + "/delete").then(() => {
            delete detailCache[e.target.dataset.del];
            comboSel.delete(e.target.dataset.del);
            if (String(selectedId) === e.target.dataset.del) selectedId = "live";
            refreshAll();
          });
          return;
        }
        selectFight(id);
      });
      el.appendChild(item);
    });
    $$("#histList .zoneparse").forEach((b) => b.addEventListener("click", async (e) => {
      e.stopPropagation();
      await parseZone(b.dataset.zone);
    }));
    updateComboBar();
  }
  async function parseZone(zone) {
    try {
      const res = await post("/api/aggregate", { zone: zone || "" });
      showCombo(res, "Whole zone: " + (zone || "Unknown"));
    } catch { flashToast("Zone parse failed", "", "alarm"); }
  }
  function updateComboBar() {
    $("#comboCount").textContent = comboSel.size + " selected";
    $("#btnCombine").disabled = comboSel.size < 1;
  }
  async function showCombo(res, label) {
    if (!res || !res.summary) { flashToast("Nothing to combine", "", "ding"); return; }
    detailCache["combo"] = res;
    selectedId = "combo";
    renderHistory();
    renderCurrentSelection();
    flashToast(label, res.summary.name || "", "ding");
  }
  $("#btnCombine").addEventListener("click", async () => {
    if (!comboSel.size) return;
    try {
      const res = await post("/api/aggregate", { ids: Array.from(comboSel) });
      showCombo(res, "Combined " + comboSel.size + " fights");
    } catch { flashToast("Combine failed", "", "alarm"); }
  });
  $("#btnZone").addEventListener("click", async () => {
    // zone of the first selected fight, else the top (most recent) fight's zone
    let zone = null;
    if (comboSel.size) {
      const first = lastFightList.find((f) => comboSel.has(String(f.live ? "live" : f.id)));
      zone = first && (first.zone || "");
    }
    if (zone == null) zone = lastFightList.length ? (lastFightList[0].zone || "") : "";
    try {
      const res = await post("/api/aggregate", { zone });
      showCombo(res, "Whole zone: " + (zone || "Unknown"));
    } catch { flashToast("Zone combine failed", "", "alarm"); }
  });
  $("#btnParseZone").addEventListener("click", () =>
    parseZone(currentZone || (lastFightList[0] && lastFightList[0].zone) || ""));
  $("#btnComboClear").addEventListener("click", () => {
    comboSel.clear();
    if (selectedId === "combo") { selectedId = "live"; }
    renderHistory(); renderCurrentSelection();
  });

  /* ---------------- paste ---------------- */
  $("#btnPaste").addEventListener("click", async () => {
    try {
      const r = await api("/api/fights/" + selectedId + "/paste");
      $("#pasteText").value = r.text;
      $("#pasteModal").classList.add("open");
      $("#pasteCopied").textContent = "";
    } catch {}
  });
  $("#pasteClose").addEventListener("click", () => $("#pasteModal").classList.remove("open"));
  $("#pasteCopyBtn").addEventListener("click", () => {
    const ta = $("#pasteText"); ta.select();
    navigator.clipboard.writeText(ta.value).then(
      () => { $("#pasteCopied").textContent = "copied!"; },
      () => { document.execCommand("copy"); $("#pasteCopied").textContent = "copied"; });
  });
  /* ---------------- fight breakdown modal ---------------- */
  let bdSummary = null, bdMember = null, bdMetric = "damage";
  function metricVal(c) {
    if (bdMetric === "healing") return (c.healing || 0) + (c.warding || 0);
    if (bdMetric === "threat") return c.threat || 0;
    return c.damage || 0;
  }
  function rateLabel() {
    return bdMetric === "healing" ? "hps" : bdMetric === "threat" ? "tps" : "dps";
  }
  function skillMatch(name) {
    const heal = /\((heal|ward)\)$/.test(name);
    const threat = /\(threat\)$/.test(name);
    if (bdMetric === "healing") return heal;
    if (bdMetric === "threat") return threat;
    return !heal && !threat;
  }
  $$("#bdMetric .bdm").forEach((b) => b.addEventListener("click", () => {
    bdMetric = b.dataset.metric;
    $$("#bdMetric .bdm").forEach((x) => x.classList.toggle("active", x === b));
    // jump to the top contributor for this metric
    const ranked = (bdSummary.combatants || []).slice()
      .sort((a, c) => metricVal(c) - metricVal(a));
    bdMember = (ranked[0] || {}).name || bdMember;
    renderBdMembers(); renderBdDetail();
  }));
  $("#btnBreakdown").addEventListener("click", () => openBreakdown());
  $("#bdClose").addEventListener("click", () => $("#bdModal").classList.remove("open"));
  $("#bdModal").addEventListener("click", (e) => {
    if (e.target.id === "bdModal") $("#bdModal").classList.remove("open");
  });
  function openBreakdown() {
    const s = currentSummary();
    if (!s || !s.combatants || !s.combatants.length) {
      flashToast("No fight selected", "Pick a fight first", "ding"); return;
    }
    bdSummary = s;
    $("#bdTitle").textContent = "Breakdown — " + (s.name || "fight");
    $("#bdStats").innerHTML =
      stat("DURATION", durStr(s.duration)) +
      stat("RAID DPS", fmt(s.raid_dps), true) +
      stat("TOTAL", fmt(s.total_damage)) +
      stat("MEMBERS", s.combatants.length) +
      stat("TOP", (s.combatants[0] || {}).name || "—");
    bdMember = s.combatants[0].name;
    renderBdMembers();
    renderBdDetail();
    $("#bdModal").classList.add("open");
  }
  function stat(k, v, accent) {
    return `<div class="s"><span class="k">${k}</span>` +
      `<span class="v${accent ? " accent" : ""}">${esc(v)}</span></div>`;
  }
  function renderBdMembers() {
    const s = bdSummary;
    const dur = s.duration || 1;
    const ranked = s.combatants.slice().sort((a, c) => metricVal(c) - metricVal(a));
    const total = ranked.reduce((t, c) => t + metricVal(c), 0) || 1;
    const max = metricVal(ranked[0]) || 1;
    $("#bdMemberList").innerHTML = ranked.map((c, i) => {
      const v = metricVal(c), col = EQChart.colorFor(i), w = Math.max(2, (v / max) * 100);
      const pct = 100 * v / total;
      return `<div class="bd-row ${c.name === bdMember ? "sel" : ""}" data-m="${escA(c.name)}">` +
        `<div class="bar" style="width:${w}%;background:${col}"></div>` +
        `<div class="nm">${i + 1}. ${esc(c.name)}</div>` +
        `<div class="dp">${fmt(v / dur)} · ${pct.toFixed(0)}%</div></div>`;
    }).join("");
    $$("#bdMemberList .bd-row").forEach((r) => r.addEventListener("click", () => {
      bdMember = r.dataset.m; renderBdMembers(); renderBdDetail();
    }));
  }
  function renderBdDetail() {
    const c = (bdSummary.combatants || []).find((x) => x.name === bdMember);
    if (!c) return;
    const dur = bdSummary.duration || 1;
    const total = (bdSummary.combatants || []).reduce((t, x) => t + metricVal(x), 0) || 1;
    const v = metricVal(c);
    const kind = bdMetric === "healing" ? "healing" : bdMetric === "threat" ? "threat" : "dmg";
    $("#bdMemberName").textContent =
      `${c.name} — ${fmt(v)} ${kind} · ${fmt(v / dur)} ${rateLabel()} · ` +
      `${(100 * v / total).toFixed(1)}% of group` +
      (bdMetric === "damage" ? ` · ${c.crit_pct.toFixed(0)}% crit` : "");
    // donut of top skills for the selected metric (+ "other")
    let skills = (c.skills || []).filter((s) => s.total > 0 && skillMatch(s.name));
    const top = skills.slice(0, 8);
    const restTotal = skills.slice(8).reduce((s, k) => s + k.total, 0);
    const items = top.map((s) => ({ label: s.name, value: s.total }));
    if (restTotal > 0) items.push({ label: "other", value: restTotal });
    const legend = EQChart.drawDonut($("#bdDonut"), items, { size: 220, centerLabel: kind });
    $("#bdLegend").innerHTML = legend.map((l) =>
      `<span class="lg"><span class="sw" style="background:${l.color}"></span>` +
      `${esc(l.label)} ${l.pct.toFixed(0)}%</span>`).join("");
    // skill bars
    const skMax = skills.length ? skills[0].total : 1;
    $("#bdSkills").innerHTML = skills.map((s, i) => {
      const col = EQChart.colorFor(i), w = Math.max(2, (s.total / skMax) * 100);
      const pct = v ? (100 * s.total / v) : 0;
      return `<div class="bd-skill">` +
        `<div class="bar" style="width:${w}%;background:${col}"></div>` +
        `<div class="sn">${esc(s.name)}</div>` +
        `<div class="sv">${fmt(s.total)}</div>` +
        `<div class="sx">${pct.toFixed(1)}%</div>` +
        `<div class="sd">${s.hits} hits · ${s.crit_pct.toFixed(0)}% crit · max ${fmt(s.max_hit)} · avg ${fmt(s.total / Math.max(s.hits, 1))}</div>` +
        `</div>`;
    }).join("") || '<div class="muted">no abilities recorded</div>';
  }

  $("#btnEnd").addEventListener("click", () => post("/api/control/end").then(refreshAll));
  $("#btnClear").addEventListener("click", () => {
    if (confirm("Delete ALL saved fights?")) post("/api/control/clear").then(() => {
      detailCache = {}; selectedId = "live"; refreshAll();
    });
  });

  /* ---------------- triggers ---------------- */
  let trigData = [];
  async function loadTriggers() {
    trigData = await api("/api/triggers");
    renderTriggers();
  }
  function renderTriggers() {
    const el = $("#trigList");
    el.innerHTML = "";
    trigData.forEach((t, i) => {
      const row = document.createElement("div");
      row.className = "trig-row";
      row.innerHTML =
        `<input type="checkbox" ${t.enabled ? "checked" : ""} data-k="enabled">` +
        `<input type="text" value="${escA(t.name)}" data-k="name">` +
        `<input type="text" value="${escA(t.pattern)}" data-k="pattern" class="${t.valid === false ? "bad" : ""}">` +
        `<select data-k="sound">` +
          ["ding", "alarm", "chime", "none"].map((s) =>
            `<option ${t.sound === s ? "selected" : ""}>${s}</option>`).join("") +
        `</select>` +
        `<input type="checkbox" ${t.tts ? "checked" : ""} data-k="tts">` +
        `<input type="text" value="${escA(t.say)}" data-k="say" placeholder="message (\\1 = group)">` +
        `<input type="number" value="${t.cooldown}" step="0.5" min="0" data-k="cooldown">` +
        `<button class="btn tiny ghost" data-del="${i}">del</button>`;
      row.querySelectorAll("[data-k]").forEach((inp) => {
        inp.addEventListener("change", () => {
          const k = inp.dataset.k;
          trigData[i][k] = inp.type === "checkbox" ? inp.checked
            : (k === "cooldown" ? parseFloat(inp.value) || 0 : inp.value);
        });
      });
      row.querySelector("[data-del]").addEventListener("click", () => {
        trigData.splice(i, 1); renderTriggers();
      });
      el.appendChild(row);
    });
  }
  $("#btnAddTrigger").addEventListener("click", () => {
    trigData.push({ id: "", name: "new trigger", pattern: "", enabled: true,
      sound: "ding", tts: false, say: "", cooldown: 2.0 });
    renderTriggers();
  });
  $("#btnSaveTriggers").addEventListener("click", async () => {
    const r = await post("/api/triggers", { triggers: trigData });
    trigData = r.triggers; renderTriggers(); flashToast("Triggers saved", "", "ding");
  });
  $("#btnTestSound").addEventListener("click", () => playSound("ding"));
  $("#btnRunTest").addEventListener("click", async () => {
    const r = await post("/api/triggers/test",
      { pattern: $("#testPattern").value, sample: $("#testSample").value });
    $("#testResult").textContent = r.ok
      ? (r.matched ? "✓ match  groups: [" + r.groups.join(", ") + "]" : "✗ no match")
      : "regex error: " + r.error;
    $("#testResult").style.color = r.ok && r.matched ? "var(--good)"
      : (r.ok ? "var(--muted)" : "var(--bad)");
  });

  /* ---------------- settings ---------------- */
  async function loadSettings() {
    settings = await api("/api/settings");
    $("#setLogPath").value = settings.log_path || "";
    $("#setMe").value = settings.me || "";
    $("#setMode").value = settings.mode || "group";
    $("#setTimeout").value = settings.encounter_timeout || 12;
    $("#setPasteTop").value = settings.paste_top || 6;
    $("#setPasteTitle").value = settings.paste_title || "EQ2ACT";
    $("#setAutoCopy").checked = settings.autocopy_enabled !== false;
    $("#setAutoSecs").value = settings.autocopy_min_seconds ?? 30;
    $("#setAutoDmg").value = settings.autocopy_min_damage ?? 0;
    loadArchive();
  }

  async function loadArchive() {
    let a;
    try { a = await api("/api/archive"); } catch { return; }
    $("#setArchive").checked = !!a.enabled;
    $("#setArchiveMB").value = a.max_mb ?? 50;
    $("#setArchiveRet").value = a.retention_days ?? 0;
    $("#setArchiveDir").value = a.archive_dir || "";
    const mb = (a.live_bytes || 0) / 1048576;
    const cap = a.max_mb || 0;
    $("#hvLiveSize").textContent =
      `live log ${mb.toFixed(1)} MB` + (cap ? ` / ${cap} MB cap` : "");
    $("#hvLiveSize").style.color = cap && mb >= cap ? "var(--bad)"
      : (cap && mb >= cap * 0.8 ? "var(--warn, #e3b341)" : "var(--muted)");
    const arr = a.archives || [];
    $("#archiveCount").textContent = arr.length
      ? arr.length + " file" + (arr.length === 1 ? "" : "s") : "none yet";
    $("#archiveList").innerHTML = arr.length
      ? arr.slice().reverse().map((x) => {
          const span = spanStr(x.first, x.last);
          return `<span class="rchip" title="${escA(x.path)}">` +
            `${esc(x.character)} · ${span} · ${(x.bytes / 1048576).toFixed(1)}MB</span>`;
        }).join("")
      : '<span class="muted">Archives appear here once the log rolls.</span>';
  }
  function spanStr(a, b) {
    const d = (t) => { if (!t) return "?"; const x = new Date(t * 1000);
      return (x.getMonth() + 1) + "/" + x.getDate(); };
    return d(a) + "–" + d(b);
  }

  $("#btnSaveArchive").addEventListener("click", async () => {
    await post("/api/settings", {
      archive_enabled: $("#setArchive").checked,
      archive_max_mb: parseInt($("#setArchiveMB").value) || 50,
      archive_retention_days: parseInt($("#setArchiveRet").value) || 0,
      archive_dir: $("#setArchiveDir").value.trim(),
    });
    flashToast("Archiving saved", $("#setArchive").checked
      ? "auto-roll on" : "auto-roll off", "ding");
    loadArchive();
  });
  $("#btnRollNow").addEventListener("click", async () => {
    if (!confirm("Roll the live log into an archive now? The game keeps writing " +
      "to a fresh file; nothing is lost.")) return;
    const btn = $("#btnRollNow"); btn.disabled = true;
    $("#archiveResult").textContent = "rolling…";
    try {
      const r = await post("/api/archive/rotate", {});
      if (r.ok) {
        $("#archiveResult").textContent =
          `rolled ${(r.bytes / 1048576).toFixed(1)} MB` +
          (r.pruned ? `, pruned ${r.pruned} old` : "");
        $("#archiveResult").style.color = "var(--good)";
      } else {
        $("#archiveResult").textContent = r.error || "nothing to roll";
        $("#archiveResult").style.color = "var(--muted)";
      }
    } catch { $("#archiveResult").textContent = "failed"; }
    btn.disabled = false;
    loadArchive();
  });
  $("#btnSaveSettings").addEventListener("click", async () => {
    const patch = {
      log_path: $("#setLogPath").value.trim(),
      me: $("#setMe").value.trim(),
      mode: $("#setMode").value,
      encounter_timeout: parseFloat($("#setTimeout").value) || 12,
      paste_top: parseInt($("#setPasteTop").value) || 6,
      paste_title: $("#setPasteTitle").value.trim() || "EQ2ACT",
      autocopy_enabled: $("#setAutoCopy").checked,
      autocopy_min_seconds: parseFloat($("#setAutoSecs").value) || 0,
      autocopy_min_damage: parseInt($("#setAutoDmg").value) || 0,
    };
    await post("/api/settings", patch);
    flashToast("Settings saved", "Restart EQ2ACT if you changed the log path.", "ding");
    refreshAll();
  });
  function renderRoster(g) {
    if (!g) return;
    const me = g.me;
    const chips = [];
    chips.push(`<span class="rchip me">${esc(me)} (you)</span>`);
    (g.group || []).forEach((n) => { if (n !== me) chips.push(`<span class="rchip">${esc(n)}</span>`); });
    if (g.mode === "raid") (g.raid || []).forEach((n) =>
      chips.push(`<span class="rchip">${esc(n)} (raid)</span>`));
    Object.keys(g.pets || {}).forEach((p) =>
      chips.push(`<span class="rchip pet">${esc(p)} → ${esc(g.pets[p])}</span>`));
    $("#rosterView").innerHTML = chips.join("") || '<span class="muted">none yet</span>';
  }

  /* ---------------- characters + history import ---------------- */
  let charsLoaded = 0;
  async function loadCharacters(current) {
    // throttle: refreshAll runs every 3s; only refetch list occasionally
    const now = Date.now();
    let data;
    try { data = await api("/api/characters"); } catch { return; }
    const sel = $("#charSelect"), imp = $("#impChar"), hvImp = $("#hvImpChar");
    const opts = data.characters.map((c) => {
      const ago = c.mtime ? Math.round((Date.now() / 1000 - c.mtime) / 60) : 0;
      const tag = ago < 3 ? " ●" : "";
      return { v: c.character, label: c.character + tag, ago };
    });
    function fill(el, withActive) {
      if (!el) return;
      const prev = el.value;
      el.innerHTML = opts.map((o) =>
        `<option value="${esc(o.v)}">${esc(o.label)}</option>`).join("");
      if (prev && opts.some((o) => o.v === prev)) el.value = prev;
    }
    // only repopulate live selector if the option set changed (avoid clobbering)
    const sig = opts.map((o) => o.v).join(",");
    if (sig !== charsLoaded._sig) {
      fill(sel); fill(imp); fill(hvImp);
      charsLoaded = { _sig: sig };
    }
    if (current && sel && !sel.dataset.touched) sel.value = current;
  }
  $("#charSelect").addEventListener("change", async (e) => {
    e.target.dataset.touched = "1";
    await post("/api/switch", { character: e.target.value });
    flashToast("Now following", e.target.value, "ding");
    setTimeout(refreshAll, 400);
  });

  function toEpoch(v) { return v ? Math.floor(new Date(v).getTime() / 1000) : 0; }
  function fmtLocal(d) {
    const p = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      "T" + p(d.getHours()) + ":" + p(d.getMinutes());
  }
  $("#quickRange").addEventListener("click", (e) => {
    const r = e.target.dataset.range; if (!r) return;
    const now = new Date(); let from = null, to = now;
    if (r === "all") { from = null; to = null; }
    else if (r === "2h") { from = new Date(now - 2 * 3600e3); }
    else if (r === "today") { from = new Date(now); from.setHours(0, 0, 0, 0); }
    else if (r === "tonight") {
      from = new Date(now); from.setHours(17, 0, 0, 0);
      if (from > now) from.setDate(from.getDate() - 1);
    }
    $("#impFrom").value = from ? fmtLocal(from) : "";
    $("#impTo").value = to ? fmtLocal(to) : "";
  });
  $("#btnImport").addEventListener("click", async () => {
    const btn = $("#btnImport"); btn.disabled = true;
    $("#impResult").textContent = "parsing…";
    try {
      const res = await post("/api/import", {
        character: $("#impChar").value,
        mode: $("#impMode").value,
        start_ts: toEpoch($("#impFrom").value),
        end_ts: toEpoch($("#impTo").value),
      });
      if (res.ok && res.imported > 0) {
        $("#impResult").textContent =
          `imported ${res.imported} fight(s) — opening on the Dashboard…`;
        $("#impResult").style.color = "var(--good)";
        // jump to the Dashboard and auto-open the biggest imported fight
        const biggest = res.fights.slice().sort(
          (a, b) => b.total_damage - a.total_damage)[0];
        activateTab("dashboard");
        await refreshAll();
        if (biggest) await selectFight(biggest.id);
      } else if (res.ok) {
        $("#impResult").textContent = "no encounters found in that range";
        $("#impResult").style.color = "var(--muted)";
      } else {
        $("#impResult").textContent = "error: " + res.error;
        $("#impResult").style.color = "var(--bad)";
      }
    } catch (e) { $("#impResult").textContent = "failed"; }
    btn.disabled = false;
  });

  /* ---------------- harvest ---------------- */
  function harvestActive() { return $("#harvest").classList.contains("active"); }
  let harvestQueued = false;
  function queueHarvest() {
    if (harvestQueued) return;
    harvestQueued = true;
    setTimeout(() => { harvestQueued = false; loadHarvest(); }, 200);
  }

  async function loadHarvest() {
    let s;
    try { s = await api("/api/harvest"); } catch { return; }
    $("#hvChar").textContent = s.character || "—";
    $("#hvQty").textContent = fmt(s.total_qty || 0);
    $("#hvActions").textContent = fmt(s.total_actions || 0);
    $("#hvUnique").textContent = fmt(s.unique_items || 0);
    $("#hvRares").textContent = fmt(s.rare_total || 0);
    $("#hvEnabled").checked = !!s.enabled;
    renderHarvestDonut(s.categories || []);
    renderHarvestTable(s.items || []);
    // keep the import char picker populated (reuses the live char list)
    loadCharacters(s.character);
  }

  function renderHarvestDonut(cats) {
    const canvas = $("#hvDonut");
    const legend = EQChart.drawDonut(canvas,
      cats.map((c) => ({ label: c.label, value: c.value })),
      { size: 220, centerLabel: "harvested" });
    $("#hvCatSub").textContent = cats.length
      ? cats.length + " categor" + (cats.length === 1 ? "y" : "ies") : "";
    $("#hvLegend").innerHTML = legend.map((l) =>
      `<span class="lg"><i style="background:${l.color}"></i>` +
      `${esc(l.label)} <b>${fmt(l.value)}</b> · ${l.pct.toFixed(0)}%</span>`).join("");
  }

  function renderHarvestTable(items) {
    const el = $("#hvTable");
    if (!items.length) {
      el.innerHTML = '<div class="muted" style="padding:14px">No harvests yet — ' +
        'gather something with Live tracking on, or parse a past log.</div>';
      $("#hvTableSub").textContent = "";
      return;
    }
    const max = items[0].qty || 1;
    $("#hvTableSub").textContent = items.length + " items";
    el.innerHTML = items.map((it, i) => {
      const col = EQChart.colorFor(i);
      const w = Math.max(2, (it.qty / max) * 100);
      const rare = it.rares ? `<span class="tag" title="rare pulls">✦ ${it.rares}</span>` : "";
      return `<div class="dps-row">` +
        `<div class="dps-bar" style="width:${w}%;background:${col}"></div>` +
        `<div class="dps-rank">${i + 1}</div>` +
        `<div class="dps-name">${esc(it.item)}` +
          `<span class="tag" style="color:var(--dim)">${esc(it.category)}` +
          (it.node ? " · " + esc(it.node) : "") + `</span>${rare}</div>` +
        `<div class="dps-dps">${fmt(it.qty)}</div>` +
        `<div class="dps-amt">${it.actions} pulls</div>` +
        `<div class="dps-pct">${(it.pct || 0).toFixed(1)}%</div>` +
      `</div>`;
    }).join("");
  }

  $("#hvEnabled").addEventListener("change", async (e) => {
    await post("/api/settings", { harvest_enabled: e.target.checked });
    flashToast("Harvest tracking", e.target.checked ? "on" : "off", "ding");
  });
  $("#hvClear").addEventListener("click", async () => {
    if (!confirm("Reset this character's harvest totals?")) return;
    await post("/api/harvest/clear", {});
    loadHarvest();
  });
  $("#hvQuickRange").addEventListener("click", (e) => {
    const r = e.target.dataset.range; if (!r) return;
    const now = new Date(); let from = null, to = now;
    if (r === "all") { from = null; to = null; }
    else if (r === "2h") { from = new Date(now - 2 * 3600e3); }
    else if (r === "week") { from = new Date(now - 7 * 86400e3); }
    else if (r === "today") { from = new Date(now); from.setHours(0, 0, 0, 0); }
    $("#hvFrom").value = from ? fmtLocal(from) : "";
    $("#hvTo").value = to ? fmtLocal(to) : "";
  });
  $("#hvImport").addEventListener("click", async () => {
    const btn = $("#hvImport"); btn.disabled = true;
    $("#hvImpResult").textContent = "parsing…";
    try {
      const res = await post("/api/harvest/import", {
        character: $("#hvImpChar").value,
        start_ts: toEpoch($("#hvFrom").value),
        end_ts: toEpoch($("#hvTo").value),
      });
      if (res.ok) {
        $("#hvImpResult").textContent = res.imported_qty
          ? `+${res.imported_qty} harvested (${res.imported_items} items, ` +
            `${res.imported_rares} rare) merged in`
          : "no harvests found in that range";
        $("#hvImpResult").style.color = res.imported_qty ? "var(--good)" : "var(--muted)";
        loadHarvest();
      } else {
        $("#hvImpResult").textContent = "error: " + res.error;
        $("#hvImpResult").style.color = "var(--bad)";
      }
    } catch (e) { $("#hvImpResult").textContent = "failed"; }
    btn.disabled = false;
  });

  /* ---------------- notifications ---------------- */
  let audioCtx = null;
  function ctx() { return audioCtx || (audioCtx = new (window.AudioContext || window.webkitAudioContext)()); }
  function playSound(kind) {
    if (kind === "none") return;
    try {
      const c = ctx();
      const now = c.currentTime;
      const notes = kind === "alarm" ? [880, 660, 880, 660]
        : kind === "chime" ? [784, 1047] : [988, 1319];
      notes.forEach((f, i) => {
        const o = c.createOscillator(), g = c.createGain();
        o.type = kind === "alarm" ? "square" : "sine";
        o.frequency.value = f;
        const t0 = now + i * (kind === "alarm" ? 0.16 : 0.12);
        g.gain.setValueAtTime(0.0001, t0);
        g.gain.exponentialRampToValueAtTime(0.25, t0 + 0.01);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.22);
        o.connect(g); g.connect(c.destination);
        o.start(t0); o.stop(t0 + 0.24);
      });
    } catch {}
  }
  function speak(text) {
    try {
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.05; window.speechSynthesis.speak(u);
    } catch {}
  }
  function fireTrigger(msg) {
    playSound(msg.sound || "ding");
    if (msg.tts && msg.text) speak(msg.text);
    flashToast(msg.name || "Trigger", msg.text || msg.match || "",
      msg.sound === "alarm" ? "alarm" : "ding");
  }
  function firePaste(msg) {
    // server already copied via xclip/wl-copy; browser write is a best-effort backup
    if (msg.text) { try { navigator.clipboard.writeText(msg.text); } catch {} }
    playSound("chime");
    const where = msg.backend ? "✓ copied to clipboard (" + msg.backend + ")"
                              : "⚠ no clipboard tool — use Copy parse";
    const t = document.createElement("div");
    t.className = "toast paste";
    t.innerHTML = `<div class="tt">Parse copied — ${esc(msg.name || "fight")}</div>` +
      `<div class="tm" style="color:var(--accent)">${esc(where)}</div>` +
      `<pre class="pastebody">${esc(msg.text || "")}</pre>`;
    $("#toasts").appendChild(t);
    setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .5s";
      setTimeout(() => t.remove(), 500); }, 8000);
  }
  function fireArchived(msg) {
    if (msg.pruned && !msg.bytes) {
      flashToast("Archives pruned", msg.pruned + " old log(s) deleted", "ding");
    } else {
      const mb = msg.bytes ? (msg.bytes / 1048576).toFixed(1) + " MB" : "";
      flashToast("Log rolled", `${esc(msg.character || "")} — ${mb} archived` +
        (msg.reason === "auto" ? " (auto)" : ""), "ding");
    }
    if ($("#settings").classList.contains("active")) loadArchive();
  }
  function flashToast(title, body, kind) {
    const t = document.createElement("div");
    t.className = "toast" + (kind === "alarm" ? " alarm" : "");
    t.innerHTML = `<div class="tt">${esc(title)}</div>` +
      (body ? `<div class="tm">${esc(body)}</div>` : "");
    $("#toasts").appendChild(t);
    setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .4s";
      setTimeout(() => t.remove(), 400); }, 4200);
  }

  /* ---------------- helpers ---------------- */
  function durStr(sec) {
    sec = Math.floor(sec || 0);
    const m = Math.floor(sec / 60), s = sec % 60;
    return m ? `${m}m${String(s).padStart(2, "0")}s` : `${s}s`;
  }
  function esc(s) { return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function escA(s) { return esc(s).replace(/"/g, "&quot;"); }

  // tick live duration even when log is quiet
  setInterval(() => {
    if (selectedId === "live" && liveSummary && liveSummary.active) {
      liveSummary.duration += 1;
      $("#fightDur").textContent = durStr(liveSummary.duration);
    }
  }, 1000);

  /* ---------------- boot ---------------- */
  const initialTab = (location.hash || "").replace("#", "");
  if (["harvest", "triggers", "settings"].includes(initialTab)) activateTab(initialTab);
  connectSSE();
  refreshAll();
  setInterval(refreshAll, 3000);   // safety poll in case SSE drops
})();
