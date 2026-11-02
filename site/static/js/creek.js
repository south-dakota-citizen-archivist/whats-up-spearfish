// Spearfish Creek flow chart: past 7 days (hourly readings) or past 30 days (daily averages).
// One series, zero baseline, hairline grid, end label, crosshair + readout on hover.
document.addEventListener("alpine:init", () => {
  const NS = "http://www.w3.org/2000/svg";
  const LINE = "#0284c7"; // sky-600
  const GRID = "#e7e5e4"; // stone-200
  const INK = "#78716c"; // stone-500
  const H = 240;
  const M = { top: 14, right: 44, bottom: 26, left: 40 };

  const localDate = (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d, 12);
  };
  const fmt = (d, opts) => d.toLocaleString("en-US", opts);

  function niceStep(max) {
    const raw = max / 4;
    const mag = 10 ** Math.floor(Math.log10(raw));
    return [1, 2, 2.5, 5, 10].map((s) => s * mag).find((s) => s >= raw);
  }

  function el(name, attrs, text) {
    const n = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text != null) n.textContent = text;
    return n;
  }

  Alpine.data("creekChart", () => ({
    range: "7",
    readout: null,

    init() {
      this.data = JSON.parse(this.$refs.data.textContent);
      this.$watch("range", () => this.draw());
      new ResizeObserver(() => this.draw()).observe(this.$refs.box);
    },

    points() {
      if (this.range === "7") return this.data.series7d.map((p) => ({ t: new Date(p.t), v: p.cfs, hourly: true }));
      return this.data.daily30.map((p) => ({ t: localDate(p.date), v: p.cfs, hourly: false }));
    },

    label(p) {
      return p.hourly
        ? fmt(p.t, { weekday: "short", month: "short", day: "numeric", hour: "numeric" })
        : fmt(p.t, { weekday: "short", month: "short", day: "numeric" }) + " (daily average)";
    },

    draw() {
      const box = this.$refs.box;
      const pts = this.points();
      box.replaceChildren();
      this.readout = null;
      if (pts.length < 2) return;

      const W = box.clientWidth;
      const iw = W - M.left - M.right;
      const ih = H - M.top - M.bottom;
      const t0 = pts[0].t.getTime();
      const t1 = pts[pts.length - 1].t.getTime();
      const step = niceStep(Math.max(...pts.map((p) => p.v)) * 1.1 || 1);
      const ymax = step * 4;
      const x = (t) => M.left + ((t - t0) / (t1 - t0)) * iw;
      const y = (v) => M.top + ih - (v / ymax) * ih;

      const svg = el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: "block select-none" });
      svg.setAttribute("aria-hidden", "true");

      // y grid + labels
      for (let v = 0; v <= ymax; v += step) {
        svg.append(el("line", { x1: M.left, x2: W - M.right, y1: y(v), y2: y(v), stroke: GRID, "stroke-width": 1 }));
        svg.append(el("text", { x: M.left - 6, y: y(v) + 4, "text-anchor": "end", "font-size": 11, fill: INK }, v.toLocaleString()));
      }

      // x ticks: midnights (7 days) or every 7th day (30 days); thin out on narrow screens
      const ticks = [];
      const d = new Date(t0);
      d.setHours(0, 0, 0, 0);
      const every = this.range === "7" ? (iw < 320 ? 2 : 1) : iw < 320 ? 10 : 7;
      for (d.setDate(d.getDate() + 1); d.getTime() <= t1; d.setDate(d.getDate() + every)) ticks.push(new Date(d));
      for (const tk of ticks) {
        const tx = x(tk.getTime());
        svg.append(el("line", { x1: tx, x2: tx, y1: M.top + ih, y2: M.top + ih + 4, stroke: INK, "stroke-width": 1 }));
        const text = this.range === "7" ? fmt(tk, { weekday: "short" }) : fmt(tk, { month: "short", day: "numeric" });
        svg.append(el("text", { x: tx, y: H - 6, "text-anchor": "middle", "font-size": 11, fill: INK }, text));
      }

      // area wash + line
      const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p.t.getTime()).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
      svg.append(el("path", { d: `${line}L${x(t1)},${y(0)}L${x(t0)},${y(0)}Z`, fill: LINE, "fill-opacity": 0.1 }));
      svg.append(el("path", { d: line, fill: "none", stroke: LINE, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));

      // latest value: end dot (with surface ring) + label
      const last = pts[pts.length - 1];
      svg.append(el("circle", { cx: x(t1), cy: y(last.v), r: 4, fill: LINE, stroke: "#fff", "stroke-width": 2 }));
      svg.append(el("text", { x: x(t1) + 8, y: y(last.v) + 4, "font-size": 12, "font-weight": 600, fill: "#1c1917" }, last.v.toLocaleString()));

      // hover: crosshair snaps to the nearest reading
      const cross = el("line", { y1: M.top, y2: M.top + ih, stroke: INK, "stroke-width": 1, visibility: "hidden" });
      const dot = el("circle", { r: 4, fill: LINE, stroke: "#fff", "stroke-width": 2, visibility: "hidden" });
      const hit = el("rect", { x: M.left, y: M.top, width: iw, height: ih, fill: "transparent" });
      svg.append(cross, dot, hit);
      const show = (evt) => {
        const px = evt.clientX - svg.getBoundingClientRect().left;
        const t = t0 + ((px - M.left) / iw) * (t1 - t0);
        const p = pts.reduce((a, b) => (Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a));
        const cx = x(p.t.getTime());
        cross.setAttribute("x1", cx);
        cross.setAttribute("x2", cx);
        dot.setAttribute("cx", cx);
        dot.setAttribute("cy", y(p.v));
        cross.setAttribute("visibility", "visible");
        dot.setAttribute("visibility", "visible");
        this.readout = { value: p.v.toLocaleString(), when: this.label(p), left: Math.min(Math.max(cx, 80), W - 80) };
      };
      hit.addEventListener("pointermove", show);
      hit.addEventListener("pointerdown", show);
      hit.addEventListener("pointerleave", () => {
        cross.setAttribute("visibility", "hidden");
        dot.setAttribute("visibility", "hidden");
        this.readout = null;
      });
      box.append(svg);
    },
  }));
});
