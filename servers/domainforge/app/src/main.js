// MCP App picker: shows availability, and the "Reserve" button calls BACK into the server's reserve_domain tool.
// Checked against @modelcontextprotocol/ext-apps 2.0.0: App, addEventListener("toolresult"), connect(), callServerTool().
import { App } from "@modelcontextprotocol/ext-apps";

const app = new App({ name: "DomainForge Picker", version: "1.1.0" });
const grid = document.getElementById("grid");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);

function render(result) {
  const data = result?.structuredContent;
  if (!data?.results) return;
  const avail = data.results.filter(r => r.status === "available").length;
  document.getElementById("title").textContent = `${avail} of ${data.results.length} domains look available — pick one`;
  grid.innerHTML = "";
  for (const r of data.results) {
    const card = document.createElement("div"); card.className = "card";
    card.innerHTML = `<div class="name">${esc(r.domain)}</div><span class="badge ${esc(r.status)}">${esc(r.status)}</span>`;
    const btn = document.createElement("button");
    btn.textContent = r.status === "available" ? "Reserve" : "—"; btn.disabled = r.status !== "available";
    btn.onclick = async () => {
      btn.disabled = true; btn.textContent = "Reserving…";
      try {
        const res = await app.callServerTool({ name: "reserve_domain", arguments: { domain: r.domain, owner: "cdc-audience" } });
        if (res?.isError) throw new Error(JSON.stringify(res.content));
        btn.textContent = "Reserved ✓"; card.classList.add("reserved");
      } catch (e) { btn.textContent = "Failed"; btn.disabled = false; console.error(e); }
    };
    card.appendChild(btn); grid.appendChild(card);
  }
}

app.addEventListener("toolresult", render);
await app.connect();
