// Pages are written when the site is built, but read hours later. This keeps their
// dates true at reading time: "3 hours ago" and "Today" are recomputed in Spearfish
// time, and a note appears if the site itself has stopped updating.
(() => {
  const TZ = "America/Denver";
  const BEHIND_HOURS = 8; // the site rebuilds every 3 hours; this means at least two missed

  const parts = (iso) => iso.slice(0, 10).split("-").map(Number);
  const utcDay = (iso) => {
    const [y, m, d] = parts(iso);
    return Date.UTC(y, m - 1, d);
  };

  // Today's date in Spearfish, as YYYY-MM-DD, wherever the reader is
  const today = () =>
    new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());

  const addDays = (iso, n) => new Date(utcDay(iso) + n * 86400000).toISOString().slice(0, 10);
  const dayDiff = (a, b) => Math.round((utcDay(a) - utcDay(b)) / 86400000);
  const weekday = (iso) => new Date(utcDay(iso)).getUTCDay(); // 0 = Sunday
  const fmtDay = (iso, opts) => new Date(utcDay(iso)).toLocaleDateString("en-US", { timeZone: "UTC", ...opts });

  function dayLabel(iso) {
    const n = dayDiff(iso, today());
    if (n === 0) return "Today";
    if (n === 1) return "Tomorrow";
    if (n === -1) return "Yesterday";
    return fmtDay(iso, { weekday: "long", month: "long", day: "numeric" });
  }

  function ago(when) {
    const secs = (Date.now() - when.getTime()) / 1000;
    if (secs < 90) return "just now";
    for (const [unit, size] of [["day", 86400], ["hour", 3600], ["minute", 60]]) {
      if (secs >= size) {
        const n = Math.floor(secs / size);
        return `${n} ${unit}${n === 1 ? "" : "s"} ago`;
      }
    }
    return "just now";
  }

  function refresh() {
    for (const el of document.querySelectorAll("time[data-ago]")) {
      const text = ago(new Date(el.dateTime));
      el.textContent = el.hasAttribute("data-cap") ? text[0].toUpperCase() + text.slice(1) : text;
    }
    for (const el of document.querySelectorAll("time[data-day]")) {
      let label = dayLabel(el.dateTime);
      // mid-sentence: "Happening today", but "Happening Monday, November 2" once that day has passed
      if (el.hasAttribute("data-lower")) {
        const n = dayDiff(el.dateTime, today());
        label = n === 0 || n === 1 ? label.toLowerCase() : fmtDay(el.dateTime, { weekday: "long", month: "long", day: "numeric" });
      }
      el.textContent = label;
    }
    for (const el of document.querySelectorAll("[data-today]")) {
      el.textContent = fmtDay(today(), { weekday: "short", month: "short", day: "numeric" });
    }
    // meetings: "coming up" until they start, then past (data-moves-at, data-list="up" | "past")
    for (const el of document.querySelectorAll("[data-moves-at]")) {
      if (!el.dataset.movesAt) continue;
      const over = Date.now() >= new Date(el.dataset.movesAt).getTime();
      el.classList.toggle("hidden", el.dataset.list === "up" ? over : !over);
    }
    // a "coming up" list whose meetings have all started says so
    for (const note of document.querySelectorAll("[data-up-empty]")) {
      const items = note.parentElement.querySelectorAll('[data-list="up"]');
      const any = [...items].some((el) => !el.classList.contains("hidden"));
      note.classList.toggle("hidden", !!any);
    }
    const note = document.getElementById("behind");
    if (note) note.hidden = Date.now() - new Date(note.dataset.built).getTime() < BEHIND_HOURS * 3600000;
  }

  window.wus = { TZ, today, addDays, dayDiff, weekday, fmtDay, dayLabel, ago };
  document.addEventListener("DOMContentLoaded", refresh);
  setInterval(refresh, 60000);
})();
