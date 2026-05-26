const $ = (id) => document.getElementById(id);
const USER_ID = "local-user";

const state = {
  activeConversationId: null,
  // A stable token for whatever the user is currently looking at. For a saved
  // chat it's the conversation id; for an unsaved "New prompt" view it's a
  // unique "new:N" token. This lets an in-flight optimization tell whether the
  // user is still on the chat it belongs to, so starting a new chat never wipes
  // the one being optimized.
  activeViewToken: null,
  conversations: [],
  models: [],
  health: null,
  busy: false,
  // The optimization currently in flight (only one at a time): which view
  // started it and the prompt text, so we can re-show a pending bubble if the
  // user navigates back to it.
  activeRun: null,
};

let viewCounter = 0;
function freshViewToken() {
  viewCounter += 1;
  return `new:${viewCounter}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function truncate(value, limit = 180) {
  const text = String(value ?? "").trim();
  return text.length > limit ? `${text.slice(0, limit - 3)}...` : text;
}

function setStatus(message) {
  $("runStatus").textContent = message;
}

// Busy reflects whether an optimization is running. It is decoupled from the
// status text so that navigating between chats (which changes the status line)
// never re-enables the send button while a run is still in flight.
function setBusy(busy) {
  state.busy = busy;
  $("runStatus").classList.toggle("busy", busy);
  $("optimizeButton").disabled = busy;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    const body = await response.text();
    try {
      message = JSON.parse(body).detail || message;
    } catch {
      message = body || message;
    }
    throw new Error(message);
  }
  return response.json();
}

/* ============================ Views ============================ */
function showChat() {
  $("chatView").classList.add("active");
  $("settingsView").classList.remove("active");
  $("openSettings").classList.remove("active");
  // Restore the breadcrumb title for the current chat context.
  const active = state.conversations.find((c) => c.id === state.activeConversationId);
  $("sectionTitle").textContent = active ? active.title : "New prompt";
}

function showSettings() {
  $("settingsView").classList.add("active");
  $("chatView").classList.remove("active");
  $("openSettings").classList.add("active");
  $("sectionTitle").textContent = "Settings";
}

/* ======================= Health / status ======================= */
async function loadHealth() {
  try {
    const data = await fetchJson(`/api/health?ts=${Date.now()}`);
    state.health = data;
    $("healthBadge").textContent = data.openrouter_configured ? `Ready v${data.app_version}` : `No OpenRouter key v${data.app_version}`;
    $("healthBadge").classList.toggle("warn", !data.openrouter_configured);
    $("openrouterInfo").textContent = data.openrouter_configured
      ? `Configured. Default: ${data.default_model || "auto"}. Selected: ${data.selected_model || "auto"}.`
      : "Not configured. Add OPENROUTER_API_KEY to .env.";
  } catch (error) {
    $("healthBadge").textContent = "Offline";
    $("healthBadge").classList.add("warn");
    $("openrouterInfo").textContent = error.message;
  }
}

async function loadModels() {
  try {
    const data = await fetchJson("/api/models");
    state.models = data.models || [];
    const current = $("modelSelect").value || "auto";
    $("modelSelect").innerHTML = `<option value="auto">Auto</option>`;
    state.models.forEach((model) => {
      if (!model.id) return;
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = model.name ? `${model.name} (${model.id})` : model.id;
      $("modelSelect").appendChild(option);
    });
    $("modelSelect").value = [...$("modelSelect").options].some((option) => option.value === current) ? current : "auto";
    $("modelStatus").textContent = data.configured
      ? `${state.models.length} OpenRouter models available`
      : "OpenRouter API key not configured";
    updateComposerSummary();
  } catch (error) {
    $("modelStatus").textContent = `Model load failed: ${error.message}`;
  }
}

async function loadHermesStatus() {
  try {
    const data = await fetchJson("/api/hermes/status");
    $("hermesInfo").textContent = data.installed
      ? `Installed. ${data.message || "Ready for prompt orchestration."}`
      : `Not installed. ${data.message || "Run scripts/install_hermes.ps1."}`;
  } catch (error) {
    $("hermesInfo").textContent = error.message;
  }
}

async function loadMemoryInsights() {
  try {
    const data = await fetchJson(`/api/memory/insights?user_id=${USER_ID}`);
    const runs = (data.task_types || []).reduce((sum, item) => sum + Number(item.runs || 0), 0);
    $("memoryInfo").textContent = runs ? `${runs} prior runs available for retrieval.` : "No prior optimization memory yet.";
  } catch (error) {
    $("memoryInfo").textContent = error.message;
  }
}

async function loadFeedbackSummary() {
  try {
    const data = await fetchJson(`/api/feedback/summary?user_id=${USER_ID}`);
    $("feedbackInfo").textContent = data.total_feedback
      ? `${data.total_feedback} ratings, average ${data.average_rating || "--"}/5.`
      : "No feedback saved yet.";
  } catch (error) {
    $("feedbackInfo").textContent = error.message;
  }
}

/* ======================= Conversations ======================= */
async function loadConversations() {
  try {
    const rows = await fetchJson(`/api/conversations?user_id=${USER_ID}&limit=80`);
    state.conversations = rows;
    renderConversationList(rows);
  } catch (error) {
    $("conversationList").className = "conv-list empty";
    $("conversationList").textContent = `Could not load chats: ${error.message}`;
  }
}

function renderConversationList(rows) {
  const container = $("conversationList");
  const run = state.activeRun;
  // While a brand-new chat is optimizing it has no DB row yet, so show a
  // client-side pending entry at the top (ChatGPT-style) until it's saved.
  const pendingRows =
    run && !run.conversationId
      ? [{ id: run.viewToken, title: run.title || "New prompt", turn_count: 0, __pending: true }]
      : [];
  const all = [...pendingRows, ...rows];
  if (!all.length) {
    container.className = "conv-list empty";
    container.textContent = "No chats yet. Start one below.";
    return;
  }
  container.className = "conv-list";
  container.innerHTML = all
    .map((row) => {
      const id = escapeHtml(row.id);
      const title = escapeHtml(row.title || "Untitled");
      const isActive = row.id === state.activeConversationId || row.id === state.activeViewToken;
      const isLoading = Boolean(row.__pending) || Boolean(run && run.conversationId && row.id === run.conversationId);
      const leftIcon = isLoading
        ? `<span class="conv-spinner" aria-hidden="true"></span>`
        : `<svg class="icon"><use href="#i-message" /></svg>`;
      const right = isLoading
        ? `<span class="conv-item-loading">…</span>`
        : `<span class="conv-item-count">${row.turn_count || 0}</span>`;
      const del = row.__pending
        ? ""
        : `<button class="conv-item-delete" type="button" data-del-id="${id}" data-del-title="${title}" title="Delete chat" aria-label="Delete chat">
            <svg class="icon"><use href="#i-trash" /></svg>
          </button>`;
      return `
        <div class="conv-item ${isActive ? "active" : ""} ${isLoading ? "loading" : ""}" data-conv-id="${id}">
          <button class="conv-item-open" type="button" data-open-id="${id}" title="${title}">
            ${leftIcon}
            <span class="conv-item-title">${title}</span>
            ${right}
          </button>
          ${del}
        </div>
      `;
    })
    .join("");
  container.querySelectorAll("[data-open-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.openId;
      if (state.activeRun && (id === state.activeRun.viewToken || id === state.activeRun.conversationId)) {
        openRunView();
      } else {
        openConversation(id);
      }
    });
  });
  container.querySelectorAll("[data-del-id]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      askDeleteConversation(btn.dataset.delId, btn.dataset.delTitle);
    });
  });
}

// Toggle the sidebar's active highlight to match the current view (a real
// conversation id or an in-flight run's view token).
function highlightSidebar() {
  document.querySelectorAll(".conv-item").forEach((item) => {
    const id = item.dataset.convId;
    item.classList.toggle("active", id === state.activeConversationId || id === state.activeViewToken);
  });
}

async function openConversation(conversationId) {
  showChat();
  state.activeConversationId = conversationId;
  state.activeViewToken = conversationId;
  highlightSidebar();
  // If this chat is the one currently optimizing, show its live agent view.
  if (state.activeRun && (state.activeRun.conversationId === conversationId || state.activeRun.viewToken === conversationId)) {
    openRunView();
    return;
  }
  setStatus("Loading chat...");
  try {
    const data = await fetchJson(`/api/conversations/${encodeURIComponent(conversationId)}?user_id=${USER_ID}`);
    $("sectionTitle").textContent = data.conversation?.title || "Chat";
    renderThread(data.turns || []);
    refreshRunStatus();
  } catch (error) {
    setStatus(`Could not load chat: ${error.message}`);
  }
}

// Render the live in-flight optimization (user prompt + agent stepper), keeping
// any earlier saved turns of the same chat above it.
async function openRunView() {
  const run = state.activeRun;
  if (!run) return;
  showChat();
  state.activeViewToken = run.viewToken;
  state.activeConversationId = run.conversationId || null;
  highlightSidebar();
  $("sectionTitle").textContent = run.title || (run.isFollowUp ? "Chat" : "New prompt");
  const thread = $("chatThread");
  thread.innerHTML = "";
  $("chatEmpty").classList.add("is-hidden");
  if (run.conversationId) {
    try {
      const data = await fetchJson(`/api/conversations/${encodeURIComponent(run.conversationId)}?user_id=${USER_ID}`);
      appendTurns(thread, data.turns || []);
    } catch {
      /* a brand-new chat has no saved turns yet; that's fine */
    }
  }
  thread.appendChild(buildUserMessage(run.rawPrompt));
  thread.appendChild(buildAgentStepper(run));
  scrollChatToBottom();
  refreshRunStatus();
}

function newConversation() {
  showChat();
  state.activeConversationId = null;
  state.activeViewToken = freshViewToken();
  highlightSidebar();
  $("sectionTitle").textContent = "New prompt";
  $("chatThread").innerHTML = "";
  $("chatEmpty").classList.remove("is-hidden");
  // Any run in another chat keeps going and stays visible in the sidebar — tell
  // the user instead of pretending it's gone.
  refreshRunStatus();
  focusComposer();
}

// Reflect the in-flight run in the status line for whatever the user is viewing.
function refreshRunStatus() {
  const run = state.activeRun;
  if (run && run.viewToken === state.activeViewToken) {
    setStatus(run.isFollowUp ? "Hermes is refining your prompt…" : "Hermes agents are optimizing your prompt…");
  } else if (state.busy) {
    setStatus("Still optimizing another chat — it stays in the sidebar until it's done.");
  } else {
    setStatus("Ready.");
  }
}

/* ======================= Chat thread render ======================= */
function appendTurns(thread, turns) {
  turns.forEach((turn) => {
    thread.appendChild(buildUserMessage(turn.raw_prompt));
    thread.appendChild(
      buildAssistantMessage({
        historyId: turn.history_id,
        prompt: turn.winner_prompt || "(no prompt stored)",
        score: turn.winner_score,
        label: turn.winner_label,
        model: turn.target_model,
      }),
    );
  });
}

function renderThread(turns) {
  const thread = $("chatThread");
  thread.innerHTML = "";
  if (!turns.length) {
    $("chatEmpty").classList.remove("is-hidden");
    return;
  }
  $("chatEmpty").classList.add("is-hidden");
  appendTurns(thread, turns);
  scrollChatToBottom();
}

function buildUserMessage(text) {
  const wrap = document.createElement("article");
  wrap.className = "msg msg-user";
  const body = document.createElement("div");
  body.className = "msg-body";
  body.textContent = text || "";
  wrap.appendChild(body);
  return wrap;
}

function buildAssistantMessage({ historyId, prompt, score, label, model, pending = false }) {
  const wrap = document.createElement("article");
  wrap.className = "msg msg-assistant";
  if (historyId) wrap.dataset.historyId = historyId;

  const meta = [label, model].filter(Boolean).map(escapeHtml).join(" · ");
  const scoreText = score === null || score === undefined ? "--" : escapeHtml(String(score));
  const actions = pending
    ? ""
    : `
      <div class="msg-actions">
        <button class="btn btn-ghost copy-btn" type="button">
          <svg class="icon"><use href="#i-copy" /></svg>
          Copy
        </button>
        ${historyId ? `<button class="btn btn-ghost details-btn" type="button">
          <svg class="icon"><use href="#i-layers" /></svg>
          View details
        </button>` : ""}
      </div>`;

  wrap.innerHTML = `
    <div class="msg-card ${pending ? "msg-pending" : ""}">
      <div class="msg-head">
        <span class="agent-badge"><svg class="icon"><use href="#i-sparkles" /></svg></span>
        <span class="msg-title">Hermes${meta ? ` <small>${meta}</small>` : ""}</span>
        <span class="msg-score">${scoreText}</span>
      </div>
      <pre class="msg-body-prompt">${escapeHtml(prompt)}</pre>
      ${actions}
    </div>`;

  if (!pending) {
    const copyBtn = wrap.querySelector(".copy-btn");
    if (copyBtn) copyBtn.addEventListener("click", () => copyText(prompt));
    const detailsBtn = wrap.querySelector(".details-btn");
    if (detailsBtn) detailsBtn.addEventListener("click", () => inspectRun(historyId));
  }
  return wrap;
}

function scrollChatToBottom() {
  const scroller = $("chatScroll");
  scroller.scrollTop = scroller.scrollHeight;
}

/* ======================= Live agent stepper ======================= */
function deriveTitle(text) {
  const t = (text || "").trim().replace(/\s+/g, " ");
  if (!t) return "New prompt";
  return t.length > 60 ? `${t.slice(0, 60)}...` : t;
}

function stepIndicator(status) {
  if (status === "done") return `<svg class="icon"><use href="#i-check" /></svg>`;
  if (status === "failed") return `<svg class="icon"><use href="#i-x" /></svg>`;
  if (status === "skipped") return `<svg class="icon"><use href="#i-minus" /></svg>`;
  return `<span class="step-spinner" aria-hidden="true"></span>`;
}

// Build the live agent progress card: a vertical stepper of the pipeline agents,
// the running one highlighted, each marked done/skipped/failed as events arrive.
function buildAgentStepper(run) {
  const wrap = document.createElement("article");
  wrap.className = "msg msg-assistant";
  wrap.id = "agentStepper";
  const steps = run.steps || [];
  const done = steps.filter((s) => s.status !== "running").length;
  const running = run.status === "running";
  const title =
    run.status === "failed"
      ? "Optimization failed"
      : run.status === "done"
        ? "Optimization complete"
        : run.isFollowUp
          ? "Hermes is refining your prompt"
          : "Hermes agents are optimizing your prompt";
  const count = steps.length ? `${done}/${steps.length}` : "…";
  const stepsHtml = steps
    .map((s) => {
      const status = s.status || "running";
      const dur = s.duration_ms != null && status !== "running" ? `${s.duration_ms} ms` : "";
      return `
        <li class="agent-step ${status}">
          <span class="agent-step-ind">${stepIndicator(status)}</span>
          <span class="agent-step-body">
            <strong>${escapeHtml(s.agent || "Agent")}</strong>
            <small>${escapeHtml(s.description || "")}</small>
          </span>
          <span class="agent-step-time">${dur}</span>
        </li>`;
    })
    .join("");
  const placeholder = `
    <li class="agent-step pending">
      <span class="agent-step-ind"><span class="step-spinner" aria-hidden="true"></span></span>
      <span class="agent-step-body"><strong>Starting…</strong><small>Spinning up the agent pipeline.</small></span>
      <span class="agent-step-time"></span>
    </li>`;
  wrap.innerHTML = `
    <div class="msg-card agent-run">
      <div class="agent-run-head">
        <span class="agent-badge ${running ? "spinning" : ""}"><svg class="icon"><use href="#i-sparkles" /></svg></span>
        <span class="agent-run-title">${escapeHtml(title)}</span>
        <span class="agent-run-count">${count}</span>
      </div>
      <ol class="agent-steps">${stepsHtml || placeholder}</ol>
      ${run.status === "failed" && run.error ? `<div class="agent-run-error">${escapeHtml(run.error)}</div>` : ""}
    </div>`;
  return wrap;
}

// Refresh the stepper in place, but only when the user is actually viewing the
// chat the run belongs to (otherwise it keeps progressing silently).
function updateRunDom() {
  const run = state.activeRun;
  if (!run || state.activeViewToken !== run.viewToken) return;
  const existing = document.getElementById("agentStepper");
  const fresh = buildAgentStepper(run);
  if (existing) {
    existing.replaceWith(fresh);
  } else {
    $("chatThread").appendChild(fresh);
  }
  scrollChatToBottom();
}

/* ======================= Optimize (send) ======================= */
async function optimizePrompt() {
  if (state.busy) return;
  const rawPrompt = $("rawPrompt").value.trim();
  if (!rawPrompt) {
    setStatus("Paste a prompt first.");
    $("rawPrompt").focus();
    return;
  }

  const isFollowUp = Boolean(state.activeConversationId);
  // The run is anchored to the view it started in. For a brand-new chat the view
  // token is "new:N" until the server returns a real conversation id.
  state.activeRun = {
    runId: `run-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    viewToken: state.activeViewToken,
    conversationId: state.activeConversationId,
    rawPrompt,
    isFollowUp,
    title: isFollowUp ? $("sectionTitle").textContent || "Chat" : deriveTitle(rawPrompt),
    steps: [],
    status: "running",
    result: null,
    error: null,
  };

  $("rawPrompt").value = "";
  autoGrow();
  setBusy(true);

  // Show the live agent view here, and surface the chat in the sidebar at once
  // (so it's visible "on the side" even if the user opens another chat).
  openRunView();
  renderConversationList(state.conversations);

  const payload = {
    raw_prompt: rawPrompt,
    user_id: USER_ID,
    target_model: $("modelSelect").value || "auto",
    versions: Number($("versionCount").value || 3),
    force_clarification: $("forceClarification").checked,
    use_hermes: $("useHermes").checked,
    conversation_id: state.activeRun.conversationId,
  };

  try {
    await streamOptimize(payload, handleRunEvent);
  } catch (error) {
    if (state.activeRun) {
      state.activeRun.status = "failed";
      state.activeRun.error = error.message;
      updateRunDom();
    }
  }
  await finalizeRun();
}

