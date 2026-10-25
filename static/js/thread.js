/* Chat + comments on one ticket, used by both the dealer and the customer pages.
   mountThread(element, ticketId) returns a function that stops the polling. */
function mountThread(el, ticketId) {
  const base = `/api/tickets/${ticketId}/thread`;
  let last = 0, kind = "chat", stopped = false;

  el.innerHTML = `
    <div class="thread-list" role="log" aria-live="polite"><p class="muted" data-empty>No messages yet.</p></div>
    <form class="thread-form">
      <div class="seg" role="group" aria-label="Message type">
        <button type="button" data-kind="chat" aria-pressed="true">Chat</button>
        <button type="button" data-kind="comment" aria-pressed="false">Comment on agreement</button>
      </div>
      <p class="muted" data-hint>Quick messages between the two of you.</p>
      <textarea class="short" maxlength="2000" aria-label="Message" placeholder="Write a message"></textarea>
      <button class="btn primary" type="submit">Send</button>
    </form>`;
  const list = el.querySelector(".thread-list"), form = el.querySelector("form"), box = form.querySelector("textarea");

  form.querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => {
    kind = b.dataset.kind;
    form.querySelectorAll("[data-kind]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    form.querySelector("[data-hint]").textContent = kind === "comment"
      ? "Comments on the agreement are saved in the evidence trail for both sides."
      : "Quick messages between the two of you.";
  }));

  function draw(messages) {
    if (!messages.length) return;
    list.querySelector("[data-empty]")?.remove();
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
    for (const m of messages) {
      last = Math.max(last, m.id);
      const div = document.createElement("div");
      div.className = "msg " + (m.mine ? "mine" : "theirs");
      div.innerHTML = `<div class="msg-meta"><b>${esc(m.sender_name)}</b> ${esc(m.sender_role)}
        ${m.kind === "comment" ? '<span class="tag yellow">comment on agreement</span>' : ""}
        <span class="muted">${esc(new Date(m.created).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }))}</span></div>
        <div>${esc(m.body)}</div>`;
      list.appendChild(div);
    }
    if (nearBottom || messages.some((m) => m.mine)) list.scrollTop = list.scrollHeight;
  }

  async function poll() {
    if (stopped || !el.isConnected) return stop();
    try {
      const r = await fetch(`${base}?after=${last}`);
      if (r.ok) draw(await r.json());
    } catch { /* offline: try again next tick */ }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = box.value.trim();
    if (!body) return;
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      const r = await fetch(base, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body, kind }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Could not send");
      box.value = "";
      await poll();
    } catch (err) { alert(err.message); }
    finally { btn.disabled = false; }
  });

  const timer = setInterval(poll, 4000);
  function stop() { stopped = true; clearInterval(timer); }
  stop.prefill = (text) => {
    form.querySelector('[data-kind="chat"]').click();
    box.value = text;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    box.focus();
    box.setSelectionRange(text.length, text.length);
  };
  poll();
  return stop;
}
