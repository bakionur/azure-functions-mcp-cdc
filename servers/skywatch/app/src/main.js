// MCP App (SEP-1865). Receives the tool result of `flights_overhead` from the host and draws a radar.
// Checked against @modelcontextprotocol/ext-apps 2.0.0: App, addEventListener("toolresult"), connect(), callServerTool().
// Live mode: every 15 s the widget calls flights_overhead again THROUGH the host — the radar keeps moving.
import { App } from "@modelcontextprotocol/ext-apps";

const REFRESH_MS = 15000;
const app = new App({ name: "SkyWatch Radar", version: "1.1.0" });
const cv = document.getElementById("radar"), ctx = cv.getContext("2d");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
let sweep = 0, data = null, timer = null;

function draw() {
  const c = cv.width / 2, r = c - 16;
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.strokeStyle = "#d4460c"; ctx.lineWidth = 1;
  for (let k = 1; k <= 4; k++) { ctx.beginPath(); ctx.arc(c, c, r * k / 4, 0, Math.PI * 2); ctx.stroke(); }
  ctx.strokeStyle = "#5a321e"; ctx.beginPath(); ctx.moveTo(c, c - r); ctx.lineTo(c, c + r); ctx.moveTo(c - r, c); ctx.lineTo(c + r, c); ctx.stroke();
  // sweep
  const g = ctx.createConicGradient ? ctx.createConicGradient(sweep, c, c) : null;
  if (g) { g.addColorStop(0, "rgba(240,138,75,0.35)"); g.addColorStop(0.15, "rgba(240,138,75,0)"); g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(c, c); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.fill(); }
  if (data) {
    const maxKm = data.radius_nm * 1.852;
    for (const a of data.aircraft) {
      const d = Math.min(a.distance_km, maxKm) / maxKm * r, b = a.bearing_deg * Math.PI / 180;
      const x = c + d * Math.sin(b), y = c - d * Math.cos(b);
      ctx.fillStyle = "#f08a4b"; ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#fbf4ec"; ctx.font = "11px system-ui"; ctx.fillText(a.callsign || "?", x + 6, y - 6);
    }
  }
  sweep += 0.03; requestAnimationFrame(draw);
}

function render(result) {
  if (!result?.structuredContent) return;
  data = result.structuredContent;
  document.getElementById("title").textContent = `${data.count} aircraft within ${data.radius_nm} NM of ${data.center.name}`;
  document.getElementById("meta").innerHTML =
    `<span class="pill">${esc(data.source)}</span> live ADS-B · updated ${new Date().toLocaleTimeString()}`;
  const route = (a) => (a.from || a.to)
    ? `<span title="${esc(a.from_city)} → ${esc(a.to_city)}">${esc(a.from ?? "?")} → ${esc(a.to ?? "?")}</span>` : "<span class=dim>—</span>";
  const rows = data.aircraft.slice(0, 10).map(a =>
    `<tr><td><b>${esc(a.callsign ?? "?")}</b><div class=dim>${esc(a.airline ?? "")}</div></td><td>${route(a)}</td><td>${esc(a.type)}</td><td>${esc(a.altitude_ft)} ft</td><td>${esc(a.distance_km)} km</td></tr>`).join("");
  document.getElementById("list").innerHTML = `<tr><th>Callsign</th><th>Route</th><th>Type</th><th>Alt</th><th>Dist</th></tr>${rows}`;
  scheduleRefresh();
}

// The widget calls the server tool itself (via the host) — no model round-trip, no tokens.
function scheduleRefresh() {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    try {
      render(await app.callServerTool({
        name: "flights_overhead",
        arguments: { radius_nm: data.radius_nm, lat: data.center.lat, lon: data.center.lon },
      }));
    } catch (e) { console.warn("refresh failed", e); scheduleRefresh(); }
  }, REFRESH_MS);
}

app.addEventListener("toolresult", render);
await app.connect();
draw();