// POST to the SSE endpoint and dispatch each `data:` frame to `onEvent`.
async function streamOptimize(payload, onEvent) {
  const response = await fetch("/api/optimize/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) {
    let message = `${response.status} ${response.statusText}`;
    try {
      message = JSON.parse(await response.text()).detail || message;
    } catch {
      /* keep status text */
    }
    throw new Error(message);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const json = line.slice(5).trim();
      if (!json) continue;
      try {
        onEvent(JSON.parse(json));
      } catch {
        /* ignore a malformed frame */
      }
    }
  }
}

function handleRunEvent(event) {
  const run = state.activeRun;
  if (!run) return;
  if (event.type === "conversation") {
    run.conversationId = event.conversation_id;
    // Promote a brand-new chat to its real id so the client "pending" row turns
    // into a normal (still-loading) conversation backed by the DB.
    if (!run.isFollowUp) {
      if (state.activeViewToken === run.viewToken) {
        state.activeViewToken = event.conversation_id;
        state.activeConversationId = event.conversation_id;
      }
      run.viewToken = event.conversation_id;
    }
    loadConversations();
  } else if (event.type === "agent_start") {
    run.steps.push({ agent: event.agent, description: event.description, status: "running" });
    updateRunDom();
  } else if (event.type === "agent_done") {
    // The backend reports "completed"; the stepper UI/CSS use "done".
    const status = event.status === "completed" ? "done" : event.status || "done";
    for (let i = run.steps.length - 1; i >= 0; i--) {
      if (run.steps[i].agent === event.agent && run.steps[i].status === "running") {
        run.steps[i].status = status;
        run.steps[i].duration_ms = event.duration_ms;
        break;
      }
    }
    updateRunDom();
  } else if (event.type === "result") {
    run.status = "done";
    run.result = event.data;
  } else if (event.type === "error") {
    run.status = "failed";
    run.error = event.detail || "Optimization failed.";
    updateRunDom();
  }
}

