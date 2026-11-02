// Live National Weather Service data, fetched in the browser so it's always current.
const NWS = {
  point: "44.4908,-103.8594",
  station: "KSPF",
  grid: "UNR/78,79",
  headers: { Accept: "application/geo+json" },
};

document.addEventListener("alpine:init", () => {
  Alpine.data("weather", () => ({
    ready: false,
    error: false,
    now: { temp: "", text: "" },
    periods: [],
    async load() {
      try {
        const [obs, fc] = await Promise.all([
          fetch(`https://api.weather.gov/stations/${NWS.station}/observations/latest`, { headers: NWS.headers }).then((r) => r.json()),
          fetch(`https://api.weather.gov/gridpoints/${NWS.grid}/forecast`, { headers: NWS.headers }).then((r) => r.json()),
        ]);
        const c = obs.properties.temperature.value;
        const periods = fc.properties.periods || [];
        this.now = {
          temp: c == null ? `${periods[0]?.temperature ?? "–"}°` : `${Math.round((c * 9) / 5 + 32)}°`,
          text: obs.properties.textDescription || periods[0]?.shortForecast || "",
        };
        this.periods = periods.slice(0, 5).map((p) => ({ name: p.name, temp: `${p.temperature}°`, short: p.shortForecast }));
        this.ready = true;
      } catch (e) {
        this.error = true;
      }
    },
  }));

  // Alerts a reader has closed stay closed (on this device) until a new alert comes along.
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

  Alpine.data("nwsAlerts", () => ({
    alerts: [],
    async load() {
      try {
        const r = await fetch(`https://api.weather.gov/alerts/active?point=${NWS.point}`, { headers: NWS.headers });
        const data = await r.json();
        this.alerts = (data.features || []).map((f) => ({
          id: f.id,
          event: f.properties.event,
          headline: f.properties.headline || "",
          severe: ["Severe", "Extreme"].includes(f.properties.severity),
          url: `https://forecast.weather.gov/MapClick.php?lat=44.4908&lon=-103.8594`,
        }));
      } catch (e) {
        this.alerts = [];
      }
    },
  }));
});
