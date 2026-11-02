// "What's being built here?" — permit and application lookup by address, search or location.
document.addEventListener("alpine:init", () => {
  // Map dot colors by category (see permit_category in sitegen/pages.py)
  const CATEGORIES = {
    r: { label: "Residential", color: "#2563eb" },
    c: { label: "Commercial", color: "#ea580c" },
    l: { label: "Land, streets & zoning", color: "#a21caf" },
    o: { label: "Other", color: "#a8a29e" },
  };

  Alpine.data("permits", (url, latestReport) => {
    // Leaflet objects live outside Alpine's reactive state.
    let map = null;
    let markers = null;
    let youAreHere = null;

    return {
      sites: [],
      loading: true,
      error: "",
      q: "",
      since: "2",
      categories: CATEGORIES,
      show: { r: true, c: true, l: true, o: true },
      here: null,
      locating: false,
      selected: null,

      async init() {
        this.sites = await (await fetch(url)).json();
        this.loading = false;
        this.$nextTick(() => {
          map = L.map(this.$refs.map, { preferCanvas: true }).setView([44.4906, -103.8594], 13);
          L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          }).addTo(map);
          markers = L.layerGroup().addTo(map);
          this.draw();
          const key = decodeURIComponent(location.hash.replace(/^#site=/, ""));
          const s = key && this.sites.find((x) => x.k === key);
          if (s) this.select(s);
        });
        this.$watch("since", () => this.draw());
        this.$watch("show", () => this.draw(), { deep: true });
        this.$watch("q", () => {
          const pts = this.q.trim() ? this.results.filter((s) => s.lat != null).map((s) => [s.lat, s.lon]) : [];
          if (map && pts.length) map.fitBounds(pts, { maxZoom: 17, padding: [30, 30] });
        });
      },

      cutoff() {
        if (this.since === "all" || this.since === "latest") return "";
        const d = new Date();
        d.setFullYear(d.getFullYear() - Number(this.since));
        return d.toISOString().slice(0, 10);
      },

      // Records that fall in the chosen time period
      inPeriod(r) {
        if (this.since === "latest") return r.src === "permit" && (r.d || "").startsWith(latestReport);
        const c = this.cutoff();
        return !c || (r.d || "") >= c;
      },

      // A site's category: its most recent residential/commercial/land record in the period
      category(s) {
        const recs = s.r.filter((r) => this.inPeriod(r));
        return (recs.find((r) => r.c && r.c !== "o") || recs[0] || s.r[0]).c || "o";
      },

      inRange() {
        return this.sites.filter((s) => s.r.some((r) => this.inPeriod(r)) && this.show[this.category(s)]);
      },

      color(s) {
        return CATEGORIES[this.category(s)].color;
      },

      draw() {
        if (!markers) return;
        markers.clearLayers();
        for (const s of this.inRange()) {
          if (s.lat == null) continue;
          L.circleMarker([s.lat, s.lon], { radius: 6, weight: 1, color: "#1c1917", fillColor: this.color(s), fillOpacity: 0.9 })
            .on("click", () => this.select(s))
            .addTo(markers);
        }
      },

      get results() {
        const q = this.q.trim().toLowerCase();
        if (q) {
          const words = q.split(/\s+/);
          return this.sites
            .filter((s) => {
              const hay = (s.a + " " + s.r.map((r) => [r.no, r.t, r.con, r.who, r.own, r.desc].join(" ")).join(" ")).toLowerCase();
              return words.every((w) => hay.includes(w));
            })
            .slice(0, 60);
        }
        const pool = this.inRange();
        if (this.here) {
          return pool
            .filter((s) => s.lat != null)
            .map((s) => ({ ...s, dist: this.distance(this.here, s) }))
            .sort((a, b) => a.dist - b.dist)
            .slice(0, 30);
        }
        return pool.slice(0, 40);
      },

      near() {
        if (!navigator.geolocation) {
          this.error = "Your browser can't share its location.";
          return;
        }
        this.locating = true;
        this.error = "";
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            this.locating = false;
            this.q = "";
            this.selected = null;
            this.here = { lat: pos.coords.latitude, lon: pos.coords.longitude };
            if (youAreHere) youAreHere.remove();
            youAreHere = L.circleMarker([this.here.lat, this.here.lon], { radius: 8, weight: 3, color: "#0369a1", fillColor: "#38bdf8", fillOpacity: 1 }).addTo(map);
            map.setView([this.here.lat, this.here.lon], 17);
          },
          () => {
            this.locating = false;
            this.error = "Couldn't get your location. Check your browser's location permission, or search by address.";
          },
          { enableHighAccuracy: true, timeout: 15000 },
        );
      },

      select(s) {
        this.selected = s;
        history.replaceState(null, "", "#site=" + encodeURIComponent(s.k));
        if (s.lat != null && map) map.setView([s.lat, s.lon], Math.max(map.getZoom(), 17));
        this.$nextTick(() => this.$refs.detail?.scrollIntoView({ behavior: "smooth", block: "start" }));
      },

      distance(a, b) {
        const R = 6371000;
        const rad = (x) => (x * Math.PI) / 180;
        const dLat = rad(b.lat - a.lat);
        const dLon = rad(b.lon - a.lon);
        const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
        return 2 * R * Math.asin(Math.sqrt(h));
      },

      feet(m) {
        const ft = m * 3.28084;
        return ft < 1000 ? `${Math.round(ft / 10) * 10} ft` : `${(ft / 5280).toFixed(1)} mi`;
      },

      money(v) {
        return v ? "$" + Math.round(v).toLocaleString() : "";
      },

      day(iso) {
        if (!iso) return "";
        const [y, m, d] = iso.split("-").map(Number);
        return new Date(y, m - 1, d || 1).toLocaleDateString("en-US", { month: "short", day: d ? "numeric" : undefined, year: "numeric" });
      },
    };
  });
});
