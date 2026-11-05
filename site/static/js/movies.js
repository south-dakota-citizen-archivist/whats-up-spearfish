// Movie showtimes, one day at a time. The page is built ahead of time, so the day it
// opens on is picked here, in Spearfish time: the first day with a show still to come.
// Shows that have already started that day are struck through, and that's kept
// current while the page stays open.
//
//   <div x-data="showtimes" data-days='[{"date": "2026-11-05", "last": "2026-11-05T18:45"}, …]'>
//     <button @click="day = '2026-11-05'" x-text="label('2026-11-05')">…</button>
//     <p x-show="day === '2026-11-05'"><span :class="past('2026-11-05T15:30') && '…'">3:30 PM</span></p>
//   </div>
document.addEventListener("alpine:init", () => {
  const TZ = "America/Denver";

  // now in Spearfish as 'YYYY-MM-DDTHH:MM', to compare with showtimes as text
  function spearfishNow() {
    const p = Object.fromEntries(
      new Intl.DateTimeFormat("en-CA", {
        timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
      }).formatToParts(new Date()).map((x) => [x.type, x.value]),
    );
    return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
  }

  const dayDiff = (a, b) => Math.round((Date.parse(a.slice(0, 10)) - Date.parse(b.slice(0, 10))) / 86400000);

  Alpine.data("showtimes", () => ({
    days: [],
    day: "",
    now: "",

    init() {
      this.days = JSON.parse(this.$el.dataset.days || "[]");
      this.now = spearfishNow();
      const next = this.days.find((d) => d.last > this.now) || this.days[this.days.length - 1];
      if (next) this.day = next.date;
      setInterval(() => (this.now = spearfishNow()), 60000);
    },
    past(at) {
      return at <= this.now;
    },
    label(iso) {
      const n = dayDiff(iso, this.now);
      if (n === 0) return "Today";
      if (n === 1) return "Tomorrow";
      return new Date(Date.parse(iso)).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });
    },
  }));
});
