/* Customer portal. Customers never create anything here. They:
     #/          overview, #/requests waiting for an answer, #/history answered, #/dealers who sent them things
     #/t/ID  verify one request term by term against the references, message the dealer, then approve or ask for a change */
const $ = (s, r = document) => r.querySelector(s);
const view = $("#view");
let stopThread = null;

const STATUS = { sent: ["Waiting for your answer", "yellow"], confirmed: ["You approved", "green"], change_requested: ["You asked for changes", "red"] };
const SOURCE = { chat: "chat", voice: "voice note (machine transcript)", image: "screenshot (machine text)", document: "document", note: "call note", file: "file" };
const GST = { included: "GST included", excluded: "GST extra", not_mentioned: "GST not discussed" };
const TRAIL = {
  evidence_added: "Evidence added", terms_extracted: "Terms read from the evidence", terms_confirmed: "Dealer checked the terms",
  agreement_generated: "Agreement written", owner_approved: "Dealer sent it to you", comment_added: "Comment on the agreement",
  counterparty_confirmed: "You approved", counterparty_requested_change: "You asked for a change",
};


/* ---------------------------------------------------------------- list */
function tableOf(rows) {
  return `<div class="tablewrap"><table class="t"><thead><tr><th>Request</th><th>From dealer</th><th>Needed by</th><th>Checked</th><th>Status</th><th>Updated</th></tr></thead><tbody>
    ${rows.map((t) => `<tr data-go="#/t/${t.id}" tabindex="0"><td><b>${esc(t.title)}</b></td><td>${esc(t.dealer_business || t.dealer_name)}<br><span class="muted">${esc(t.dealer_name)}</span></td><td>${day(t.due_date)}</td>
      <td>${t.status === "sent" ? t.checked + " of 4 terms" : "-"}</td><td><span class="tag ${STATUS[t.status][1]}">${esc(STATUS[t.status][0])}</span></td><td>${when(t.updated)}</td></tr>`).join("")}</tbody></table></div>`;
}

async function overview() {
  const all = await api("/api/my/tickets");
  const n = (s) => all.filter((t) => t.status === s).length, waiting = all.filter((t) => t.status === "sent");
  view.innerHTML = `<h1 class="pt">Overview</h1>
    <div class="grid2"><div class="card"><h3>Waiting for your answer</h3><p style="font-size:2rem;font-weight:800;margin:0">${n("sent")}</p></div>
    <div class="card"><h3>You approved</h3><p style="font-size:2rem;font-weight:800;margin:0">${n("confirmed")}</p><p class="muted">${n("change_requested")} sent back for changes</p></div></div>
    <h2>Needs your answer</h2>
    ${waiting.length ? tableOf(waiting) : '<div class="card"><p>Nothing is waiting for you.</p></div>'}`;
}

async function dealersPage() {
  const ds = await api("/api/my/dealers");
  view.innerHTML = `<h1 class="pt">My dealers</h1><p class="muted">Dealers who have sent you agreements. Check these details before you approve anything.</p>
    ${ds.length ? ds.map((d) => `<div class="card"><h3>${esc(d.business || d.name)}</h3><p>${esc(d.name)} · ${esc(d.phone || "no phone")} · ${esc(d.email)}</p>
      <p class="muted">${d.total} request${d.total === 1 ? "" : "s"}${d.waiting ? `, <b>${d.waiting} waiting for you</b>` : ""}</p>
      <a class="btn small plain" href="#/requests?dealer=${encodeURIComponent(d.name)}">See their requests</a></div>`).join("") : '<div class="card"><p>No dealer has sent you anything yet.</p></div>'}`;
}

