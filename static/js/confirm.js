/* Confirmation page for the no-account link /c/<token>. */
const $ = (id) => document.getElementById(id);
const token = location.pathname.split("/").pop();

/* public page: no login redirect, POST when a body is given */
async function call(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Something went wrong");
  return data;
}

(async () => {
  try {
    const d = await call(`/api/c/${token}`);
    $("intro").textContent = `${d.parties.join(" and ")} agreed this on chat. Please check it.`;
    $("docTitle").textContent = d.title;
    $("agreementText").textContent = d.agreement;
    $("doc").classList.remove("hidden");
    if (d.status === "confirmed") { $("intro").textContent = "This agreement is already confirmed."; return; }
    $("verify").classList.remove("hidden");
  } catch (e) {
    $("intro").textContent = e.message;
  }
})();

$("getCode").addEventListener("click", async (e) => {
  if ($("phone").value.replace(/\D/g, "").length < 10) return toast("Enter a 10-digit phone number", true);
  e.target.disabled = true;
  try {
    const r = await call(`/api/c/${token}/otp`, { phone: $("phone").value });
    if (r.demo_otp) { $("demoCode").textContent = "Demo code: " + r.demo_otp; $("demoCode").classList.remove("hidden"); }
    else toast("Code sent");
    $("respond").classList.remove("hidden");
  } catch (err) { toast(err.message, true); }
  finally { e.target.disabled = false; }
});

async function respond(action) {
  if (action === "change" && !$("note").value.trim()) return toast("Tell us what to change", true);
  try {
    const r = await call(`/api/c/${token}/respond`, { name: $("name").value, otp: $("otp").value, action, note: $("note").value });
    $("verify").classList.add("hidden");
    $("doneTitle").textContent = r.status === "confirmed" ? "Confirmed. Thank you." : "Change request sent.";
    $("doneText").textContent = r.status === "confirmed"
      ? "Your confirmation is saved in the evidence trail. Both sides can now prove what was agreed."
      : "The other side will see your note and update the agreement.";
    $("receipt").textContent = r.receipt;
    $("done").classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (err) { toast(err.message, true); }
}
$("agree").addEventListener("click", () => respond("agree"));
$("change").addEventListener("click", () => respond("change"));
