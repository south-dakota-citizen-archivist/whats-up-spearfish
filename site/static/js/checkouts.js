// Library checkouts by month: one line per way of borrowing (physical items, Libby,
// Hoopla). Zero baseline, hairline grid, each line labeled at its end, crosshair
// and readout on hover. Colors come from the --series-N custom properties.
document.addEventListener("alpine:init", () => {
  const NS = "http://www.w3.org/2000/svg";
  const GRID = "#e7e5e4"; // stone-200
  const INK = "#67605a"; // stone-500 (darkened in input.css)
  const H = 224;
  const M = { top: 12, right: 64, bottom: 24, left: 44 };

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const monthTime = (ym) => {
    const [y, m] = ym.split("-").map(Number);
    return Date.UTC(y, m - 1, 15);
  };
  const monthsApart = (a, b) => {
    const [ya, ma] = a.split("-").map(Number);
    const [yb, mb] = b.split("-").map(Number);
    return (yb - ya) * 12 + (mb - ma);
  };
  const monthName = (ym) =>
    new Date(monthTime(ym)).toLocaleDateString("en-US", { timeZone: "UTC", month: "long", year: "numeric" });

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

  Alpine.data("checkoutsChart", () => ({
    readout: null,

    init() {
      const { rows, series } = JSON.parse(this.$refs.data.textContent);
      this.rows = rows;
      this.series = series.map(([key, label], i) => ({ key, label, short: label.split(" ")[0], color: css(`--series-${i + 1}`) }));
      new ResizeObserver(() => this.draw()).observe(this.$refs.box);
    },

    draw() {
      const box = this.$refs.box;
      const rows = this.rows;
      box.replaceChildren();
      this.readout = null;
      if (rows.length < 2) return;

      const W = box.clientWidth;
      const iw = W - M.left - M.right;
      const ih = H - M.top - M.bottom;
      const t0 = monthTime(rows[0].month);
      const t1 = monthTime(rows[rows.length - 1].month);
      const max = Math.max(...rows.flatMap((r) => this.series.map((s) => r[s.key] || 0)));
      const step = niceStep(max * 1.05 || 1);
      const ymax = Math.ceil((max * 1.05) / step) * step;
      const x = (t) => M.left + ((t - t0) / (t1 - t0)) * iw;
      const y = (v) => M.top + ih - (v / ymax) * ih;

      const svg = el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: "block select-none" });
      svg.setAttribute("aria-hidden", "true");

      for (let v = 0; v <= ymax; v += step) {
        svg.append(el("line", { x1: M.left, x2: W - M.right, y1: y(v), y2: y(v), stroke: GRID, "stroke-width": 1 }));
        svg.append(el("text", { x: M.left - 6, y: y(v) + 4, "text-anchor": "end", "font-size": 11, fill: INK }, v.toLocaleString()));
      }

      // a tick each January; on narrow screens label every other year
      const first = Number(rows[0].month.slice(0, 4)) + 1;
      const last = Number(rows[rows.length - 1].month.slice(0, 4));
      const every = iw / (last - first + 1) < 44 ? 2 : 1;
      for (let yr = first; yr <= last; yr++) {
        const tx = x(Date.UTC(yr, 0, 1));
        svg.append(el("line", { x1: tx, x2: tx, y1: M.top + ih, y2: M.top + ih + 4, stroke: INK, "stroke-width": 1 }));
        if ((yr - first) % every === 0) {
          svg.append(el("text", { x: tx, y: H - 6, "text-anchor": "middle", "font-size": 11, fill: INK }, String(yr)));
        }
      }

      // one line per series, broken across missing months
      const ends = [];
      for (const s of this.series) {
        let d = "";
        let prev = null;
        let end = null;
        for (const r of rows) {
          const v = r[s.key];
          if (v == null) {
            prev = null;
            continue;
          }
          const join = prev && monthsApart(prev, r.month) === 1;
          d += `${join ? "L" : "M"}${x(monthTime(r.month)).toFixed(1)},${y(v).toFixed(1)}`;
          prev = r.month;
          end = { t: monthTime(r.month), v };
        }
        if (!end) continue;
        svg.append(el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
        ends.push({ ...end, s, ly: y(end.v) });
      }

      // end dots, and labels nudged apart so they never overlap
      ends.sort((a, b) => a.ly - b.ly);
      for (let i = 1; i < ends.length; i++) ends[i].ly = Math.max(ends[i].ly, ends[i - 1].ly + 13);
      for (const e of ends) {
        const cx = x(e.t);
        svg.append(el("circle", { cx, cy: y(e.v), r: 4, fill: e.s.color, stroke: "#fff", "stroke-width": 2 }));
        svg.append(el("text", { x: cx + 8, y: e.ly + 4, "font-size": 11, "font-weight": 600, fill: "#1c1917" }, e.s.short));
      }

      // hover: crosshair snaps to the nearest month
      const cross = el("line", { y1: M.top, y2: M.top + ih, stroke: INK, "stroke-width": 1, visibility: "hidden" });
      const dots = this.series.map((s) => el("circle", { r: 4, fill: s.color, stroke: "#fff", "stroke-width": 2, visibility: "hidden" }));
      const hit = el("rect", { x: M.left, y: M.top, width: iw, height: ih, fill: "transparent" });
      svg.append(cross, ...dots, hit);
      const show = (evt) => {
        const px = evt.clientX - svg.getBoundingClientRect().left;
        const t = t0 + ((px - M.left) / iw) * (t1 - t0);
        const r = rows.reduce((a, b) => (Math.abs(monthTime(b.month) - t) < Math.abs(monthTime(a.month) - t) ? b : a));
        const cx = x(monthTime(r.month));
        cross.setAttribute("x1", cx);
        cross.setAttribute("x2", cx);
        cross.setAttribute("visibility", "visible");
        this.series.forEach((s, i) => {
          const v = r[s.key];
          dots[i].setAttribute("visibility", v == null ? "hidden" : "visible");
          if (v != null) {
            dots[i].setAttribute("cx", cx);
            dots[i].setAttribute("cy", y(v));
          }
        });
        this.readout = {
          when: monthName(r.month),
          left: Math.min(Math.max(cx, 90), W - 90),
          lines: this.series.filter((s) => r[s.key] != null).map((s) => ({ label: s.label, color: s.color, value: r[s.key].toLocaleString() })),
        };
      };
      hit.addEventListener("pointermove", show);
      hit.addEventListener("pointerdown", show);
      hit.addEventListener("pointerleave", () => {
        cross.setAttribute("visibility", "hidden");
        dots.forEach((d) => d.setAttribute("visibility", "hidden"));
        this.readout = null;
      });
      box.append(svg);
    },
  }));
});
