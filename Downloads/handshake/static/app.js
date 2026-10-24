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
  chat_export: "Chat saved",
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
    return m ? `<blockquote class="quote"><b>${esc(m.sender)}</b> on ${esc(m.date)}, ${esc(m.time)}<br>${esc(m.text)}</blockquote>` : "";
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

/* ---------- wiring ---------- */
$("sample").addEventListener("click", async () => {
  try {
    $("chat").value = await (await fetch("/api/sample")).text();
    $("title").value = "Wedding cards for Ravi";
    toast("Sample chat loaded");
  } catch { toast("Could not load the sample", true); }
});

$("analyze").addEventListener("click", (e) => busy(e.target, "Reading…", async () => {
  const fd = new FormData();
  fd.append("title", $("title").value);
  fd.append("chat_text", $("chat").value);
  if ($("file").files[0]) fd.append("file", $("file").files[0]);
  deal = await api("/api/deals", { method: "POST", body: fd });
  history.replaceState(null, "", `?deal=${deal.id}`);
  renderTerms();
  renderProof();
  showStep(2);
}));

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

document.querySelectorAll("#steps button").forEach((b) => b.addEventListener("click", () => { if (deal || +b.dataset.step === 1) showStep(+b.dataset.step); }));

/* reopen a deal from ?deal=ID */
(async () => {
  const id = new URLSearchParams(location.search).get("deal");
  if (!id) return;
  try {
    deal = await api(`/api/deals/${id}`);
    tone = deal.tone || "friendly";
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
    }
    else showStep(2);
  } catch { /* unknown deal: stay on step 1 */ }
})();
