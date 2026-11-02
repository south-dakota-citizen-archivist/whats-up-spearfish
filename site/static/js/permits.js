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
  const large = () => window.matchMedia("(min-width: 1024px)").matches;

  // Help for each way a location request fails (GeolocationPositionError codes)
  const LOCATION_HELP = {
    1: [
      "Location sharing is off for this site.",
      "Your browser won't ask again once it's been told no. iPhone: Settings → Privacy & Security → Location Services: on, and Safari Websites set to “While Using.” Android: tap the icon left of the web address → Permissions → Location → Allow. Then try again.",
    ],
    2: [
      "Your phone couldn't work out where you are.",
      "Location Services may be turned off for the whole phone, or there's no signal. Turn it on in your phone's settings and try again.",
    ],
    3: ["Finding your location took too long.", "Try again, ideally with a clear view of the sky or on Wi-Fi."],
  };

  // Double-tap to zoom in. Leaflet waits for the browser's dblclick, which iPhones (WebKit)
  // don't send for touches, so watch the taps ourselves; and handle dblclick here too, so a
  // browser that sends both (Chrome on Android) doesn't zoom twice.
  function doubleTapZoom(map) {
    map.doubleClickZoom.disable();
    let last = null;
    let touchZoomAt = 0;
    const zoomAround = (point, out) => map.setZoomAround(point, map.getZoom() + (out ? -1 : 1), glide());
    map.getContainer().addEventListener("pointerup", (e) => {
      if (e.pointerType !== "touch" || !e.isPrimary) return;
      const now = Date.now();
      const here = map.mouseEventToContainerPoint(e);
      if (last && now - last.t < 300 && here.distanceTo(last.p) < 30) {
        touchZoomAt = now;
        last = null;
        zoomAround(here, false);
      } else {
        last = { t: now, p: here };
      }
    });
    map.on("dblclick", (e) => {
      if (Date.now() - touchZoomAt < 600) return; // the double-tap above already zoomed
      zoomAround(e.containerPoint, e.originalEvent.shiftKey);
    });
  }

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
      open: false, // phones: the bottom sheet pulled up to show the list
      swipeFrom: null, // where a swipe on the sheet's handle began
      errorHelp: "",
      canUseCenter: false, // offer "places near the middle of the map" when location fails
      hereLabel: "",
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
          // phones pinch to zoom, so the +/− buttons only appear on large screens
          map = L.map(this.$refs.map, { preferCanvas: true, zoomControl: false }).setView([44.4906, -103.8594], 13);
          if (large()) L.control.zoom({ position: "topright" }).addTo(map);
          doubleTapZoom(map);
          // the zoom level on the page, for tests and anyone curious
          const noteZoom = () => (this.$refs.map.dataset.zoom = map.getZoom());
          map.on("zoomend", noteZoom);
          noteZoom();
          L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          }).addTo(map);
          markers = L.layerGroup().addTo(map);
          // a tap on open map (not a dot) tucks the sheet away, so the map is always one tap from full view
          map.on("click", () => {
            if (large()) return;
            this.open = false;
            if (this.selected) this.back();
          });
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
          if (this.q.trim()) {
            this.loadAll();
            this.open = true;
          }
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
            .on("click", (e) => {
              L.DomEvent.stopPropagation(e); // a dot, not open map
              this.pick(s);
            })
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

      // Where am I? Ask the browser, explain plainly if it can't say, and offer the map's middle instead.
      async near() {
        this.error = "";
        this.errorHelp = "";
        if (!navigator.geolocation) return this.fail("Your browser can't share its location.", "", true);
        // If location was already refused, the browser won't ask again: say so before trying.
        try {
          const status = await navigator.permissions?.query({ name: "geolocation" });
          if (status?.state === "denied") return this.fail(...LOCATION_HELP[1], true);
        } catch {
          // older browsers can't answer; just ask
        }
        this.locating = true;
        const ask = (precise) =>
          new Promise((resolve, reject) =>
            navigator.geolocation.getCurrentPosition(resolve, reject, {
              enableHighAccuracy: precise,
              timeout: precise ? 10000 : 20000,
              maximumAge: 60000,
            }),
          );
        try {
          let pos;
          try {
            pos = await ask(true);
          } catch (err) {
            if (err.code === 1) throw err;
            pos = await ask(false); // GPS too slow or unavailable: a rougher fix is fine
          }
          this.goHere({ lat: pos.coords.latitude, lon: pos.coords.longitude }, "you");
          youAreHere = L.circleMarker([this.here.lat, this.here.lon], { radius: 8, weight: 3, color: "#0369a1", fillColor: "#38bdf8", fillOpacity: 1, interactive: false }).addTo(map);
        } catch (err) {
          this.fail(...(LOCATION_HELP[err.code] || ["Couldn't get your location.", ""]), true);
        } finally {
          this.locating = false;
        }
      },

      // No location? Pan the map to the spot you care about and use its middle.
      nearCenter() {
        const c = map.getCenter();
        this.error = "";
        this.goHere({ lat: c.lat, lon: c.lng }, "the middle of the map");
      },

      goHere(point, label) {
        this.q = "";
        this.back();
        this.here = point;
        this.hereLabel = label;
        this.open = true;
        if (youAreHere) youAreHere.remove();
        youAreHere = null;
        map.flyTo([point.lat, point.lon], Math.max(map.getZoom(), 16), glide());
      },

      fail(message, help = "", offerCenter = false) {
        this.error = message;
        this.errorHelp = help;
        this.canUseCenter = offerCenter && !!map;
      },

      // Phones: tap the handle to open or close the sheet, or swipe it up or down
      toggleSheet() {
        if (Date.now() - (this._swiped || 0) < 400) return;
        if (this.open || this.selected) {
          this.open = false;
          if (this.selected) this.back();
        } else this.open = true;
      },

      swipeSheet(y) {
        if (this.swipeFrom == null) return;
        const dy = y - this.swipeFrom;
        this.swipeFrom = null;
        if (Math.abs(dy) < 25) return; // a tap; the click handler takes it
        const up = dy < 0;
        if (up !== (this.open || !!this.selected)) this.toggleSheet();
        this._swiped = Date.now(); // the click that follows a swipe shouldn't undo it
      },

      sheetTitle() {
        const n = this.matches.length;
        const places = `${n.toLocaleString()} ${n === 1 ? "place" : "places"}`;
        if (this.q.trim()) return `${places} match “${this.q.trim()}”`;
        if (this.here) return `Closest to ${this.hereLabel}`;
        if (this.since === "latest") return `${places} in the latest permit report`;
        return `${places}, most recent first`;
      },

      // Chosen from the list, a search result or a shared link: glide the map there.
      select(s) {
        this.show_(s);
        this.focusMap(s);
        this.$nextTick(() => {
          this.$refs.sheet?.scrollTo(0, 0);
          // keyboard and screen-reader users land on the details they asked for
          this.$refs.detailTitle?.focus({ preventScroll: true });
        });
      },

      // Tapped on the map: open the details in the sheet; the reader is already looking at the spot.
      pick(s) {
        this.show_(s);
        this.$nextTick(() => this.$refs.sheet?.scrollTo(0, 0));
      },

      // Center a place in the part of the map the sheet doesn't cover.
      focusMap(s) {
        if (s.lat == null || !map) return;
        const zoom = Math.max(map.getZoom(), 16);
        let target = L.latLng(s.lat, s.lon);
        const sheet = this.$refs.sheet?.parentElement;
        if (!large() && sheet) {
          // the sheet will cover the bottom ~60%; aim the spot at the middle of what's left
          const lift = (this.$refs.map.clientHeight * 0.62) / 2;
          target = map.unproject(map.project(target, zoom).add([0, lift]), zoom);
        } else if (large()) {
          target = map.unproject(map.project(target, zoom).subtract([200, 0]), zoom); // clear of the side panel
        }
        map.flyTo(target, zoom, glide());
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

      // Back from a place to the list
      back() {
        const was = this.selected;
        this.selected = null;
        if (ring) ring.remove();
        ring = null;
        history.replaceState(null, "", location.pathname);
        if (was) this.$nextTick(() => this.$refs.sheet?.querySelector("li button")?.focus({ preventScroll: true }));
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
