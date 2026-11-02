// Unified events calendar: loads events.json and filters it client-side.
// Readers can pick events and add just those to their own calendar: a
// calendar file built in the browser, or Google Calendar links.

const PICKS_KEY = "wus-picked-events";

// "2026-11-02T11:00:00-07:00" → "20261102T180000Z"; "2026-11-06" → "20261106"
function icsTime(value) {
  if (value.length === 10) return value.replaceAll("-", "");
  return new Date(value).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
}

function nextDay(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + 1));
  return t.toISOString().slice(0, 10);
}

// Start and end as calendar values. All-day ends are the day after (calendars
// treat them as exclusive); timed events without an end get an hour.
function span(e) {
  if (e.all_day) {
    const start = e.start.slice(0, 10);
    const last = e.end ? e.end.slice(0, 10) : start;
    return [icsTime(start), icsTime(nextDay(last < start ? start : last))];
  }
  const end = e.end || new Date(new Date(e.start).getTime() + 3600000).toISOString();
  return [icsTime(e.start), icsTime(end)];
}

function details(e) {
  return [e.description, e.url].filter(Boolean).join("\n\n");
}

function icsText(s) {
  return String(s).replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}

// Calendar files want lines of at most 75 bytes, continued with a leading space.
function fold(line) {
  const enc = new TextEncoder();
  const out = [];
  let cur = "";
  let bytes = 0;
  for (const ch of line) {
    const n = enc.encode(ch).length;
    if (bytes + n > (out.length ? 74 : 75)) {
      out.push(cur);
      cur = "";
      bytes = 0;
    }
    cur += ch;
    bytes += n;
  }
  out.push(cur);
  return out.join("\r\n ");
}

function buildIcs(events) {
  const stamp = icsTime(new Date().toISOString());
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//What's up, Spearfish?//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"];
  for (const e of events) {
    const [start, end] = span(e);
    const kind = e.all_day ? ";VALUE=DATE" : "";
    lines.push(
      "BEGIN:VEVENT",
      `UID:${e.id}@whats-up-spearfish`,
      `DTSTAMP:${stamp}`,
      `DTSTART${kind}:${start}`,
      `DTEND${kind}:${end}`,
      `SUMMARY:${icsText(e.title)}`,
    );
    if (e.location) lines.push(`LOCATION:${icsText(e.location)}`);
    if (details(e)) lines.push(`DESCRIPTION:${icsText(details(e))}`);
    if (e.url) lines.push(`URL:${e.url}`);
    lines.push("END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.map(fold).join("\r\n") + "\r\n";
}

function googleLink(e) {
  const p = new URLSearchParams({ action: "TEMPLATE", text: e.title, dates: span(e).join("/") });
  if (details(e)) p.set("details", details(e));
  if (e.location) p.set("location", e.location);
  return `https://calendar.google.com/calendar/render?${p}`;
}

document.addEventListener("alpine:init", () => {
  Alpine.data("calendar", (url) => ({
    all: [],
    loading: true,
    error: false,
    q: "",
    range: "week",
    cats: [],
    limit: 150,
    picked: [],
    showPicked: false,

    async init() {
      if (location.hash === "#weekend") this.range = "weekend";
      try {
        this.picked = JSON.parse(localStorage.getItem(PICKS_KEY)) || [];
      } catch {
        this.picked = [];
      }
      try {
        const r = await fetch(url);
        if (!r.ok) throw new Error(r.status);
        this.all = await r.json();
      } catch {
        this.error = true;
        this.loading = false;
        return;
      }
      // events that have since passed drop off the list
      const ids = new Set(this.all.map((e) => e.id));
      this.picked = this.picked.filter((id) => ids.has(id));
      this.$watch("picked", (v) => {
        try {
          localStorage.setItem(PICKS_KEY, JSON.stringify(v));
        } catch {
          // picks still work for this visit; they just won't be remembered
        }
      });
      this.loading = false;
    },

    isPicked(e) {
      return this.picked.includes(e.id);
    },

    pick(e) {
      this.picked = this.isPicked(e) ? this.picked.filter((id) => id !== e.id) : [...this.picked, e.id];
      if (!this.picked.length) this.showPicked = false;
    },

    clearPicks() {
      this.picked = [];
      this.showPicked = false;
    },

    get pickedEvents() {
      const ids = new Set(this.picked);
      return this.all.filter((e) => ids.has(e.id));
    },

    googleLink,

    download() {
      const blob = new Blob([buildIcs(this.pickedEvents)], { type: "text/calendar;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = this.picked.length === 1 ? "spearfish-event.ics" : "spearfish-events.ics";
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    },

    // Date ranges in Spearfish time (wus helpers from time.js), whatever the reader's time zone
    bounds() {
      const t = wus.today();
      const plus = (n) => wus.addDays(t, n);
      switch (this.range) {
        case "today":
          return [t, t];
        case "weekend": {
          // Saturday–Sunday; on a Sunday, just today
          const dow = wus.weekday(t);
          if (dow === 0) return [t, t];
          return [plus(6 - dow), plus(7 - dow)];
        }
        case "week":
          return [t, plus(6)];
        case "month":
          return [t, plus(30)];
        default:
          return [t, "9999"];
      }
    },

    get filtered() {
      const [lo, hi] = this.bounds();
      const q = this.q.trim().toLowerCase();
      return this.all.filter((e) => {
        const end = e.end ? e.end.slice(0, 10) : e.date;
        if (end < lo || e.date > hi) return false;
        if (this.cats.length && !this.cats.includes(e.category)) return false;
        if (q && !`${e.title} ${e.location} ${e.description}`.toLowerCase().includes(q)) return false;
        return true;
      });
    },

    get days() {
      const [lo] = this.bounds();
      const groups = [];
      let current = null;
      for (const e of this.filtered.slice(0, this.limit)) {
        const day = e.date < lo ? lo : e.date;
        if (!current || current.date !== day) {
          current = { date: day, events: [] };
          groups.push(current);
        }
        current.events.push(e);
      }
      return groups;
    },

    toggle(cat) {
      this.cats = this.cats.includes(cat) ? this.cats.filter((c) => c !== cat) : [...this.cats, cat];
      this.limit = 150;
    },

    shortDay(iso) {
      return wus.fmtDay(iso, { month: "short", day: "numeric" });
    },

    heading(iso) {
      const label = wus.dayLabel(iso);
      return label === "Yesterday" ? wus.fmtDay(iso, { weekday: "long", month: "long", day: "numeric" }) : label;
    },
  }));
});
