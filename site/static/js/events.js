// Unified events calendar: loads events.json and filters it client-side.
document.addEventListener("alpine:init", () => {
  Alpine.data("calendar", (url) => ({
    all: [],
    loading: true,
    q: "",
    range: "week",
    cats: [],
    source: "",
    limit: 150,

    async init() {
      if (location.hash === "#weekend") this.range = "weekend";
      const r = await fetch(url);
      this.all = await r.json();
      this.loading = false;
    },

    iso(d) {
      const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
      return z.toISOString().slice(0, 10);
    },

    bounds() {
      const today = new Date();
      const t = this.iso(today);
      const plus = (n) => this.iso(new Date(today.getFullYear(), today.getMonth(), today.getDate() + n));
      switch (this.range) {
        case "today":
          return [t, t];
        case "weekend": {
          // Saturday–Sunday; on a Sunday, just today
          const dow = today.getDay();
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
        if (this.source && e.source_label !== this.source && !e.also.some((a) => a.source === this.source)) return false;
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

    heading(iso) {
      const t = this.iso(new Date());
      const tomorrow = this.iso(new Date(Date.now() + 86400000));
      if (iso === t) return "Today";
      if (iso === tomorrow) return "Tomorrow";
      const [y, m, d] = iso.split("-").map(Number);
      return new Date(y, m - 1, d).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
    },
  }));
});
