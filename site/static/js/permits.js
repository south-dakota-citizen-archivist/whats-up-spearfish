// "What's being built here?" — permit and application lookup by address, search or location.
document.addEventListener("alpine:init", () => {
  // Map dot colors by category (see permit_category in sitegen/pages.py)
  const CATEGORIES = {
    r: { label: "Residential", color: "#2563eb" },
    c: { label: "Commercial", color: "#ea580c" },
    l: { label: "Land, streets & zoning", color: "#a21caf" },
    o: { label: "Other", color: "#a8a29e" },
  };

  // Readers who ask for less motion get instant jumps instead of glides
  const calm = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const glide = () => (calm() ? { animate: false } : { duration: 0.8 });
  const scrollMode = () => (calm() ? "auto" : "smooth");

  // recentUrl: places active in the past two years (what the page opens on);
  // allUrl: every place, fetched when a reader searches or looks further back
  Alpine.data("permits", (recentUrl, allUrl, latestReport, outlinesUrl, beacon) => {
    // Leaflet objects live outside Alpine's reactive state.
    let map = null;
    let markers = null;
    let youAreHere = null;
    let ring = null; // highlight around the selected site
    let outlines = null; // parcel outlines, loaded the first time a parcel is selected

    return {
      sites: [],
      loading: true,
      full: false, // every place loaded, not just recent ones
      loadingAll: false,
      failed: false, // the records didn't load; nothing else on the page can work
      error: "",
      q: "",
      since: "2",
      categories: CATEGORIES,
      show: { r: true, c: true, l: true, o: true },
      here: null,
      locating: false,
      selected: null,
      peek: null, // small-screen preview card shown over the map after tapping a dot
      limit: 40, // how many places the list shows before "Show more"

      async init() {
        try {
          const r = await fetch(recentUrl);
          if (!r.ok) throw new Error(r.status);
          this.sites = await r.json();
        } catch {
          this.error = "The permit records didn't load. Check your connection and reload the page.";
          this.failed = true;
          this.loading = false;
          return;
        }
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
          if (!key || key === location.hash) return;
          const s = this.sites.find((x) => x.k === key);
          if (s) this.select(s);
          else this.loadAll().then(() => {
            const old = this.sites.find((x) => x.k === key); // a link to a place with no recent activity
            if (old) this.select(old);
          });
        });
        this.$watch("since", (v) => {
          this.limit = 40;
          if (v === "5" || v === "all") this.loadAll();
          this.draw();
        });
        this.$watch("show", () => {
          this.limit = 40;
          this.draw();
        }, { deep: true });
        this.$watch("q", () => {
          this.limit = 40;
          if (this.q.trim()) this.loadAll();
          const pts = this.q.trim() ? this.results.filter((s) => s.lat != null).map((s) => [s.lat, s.lon]) : [];
          if (map && pts.length) map.flyToBounds(pts, { maxZoom: 17, padding: [30, 30], ...glide() });
        });
      },

      // Swap in every place, once. If it fails, the recent ones stay put.
      async loadAll() {
        if (this.full || this.loadingAll || this.failed) return;
        this.loadingAll = true;
        try {
          const r = await fetch(allUrl);
          if (!r.ok) throw new Error(r.status);
          const all = await r.json();
          const key = this.selected?.k;
          this.sites = all;
          this.full = true;
          if (key) this.selected = all.find((x) => x.k === key) || this.selected;
          this.draw();
        } catch {
          this.error = "Older records didn't load, so only the past two years are shown. Reload the page to try again.";
        } finally {
          this.loadingAll = false;
        }
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
            .on("click", () => this.pick(s))
            .addTo(markers);
        }
      },

      get results() {
        return this.matches.slice(0, this.limit);
      },

      // Every place matching the search, location or filters, in list order
      get matches() {
        const q = this.q.trim().toLowerCase();
        if (q) {
          const words = q.split(/\s+/);
          return this.sites
            .filter((s) => {
              const hay = (s.a + " " + (s.own || "") + " " + (s.pid || "") + " " + s.r.map((r) => [r.no, r.t, r.con, r.who, r.own, r.desc, r.loc, r.legal].join(" ")).join(" ")).toLowerCase();
              return words.every((w) => hay.includes(w));
            });
        }
        const pool = this.inRange();
        if (this.here) {
          return pool
            .filter((s) => s.lat != null)
            .map((s) => ({ ...s, dist: this.distance(this.here, s) }))
            .sort((a, b) => a.dist - b.dist);
        }
        return pool;
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
            this.clear();
            this.here = { lat: pos.coords.latitude, lon: pos.coords.longitude };
            if (youAreHere) youAreHere.remove();
            youAreHere = L.circleMarker([this.here.lat, this.here.lon], { radius: 8, weight: 3, color: "#0369a1", fillColor: "#38bdf8", fillOpacity: 1 }).addTo(map);
            map.flyTo([this.here.lat, this.here.lon], 17, glide());
          },
          () => {
            this.locating = false;
            this.error = "Couldn't get your location. Check your browser's location permission, or search by address.";
          },
          { enableHighAccuracy: true, timeout: 15000 },
        );
      },

      // Chosen from the list, a search result or a shared link: glide the map there.
      select(s) {
        this.show_(s);
        this.peek = null;
        if (s.lat != null && map) map.flyTo([s.lat, s.lon], Math.max(map.getZoom(), 16), glide());
        this.$nextTick(() => {
          this.reveal();
          // keyboard and screen-reader users land on the details they asked for
          this.$refs.detailTitle?.focus({ preventScroll: true });
        });
      },

      // Tapped on the map: the reader is already looking at it, so leave the map alone.
      pick(s) {
        this.show_(s);
        if (window.matchMedia("(min-width: 1024px)").matches) this.$nextTick(() => this.reveal());
        else this.peek = s;
      },

      show_(s) {
        this.selected = s;
        history.replaceState(null, "", "#site=" + encodeURIComponent(s.k));
        if (ring) ring.remove();
        ring = null;
        if (s.lat == null || !map) return;
        ring = L.circleMarker([s.lat, s.lon], { radius: 11, weight: 3, color: "#1c1917", fill: false, interactive: false }).addTo(map);
        if (s.pid) this.outline(s);
      },

      // Swap the ring for the parcel's outline once outlines are loaded
      async outline(s) {
        if (!outlines) {
          try {
            const r = await fetch(outlinesUrl);
            if (!r.ok) throw new Error(r.status);
            outlines = await r.json();
          } catch {
            return; // keep the circle; the outline is a nicety
          }
        }
        const rings = outlines[s.pid];
        if (!rings || this.selected !== s) return;
        if (ring) ring.remove();
        ring = L.featureGroup(
          rings.map((r) => L.polygon(r.map(([lon, lat]) => [lat, lon]), { weight: 3, color: "#1c1917", fillColor: "#facc15", fillOpacity: 0.25, interactive: false })),
        ).addTo(map);
      },

      parcelUrl(s) {
        return beacon + encodeURIComponent(s.pid);
      },

      // returnFocus: closed from the details panel, so put focus back on the search box
      clear(returnFocus = false) {
        if (returnFocus) document.getElementById("pq")?.focus();
        this.selected = null;
        this.peek = null;
        if (ring) ring.remove();
        ring = null;
        history.replaceState(null, "", location.pathname);
      },

      // Scroll the details into view only if they aren't already on screen.
      reveal() {
        const el = this.$refs.detail;
        if (!el) return;
        const r = el.getBoundingClientRect();
        if (r.top < 60 || r.top > window.innerHeight * 0.5) el.scrollIntoView({ behavior: scrollMode(), block: "start" });
      },

      showDetail() {
        this.peek = null;
        this.$nextTick(() => {
          this.$refs.detail?.scrollIntoView({ behavior: scrollMode(), block: "start" });
          this.$refs.detailTitle?.focus({ preventScroll: true });
        });
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
