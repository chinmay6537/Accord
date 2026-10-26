/* Dealer dashboard. Hash routes:
   #/                 overview
   #/tickets          all tickets (past requests), filterable      ?status=&customer=&segment=
   #/ticket/ID        one ticket: details, customer, chat, history
   #/new  #/new/CID   new ticket (optionally for a customer)
   #/edit/ID          edit a ticket that was not sent yet
   #/customers        customers                                    ?segment=
   #/customer/ID      one customer and their tickets
   #/segments         customer groups
   The evidence + agreement builder lives on its own page: /ticket/ID */

const $ = (s, r = document) => r.querySelector(s);
const view = $("#view");
let stopThread = null;

const STATUS = {
  collecting: ["Collecting evidence", ""], draft: ["Ready to send", "yellow"], sent: ["Waiting for customer", "yellow"],
  confirmed: ["Confirmed", "green"], change_requested: ["Customer wants changes", "red"],
};
const TYPE = { supply: "Supply goods", service: "Service", repair: "Repair", rental: "Rental", other: "Other" };
const GST = { "": "Not set", included: "Included", extra: "Extra", not_sure: "Not sure" };
const CHANNEL = { "": "Not set", whatsapp: "WhatsApp", call: "Phone call", in_person: "In person", mixed: "A mix" };
const HISTORY = {
  evidence_added: "Evidence added", evidence_edited: "Evidence edited", evidence_removed: "Evidence removed",
  terms_extracted: "Terms read from evidence", terms_confirmed: "Terms checked by you", agreement_generated: "Agreement written",
  owner_approved: "Sent to customer", counterparty_confirmed: "Customer agreed",
  counterparty_requested_change: "Customer asked for a change", comment_added: "Comment on the agreement",
};

const money = (n) => (n == null || n === "" ? "-" : "₹" + Number(n).toLocaleString("en-IN"));
const tag = (status) => `<span class="tag ${STATUS[status]?.[1] || ""}">${esc(STATUS[status]?.[0] || status)}</span>`;



function ticketTable(rows) {
  if (!rows.length) return '<p class="muted">Nothing here yet.</p>';
  return `<div class="tablewrap"><table class="t"><thead><tr><th>Ticket</th><th>Customer</th><th>Type</th><th>Value</th><th>Due</th><th>Status</th><th>Updated</th></tr></thead><tbody>
    ${rows.map((t) => `<tr data-go="#/ticket/${t.id}" tabindex="0">
      <td><b>${esc(t.title)}</b>${t.priority === "urgent" ? ' <span class="tag red">urgent</span>' : ""}</td>
      <td>${esc(t.customer_name || "-")}${t.segment_name ? `<br><span class="muted">${esc(t.segment_name)}</span>` : ""}</td>
      <td>${esc(TYPE[t.deal_type] || "")}</td><td>${money(t.est_value)}</td><td>${day(t.due_date)}</td>
      <td>${tag(t.status)}</td><td>${when(t.updated)}</td></tr>`).join("")}</tbody></table></div>`;
}

/* ---------------------------------------------------------------- overview */
async function overview() {
  const o = await api("/api/dealer/overview");
  const tile = (label, n, status) => `<a class="tile" href="#/tickets?status=${status}"><b>${n}</b><span>${label}</span></a>`;
  view.innerHTML = `<h1 class="pt">Overview</h1>
    <div class="tiles">
      ${tile("Collecting evidence", o.counts.collecting, "collecting")}${tile("Ready to send", o.counts.draft, "draft")}
      ${tile("Waiting for customer", o.counts.sent, "sent")}${tile("Customer wants changes", o.counts.change_requested, "change_requested")}
      ${tile("Confirmed", o.counts.confirmed, "confirmed")}
      <a class="tile" href="#/customers"><b>${o.customers}</b><span>Customers</span></a>
    </div>
    <p class="muted">Value of confirmed agreements: <b>${money(o.confirmed_value)}</b> (from the value you entered on each ticket)</p>
    <h2>Needs your attention</h2>${ticketTable(o.needs_attention)}
    <h2>Recent tickets</h2>${ticketTable(o.recent)}`;
}

