// School menus: tap a meal to see every dish with photos, allergens and nutrition.
document.addEventListener("alpine:init", () => {
  Alpine.data("menus", (url) => ({
    day: 0,
    all: null,
    menu: null,

    init() {
      const key = decodeURIComponent(location.hash.replace(/^#menu=/, ""));
      if (key && key !== location.hash) this.open(key);
    },

    async open(key) {
      if (!this.all) this.all = await (await fetch(url)).json();
      this.menu = this.all[key] || null;
      if (!this.menu) return;
      history.replaceState(null, "", "#menu=" + encodeURIComponent(key));
      this.$refs.dialog.showModal();
    },

    close() {
      this.$refs.dialog.close();
    },

    closed() {
      this.menu = null;
      history.replaceState(null, "", location.pathname);
    },

    heading(iso) {
      const [y, m, d] = iso.split("-").map(Number);
      return new Date(y, m - 1, d).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
    },
  }));
});
