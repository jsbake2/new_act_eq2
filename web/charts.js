/* Tiny hand-rolled canvas charts — no external libs, dark Grafana look. */
(function (global) {
  const PALETTE = [
    "#36c2ce", "#7b6cf0", "#3fb950", "#e3b341", "#f0556a",
    "#58a6ff", "#db61a2", "#56d364", "#f0883e", "#a371f7",
    "#2dd4bf", "#facc15",
  ];

  // colors come from CSS custom properties so the theme picker restyles charts
  const cssVars = () => getComputedStyle(document.documentElement);
  let _pal = null, _ink = null;
  function themeVar(name, fb) { const v = cssVars().getPropertyValue(name).trim(); return v || fb; }
  function palette() {
    if (_pal) return _pal;
    const cs = cssVars(); const out = [];
    for (let i = 1; i <= 12; i++) { const v = cs.getPropertyValue("--chart-" + i).trim(); if (v) out.push(v); }
    _pal = out.length ? out : PALETTE; return _pal;
  }
  function ink() {
    if (_ink) return _ink;
    _ink = { grid: themeVar("--line", "#222a35"), label: themeVar("--dim", "#5a6573"),
             text: themeVar("--text", "#d6dde7"), sub: themeVar("--muted", "#7d8896") };
    return _ink;
  }
  function refreshPalette() { _pal = null; _ink = null; }
  function colorFor(i) { const p = palette(); return p[i % p.length]; }

  function fmt(n) {
    n = +n || 0;
    const a = Math.abs(n);
    if (a >= 1e12) return (n / 1e12).toFixed(2) + "T";
    if (a >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return n.toFixed(0);
  }

  /* data = { seconds:[...], series:{name:[per-second dmg...]} }  (stacked area of DPS) */
  function drawStacked(canvas, data, opts) {
    opts = opts || {};
    const dpr = global.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 600;
    const cssH = opts.height || canvas.height || 240;
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const padL = 52, padR = 12, padT = 12, padB = 22;
    const W = cssW - padL - padR, H = cssH - padT - padB;
    const secs = data.seconds || [];
    const names = Object.keys(data.series || {});

    // smooth DPS: convert per-second damage to a rolling DPS-ish value (window)
    const win = 1;
    const n = secs.length;
    if (n === 0 || names.length === 0) {
      ctx.fillStyle = ink().label;
      ctx.font = "13px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("no data yet", cssW / 2, cssH / 2);
      return [];
    }

    // stacked totals per second to find y-max
    const stacks = new Array(n).fill(0);
    for (let i = 0; i < n; i++) {
      let s = 0;
      for (const nm of names) s += (data.series[nm][i] || 0);
      stacks[i] = s;
    }
    let ymax = Math.max(1, ...stacks);
    ymax *= 1.1;

    const x = (i) => padL + (n === 1 ? W / 2 : (i / (n - 1)) * W);
    const y = (v) => padT + H - (v / ymax) * H;

    // grid + y labels
    ctx.strokeStyle = ink().grid;
    ctx.fillStyle = ink().label;
    ctx.font = "10px JetBrains Mono, monospace";
    ctx.textAlign = "right";
    ctx.lineWidth = 1;
    for (let g = 0; g <= 4; g++) {
      const gy = padT + (H * g) / 4;
      ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + W, gy); ctx.stroke();
      ctx.fillText(fmt(ymax * (1 - g / 4)), padL - 6, gy + 3);
    }
    // x labels (time)
    ctx.textAlign = "center";
    const step = Math.max(1, Math.ceil(n / 8));
    for (let i = 0; i < n; i += step) {
      ctx.fillText(secs[i] + "s", x(i), padT + H + 15);
    }

    // draw stacked areas (bottom-up)
    const baseline = new Array(n).fill(0);
    // order by total desc so big contributors are at the bottom
    const order = names.slice().sort((a, b) => {
      const sa = data.series[a].reduce((p, c) => p + c, 0);
      const sb = data.series[b].reduce((p, c) => p + c, 0);
      return sb - sa;
    });
    const legend = [];
    order.forEach((nm, idx) => {
      const col = colorFor(idx);
      legend.push({ name: nm, color: col });
      const arr = data.series[nm];
      ctx.beginPath();
      // top edge
      for (let i = 0; i < n; i++) {
        const v = baseline[i] + (arr[i] || 0);
        const px = x(i), py = y(v);
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      // back along baseline
      for (let i = n - 1; i >= 0; i--) {
        ctx.lineTo(x(i), y(baseline[i]));
      }
      ctx.closePath();
      const grad = ctx.createLinearGradient(0, padT, 0, padT + H);
      grad.addColorStop(0, hexA(col, 0.55));
      grad.addColorStop(1, hexA(col, 0.06));
      ctx.fillStyle = grad;
      ctx.fill();
      // top line
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const v = baseline[i] + (arr[i] || 0);
        const px = x(i), py = y(v);
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.stroke();
      for (let i = 0; i < n; i++) baseline[i] += (arr[i] || 0);
    });
    return legend;
  }

  function hexA(hex, a) {
    const h = hex.replace("#", "");
    const r = parseInt(h.substr(0, 2), 16);
    const g = parseInt(h.substr(2, 2), 16);
    const b = parseInt(h.substr(4, 2), 16);
    return `rgba(${r},${g},${b},${a})`;
  }

  /* items = [{label, value}] -> donut chart. Returns [{label,color,value,pct}]. */
  function drawDonut(canvas, items, opts) {
    opts = opts || {};
    const dpr = global.devicePixelRatio || 1;
    const size = opts.size || 220;
    canvas.width = size * dpr; canvas.height = size * dpr;
    canvas.style.width = size + "px"; canvas.style.height = size + "px";
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    const total = items.reduce((s, i) => s + (i.value || 0), 0);
    const cx = size / 2, cy = size / 2, r = size / 2 - 6, inner = r * 0.58;
    const out = [];
    if (total <= 0) {
      ctx.fillStyle = ink().label; ctx.font = "13px Inter"; ctx.textAlign = "center";
      ctx.fillText("no data", cx, cy); return out;
    }
    let a0 = -Math.PI / 2;
    items.forEach((it, i) => {
      const frac = (it.value || 0) / total;
      const a1 = a0 + frac * Math.PI * 2;
      const col = colorFor(i);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, r, a0, a1);
      ctx.closePath();
      ctx.fillStyle = col; ctx.fill();
      out.push({ label: it.label, color: col, value: it.value, pct: frac * 100 });
      a0 = a1;
    });
    // punch the hole
    ctx.globalCompositeOperation = "destination-out";
    ctx.beginPath(); ctx.arc(cx, cy, inner, 0, Math.PI * 2); ctx.fill();
    ctx.globalCompositeOperation = "source-over";
    // center label
    ctx.fillStyle = ink().text; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.font = "600 18px JetBrains Mono, monospace";
    ctx.fillText(fmt(total), cx, cy - 6);
    ctx.fillStyle = ink().sub; ctx.font = "10px Inter";
    ctx.fillText(opts.centerLabel || "total", cx, cy + 12);
    return out;
  }

  global.EQChart = { drawStacked, drawDonut, colorFor, fmt, refreshPalette };
})(window);
