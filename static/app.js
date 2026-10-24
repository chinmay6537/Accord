const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const FIELDS = [
  { key: "scope", label: "What was agreed", tall: true },
  { key: "price", label: "Price" },
  { key: "delivery", label: "Delivery" },
  { key: "payment_terms", label: "Payment", tall: true },
];
const FIELD_LABEL = { scope: "What was agreed", price: "Price", delivery: "Delivery", payment_terms: "Payment" };
const KIND = {
  evidence_added: "Evidence added",
  evidence_edited: "Evidence text or details edited",
  evidence_removed: "Evidence removed from the analysis",
  terms_extracted: "Terms read from the chat",
  terms_confirmed: "Terms checked by you",
  agreement_generated: "Agreement written",
  owner_approved: "You approved and sent it",
  counterparty_confirmed: "Other party agreed",
  counterparty_requested_change: "Other party asked for a change",
};
const STATUS = {
  draft: "Draft",
  sent: "Waiting for the other party",
  confirmed: "Confirmed by both sides",
  change_requested: "The other party asked for changes",
};

const SRC = { voice: "voice note", image: "screenshot", document: "document", note: "call note", file: "file" };
const KIND_NAME = { chat: "Chat", voice: "Voice note", image: "Screenshot", document: "Document", note: "Note", file: "File" };
const TEXT_STATUS = {
  ready: ["Text read", "green"], typed: ["Typed by you", "green"], confirmed: ["Checked by you", "green"],
  machine: ["Machine text: check it", "yellow"], needs_text: ["Needs text", "red"],
};

let deal = null;
let maxStep = 1;
let tone = "friendly";

/* ---------- helpers ---------- */
function toast(msg, err = false) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.setAttribute("role", "status");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3200);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Something went wrong");
  return data;
}

const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

async function busy(btn, label, fn) {
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = label;
  try { return await fn(); }
  catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = old; }
}