async function list(q, mode = "requests") {
  const all = await api("/api/my/tickets");
  const dealers = [...new Map(all.map((t) => [t.dealer_name, t.dealer_business || t.dealer_name])).entries()];
  const want = q.get("dealer"), hist = mode === "history";
  let rows = hist ? all.filter((t) => t.status !== "sent") : all.filter((t) => t.status === "sent");
  if (want) rows = rows.filter((t) => t.dealer_name === want);
  const waiting = all.filter((t) => t.status === "sent").length;
  view.innerHTML = `<h1 class="pt">${hist ? "History" : "Requests from dealers"}</h1>
    <p class="muted">${hist ? "Requests you already answered." : "Dealers send you agreements to check. Nothing is final until you approve it."}</p>
    ${dealers.length > 1 ? `<form class="filters" id="filters"><select name="dealer" aria-label="Dealer"><option value="">All dealers</option>${dealers.map(([n, b]) => `<option value="${esc(n)}" ${want === n ? "selected" : ""}>${esc(b)}</option>`).join("")}</select></form>` : ""}
    ${rows.length ? tableOf(rows)
    : `<div class="card"><p>${hist ? "You have not answered anything yet." : "Nothing is waiting for you."}</p><p class="muted">When a dealer sends you an agreement it appears here. If you are expecting one, ask the dealer for your private join link, and sign up through it.</p></div>`}`;
  $("#filters")?.addEventListener("change", (e) => { location.hash = (hist ? "#/history" : "#/requests") + (e.target.value ? "?dealer=" + encodeURIComponent(e.target.value) : ""); });
}

/* ---------------------------------------------------------------- verify one request */
function quotes(refs) {
  return refs.length ? refs.map((r) => `<blockquote class="quote"><b>${esc(r.sender)}</b> on ${esc(r.date)}${r.time ? ", " + esc(r.time) : ""}
      <span class="tag">${esc(SOURCE[r.kind] || r.kind)}</span><br>${esc(r.text)}</blockquote>`).join("")
    : '<p class="muted">No message was linked to this. Ask the dealer where it comes from.</p>';
}

function termCard(t, locked, check) {
  const mine = check?.result;
  const empty = !t.value;
  return `<article class="item term ${mine === "match" ? "ok" : mine === "mismatch" ? "bad" : ""}" data-key="${t.key}">
    <div class="item-head"><h3>${esc(t.label)}</h3><span class="tag state">${empty ? "Not agreed yet" : mine === "match" ? "Matches my records" : mine === "mismatch" ? "Does not match" : "Not checked"}</span></div>
    <div class="value">${empty ? '<span class="muted">Nothing was agreed on this in the chat</span>' : esc(t.value)}
      ${t.key === "price" && !empty ? `<span class="tag">${esc(GST[t.gst] || "")}</span>` : ""}</div>
    ${t.edited ? `<p><span class="tag red">Changed by the dealer</span> The evidence itself said <b>${esc(t.extracted_value || "nothing")}</b>. Ask them why it is different.</p>` : ""}
    ${empty ? "" : `<details open class="refs"><summary>Where this comes from (${t.refs.length} reference${t.refs.length === 1 ? "" : "s"})</summary>${quotes(t.refs)}</details>`}
    ${t.history.length ? `<details><summary>It changed along the way (${t.history.length})</summary>${t.history.map((h) => `<p class="history-line"><s>${esc(h.old)}</s> &rarr; <b>${esc(h.new)}</b></p>${quotes(h.refs)}`).join("")}</details>` : ""}
    ${empty ? "" : `<div class="verdict">
      <label class="choice"><input type="radio" name="chk_${t.key}" value="match" ${mine === "match" ? "checked" : ""} ${locked ? "disabled" : ""}> This matches my records</label>
      <label class="choice"><input type="radio" name="chk_${t.key}" value="mismatch" ${mine === "mismatch" ? "checked" : ""} ${locked ? "disabled" : ""}> This does not match</label>
      <button class="btn small plain" data-ask="${t.key}">Ask the dealer about this</button>
      <input type="text" class="f-note ${mine === "mismatch" ? "" : "hidden"}" maxlength="300" value="${esc(check?.note || "")}" placeholder="What is different? The dealer will see this" aria-label="What is different" ${locked ? "disabled" : ""}>
    </div>`}
  </article>`;
}

