/* Log in / sign up. Routes: /login, /signup and /join/<token> (a customer's private invite from a dealer).
   API: POST /api/auth/login {email,password}
        POST /api/auth/signup {name,email,password,role,phone?,business_name?,invite_token?}
   Both answer {home}; the server sets the session cookie. */
const $ = (id) => document.getElementById(id);
const inviteToken = location.pathname.startsWith("/join/") ? location.pathname.split("/")[2] : "";
const params = new URLSearchParams(location.search);
let mode = location.pathname === "/login" ? "login" : "signup";
let role = params.get("role") === "customer" ? "customer" : "dealer";
if (inviteToken) role = "customer";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function setError(fieldId, msg) {
  const f = $(fieldId);
  f.classList.toggle("invalid", !!msg);
  f.querySelector(".error").textContent = msg || "";
}
function formError(msg) { $("formError").textContent = msg || ""; $("formError").classList.toggle("hidden", !msg); }
function clearErrors() { ["fName", "fBiz", "fPhone", "fEmail", "fPw"].forEach((id) => setError(id, "")); formError(""); }

function paint() {
  const login = mode === "login";
  $("tabLogin").setAttribute("aria-pressed", login);
  $("tabSignup").setAttribute("aria-pressed", !login);
  $("signupOnly").classList.toggle("hidden", login);
  $("strengthBox").classList.toggle("hidden", login);
  $("title").textContent = login ? "Welcome back" : "Create your account";
  $("lead").textContent = login ? "Log in to see your agreements." : role === "dealer" ? "Set up a dealer account to build and send agreements." : "Set up a customer account to check and approve agreements.";
  $("go").textContent = login ? "Log in" : "Create account";
  $("pw").autocomplete = login ? "current-password" : "new-password";
  $("roleDealer").setAttribute("aria-pressed", role === "dealer");
  $("roleCustomer").setAttribute("aria-pressed", role === "customer");
  $("roleDealer").disabled = !!inviteToken;
  $("fBiz").classList.toggle("hidden", role !== "dealer");
  $("switch").innerHTML = login ? 'New here? <a href="/signup" id="swap">Create an account</a>' : 'Already have an account? <a href="/login" id="swap">Log in</a>';
  $("swap").onclick = (e) => { e.preventDefault(); go(login ? "signup" : "login"); };
  document.title = "Handshake: " + (login ? "log in" : "sign up");
  clearErrors();
}
function go(m) {
  mode = m;
  if (!inviteToken) history.replaceState(null, "", "/" + m);
  paint(); $(m === "login" ? "email" : "name").focus();
}

$("tabLogin").onclick = () => go("login");
$("tabSignup").onclick = () => go("signup");
$("roleDealer").onclick = () => { if (!inviteToken) { role = "dealer"; paint(); } };
$("roleCustomer").onclick = () => { role = "customer"; paint(); };
$("showPw").onclick = () => {
  const show = $("pw").type === "password";
  $("pw").type = show ? "text" : "password";
  $("showPw").textContent = show ? "Hide" : "Show";
  $("showPw").setAttribute("aria-label", show ? "Hide password" : "Show password");
};

/* password strength: a simple length + variety guide, not a rule (the server only needs 8 characters) */
$("pw").addEventListener("input", () => {
  const p = $("pw").value;
  const score = Math.min(4, (p.length >= 8) + (p.length >= 12) + (/[A-Z]/.test(p) && /[a-z]/.test(p)) + (/\d/.test(p) || /[^A-Za-z0-9]/.test(p)));
  document.querySelectorAll("#strength i").forEach((el, i) => el.classList.toggle("on", i < score));
  $("pwHelp").textContent = !p ? "At least 8 characters. A longer phrase is stronger." : p.length < 8 ? `${8 - p.length} more character${8 - p.length > 1 ? "s" : ""} needed.` : ["", "OK", "Good", "Strong", "Very strong"][score] || "OK";
});

function validate() {
  clearErrors();
  let ok = true;
  const bad = (id, msg) => { setError(id, msg); ok = false; };
  if (mode === "signup") {
    if (!$("name").value.trim()) bad("fName", "Enter your name");
    if (role === "dealer" && !$("biz").value.trim()) bad("fBiz", "Enter your business name");
  }
  if (!EMAIL.test($("email").value.trim())) bad("fEmail", "Enter a valid email address");
  if (!$("pw").value) bad("fPw", "Enter your password");
  else if (mode === "signup" && $("pw").value.length < 8) bad("fPw", "Use at least 8 characters");
  if (!ok) document.querySelector(".invalid input")?.focus();
  return ok;
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!validate()) return;
  const body = mode === "login"
    ? { email: $("email").value.trim(), password: $("pw").value }
    : { name: $("name").value.trim(), email: $("email").value.trim(), password: $("pw").value, role, phone: $("phone").value.trim(),
        business_name: role === "dealer" ? $("biz").value.trim() : "", invite_token: inviteToken };
  const btn = $("go"), label = btn.textContent;
  btn.disabled = true; btn.textContent = mode === "login" ? "Logging in..." : "Creating account...";
  try {
    const res = await fetch("/api/auth/" + mode, J("POST", body));
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = typeof data.detail === "string" ? data.detail : data.detail?.[0]?.msg || "Check the form and try again";
      if (mode === "signup" && /email/i.test(msg)) setError("fEmail", msg);
      else if (mode === "signup" && /password/i.test(msg)) setError("fPw", msg);
      else formError(msg);
      btn.disabled = false; btn.textContent = label; return;
    }
    btn.textContent = "Taking you in...";
    location.href = data.home;
  } catch { formError("Could not reach the server. Check your connection and try again."); btn.disabled = false; btn.textContent = label; }
});

if (inviteToken) {
  mode = "signup";
  fetch("/api/join/" + inviteToken).then((r) => (r.ok ? r.json() : Promise.reject())).then((i) => {
    $("invite").innerHTML = `<b>${esc(i.business_name || i.dealer_name)}</b> invited you (${esc(i.customer_name)}). Create a customer account to see your agreements.`;
    $("invite").classList.remove("hidden");
  }).catch(() => { $("invite").textContent = "This invite link is not valid or was already used."; $("invite").classList.remove("hidden"); });
}
paint();
(mode === "login" ? $("email") : $("name")).focus();
