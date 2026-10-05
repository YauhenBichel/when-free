// when-free on a phone. The token arrives once in the address fragment (#t=...), which browsers never send to a
// server, and is then kept only on this device. Everything shown is set with textContent: nothing becomes HTML.
"use strict";

const KEY = "when-free-token";
const NAME = "when-free-device";
const $ = (id) => document.getElementById(id);

function token() {
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.get("t")) {
    try {
      localStorage.setItem(KEY, hash.get("t"));
      if (hash.get("n")) localStorage.setItem(NAME, hash.get("n"));
    } catch (e) { /* private mode: works for this visit only */ }
    history.replaceState(null, "", location.pathname);      // the token leaves the address bar and history
    return hash.get("t");
  }
  try { return localStorage.getItem(KEY); } catch (e) { return null; }
}

const TOKEN = token();

async function ask(path, body) {
  const options = { headers: { Authorization: "Bearer " + TOKEN }, cache: "no-store" };
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let data;
  try { data = await response.json(); } catch (e) { data = { ok: false, error: "The computer sent an answer this page cannot read." }; }
  if (response.status === 401) {
    try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ }
    throw new Error("This phone is no longer paired. Add it again on your computer: whenfree devices add");
  }
  if (!data.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

function showError(error) {
  const box = $("error");
  box.textContent = error ? (error.message || String(error)) : "";
  box.hidden = !error;
}

async function refreshNow() {
  try {
    const { data, text } = await ask("status");
    const lines = text.split("\n");
    $("status").textContent = lines[0];
    $("status").className = "big " + (data.free_now ? "free" : "busy");
    $("status-more").textContent = lines.slice(1).join(" · ");
    showError(null);
  } catch (e) {
    $("status").textContent = "?";
    showError(e);
  }
}

async function refreshWeek() {
  try {
    const { data } = await ask("free_slots", {});
    const list = $("week");
    list.replaceChildren();
    for (const day of data.days) {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.className = "day";
      label.textContent = day.label;
      const free = document.createElement("span");
      free.textContent = day.free.length ? day.free.map(([a, b]) => a + "–" + b).join(", ") : "no free slot";
      if (!day.free.length) free.className = "quiet";
      item.append(label, free);
      list.append(item);
    }
  } catch (e) {
    showError(e);
  }
}

async function answer(event) {
  event.preventDefault();
  const message = $("message").value.trim();
  if (!message) return;
  const button = event.submitter || $("ask").querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const { data, text } = await ask("free_slots", { message });
    const lines = text.split("\n");
    const slots = lines.filter((l) => l.startsWith("- "));
    $("answer-head").textContent = lines[0];
    $("answer-text").textContent = slots.join("\n");
    $("answer-note").textContent = lines.filter((l) => l && !l.startsWith("- ") && l !== lines[0]).join(" ");
    $("answer").hidden = false;
    $("answer").scrollIntoView({ behavior: "smooth", block: "start" });
    showError(null);
  } catch (e) {
    $("answer").hidden = true;
    showError(e);
  } finally {
    button.disabled = false;
  }
}

function start() {
  if (!TOKEN) {
    $("setup").hidden = false;
    $("now").hidden = true;
    return;
  }
  try { $("device").textContent = localStorage.getItem(NAME) || ""; } catch (e) { /* ignore */ }
  $("ask").addEventListener("submit", answer);
  $("paste").addEventListener("click", async () => {
    try { $("message").value = await navigator.clipboard.readText(); } catch (e) { $("message").focus(); }
  });
  $("copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("answer-text").textContent);
      $("copy").textContent = "Copied";
      setTimeout(() => { $("copy").textContent = "Copy"; }, 1500);
    } catch (e) { showError(new Error("Copying is not allowed here; select the text instead.")); }
  });
  if (navigator.share) {
    $("share").hidden = false;
    $("share").addEventListener("click", () => navigator.share({ text: $("answer-text").textContent }).catch(() => {}));
  }
  refreshNow();
  refreshWeek();
  setInterval(refreshNow, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { refreshNow(); refreshWeek(); } });
}

start();