async function detail(id) {
  const r = await api("/api/my/tickets/" + id);
  const locked = r.status !== "sent";
  const checks = r.checks;
  const needed = r.terms.filter((t) => t.value).map((t) => t.key);
  const st = STATUS[r.status];

  view.innerHTML = `<p><a href="#/requests">&larr; All requests</a></p>
    <div class="head"><div><h1 class="pt">${esc(r.title)}</h1><p><span class="tag ${st[1]}">${esc(st[0])}</span> Sent ${when(r.sent_at)}${r.due_date ? ", needed by " + day(r.due_date) : ""}</p></div></div>
    <div class="dealer-card"><b>${esc(r.dealer_business || r.dealer_name)}</b> sent you this request.<br>
      <span class="muted">Dealer: ${esc(r.dealer_name)}${r.dealer_phone ? ", phone " + esc(r.dealer_phone) : ""}, email ${esc(r.dealer_email)}. Not the dealer you expected? Do not approve, and tell them.</span></div>
    ${r.description ? `<p><b>About this deal:</b> ${esc(r.description)}</p>` : ""}
    ${r.parties.length ? `<p class="muted">People in the evidence: ${r.parties.map(esc).join(", ")}</p>` : ""}

    ${locked ? "" : `<div class="progress" id="progress" role="status"></div>`}
    <h2>Check each term against your own records</h2>
    <p class="muted">Compare what the dealer says with your own chat, bills and memory. Read the references under each term. If something looks wrong, use “Ask the dealer about this”.</p>
    <div id="terms">${r.terms.map((t) => termCard(t, locked, checks[t.key])).join("")}</div>

    ${r.open_points.length ? `<div class="card"><h2>Not settled yet</h2><p class="muted">These were not clearly agreed in the evidence. Talk to the dealer if any matter to you.</p>
      <ul>${r.open_points.map((o) => `<li><b>${esc(o.field)}</b>: ${esc(o.why)}</li>`).join("")}</ul></div>` : ""}

    <div class="card"><h2>Chat with the dealer</h2><p class="muted">Ask anything before you decide. Comments on the agreement are saved in the shared trail. Plain chat is not.</p><div id="thread"></div></div>

    <div class="card"><h2>Proof that nothing was changed</h2>
      <p><span class="tag ${r.proof.valid ? "green" : "red"}">${r.proof.valid ? "Intact" : "Something was changed"}</span>
        ${r.proof.entries} entries. ${r.proof.valid ? "Every file and every step still matches its fingerprint." : `Broken at step ${r.proof.broken_at || "-"}${r.proof.bad_files ? `, ${r.proof.bad_files} file(s) changed` : ""}. Do not approve until the dealer explains.`}</p>
      <details><summary>Evidence the dealer added (${r.evidence.length})</summary>
        ${r.evidence.map((e) => `<p><b>${esc(e.label || e.name)}</b> <span class="tag">${esc(SOURCE[e.kind] || e.kind)}</span>${e.machine_text ? ' <span class="tag yellow">machine text</span>' : ""}<br>
          <span class="muted">Added ${when(e.added)}. Fingerprint</span> <span class="fingerprint">${esc(e.sha256)}</span></p>`).join("") || '<p class="muted">None</p>'}</details>
      <details><summary>Step-by-step trail (${r.trail.length})</summary><ol class="hist">
        ${r.trail.map((e) => `<li><b>${esc(TRAIL[e.kind] || e.kind)}</b>${e.name && e.kind !== "evidence_added" ? " by " + esc(e.name) : e.name ? ": " + esc(e.name) : ""}<br><span class="muted">${when(e.ts)}</span> <span class="fingerprint">${esc(e.hash.slice(0, 24))}…</span></li>`).join("")}</ol></details></div>

    <div class="card"><h2>Your answer</h2>
      <div class="gate" id="gate"></div>
      <details><summary>Read the full agreement</summary><pre class="paper">${esc(r.agreement)}</pre></details>
      ${locked ? `<p class="muted">${r.status === "confirmed" ? "You approved this. It is saved in the shared evidence trail, with what you checked." : "You asked the dealer for changes. They will update the agreement."}</p>`
      : `<label for="note" style="margin-top:12px">Note for the dealer (needed if you ask for a change and have not written what is wrong above)</label><textarea id="note" class="short" maxlength="500"></textarea>
        <div class="row"><button class="btn primary" id="agree" disabled>I checked everything. Approve</button><button class="btn plain" id="change">Ask for changes</button></div>`}
    </div>`;

  stopThread = mountThread($("#thread"), id);
  if (locked) { $("#gate").remove(); return; }

  const state = { ...checks };
  function paint() {
    const ok = needed.filter((k) => state[k]?.result === "match").length;
    const bad = needed.filter((k) => state[k]?.result === "mismatch").length;
    $("#progress").innerHTML = `${ok} of ${needed.length} terms match your records<span class="bar"><i style="width:${needed.length ? (100 * ok) / needed.length : 0}%"></i></span>`;
    const ready = ok === needed.length && !bad;
    $("#agree").disabled = !ready;
    $("#gate").className = "gate" + (ready ? " ready" : "");
    $("#gate").textContent = ready ? "Everything matches your records. You can approve."
      : bad ? "You marked something as not matching. Ask the dealer to change it instead of approving."
      : `Check ${needed.length - ok} more term${needed.length - ok === 1 ? "" : "s"} above before you can approve.`;
    document.querySelectorAll(".term").forEach((card) => {
      const c = state[card.dataset.key]?.result;
      card.classList.toggle("ok", c === "match"); card.classList.toggle("bad", c === "mismatch");
      const s = card.querySelector(".state");
      if (s && card.querySelector(".verdict")) s.textContent = c === "match" ? "Matches my records" : c === "mismatch" ? "Does not match" : "Not checked";
      card.querySelector(".f-note")?.classList.toggle("hidden", c !== "mismatch");
    });
  }
  async function save(key, result, note = "") {
    try { state[key] = result === "clear" ? undefined : { result, note }; paint();
      await api(`/api/my/tickets/${id}/checks/${key}`, J("PUT", { result, note })); }
    catch (e) { toast(e.message, true); }
  }
  document.querySelectorAll(".term").forEach((card) => {
    const key = card.dataset.key;
    card.querySelectorAll("input[type=radio]").forEach((rad) => rad.addEventListener("change", () => save(key, rad.value, card.querySelector(".f-note").value)));
    card.querySelector(".f-note")?.addEventListener("change", (e) => save(key, "mismatch", e.target.value));
    card.querySelector("[data-ask]")?.addEventListener("click", () => {
      const t = r.terms.find((x) => x.key === key);
      stopThread.prefill(`About "${t.label}" (${t.value}): `);
    });
  });
  paint();

  const respond = async (action) => {
    try {
      await api(`/api/my/tickets/${id}/respond`, J("POST", { action, note: $("#note").value }));
      toast(action === "agree" ? "Thank you. Approved." : "Change request sent"); detail(id);
    } catch (err) { toast(err.message, true); }
  };
  $("#agree").addEventListener("click", () => respond("agree"));
  $("#change").addEventListener("click", () => respond("change"));
}