/* ---------------------------------------------------------------- tickets */
async function tickets(q) {
  const [customers, segments] = await Promise.all([api("/api/customers"), api("/api/segments")]);
  const p = new URLSearchParams();
  for (const [k, api_k] of [["status", "status"], ["customer", "customer_id"], ["segment", "segment_id"], ["q", "q"]]) if (q.get(k)) p.set(api_k, q.get(k));
  const rows = await api("/api/tickets?" + p);
  const opt = (v, cur, label) => `<option value="${esc(v)}" ${String(cur) === String(v) ? "selected" : ""}>${esc(label)}</option>`;
  view.innerHTML = `<div class="head"><h1 class="pt">Tickets</h1><a class="btn primary" href="#/new">+ New ticket</a></div>
    <form class="filters" id="filters">
      <input type="text" name="q" placeholder="Search title or customer" value="${esc(q.get("q") || "")}" aria-label="Search">
      <select name="status" aria-label="Status"><option value="">All statuses</option>${Object.keys(STATUS).map((s) => opt(s, q.get("status"), STATUS[s][0])).join("")}</select>
      <select name="customer" aria-label="Customer"><option value="">All customers</option>${customers.map((c) => opt(c.id, q.get("customer"), c.name)).join("")}</select>
      <select name="segment" aria-label="Segment"><option value="">All segments</option>${segments.map((s) => opt(s.id, q.get("segment"), s.name)).join("")}</select>
    </form><p class="muted">${rows.length} ticket${rows.length === 1 ? "" : "s"}</p>${ticketTable(rows)}`;
  $("#filters").addEventListener("change", () => {
    const f = new FormData($("#filters")), n = new URLSearchParams();
    for (const [k, v] of f) if (v) n.set(k, v);
    location.hash = "#/tickets" + (n.toString() ? "?" + n : "");
  });
  $("#filters").addEventListener("submit", (e) => { e.preventDefault(); $("#filters").dispatchEvent(new Event("change")); });
}

/* ---------------------------------------------------------------- ticket detail */
async function ticket(id) {
  const t = await api("/api/tickets/" + id);
  const shared = ["sent", "confirmed", "change_requested"].includes(t.status);
  const open = ["collecting", "draft"].includes(t.status);
  const c = t.customer;
  let invite = "";
  if (c && !c.has_account) {
    const full = await api("/api/customers/" + c.id);
    invite = `<p>${esc(c.name)} has no account yet. Send them their private link so they can sign up and see this in their portal:</p>
      <div class="linkbox"><input type="text" readonly value="${esc(location.origin + full.invite_path)}" aria-label="Invite link"><button class="btn small" data-copy="${esc(location.origin + full.invite_path)}">Copy</button></div>`;
  } else if (c) invite = `<p class="muted">${esc(c.name)} has an account, so they see this ticket in their portal.</p>`;
  const share = shared ? `<p>Or share this one-time confirmation link (no account needed):</p>
      <div class="linkbox"><input type="text" readonly value="${esc(location.origin + "/c/" + t.token)}" aria-label="Confirmation link"><button class="btn small" data-copy="${esc(location.origin + "/c/" + t.token)}">Copy</button></div>` : "";

  view.innerHTML = `<p><a href="#/tickets">&larr; All tickets</a></p>
    <div class="head"><div><h1 class="pt">${esc(t.title)}</h1><p>${tag(t.status)} ${t.priority === "urgent" ? '<span class="tag red">urgent</span>' : ""}</p></div>
      <div class="row">${open ? `<a class="btn plain" href="#/edit/${t.id}">Edit details</a>` : ""}
        <a class="btn primary" href="/ticket/${t.id}">${open ? "Add evidence and build agreement" : "Open agreement and proof"}</a>
        ${shared ? `<a class="btn plain" href="/api/deals/${t.id}/agreement.pdf" download>Agreement PDF</a><a class="btn plain" href="/api/deals/${t.id}/report.pdf" download>Evidence report PDF</a>` : ""}</div></div>
    <div class="card"><h2>Details</h2>
      <dl class="facts">
        <dt>Customer</dt><dd>${c ? `<a href="#/customer/${c.id}">${esc(c.name)}</a>${c.business ? ", " + esc(c.business) : ""}${c.segment_name ? ` <span class="tag">${esc(c.segment_name)}</span>` : ""}` : "-"}</dd>
        <dt>What it is</dt><dd>${esc(t.description).replace(/\n/g, "<br>") || "-"}</dd>
        <dt>Type</dt><dd>${esc(TYPE[t.deal_type] || "-")}</dd><dt>Expected value</dt><dd>${money(t.est_value)}</dd>
        <dt>Advance expected</dt><dd>${money(t.advance)}</dd><dt>Delivery by</dt><dd>${day(t.due_date)}</dd>
        <dt>GST</dt><dd>${esc(GST[t.gst] || "-")}</dd><dt>Discussed on</dt><dd>${esc(CHANNEL[t.channel] || "-")}</dd>
        <dt>Your private notes</dt><dd>${esc(t.notes || "-")} <span class="muted">(the customer never sees these)</span></dd>
        <dt>Created</dt><dd>${when(t.created)}</dd></dl></div>
    ${shared || open ? `<div class="card"><h2>Share with customer</h2>${shared ? "" : '<p class="muted">Available after you build the agreement and send it.</p>'}${shared ? invite + share : invite}</div>` : ""}
    ${shared ? '<div class="card"><h2>Chat and comments</h2><div id="thread"></div></div>' : ""}
    <div class="card"><h2>History</h2><ol class="hist">${t.history.map((h) => `<li><b>${esc(HISTORY[h.kind] || h.kind)}</b>${h.meta.name && ["counterparty_confirmed", "counterparty_requested_change", "comment_added"].includes(h.kind) ? " by " + esc(h.meta.name) : ""}${h.meta.note ? ` <span class="muted">“${esc(h.meta.note)}”</span>` : ""}${h.meta.checks ? `<br><span class="muted">They checked: ${Object.entries(h.meta.checks).map(([k, v]) => esc(k.replace("_", " ")) + " " + (v === "match" ? "matches" : "does not match")).join(", ")}</span>` : ""}<br><span class="muted">${when(h.ts)}</span></li>`).join("") || "<li class='muted'>Nothing yet.</li>"}</ol></div>`;
  if (shared) stopThread = mountThread($("#thread"), id);
}

