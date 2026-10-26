/* Landing page: a free demo that reads a pasted chat. Everything after it needs an account.
   The result pane starts empty so pressing the button visibly does something. */
const $ = (id) => document.getElementById(id);

async function loadSample() {
  try { $("chat").value = await (await fetch("/api/sample")).text(); } catch { $("chat").value = ""; }
}
function showError(msg) { $("err").textContent = msg; $("err").classList.toggle("hidden", !msg); }
function reset() { $("res").hidden = true; $("idle").hidden = false; showError(""); }
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

async function run() {
  showError("");
  const btn = $("run"); btn.disabled = true; btn.textContent = "Reading the chat...";
  $("res").hidden = true; $("idle").hidden = true; $("out").classList.add("busy");
  try {
    const [res] = await Promise.all([fetch("/api/demo", J("POST", { text: $("chat").value })), pause(600)]);   // short pause so the change is visible
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(Array.isArray(data.detail) ? "Paste a chat first" : data.detail || "Something went wrong");
    show(data);
  } catch (e) { $("idle").hidden = false; showError(e.message); }
  finally { btn.disabled = false; btn.textContent = "Find the agreement"; $("out").classList.remove("busy"); }
}

function show(d) {
  $("res").hidden = false;
  $("meta").textContent = `${d.messages} messages between ${d.parties.join(" and ") || "the parties"}`;
  $("summary").textContent = d.summary || ""; $("summary").hidden = !d.summary;
  $("terms").innerHTML = d.terms.map((t) => `<div class="trow"><div class="lab">${esc(t.label)}${t.changes ? ` <span class="tag yellow">changed ${t.changes}x</span>` : ""}</div>
      <div class="val">${t.value ? esc(t.value) : '<span class="muted">Not agreed in the chat</span>'}</div>
      ${t.refs[0] ? `<div class="from">${esc(t.refs[0].sender)}: "${esc(t.refs[0].text)}"</div>` : ""}</div>`).join("");
  $("open").textContent = d.missing.length ? `${d.missing.length} things are still unsettled, like ${d.missing[0].field.toLowerCase()}.` : "Nothing obvious is missing.";
  $("out").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

$("run").addEventListener("click", run);
$("sample").addEventListener("click", async () => { await loadSample(); reset(); toast("Sample chat loaded"); });
$("chat").addEventListener("input", reset);
loadSample();
