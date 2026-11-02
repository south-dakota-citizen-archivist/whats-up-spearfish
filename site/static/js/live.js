// Front page: alerts a reader has closed stay closed (on this device) until a new alert comes along.
document.addEventListener("alpine:init", () => {
  const DISMISSED = "wus-dismissed-alerts";
  Alpine.store("dismissed", {
    ids: (() => {
      try {
        return JSON.parse(localStorage.getItem(DISMISSED)) || [];
      } catch {
        return []; // unreadable or blocked storage: show every alert rather than none
      }
    })(),
    has(id) {
      return this.ids.includes(id);
    },
    add(id) {
      this.ids = [...this.ids, id].slice(-200);
      try {
        localStorage.setItem(DISMISSED, JSON.stringify(this.ids));
      } catch {
        // can't remember it, but it's still closed for this visit
      }
    },
  });
});