/* ---------------------------------------------------------------- new / edit ticket */
async function ticketForm(editId, presetCustomer) {
  const [customers, segments] = await Promise.all([api("/api/customers"), api("/api/segments")]);
  const t = editId ? await api("/api/tickets/" + editId) : null;
  const sel = t ? t.customer?.id : presetCustomer;
  const val = (k, d = "") => esc(t ? (t[k] ?? d) : d);
  const radio = (name, map, cur) => Object.entries(map).map(([v, l]) => `<label class="choice"><input type="radio" name="${name}" value="${v}" ${String(cur) === v ? "checked" : ""}> ${esc(l)}</label>`).join("");
  view.innerHTML = `<p><a href="${editId ? "#/ticket/" + editId : "#/tickets"}">&larr; Back</a></p><h1 class="pt">${editId ? "Edit ticket" : "New ticket"}</h1>
    <form id="tform" class="card">
      <label for="f_title">Title</label><input id="f_title" name="title" type="text" maxlength="80" required value="${val("title")}" placeholder="Wedding cards for Ravi">
      <label for="f_customer">Customer</label>
      <select id="f_customer" name="customer_id" required>
        <option value="">Choose a customer</option>
        ${customers.map((c) => `<option value="${c.id}" ${sel == c.id ? "selected" : ""}>${esc(c.name)}${c.business ? " (" + esc(c.business) + ")" : ""}</option>`).join("")}
        <option value="new">+ Add a new customer</option></select>
      <div id="newCustomer" class="panel hidden">
        <label for="nc_name">Customer name</label><input id="nc_name" type="text" maxlength="80">
        <div class="grid2"><div><label for="nc_phone">Phone</label><input id="nc_phone" type="tel"></div><div><label for="nc_email">Email</label><input id="nc_email" type="text"></div></div>
        <label for="nc_seg">Segment (optional)</label><select id="nc_seg"><option value="">None</option>${segments.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select>
      </div>
      <label for="f_desc">What is the deal?</label>
      <textarea id="f_desc" name="description" class="short" maxlength="2000" required placeholder="600 wedding cards, 4-colour print with gold foil, for a wedding on 27 Oct.">${val("description")}</textarea>
      <details ${t && (t.est_value != null || t.due_date || t.gst || t.channel || t.notes) ? "open" : ""}><summary>More details (optional, helps us spot gaps later)</summary>
        <div class="grid2" style="margin-top:12px">
          <div><label for="f_type">Type of deal</label><select id="f_type" name="deal_type">${Object.entries(TYPE).map(([v, l]) => `<option value="${v}" ${(t?.deal_type || "supply") === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          <div><label for="f_due">Needed by</label><input id="f_due" name="due_date" type="date" value="${val("due_date")}"></div>
          <div><label for="f_value">Expected value (₹)</label><input id="f_value" name="est_value" type="number" min="0" step="any" value="${val("est_value")}"></div>
          <div><label for="f_adv">Advance expected (₹)</label><input id="f_adv" name="advance" type="number" min="0" step="any" value="${val("advance")}"></div>
        </div>
        <label>GST</label><div class="choices">${radio("gst", { "": "Not set", included: "Included", extra: "Extra", not_sure: "Not sure" }, t?.gst || "")}</div>
        <label>Where was it discussed?</label><div class="choices">${radio("channel", CHANNEL, t?.channel || "")}</div>
        <label>Priority</label><div class="choices">${radio("priority", { normal: "Normal", urgent: "Urgent" }, t?.priority || "normal")}</div>
        <label for="f_notes">Private notes (the customer never sees these)</label><textarea id="f_notes" name="notes" class="short" maxlength="2000">${val("notes")}</textarea>
      </details>
      <div class="row" style="margin-top:16px"><button class="btn primary" type="submit">${editId ? "Save changes" : "Create ticket and add evidence"}</button></div>
    </form>`;
  const toggleNew = () => $("#newCustomer").classList.toggle("hidden", $("#f_customer").value !== "new");
  $("#f_customer").addEventListener("change", toggleNew); toggleNew();
  $("#tform").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.submitter; btn.disabled = true;
    try {
      const f = new FormData(e.target);
      let cid = f.get("customer_id");
      if (cid === "new") {
        const nc = await api("/api/customers", J("POST", { name: $("#nc_name").value, phone: $("#nc_phone").value, email: $("#nc_email").value, segment_id: $("#nc_seg").value ? +$("#nc_seg").value : null }));
        cid = nc.id;
      }
      const num = (k) => (f.get(k) === "" || f.get(k) == null ? null : Number(f.get(k)));
      const body = { title: f.get("title"), customer_id: +cid, description: f.get("description"), deal_type: f.get("deal_type"), est_value: num("est_value"),
        advance: num("advance"), due_date: f.get("due_date") || "", gst: f.get("gst") || "", priority: f.get("priority") || "normal", channel: f.get("channel") || "", notes: f.get("notes") || "" };
      if (editId) { await api("/api/tickets/" + editId, J("PUT", body)); location.hash = "#/ticket/" + editId; toast("Saved"); }
      else { const r = await api("/api/tickets", J("POST", body)); location.href = "/ticket/" + r.id; }
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  });
}

/* ---------------------------------------------------------------- customers */
function customerFields(c, segments) {
  return `<label for="c_name">Name</label><input id="c_name" type="text" maxlength="80" value="${esc(c?.name || "")}" required>
    <div class="grid2"><div><label for="c_phone">Phone</label><input id="c_phone" type="tel" value="${esc(c?.phone || "")}"></div>
    <div><label for="c_email">Email</label><input id="c_email" type="text" value="${esc(c?.email || "")}"></div>
    <div><label for="c_biz">Business</label><input id="c_biz" type="text" value="${esc(c?.business || "")}"></div>
    <div><label for="c_seg">Segment</label><select id="c_seg"><option value="">None</option>${segments.map((s) => `<option value="${s.id}" ${c?.segment_id === s.id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></div></div>
    <label for="c_notes">Notes</label><textarea id="c_notes" class="short">${esc(c?.notes || "")}</textarea>`;
}
const readCustomer = () => ({ name: $("#c_name").value, phone: $("#c_phone").value, email: $("#c_email").value, business: $("#c_biz").value,
  segment_id: $("#c_seg").value ? +$("#c_seg").value : null, notes: $("#c_notes").value });

async function customers(q) {
  const segments = await api("/api/segments");
  const p = new URLSearchParams();
  if (q.get("q")) p.set("q", q.get("q"));
  if (q.get("segment")) p.set("segment_id", q.get("segment"));
  const rows = await api("/api/customers?" + p);
  view.innerHTML = `<div class="head"><h1 class="pt">Customers</h1><button class="btn primary" id="addBtn">+ Add customer</button></div>
    <form id="addForm" class="card hidden"><h2>New customer</h2>${customerFields(null, segments)}<div class="row"><button class="btn primary" type="submit">Save customer</button><button class="btn plain" type="button" id="cancelAdd">Cancel</button></div></form>
    <form class="filters" id="filters"><input type="text" name="q" placeholder="Search name, phone, email" value="${esc(q.get("q") || "")}" aria-label="Search">
      <select name="segment" aria-label="Segment"><option value="">All segments</option>${segments.map((s) => `<option value="${s.id}" ${q.get("segment") == s.id ? "selected" : ""}>${esc(s.name)} (${s.customers})</option>`).join("")}</select></form>
    <div class="tablewrap"><table class="t"><thead><tr><th>Name</th><th>Business</th><th>Phone</th><th>Segment</th><th>Tickets</th><th>Account</th></tr></thead><tbody>
    ${rows.map((c) => `<tr data-go="#/customer/${c.id}" tabindex="0"><td><b>${esc(c.name)}</b></td><td>${esc(c.business || "-")}</td><td>${esc(c.phone || "-")}</td>
      <td>${esc(c.segment_name || "-")}</td><td>${c.tickets}</td><td>${c.has_account ? '<span class="tag green">Joined</span>' : '<span class="tag">Not yet</span>'}</td></tr>`).join("") || '<tr><td colspan="6" class="muted">No customers yet. Add your first one.</td></tr>'}</tbody></table></div>`;
  $("#addBtn").onclick = () => { $("#addForm").classList.remove("hidden"); $("#c_name").focus(); };
  $("#cancelAdd").onclick = () => $("#addForm").classList.add("hidden");
  $("#addForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { const c = await api("/api/customers", J("POST", readCustomer())); toast("Customer saved"); location.hash = "#/customer/" + c.id; }
    catch (err) { toast(err.message, true); }
  });
  $("#filters").addEventListener("change", () => {
    const f = new FormData($("#filters")), n = new URLSearchParams();
    for (const [k, v] of f) if (v) n.set(k, v);
    location.hash = "#/customers" + (n.toString() ? "?" + n : "");
  });
  $("#filters").addEventListener("submit", (e) => { e.preventDefault(); $("#filters").dispatchEvent(new Event("change")); });
}

async function customer(id) {
  const [c, segments] = await Promise.all([api("/api/customers/" + id), api("/api/segments")]);
  const inviteUrl = location.origin + c.invite_path;
  view.innerHTML = `<p><a href="#/customers">&larr; All customers</a></p>
    <div class="head"><h1 class="pt">${esc(c.name)}</h1><a class="btn primary" href="#/new/${c.id}">+ New ticket for ${esc(c.name)}</a></div>
    <form id="cform" class="card"><h2>Details</h2>${customerFields(c, segments)}
      <div class="row"><button class="btn primary" type="submit">Save changes</button>${c.tickets ? "" : '<button class="btn danger" type="button" id="del">Delete customer</button>'}</div></form>
    <div class="card"><h2>Their account</h2>${c.has_account ? '<p><span class="tag green">Joined</span> They see any ticket you send them in their own portal.</p>'
      : `<p>${esc(c.name)} has not joined yet. Send them this private link. They sign up through it and it connects them to you.</p>
        <div class="linkbox"><input type="text" readonly value="${esc(inviteUrl)}" aria-label="Invite link"><button class="btn small" data-copy="${esc(inviteUrl)}">Copy</button>
        <a class="btn small plain" target="_blank" rel="noopener" href="https://wa.me/?text=${encodeURIComponent("Hi " + c.name + ", please join here to see our agreements: " + inviteUrl)}">Send on WhatsApp</a></div>`}</div>
    <h2>Tickets (${c.ticket_list.length})</h2>${ticketTable(c.ticket_list)}`;
  $("#cform").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("/api/customers/" + id, J("PUT", readCustomer())); toast("Saved"); } catch (err) { toast(err.message, true); }
  });
  $("#del")?.addEventListener("click", async () => {
    if (!confirm("Delete this customer?")) return;
    try { await api("/api/customers/" + id, { method: "DELETE" }); location.hash = "#/customers"; } catch (err) { toast(err.message, true); }
  });
}