// Tidy up once the stream ends: refresh the sidebar/history, and — only if the
// user is still on this chat — show the saved result (or leave the error up).
async function finalizeRun() {
  const run = state.activeRun;
  if (!run) return;
  const wasViewing = state.activeViewToken === run.viewToken;
  const conversationId = run.conversationId;
  const status = run.status;
  const error = run.error;
  state.activeRun = null;
  setBusy(false);

  await Promise.all([loadConversations(), loadHistory(), loadMemoryInsights()]);

  if (status === "done" && conversationId) {
    if (wasViewing) {
      // Reload the chat from the DB so the saved winner (and earlier turns)
      // replace the live stepper cleanly.
      state.activeConversationId = conversationId;
      await openConversation(conversationId);
      setStatus("Done.");
    } else {
      setStatus("A chat finished optimizing — find it in the sidebar.");
    }
  } else {
    // Failed: the stepper already shows the error inline for the active view.
    setStatus(`Optimization failed: ${error || "unknown error"}`);
  }
}

/* ======================= Settings: run details ======================= */
function activateDetailTab(name) {
  document.querySelectorAll(".detail-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.detail === name);
  });
  document.querySelectorAll(".detail-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `detail-${name}`);
  });
}

async function inspectRun(historyId) {
  if (!historyId) return;
  showSettings();
  activateDetailTab("versions");
  $("inspectLabel").textContent = "Loading run...";
  try {
    const run = await fetchJson(`/api/runs/${encodeURIComponent(historyId)}?user_id=${USER_ID}`);
    const winner = run.winner || {};
    const promptLabel = run.history?.raw_prompt ? truncate(run.history.raw_prompt, 60) : winner.label || "Run";
    $("inspectLabel").textContent = promptLabel;
    $("inspectScore").textContent = winner.score_total ?? winner.score?.total ?? "--";
    renderVersions(run.versions || [], winner.label);
    renderTrace(extractTrace(run));
  } catch (error) {
    $("inspectLabel").textContent = `Could not load run: ${error.message}`;
  }
}