function showStep(n) {
  maxStep = Math.max(maxStep, n);
  [1, 2, 3, 4].forEach((i) => $("s" + i).classList.toggle("hidden", i !== n));
  document.querySelectorAll("#steps button").forEach((b) => {
    const i = +b.dataset.step;
    b.disabled = i > maxStep;
    if (i === n) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ---------- citations ---------- */
function cites(ids = []) {
  return ids.map((i) => `<button type="button" class="cite" data-ids="${esc(ids.join(","))}" data-id="${i}" aria-expanded="false" title="Show message ${i}">#${i}</button>`).join("");
}

document.addEventListener("click", (e) => {
  const b = e.target.closest(".cite");
  if (!b || !deal) return;
  const ids = b.dataset.ids.split(",").map(Number);
  document.querySelectorAll(".cite").forEach((c) => c.setAttribute("aria-expanded", String(c.dataset.ids === b.dataset.ids && c === b)));
  $("sources").innerHTML = ids.map((i) => {
    const m = deal.messages.find((x) => x.id === i);
    return m ? `<blockquote class="quote"><b>${esc(m.sender)}</b> on ${esc(m.date)}${m.time ? ", " + esc(m.time) : ""}${m.kind && m.kind !== "chat" ? ` <span class="tag">${esc(SRC[m.kind] || m.kind)}: ${esc(m.item_name)}</span>` : ""}<br>${esc(m.text)}</blockquote>` : "";
  }).join("");
  $("sources").scrollIntoView({ behavior: "smooth", block: "nearest" });
});

/* ---------- step 2: terms ---------- */
function renderTerms() {
  const t = deal.terms;
  $("engine").textContent = t.engine === "claude" ? "Read by Claude. Check every line before you continue." : "Read by built-in rules (no API key set). Check every line before you continue.";
  $("parties").innerHTML = t.parties.map((p) => `<span class="tag yellow">${esc(p.name)}</span>`).join("");

  const gst = { included: ["GST included", "green"], excluded: ["GST extra", "yellow"], not_mentioned: ["GST not discussed", "red"] }[t.price.gst] || ["", ""];
  $("termFields").innerHTML = FIELDS.map((f) => {
    const term = t[f.key];
    const extra = f.key === "price" ? `<span class="tag ${gst[1]}">${gst[0]}</span>` : "";
    const input = f.tall
      ? `<textarea class="short" id="f_${f.key}">${esc(term.value)}</textarea>`
      : `<input type="text" id="f_${f.key}" value="${esc(term.value)}">`;
    return `<div><label for="f_${f.key}">${f.label}</label>${input}<div style="margin:-8px 0 16px">${extra}${cites(term.source_ids)}</div></div>`;
  }).join("");
  $("sources").innerHTML = "";

  const sup = t.superseded || [];
  $("supersededCard").classList.toggle("hidden", !sup.length);
  $("superseded").innerHTML = sup.map((s) =>
    `<p style="margin:0 0 10px"><b>${esc(FIELD_LABEL[s.field] || s.field)}:</b> <s>${esc(s.old)}</s> &rarr; <b>${esc(s.new)}</b> ${cites(s.source_ids)}</p>`).join("");

  const gaps = [
    ...(t.ambiguities || []).map((a) => ({ cls: "amb", tag: "Vague", tagCls: "yellow", title: FIELD_LABEL[a.field] || a.field, text: a.issue, nudge: a.nudge, ids: a.evidence_ids })),
    ...(t.missing || []).map((m) => ({ cls: "", tag: "Not discussed", tagCls: "red", title: m.field, text: m.why, nudge: m.nudge, ids: [] })),
  ];
  $("gaps").innerHTML = gaps.length ? gaps.map((g, i) => `
    <div class="gap ${g.cls}">
      <span class="tag ${g.tagCls}">${g.tag}</span> <b>${esc(g.title)}</b>
      <div class="muted">${esc(g.text)} ${cites(g.ids)}</div>
      <div class="nudge" id="nudge${i}">${esc(g.nudge)}</div>
      <div class="row">
        <a class="btn small plain" target="_blank" rel="noopener" href="https://wa.me/?text=${encodeURIComponent(g.nudge)}">Send on WhatsApp</a>
        <button class="btn small plain" data-copy="${i}">Copy</button>
      </div>
    </div>`).join("") : "<p>Nothing is missing. Nice and clear.</p>";
  document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", () => {
    navigator.clipboard.writeText($("nudge" + b.dataset.copy).textContent).then(() => toast("Message copied"));
  }));
}

/* ---------- step 3: agreement ---------- */
function renderAgreement() {
  $("agreementText").textContent = deal.agreement || "";
  $("toneFriendly").setAttribute("aria-pressed", String(tone === "friendly"));
  $("toneFormal").setAttribute("aria-pressed", String(tone === "formal"));
}

async function saveTermsAndMakeAgreement() {
  const body = Object.fromEntries(FIELDS.map((f) => [f.key, $("f_" + f.key).value]));
  deal = await api(`/api/deals/${deal.id}/terms`, json("PUT", body));
  deal = await api(`/api/deals/${deal.id}/agreement`, json("POST", { tone }));
  renderAgreement();
  renderProof();
  showStep(3);
}

/* ---------- step 4: proof ---------- */
function renderProof() {
  const v = deal.verification;
  const stamp = $("stamp");
  stamp.textContent = v.valid ? "Intact" : "Tampered";
  stamp.className = "stamp " + (v.valid ? "ok" : "bad");
  $("statusLine").textContent = `${STATUS[deal.status] || deal.status}. ${v.length} entries. Latest fingerprint ${v.head.slice(0, 12)}…`;
  $("chain").innerHTML = deal.chain.map((e) => {
    const broken = v.broken_at && e.seq >= v.broken_at;
    const who = e.meta.name ? ` by ${esc(e.meta.name)}` : "";
    const note = e.meta.note ? `<div class="meta">“${esc(e.meta.note)}”</div>` : "";
    return `<li class="${broken ? "broken" : ""}">
      <h3>${e.seq}. ${esc(KIND[e.kind] || e.kind)}${who}</h3>
      <div class="meta">${esc(e.ts.replace("T", " ").replace("+00:00", " UTC"))}</div>${note}
      <code title="${esc(e.entry_hash)}">entry ${esc(e.entry_hash.slice(0, 24))}…</code><br>
      <code title="${esc(e.prev_hash)}">after ${esc(e.prev_hash.slice(0, 24))}…</code>
    </li>`;
  }).join("");
  $("bundle").href = `/api/deals/${deal.id}/bundle`;
  $("bundle").setAttribute("download", `evidence-${deal.id}.json`);
}

