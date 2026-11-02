// Front page: alerts a reader has closed stay closed (on this device) until a new alert comes along.
document.addEventListener("alpine:init", () => {
  const DISMISSED = "wus-dismissed-alerts";
  Alpine.store("dismissed", {
    ids: JSON.parse(localStorage.getItem(DISMISSED) || "[]"),
    has(id) {
      return this.ids.includes(id);
    },
    add(id) {
      this.ids = [...this.ids, id].slice(-200);
      localStorage.setItem(DISMISSED, JSON.stringify(this.ids));
    },
  });
});