function extractTrace(run) {
  const traceOutput = (run.agent_outputs || []).find((item) => item.agent_name === "run_trace");
  return traceOutput?.output?.events || [];
}

function renderVersions(versions, winnerLabel) {
  const container = $("versionsList");
  if (!versions.length) {
    container.className = "stack-list empty";
    container.textContent = "No versions for this run.";
    return;
  }
  container.className = "stack-list";
  container.innerHTML = versions
    .map((version) => {
      const total = version.score_total ?? version.score?.total ?? "--";
      const isWinner = version.is_winner || version.label === winnerLabel;
      return `
        <article class="list-card version-card ${isWinner ? "winner-card" : ""}">
          <div class="card-head">
            <div>
              <strong>${escapeHtml(version.label || "version")}</strong>
              <small>${escapeHtml(version.strategy || "strategy")}</small>
            </div>
            <span>${escapeHtml(String(total))}</span>
          </div>
          <pre>${escapeHtml(version.prompt_text || version.version_text || "")}</pre>
        </article>`;
    })
    .join("");
}

function renderTrace(trace) {
  const container = $("traceList");
  if (!trace.length) {
    container.className = "stack-list empty";
    container.textContent = "No agent trace for this run.";
    return;
  }
  container.className = "stack-list";
  container.innerHTML = trace
    .map(
      (event) => `
        <article class="list-card trace-card ${escapeHtml(String(event.status || "completed").toLowerCase())}">
          <div class="card-head">
            <div>
              <strong>${escapeHtml(event.agent || "Agent")}</strong>
              <small>${escapeHtml(event.description || "")}</small>
            </div>
            <span>${escapeHtml(event.status || "done")} · ${Number(event.duration_ms || 0)} ms</span>
          </div>
          <p>${escapeHtml(event.summary || "")}</p>
          ${event.preview ? `<pre>${escapeHtml(event.preview)}</pre>` : ""}
        </article>`,
    )
    .join("");
}