/* ---------- step 1: evidence ---------- */
const fmtSize = (n) => (n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB");
const fileUrl = (id) => `/api/cases/${deal.id}/items/${id}/file`;

async function ensureCase() {
  if (deal && deal.id) return deal.id;
  deal = await api("/api/cases", json("POST", { title: $("title").value }));
  history.replaceState(null, "", `?deal=${deal.id}`);
  return deal.id;
}

async function postItems(fd) {
  const id = await ensureCase();
  const r = await api(`/api/cases/${id}/items`, { method: "POST", body: fd });
  deal.status = "collecting";
  renderEvidence(r);
}

function itemCard(it) {
  const [stLabel, stCls] = TEXT_STATUS[it.text_status] || ["", ""];
  let media = "";
  if (it.kind === "voice") media = `<audio controls preload="none" src="${fileUrl(it.id)}"></audio>`;
  else if (it.kind === "image" && it.mime !== "image/heic") media = `<img class="thumb" alt="${esc(it.name)}" src="${fileUrl(it.id)}">`;
  const meta = [fmtSize(it.size), it.kind === "chat" ? `${it.message_count} messages` : ""].filter(Boolean).join(", ");

  let body = "";
  if (it.editable) {
    const hint = it.text_status === "needs_text"
      ? "We could not read this automatically. Type what it says (listen to the audio or read the image) so it counts."
      : it.text_status === "machine" ? "Read by a machine. Fix any mistakes, then save to mark it as checked." : "";
    body = `${hint ? `<p class="muted">${hint}</p>` : ""}
      <label for="t_${it.id}">What it says</label>
      <textarea id="t_${it.id}" class="f-text">${esc(it.text || "")}</textarea>`;
  } else if (it.preview) {
    body = `<pre class="peek">${esc(it.preview)}</pre>`;
  }
  const details = it.kind === "chat" ? "" : `
    <div class="grid3">
      <div><label for="l_${it.id}">Label</label><input id="l_${it.id}" class="f-label" type="text" value="${esc(it.label)}" placeholder="${esc(KIND_NAME[it.kind])}"></div>
      <div><label for="w_${it.id}">Who said it</label><input id="w_${it.id}" class="f-speaker" type="text" value="${esc(it.speaker)}" placeholder="Suresh"></div>
      <div><label for="d_${it.id}">When</label><input id="d_${it.id}" class="f-when" type="datetime-local" value="${esc(it.occurred_at)}"></div>
    </div>`;
  const save = it.kind === "chat" ? "" : `<button class="btn small primary" data-act="save" data-id="${it.id}">Save</button>`;
  return `<article class="item" data-id="${it.id}">
    <div class="item-head">
      <h3>${esc(it.label || it.name)}</h3>
      <div><span class="tag">${esc(KIND_NAME[it.kind])}</span><span class="tag ${stCls}">${esc(stLabel)}</span></div>
    </div>
    <div class="muted">${esc(it.name)}, ${meta}. Fingerprint <code title="${esc(it.sha256)}">${esc(it.sha256.slice(0, 12))}…</code></div>
    ${media}${body}${details}
    <div class="row" style="margin-top:6px">${save}
      <a class="btn small plain" href="${fileUrl(it.id)}" target="_blank" rel="noopener">Open original</a>
      <button class="btn small danger" data-act="remove" data-id="${it.id}">Remove</button>
    </div>
  </article>`;
}

function renderEvidence(r) {
  $("count").textContent = r.items.length;
  $("items").innerHTML = r.items.length ? r.items.map(itemCard).join("") : '<p class="muted">Nothing added yet.</p>';
  const rd = r.readiness;
  const lines = [
    ...rd.blockers.map((t) => `<li class="block">${esc(t)}</li>`),
    ...rd.warnings.map((t) => `<li>${esc(t)}</li>`),
  ];
  if (rd.can_analyze && !lines.length) lines.push(`<li class="ok">All ${rd.total} items are readable. ${rd.people.length ? "People found: " + esc(rd.people.join(", ")) + "." : ""}</li>`);
  else if (rd.can_analyze && rd.people.length) lines.push(`<li class="ok">${rd.readable} of ${rd.total} items are readable. People found: ${esc(rd.people.join(", "))}.</li>`);
  $("readiness").innerHTML = `<ul class="issues">${lines.join("")}</ul>`;
  $("analyze").disabled = !rd.can_analyze;
}

function toggle(id, show) { $(id).classList.toggle("hidden", !show); }

function addFiles(list) {
  const files = [...list];
  if (!files.length) return;
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const label = files.length === 1 ? files[0].name : files.length + " files";
  toast("Adding " + label + "…");
  postItems(fd).then(() => toast("Added " + label)).catch((e) => toast(e.message, true));
}

const drop = $("drop");
drop.addEventListener("click", () => $("files").click());
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("files").click(); } });
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); addFiles(e.dataTransfer.files); });
$("files").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });

$("noteBtn").addEventListener("click", () => { toggle("noteForm", true); toggle("pasteBox", false); $("nLabel").focus(); });
$("pasteBtn").addEventListener("click", () => { toggle("pasteBox", true); toggle("noteForm", false); $("chat").focus(); });
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => toggle(b.dataset.close, false)));

$("noteForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!$("nText").value.trim()) return toast("Write what was agreed", true);
  const fd = new FormData();
  fd.append("kind", "note");
  fd.append("label", $("nLabel").value || "Note");
  fd.append("speaker", $("nSpeaker").value);
  fd.append("occurred_at", $("nWhen").value);
  fd.append("text", $("nText").value);
  try {
    await postItems(fd);
    e.target.reset();
    toggle("noteForm", false);
    toast("Note added");
  } catch (err) { toast(err.message, true); }
});

$("addPaste").addEventListener("click", (e) => busy(e.target, "Adding…", async () => {
  if (!$("chat").value.trim()) throw new Error("Paste the chat first");
  const fd = new FormData();
  fd.append("kind", "chat");
  fd.append("text", $("chat").value);
  await postItems(fd);
  $("chat").value = "";
  toggle("pasteBox", false);
  toast("Chat added");
}));

$("sample").addEventListener("click", (e) => busy(e.target, "Loading…", async () => {
  const text = await (await fetch("/api/sample")).text();
  const fd = new FormData();
  fd.append("kind", "chat");
  fd.append("name", "sample-chat.txt");
  fd.append("text", text);
  $("title").value = "Wedding cards for Ravi";
  await postItems(fd);
  toast("Sample chat added");
}));

$("items").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const id = btn.dataset.id;
  const card = btn.closest(".item");
  try {
    if (btn.dataset.act === "remove") {
      if (!confirm("Remove this from the analysis? The original stays in the evidence trail.")) return;
      renderEvidence(await api(`/api/cases/${deal.id}/items/${id}`, { method: "DELETE" }));
      toast("Removed");
    } else {
      const body = {
        label: card.querySelector(".f-label")?.value,
        speaker: card.querySelector(".f-speaker")?.value,
        occurred_at: card.querySelector(".f-when")?.value,
        text: card.querySelector(".f-text")?.value,
      };
      renderEvidence(await api(`/api/cases/${deal.id}/items/${id}`, json("PUT", body)));
      toast("Saved");
    }
  } catch (err) { toast(err.message, true); }
});