/* ---------------------------------------------------------------- segments */
async function segments() {
  const rows = await api("/api/segments");
  view.innerHTML = `<h1 class="pt">Segments</h1><p class="muted">Groups of customers, like “Wedding printers” or “Wholesale”. Use them to filter tickets and customers.</p>
    <form id="segForm" class="row" style="margin-bottom:16px"><input type="text" id="segName" placeholder="New segment name" maxlength="40" aria-label="Segment name" style="max-width:320px;margin:0"><button class="btn primary" type="submit">Add segment</button></form>
    <div class="tablewrap"><table class="t"><thead><tr><th>Segment</th><th>Customers</th><th></th></tr></thead><tbody>
    ${rows.map((s) => `<tr><td><a href="#/customers?segment=${s.id}"><b>${esc(s.name)}</b></a></td><td>${s.customers}</td>
      <td class="row"><a class="btn small plain" href="#/tickets?segment=${s.id}">Tickets</a><button class="btn small plain" data-rename="${s.id}" data-name="${esc(s.name)}">Rename</button><button class="btn small danger" data-del="${s.id}">Delete</button></td></tr>`).join("") || '<tr><td colspan="3" class="muted">No segments yet.</td></tr>'}</tbody></table></div>`;
  $("#segForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("/api/segments", J("POST", { name: $("#segName").value })); segments(); } catch (err) { toast(err.message, true); }
  });
  view.querySelectorAll("[data-rename]").forEach((b) => b.addEventListener("click", async () => {
    const name = prompt("New name", b.dataset.name);
    if (name) try { await api("/api/segments/" + b.dataset.rename, J("PUT", { name })); segments(); } catch (err) { toast(err.message, true); }
  }));
  view.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    if (confirm("Delete this segment? Its customers stay, just without a segment.")) try { await api("/api/segments/" + b.dataset.del, { method: "DELETE" }); segments(); } catch (err) { toast(err.message, true); }
  }));
}