async function loadHistory() {
  try {
    const rows = await fetchJson(`/api/history?user_id=${USER_ID}&limit=40`);
    const container = $("historyList");
    if (!rows.length) {
      container.className = "stack-list empty";
      container.textContent = "No prompt history yet.";
      return;
    }
    container.className = "stack-list";
    container.innerHTML = rows
      .map(
        (row) => `
          <article class="list-card history-card" data-history-id="${escapeHtml(row.id)}">
            <div>
              <strong>${escapeHtml(row.task_type || "prompt")}</strong>
              <p>${escapeHtml(truncate(row.raw_prompt, 150))}</p>
            </div>
            <span>${row.winner_score ?? "--"}</span>
          </article>`,
      )
      .join("");
    container.querySelectorAll("[data-history-id]").forEach((card) => {
      card.addEventListener("click", () => inspectRun(card.dataset.historyId));
    });
  } catch (error) {
    $("historyList").className = "stack-list empty";
    $("historyList").textContent = `History failed: ${error.message}`;
  }
}

/* ======================= Composer helpers ======================= */
function updateComposerSummary() {
  const model = $("modelSelect").value || "auto";
  const modelLabel = model === "auto" ? "Auto model" : model;
  const versions = $("versionCount").value || 3;
  const hermes = $("useHermes").checked ? "Hermes on" : "Hermes off";
  $("composerSummary").textContent = `${modelLabel} · ${versions} versions · ${hermes}`;
}