$("analyze").addEventListener("click", (e) => busy(e.target, "Reading…", async () => {
  deal = await api(`/api/cases/${deal.id}/analyze`, json("POST", { title: $("title").value }));
  renderTerms();
  renderProof();
  showStep(2);
}));

/* ---------- wiring ---------- */
$("toAgreement").addEventListener("click", (e) => busy(e.target, "Writing…", saveTermsAndMakeAgreement));
$("back2").addEventListener("click", () => showStep(2));

for (const [id, t] of [["toneFriendly", "friendly"], ["toneFormal", "formal"]]) {
  $(id).addEventListener("click", async () => {
    tone = t;
    try { deal = await api(`/api/deals/${deal.id}/agreement`, json("POST", { tone })); renderAgreement(); renderProof(); }
    catch (e) { toast(e.message, true); }
  });
}

$("send").addEventListener("click", (e) => busy(e.target, "Sending…", async () => {
  const r = await api(`/api/deals/${deal.id}/send`, json("POST"));
  deal = r;
  $("confirmUrl").value = r.confirm_url;
  $("waLink").href = "https://wa.me/?text=" + encodeURIComponent(`Please read and confirm our agreement: ${r.confirm_url}`);
  $("openLink").href = r.confirm_url;
  $("linkbox").classList.remove("hidden");
  renderProof();
  maxStep = 4;
  showStep(3);
  toast("Ready to send. Share the link.");
}));

$("copyLink").addEventListener("click", () => navigator.clipboard.writeText($("confirmUrl").value).then(() => toast("Link copied")));

$("refresh").addEventListener("click", async () => {
  try { deal = await api(`/api/deals/${deal.id}`); renderProof(); toast("Updated"); }
  catch (e) { toast(e.message, true); }
});

$("tamper").addEventListener("click", async () => {
  try { deal = await api(`/api/deals/${deal.id}/demo-tamper`, json("POST")); renderProof(); toast("An old entry was edited. Look at the stamp.", true); }
  catch (e) { toast(e.message, true); }
});

$("verifyFile").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  try {
    const r = await api("/api/verify-file", { method: "POST", body: fd });
    $("verifyResult").innerHTML = r.ok
      ? `<span class="tag green">Match</span> Saved as entry ${r.matches[0].seq} (${esc(KIND[r.matches[0].kind] || r.matches[0].kind)}) in deal ${esc(r.matches[0].deal_id)}.`
      : `<span class="tag red">No match</span> This file is not in any saved trail. It was changed, or it came from somewhere else.`;
  } catch (err) { toast(err.message, true); }
});

document.querySelectorAll("#steps button").forEach((b) => b.addEventListener("click", () => { if (+b.dataset.step === 1 || (deal && deal.terms)) showStep(+b.dataset.step); }));

/* reopen a deal from ?deal=ID */
(async () => {
  const id = new URLSearchParams(location.search).get("deal");
  if (!id) return;
  try {
    deal = await api(`/api/deals/${id}`);
    tone = deal.tone || "friendly";
    $("title").value = deal.title;
    renderEvidence(await api(`/api/cases/${id}/items`));
    if (!deal.terms) return;            // still collecting evidence
    renderTerms();
    renderProof();
    if (deal.agreement) {
      renderAgreement();
      if (deal.status !== "draft") {
        const url = `${location.origin}/c/${deal.token}`;
        $("confirmUrl").value = url;
        $("openLink").href = url;
        $("waLink").href = "https://wa.me/?text=" + encodeURIComponent(`Please read and confirm our agreement: ${url}`);
        $("linkbox").classList.remove("hidden");
      }
      maxStep = 4;
      showStep(deal.status === "draft" ? 3 : 4);
    } else if (deal.status === "draft") showStep(2);
  } catch { /* unknown deal: stay on step 1 */ }
})();
