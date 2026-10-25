/* Shared by every page (load this first). Page scripts add their own `$` because the dashboards
   query by selector while the ticket page queries by id. */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const day = (d) => (d ? new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "-");
const when = (t) => new Date(t).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const J = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

function toast(msg, err = false) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.setAttribute("role", "status");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3400);
}

/* fetch + JSON. A 401 means the session ended, so go to the login page. */
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (res.status === 401) { location.href = "/login"; throw new Error("Please log in"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(Array.isArray(data.detail) ? data.detail[0]?.msg || "Check the form" : data.detail || "Something went wrong");
  return data;
}

async function copy(text) { await navigator.clipboard.writeText(text); toast("Copied"); }