function autoGrow() {
  const textarea = $("rawPrompt");
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 220)}px`;
}

function focusComposer() {
  showChat();
  $("rawPrompt").focus();
}

function isTypingTarget(element) {
  if (!element) return false;
  const tag = element.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || element.isContentEditable;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text || "");
    setStatus("Copied to clipboard.");
  } catch {
    setStatus("Copy failed. Select the text and copy it manually.");
  }
}

async function restartApp() {
  try {
    setStatus("Restart requested...");
    await fetchJson("/api/restart", { method: "POST" });
    setTimeout(loadHealth, 2500);
    setStatus("Restart requested. Refresh after a moment.");
  } catch (error) {
    setStatus(`Restart failed: ${error.message}`);
  }
}

/* ======================= Delete chat ======================= */
let pendingDeleteId = null;

function askDeleteConversation(conversationId, title) {
  if (!conversationId) return;
  pendingDeleteId = conversationId;
  const name = (title || "").trim();
  $("confirmText").textContent = name
    ? `"${name}" and its optimized prompts will be permanently deleted. This can't be undone.`
    : "This chat and its optimized prompts will be permanently deleted. This can't be undone.";
  $("confirmOverlay").classList.remove("is-hidden");
  $("confirmDelete").focus();
}

function hideConfirm() {
  pendingDeleteId = null;
  $("confirmOverlay").classList.add("is-hidden");
}