/* ---------------------------------------------------------------- router */
async function route() {
  if (stopThread) { stopThread(); stopThread = null; }
  const [path, qs] = (location.hash.slice(1) || "/").split("?");
  const parts = path.split("/").filter(Boolean), q = new URLSearchParams(qs || "");
  document.querySelectorAll("[data-nav]").forEach((a) => {
    const root = parts[0] === "ticket" || parts[0] === "new" || parts[0] === "edit" ? "tickets" : parts[0] === "customer" ? "customers" : parts[0] || "";
    a.toggleAttribute("aria-current", a.dataset.nav === root);
  });
  try {
    switch (parts[0]) {
      case undefined: await overview(); break;
      case "tickets": await tickets(q); break;
      case "ticket": await ticket(parts[1]); break;
      case "new": await ticketForm(null, parts[1]); break;
      case "edit": await ticketForm(parts[1]); break;
      case "customers": await customers(q); break;
      case "customer": await customer(parts[1]); break;
      case "segments": await segments(); break;
      default: view.innerHTML = '<p>Page not found. <a href="#/">Go to overview</a></p>';
    }
  } catch (err) { view.innerHTML = `<p class="muted">${esc(err.message)}</p><p><a href="#/">Back to overview</a></p>`; }
  view.focus({ preventScroll: true });
}

document.addEventListener("click", (e) => {
  const copyBtn = e.target.closest("[data-copy]");
  if (copyBtn) return copy(copyBtn.dataset.copy);
  const row = e.target.closest("tr[data-go]");
  if (row && !e.target.closest("a, button")) location.hash = row.dataset.go;
});
document.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.matches("tr[data-go]")) location.hash = e.target.dataset.go; });
$("#logout").addEventListener("click", async () => { await fetch("/api/auth/logout", { method: "POST" }); location.href = "/login"; });
window.addEventListener("hashchange", route);

(async () => {
  try {
    const me = await api("/api/auth/me");
    $("#whoName").textContent = me.name; $("#whoBiz").textContent = me.business_name || "";
  } catch { return; }
  route();
})();
