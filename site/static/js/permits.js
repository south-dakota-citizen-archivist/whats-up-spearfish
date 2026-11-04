// Building permits — lookup by address, search or location.
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
  const START = { center: [44.4906, -103.8594], zoom: 13 }; // the whole town
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
        map.tapZoomedAt = now; // a single tap waiting to open a place stands down
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

  const isoDaysAgo = (n) => {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d.toISOString().slice(0, 10);
  };
  // recent.json holds places active in about the past two years; anything older needs sites.json
  const RECENT_FROM = isoDaysAgo(2 * 365);

  // Zoomed in this far, places with a parcel show as its outline; further out, as dots
  const OUTLINE_ZOOM = 16;
  const coarse = () => window.matchMedia("(pointer: coarse)").matches;

  // Is a point (lat, lon) inside any of a parcel's rings ([[lon, lat], …])?
  function inside(lat, lon, rings) {
    return rings.some((ring) => {
      let hit = false;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i];
        const [xj, yj] = ring[j];
        if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) hit = !hit;
      }
      return hit;
    });
  }

  // Plain words for where a record came from
  const KIND = { permit: "Building permit", app: "Permit application", pc: "Planning Commission" };

  // recentUrl: places active in the past two years (what the page opens on);
  // allUrl: every place, fetched when a reader searches or looks further back
  Alpine.data("permits", (recentUrl, allUrl, latestReport, outlinesUrl, beacon) => {
    // Leaflet objects live outside Alpine's reactive state.
    let map = null;
    let markers = null;
    let youAreHere = null;
    let ring = null; // highlight around the selected site
    let outlines = null; // parcel outlines, loaded the first time a parcel is selected
    let listScroll = 0; // where the reader was in the list, to return there from a place
    let viewBefore = null; // the map's view before a place was chosen, for "Back to results"
    let sinceBefore = null; // the time period before a search widened it to every year

    return {
      sites: [],
      loading: true,
      full: false, // every place loaded, not just recent ones
      loadingAll: false,
      failed: false, // the records didn't load; nothing else on the page can work
      error: "",
      errorHelp: "",
      canUseCenter: false, // offer "the middle of the map" when location fails
      draft: "", // what's in the search box; nothing happens until Search
      query: "", // the search in effect
      since: latestReport ? "latest" : "2", // opens on the city's latest monthly permit report
      from: isoDaysAgo(365), // "Pick dates…": a year ago through today, to start
      to: isoDaysAgo(0),
      type: "all",
      categories: CATEGORIES,
      view: "list", // phones: "list" or "map" (large screens show both)
      here: null,
      hereLabel: "",
      locating: false,
      selected: null,
      choices: [], // a tap near several places: the ones to choose from
      choicesTotal: 0, // how many were within reach (the list shows the nearest 12)
      limit: 40, // how many places the list shows before "Show more"
      mapMoved: false, // the map isn't where it started (for "Start over")

      async init() {
        // The map comes up right away; the dots follow the records.
        this.$nextTick(() => this.makeMap());
        window.addEventListener("resize", () => map?.invalidateSize());
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
        this.loadOutlines(); // parcel outlines draw as the map's shapes once they arrive
        this.$nextTick(() => {
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
        for (const f of ["since", "type", "from", "to"]) {
          this.$watch(f, () => {
            this.limit = 40;
            if (this.needsOlder()) this.loadAll();
            this.draw();
          });
        }
        // the map shows what the list shows
        this.$watch("query", () => this.draw());
        this.$watch("here", () => this.draw());
      },

      makeMap() {
        // phones pinch to zoom, so the +/− buttons only appear on large screens
        map = L.map(this.$refs.map, { preferCanvas: true, zoomControl: false }).setView(START.center, START.zoom);
        if (large()) L.control.zoom({ position: "topright" }).addTo(map);
        map.on("moveend", () => {
          const c = map.getCenter();
          this.mapMoved = map.getZoom() !== START.zoom || map.distance(c, START.center) > 50;
        });
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
        this.$refs.map.leaflet = map; // for tests: where a place sits on screen
        let outlined = map.getZoom() >= OUTLINE_ZOOM;
        map.on("zoomend", () => {
          if (outlined !== map.getZoom() >= OUTLINE_ZOOM) {
            outlined = !outlined;
            this.draw();
          }
        });
        // One handler for taps and clicks, with a target the size of a fingertip
        map.on("click", (e) => {
          if (!coarse()) return this.tap(e);
          const at = Date.now();
          setTimeout(() => {
            if ((map.tapZoomedAt || 0) >= at - 50) return; // it was the first tap of a double-tap zoom
            this.tap(e);
          }, 320);
        });
      },

      async loadOutlines() {
        if (outlines) return outlines;
        try {
          const r = await fetch(outlinesUrl);
          if (!r.ok) throw new Error(r.status);
          outlines = await r.json();
          this.draw();
        } catch {
          // dots instead of outlines; the map still works
        }
        return outlines;
      },

      // Places near a tap: inside an outline, or within a fingertip of a dot; nearest first
      tap(e) {
        const reach = coarse() ? 26 : 14;
        const shapes = map.getZoom() >= OUTLINE_ZOOM && outlines;
        const hits = [];
        for (const s of this.matches) {
          if (s.lat == null) continue;
          const rings = shapes && s.pid && outlines[s.pid];
          if (rings && inside(e.latlng.lat, e.latlng.lng, rings)) {
            hits.push({ s, d: 0 });
            continue;
          }
          const d = map.latLngToContainerPoint([s.lat, s.lon]).distanceTo(e.containerPoint);
          if (d <= reach) hits.push({ s, d });
        }
        hits.sort((a, b) => a.d - b.d);
        if (!hits.length) return;
        if (hits.length === 1) return this.openPlace(hits[0].s);
        this.selected = null;
        this.choicesTotal = hits.length;
        this.choices = hits.slice(0, 12).map((h) => h.s);
        this.showDialog();
      },

      showDialog() {
        const d = this.$refs.placeDialog;
        if (!d.open) {
          d.showModal();
          this.holdStill(true);
        }
        this.$nextTick(() => (d.scrollTop = 0));
      },

      // While the pop-up is open, swipes inside it scroll only it: the page behind is locked, and
      // the map ignores drags and pinches (iPhones otherwise pass a swipe's leftover on to them)
      holdStill(on) {
        document.documentElement.classList.toggle("overflow-hidden", on);
        document.body.classList.toggle("overflow-hidden", on);
        for (const handler of [map?.dragging, map?.touchZoom, map?.scrollWheelZoom]) {
          if (handler) on ? handler.disable() : handler.enable();
        }
      },

      // A place picked on the map: beside it on large screens, in the pop-up on phones
      openPlace(s) {
        this.choices = [];
        if (large()) {
          if (this.$refs.placeDialog.open) this.$refs.placeDialog.close();
          return this.select(s);
        }
        listScroll = 0;
        this.show_(s);
        this.showDialog();
      },

      dialogClosed() {
        this.holdStill(false);
        this.choices = [];
        if (!large()) this.back(false); // back to the map just as it was
      },

      // Phones: list or map. A map that was hidden needs to measure itself once it shows.
      showView(v) {
        this.view = v;
        if (v === "map") this.$nextTick(() => map?.invalidateSize());
        // keep the List | Map switch in sight (the page's scroll padding clears the pinned menu)
        const bar = document.getElementById("results-summary");
        if (bar && bar.getBoundingClientRect().top < 64) bar.scrollIntoView({ block: "start" });
      },

      // Search: only when the reader asks, so the map doesn't jump around while they type
      async search() {
        this.query = this.draft.trim();
        this.here = null;
        this.clearHere();
        this.back(false);
        this.limit = 40;
        if (!this.query) return this.clear();
        // someone looking up an address wants its whole history: search every year (Clear puts it back)
        if (this.since !== "all") {
          sinceBefore = this.since;
          this.since = "all";
        }
        await this.loadAll();
        const pts = this.matches.filter((s) => s.lat != null).map((s) => [s.lat, s.lon]);
        if (map && pts.length) {
          map.invalidateSize();
          map.fitBounds(pts, { maxZoom: 17, padding: [30, 30], ...glide() });
        }
      },

      clear() {
        if (this.query && sinceBefore) this.since = sinceBefore;
        sinceBefore = null;
        this.draft = this.query = "";
        this.here = null;
        this.clearHere();
        this.back(false);
        this.limit = 40;
      },

      // Anything different from how the page opened?
      changed() {
        return !!(this.query || this.draft || this.here || this.selected || this.mapMoved || this.type !== "all" ||
          this.since !== (latestReport ? "latest" : "2"));
      },

      // Start over: everything as it was when the page loaded
      startOver() {
        if (this.$refs.placeDialog?.open) this.$refs.placeDialog.close();
        this.back(false);
        this.draft = this.query = "";
        this.here = null;
        this.clearHere();
        sinceBefore = null;
        this.since = latestReport ? "latest" : "2";
        this.type = "all";
        this.from = isoDaysAgo(365);
        this.to = isoDaysAgo(0);
        this.error = "";
        this.limit = 40;
        this.view = "list";
        if (map) {
          map.invalidateSize();
          map.flyTo(START.center, START.zoom, this.$refs.map.offsetParent ? glide() : { animate: false });
        }
        window.scrollTo({ top: 0 });
      },

      clearHere() {
        if (youAreHere) youAreHere.remove();
        youAreHere = null;
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

      // Does the chosen period reach back past what the page loaded first?
      needsOlder() {
        if (this.since === "custom") return (this.from || "") < RECENT_FROM;
        return this.since === "5" || this.since === "all";
      },

      cutoff() {
        if (this.since === "all" || this.since === "latest") return "";
        if (this.since === "custom") return this.from || "";
        const d = new Date();
        d.setFullYear(d.getFullYear() - Number(this.since));
        return d.toISOString().slice(0, 10);
      },

      periodLabel() {
        if (this.since === "custom") return `${this.day(this.from) || "the start"} – ${this.day(this.to) || "today"}`;
        return { latest: "the latest permit report", 1: "the past year", 2: "the past 2 years", 5: "the past 5 years", all: "all years" }[this.since];
      },

      // Records that fall in the chosen time period
      inPeriod(r) {
        if (this.since === "latest") return r.src === "permit" && (r.d || "").startsWith(latestReport);
        const d = r.d || "";
        if (this.since === "custom") return (!this.from || d >= this.from) && (!this.to || d <= this.to);
        const c = this.cutoff();
        return !c || d >= c;
      },

      // A site's category: its most recent residential/commercial/land record in the period
      category(s) {
        const recs = s.r.filter((r) => this.inPeriod(r));
        return (recs.find((r) => r.c && r.c !== "o") || recs[0] || s.r[0]).c || "o";
      },

      // Places with a record in the period, of the chosen kind
      inRange() {
        return this.sites.filter((s) => s.r.some((r) => this.inPeriod(r)) && (this.type === "all" || this.category(s) === this.type));
      },

      color(s) {
        return CATEGORIES[this.category(s)].color;
      },

      // The map shows exactly what the list does (all of it, not just the first page)
      draw() {
        if (!markers) return;
        markers.clearLayers();
        const shapes = map.getZoom() >= OUTLINE_ZOOM && outlines;
        let n = 0;
        for (const s of this.matches) {
          if (s.lat == null) continue;
          n++;
          const rings = shapes && s.pid && outlines[s.pid];
          const style = { color: "#1c1917", fillColor: this.color(s), interactive: false };
          if (rings) {
            L.polygon(rings.map((r) => r.map(([lon, lat]) => [lat, lon])), { ...style, weight: 1.5, fillOpacity: 0.55 }).addTo(markers);
          } else {
            L.circleMarker([s.lat, s.lon], { ...style, radius: 7, weight: 1, fillOpacity: 0.9 }).addTo(markers);
          }
        }
        this.$refs.map.dataset.dots = n; // drawn on a canvas; the count, for tests and the curious
      },

      get results() {
        return this.matches.slice(0, this.limit);
      },

      // Every place matching the filters, and the search or location if there is one, in list order
      get matches() {
        let pool = this.inRange();
        const q = this.query.toLowerCase();
        if (q) {
          const words = q.split(/\s+/);
          pool = pool.filter((s) => {
            const hay = (s.a + " " + (s.own || "") + " " + (s.pid || "") + " " + s.r.map((r) => [r.no, r.t, r.con, r.who, r.own, r.desc].join(" ")).join(" ")).toLowerCase();
            return words.every((w) => hay.includes(w));
          });
          // places whose address has every word come first ("main st": Main Street before a contractor named Mainline)
          const inAddress = (s) => words.every((w) => s.a.toLowerCase().includes(w));
          pool = [...pool.filter(inAddress), ...pool.filter((s) => !inAddress(s))];
        }
        if (this.here) {
          return pool
            .filter((s) => s.lat != null)
            .map((s) => ({ ...s, dist: this.distance(this.here, s) }))
            .sort((a, b) => a.dist - b.dist);
        }
        return pool;
      },

      summary() {
        const n = this.matches.length;
        const places = `${n.toLocaleString()} ${n === 1 ? "place" : "places"}`;
        if (this.query) return `${places} match “${this.query}”`;
        if (this.here) return `${places}, closest to ${this.hereLabel} first`;
        if (this.since === "latest") return `${places} with permits issued ${this.monthName(latestReport)}`;
        return `${places} • ${this.periodLabel()}, newest first`;
      },

      // "714 North 5th Street, Spearfish, SD 57783" → "714 North 5th Street": every place here is in or near town
      placeName(s) {
        return (s.a || "").replace(/,\s*Spearfish,?\s*SD\s*\d{5}(-\d{4})?$/i, "");
      },

      // One line under a place in the list: its latest activity
      // (the latest activity within the chosen dates, not the place's latest ever)
      latestLine(s) {
        const r = s.r.find((x) => this.inPeriod(x)) || s.r[0];
        const what = r.src === "pc" ? "Planning Commission meeting" : r.t;
        const when = r.src === "permit" ? this.day((r.d || "").slice(0, 7)) : this.day(r.d);
        return [what, when, s.r.length > 1 ? `${s.r.length} records` : ""].filter(Boolean).join(" • ");
      },

      kind(r) {
        return KIND[r.src] || "Record";
      },

      // The one or two facts worth reading first
      facts(r) {
        if (r.src === "pc") return "";
        const bits = [];
        if (r.s) bits.push(r.s);
        if (r.v) bits.push(this.money(r.v));
        if (r.con) bits.push(`Contractor: ${r.con}`);
        return bits.join(" • ");
      },

      // Everything else, behind "Details"
      details(r) {
        const out = [];
        if (r.no) out.push([r.src === "app" ? "Application" : "Permit number", r.no]);
        if (r.ad) out.push(["Applied", this.day(r.ad) + (r.ano ? ` (application ${r.ano})` : "")]);
        if (r.who && r.who !== r.own) out.push(["Applicant", r.who]);
        if (r.own) out.push(["Owner", r.own + (r.own_c ? ` • ${r.own_c}` : "")]);
        if (r.con_c) out.push(["Contractor contact", r.con_c]);
        if (r.desc) out.push(["Description", r.desc]);
        return out;
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
        this.draft = this.query = "";
        this.back(false);
        this.clearHere();
        this.here = point;
        this.hereLabel = label;
        this.limit = 40;
        map.invalidateSize();
        map.flyTo([point.lat, point.lon], Math.max(map.getZoom(), 16), glide());
      },

      fail(message, help = "", offerCenter = false) {
        this.error = message;
        this.errorHelp = help;
        this.canUseCenter = offerCenter && !!map;
      },

      // Chosen from the list or a shared link: its history replaces the list, and the map goes there.
      select(s) {
        listScroll = window.scrollY;
        // remember the map as the reader left it (once: going place to place keeps the first view)
        if (map && !this.selected) viewBefore = { center: map.getCenter(), zoom: map.getZoom() };
        this.show_(s);
        this.view = "list";
        if (large()) this.focusMap(s);
        this.$nextTick(() => {
          if (this.$refs.panel.getBoundingClientRect().top < 0) this.$refs.panel.scrollIntoView();
          // keyboard and screen-reader users land on the details they asked for
          this.$refs.detailTitle?.focus({ preventScroll: true });
        });
      },

      focusMap(s) {
        if (s.lat == null || !map) return;
        this.$nextTick(() => {
          map.invalidateSize();
          map.flyTo([s.lat, s.lon], Math.max(map.getZoom(), 16), glide());
        });
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
        if (!(await this.loadOutlines())) return; // keep the circle; the outline is a nicety
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

      // Back from a place to the list, where the reader left it
      back(restore = true) {
        const was = this.selected;
        this.selected = null;
        if (ring) ring.remove();
        ring = null;
        if (!was) return;
        history.replaceState(null, "", location.pathname);
        const view = viewBefore || START; // a shared link to a place started there: show the whole town
        viewBefore = null;
        if (!restore) return;
        // (a hidden map, on a phone showing the list, just jumps there)
        if (map) map.flyTo(view.center, view.zoom, this.$refs.map.offsetParent ? glide() : { animate: false });
        this.$nextTick(() => {
          window.scrollTo({ top: listScroll });
          [...this.$refs.panel.querySelectorAll("li button")].find((b) => b.textContent.includes(this.placeName(was)))?.focus({ preventScroll: true });
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

      monthName(ym) {
        if (!ym) return "";
        const [y, m] = ym.split("-").map(Number);
        return new Date(y, m - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" });
      },

      day(iso) {
        if (!iso) return "";
        const [y, m, d] = iso.split("-").map(Number);
        return new Date(y, m - 1, d || 1).toLocaleDateString("en-US", { month: "short", day: d ? "numeric" : undefined, year: "numeric" });
      },
    };
  });
});