async function confirmDeleteNow() {
  const conversationId = pendingDeleteId;
  hideConfirm();
  if (!conversationId) return;
  try {
    await fetchJson(`/api/conversations/${encodeURIComponent(conversationId)}?user_id=${USER_ID}`, {
      method: "DELETE",
    });
    // If the chat we just deleted is the one on screen, drop back to a fresh
    // composer so we're not showing a thread that no longer exists.
    if (state.activeConversationId === conversationId || state.activeViewToken === conversationId) {
      newConversation();
    }
    await Promise.all([loadConversations(), loadHistory(), loadMemoryInsights()]);
    setStatus("Chat deleted.");
  } catch (error) {
    setStatus(`Could not delete chat: ${error.message}`);
  }
}

/* ======================= First-run OpenRouter key setup ======================= */
function showSetup() {
  $("setupOverlay").classList.remove("is-hidden");
  $("setupError").textContent = "";
  $("setupKeyInput").focus();
}

function hideSetup() {
  $("setupOverlay").classList.add("is-hidden");
}

async function saveOpenRouterKey() {
  const key = $("setupKeyInput").value.trim();
  if (key.length < 8) {
    $("setupError").textContent = "Please paste a valid OpenRouter API key.";
    return;
  }
  const btn = $("setupSaveBtn");
  const label = btn.querySelector("span");
  const original = label.textContent;
  btn.disabled = true;
  label.textContent = "Checking...";
  $("setupError").textContent = "";
  try {
    await fetchJson("/api/settings/openrouter-key", {
      method: "POST",
      body: JSON.stringify({ api_key: key }),
    });
    $("setupKeyInput").value = "";
    hideSetup();
    await Promise.all([loadHealth(), loadModels()]);
    setStatus("OpenRouter key saved. Ready.");
  } catch (error) {
    $("setupError").textContent = error.message;
  } finally {
    btn.disabled = false;
    label.textContent = original;
  }
}

