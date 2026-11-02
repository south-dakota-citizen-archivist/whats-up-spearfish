// School menus: tap a meal to see every dish with photos, allergens and nutrition.
document.addEventListener("alpine:init", () => {
  Alpine.data("menus", (url, dates = []) => ({
    day: 0,
    all: null,
    menu: null,
    error: "",

    init() {
      // Start on today's menus (or the next school day), even if the page was built yesterday
      const i = dates.findIndex((d) => d >= wus.today());
      if (i > 0) this.day = i;
      const key = decodeURIComponent(location.hash.replace(/^#menu=/, ""));
      if (key && key !== location.hash) this.open(key);
    },

    async open(key) {
      this.error = "";
      if (!this.all) {
        try {
          const r = await fetch(url);
          if (!r.ok) throw new Error(r.status);
          this.all = await r.json();
        } catch {
          this.error = "The full menu didn't load. Check your connection and try again.";
          return;
        }
      }
      this.menu = this.all[key] || null;
      if (!this.menu) {
        this.error = "That menu isn't posted any more. Here are the current ones.";
        history.replaceState(null, "", location.pathname);
        return;
      }
      history.replaceState(null, "", "#menu=" + encodeURIComponent(key));
      // open once the contents are drawn, so focus lands inside them
      await this.$nextTick();
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