/* ---------------------------------------------------------------- router */
async function route() {
  if (stopThread) { stopThread(); stopThread = null; }
  const [path, qs] = (location.hash.slice(1) || "/").split("?");
  const parts = path.split("/").filter(Boolean);
  const root = parts[0] || "";
  document.querySelectorAll("[data-nav]").forEach((a) => a.toggleAttribute("aria-current", a.dataset.nav === (root === "t" ? "requests" : root)));
  const q = new URLSearchParams(qs || "");
  try { root === "t" ? await detail(parts[1]) : root === "requests" ? await list(q) : root === "history" ? await list(q, "history")
        : root === "dealers" ? await dealersPage() : await overview(); }
  catch (err) { view.innerHTML = `<p class="muted">${esc(err.message)}</p><p><a href="#/requests">Back</a></p>`; }
  window.scrollTo(0, 0);
}
document.addEventListener("click", (e) => { const row = e.target.closest("tr[data-go]"); if (row) location.hash = row.dataset.go; });
document.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.matches("tr[data-go]")) location.hash = e.target.dataset.go; });
$("#logout").addEventListener("click", async () => { await fetch("/api/auth/logout", { method: "POST" }); location.href = "/login"; });
window.addEventListener("hashchange", route);
api("/api/auth/me").then((me) => { $("#whoName").textContent = me.name; route(); });