/* ============================ Events ============================ */
function bindEvents() {
  $("optimizeButton").addEventListener("click", optimizePrompt);
  $("clearButton").addEventListener("click", () => {
    $("rawPrompt").value = "";
    autoGrow();
    setStatus("Ready.");
    $("rawPrompt").focus();
  });
  $("newPromptNav").addEventListener("click", newConversation);
  $("openSettings").addEventListener("click", showSettings);
  $("backToChat").addEventListener("click", showChat);
  $("restartApp").addEventListener("click", restartApp);
  $("refreshHistory").addEventListener("click", loadHistory);
  $("setupSaveBtn").addEventListener("click", saveOpenRouterKey);
  $("setupKeyInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      saveOpenRouterKey();
    }
  });

  $("confirmCancel").addEventListener("click", hideConfirm);
  $("confirmDelete").addEventListener("click", confirmDeleteNow);
  $("confirmOverlay").addEventListener("click", (event) => {
    if (event.target === $("confirmOverlay")) hideConfirm();
  });

  $("rawPrompt").addEventListener("input", autoGrow);
  $("rawPrompt").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      optimizePrompt();
    }
  });

  ["modelSelect", "versionCount", "useHermes"].forEach((id) => {
    $(id).addEventListener("change", updateComposerSummary);
  });

  document.querySelectorAll(".detail-tab").forEach((tab) => {
    tab.addEventListener("click", () => activateDetailTab(tab.dataset.detail));
  });

  document.addEventListener("keydown", (event) => {
    const confirmOpen = !$("confirmOverlay").classList.contains("is-hidden");
    if (event.key === "Escape" && confirmOpen) {
      event.preventDefault();
      hideConfirm();
      return;
    }
    if (event.key === "/" && !confirmOpen && !isTypingTarget(event.target)) {
      event.preventDefault();
      focusComposer();
    }
  });
}

async function init() {
  bindEvents();
  state.activeViewToken = freshViewToken();
  updateComposerSummary();
  autoGrow();
  showChat();
  await Promise.all([
    loadHealth(),
    loadModels(),
    loadHermesStatus(),
    loadConversations(),
    loadHistory(),
    loadMemoryInsights(),
    loadFeedbackSummary(),
  ]);
  // First run: no OpenRouter key configured yet -> ask for it before anything else.
  if (state.health && !state.health.openrouter_configured) {
    showSetup();
  }
  setStatus("Ready.");
}

init();
