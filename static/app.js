const $ = (id) => document.getElementById(id);
const USER_ID = "local-user";
const LOCKED_MODEL_ID = "deepseek/deepseek-v4-pro";
const LOCKED_MODEL_LABEL = "DeepSeek V4 Pro";

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
  // Multi-select for bulk chat deletion: when on, sidebar rows show a checkbox
  // and clicking a row toggles its selection instead of opening it.
  selectMode: false,
  selectedIds: new Set(),
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

function ensureAgentLoadingOverlay() {
  let overlay = $("agentLoadingOverlay");
  if (overlay) return overlay;

  // Safety net for already-open desktop windows whose HTML was loaded before
  // the overlay markup existed. On the next JS reload this creates the missing
  // DOM instead of silently falling back to only the small status text.
  overlay = document.createElement("div");
  overlay.id = "agentLoadingOverlay";
  overlay.className = "agent-loading-overlay is-hidden";
  overlay.setAttribute("role", "status");
  overlay.setAttribute("aria-live", "polite");
  overlay.setAttribute("aria-atomic", "true");
  overlay.innerHTML = `
    <div class="agent-loading-card">
      <div class="agent-loading-orb" aria-hidden="true">
        <span></span>
        <span></span>
        <span></span>
      </div>
      <p class="eyebrow">Agent running</p>
      <h1 id="agentLoadingText" class="agent-loading-title">Agent optimizing this prompt</h1>
      <p id="agentLoadingSubtext" class="agent-loading-sub">Hermes and the prompt agents are working. Results will appear here automatically.</p>
    </div>`;
  document.body.appendChild(overlay);
  return overlay;
}

function updateAgentWorkIndicator() {
  const indicator = $("agentWorkIndicator");
  const text = $("agentWorkText");
  const overlay = ensureAgentLoadingOverlay();
  const overlayText = $("agentLoadingText");
  const overlaySubtext = $("agentLoadingSubtext");
  const run = state.activeRun;
  const isWorking = Boolean(state.busy && run);

  if (indicator) indicator.classList.toggle("is-hidden", !isWorking);
  // Never show the full-screen loading overlay. It used to cover the entire
  // window (sidebar included), so the user could not open another chat while a
  // prompt optimized, and it hid the live in-chat agent checklist drawn beneath
  // it. The small top-right badge + the sidebar spinner + the in-chat stepper
  // already signal "an agent is running" without trapping the user on one screen.
  if (overlay) overlay.classList.add("is-hidden");

  if (!isWorking) {
    if (indicator) indicator.setAttribute("aria-label", "No background agent is running");
    if (overlay) overlay.setAttribute("aria-label", "No background agent is running");
    return;
  }

  const currentChatVisible = $("chatView").classList.contains("active") && run.viewToken === state.activeViewToken;
  const message = currentChatVisible
    ? run.isFollowUp
      ? "Agent refining this prompt"
      : "Agent optimizing this prompt"
    : "Agent working in background";
  const details = run.isFollowUp
    ? "Hermes is refining your existing prompt. Results will appear here automatically."
    : "Hermes and the prompt agents are optimizing your prompt. Results will appear here automatically.";

  if (text) text.textContent = message;
  if (overlayText) overlayText.textContent = message;
  if (overlaySubtext) overlaySubtext.textContent = details;
  if (indicator) indicator.setAttribute("aria-label", message);
  if (overlay) overlay.setAttribute("aria-label", `${message}. ${details}`);
}

// Busy reflects whether an optimization is running. It is decoupled from the
// status text so that navigating between chats (which changes the status line)
// never re-enables the send button while a run is still in flight.
function setBusy(busy) {
  state.busy = busy;
  $("runStatus").classList.toggle("busy", busy);
  $("optimizeButton").disabled = busy;
  updateAgentWorkIndicator();
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
  updateAgentWorkIndicator();
}

function showSettings() {
  $("settingsView").classList.add("active");
  $("chatView").classList.remove("active");
  $("openSettings").classList.add("active");
  $("sectionTitle").textContent = "Settings";
  updateAgentWorkIndicator();
}

/* ======================= Health / status ======================= */
async function loadHealth() {
  try {
    const data = await fetchJson(`/api/health?ts=${Date.now()}`);
    state.health = data;
    $("healthBadge").textContent = data.openrouter_configured ? `Ready v${data.app_version}` : `No OpenRouter key v${data.app_version}`;
    $("healthBadge").classList.toggle("warn", !data.openrouter_configured);
    $("openrouterInfo").textContent = data.openrouter_configured
      ? `Configured. Model locked to ${data.selected_model || LOCKED_MODEL_ID}.`
      : "Not configured. Add OPENROUTER_API_KEY to .env.";
  } catch (error) {
    $("healthBadge").textContent = "Offline";
    $("healthBadge").classList.add("warn");
    $("openrouterInfo").textContent = error.message;
  }
}

/* ======================= App auto-update ======================= */
async function checkForUpdate() {
  try {
    const data = await fetchJson("/api/update/check");
    if (data && data.update_available && data.latest_version) {
      const text = $("updateBannerText");
      if (text) text.textContent = `New version v${data.latest_version} available (you have v${data.current_version}).`;
      const banner = $("updateBanner");
      if (banner) banner.classList.remove("is-hidden");
    }
  } catch {
    /* Update check is best-effort: ignore failures (offline, no releases yet, etc.). */
  }
}

async function applyUpdate() {
  const btn = $("updateNowBtn");
  const text = $("updateBannerText");
  if (btn) btn.disabled = true;
  if (text) text.textContent = "Downloading and installing the update… the app will close and reopen by itself. Please wait.";
  try {
    await fetchJson("/api/update/apply", { method: "POST" });
  } catch {
    // The installer can close this app before the request returns — that's expected.
    if (text) text.textContent = "Update started. If the app doesn't reopen on its own in a minute, open it again manually.";
  }
}

async function loadModels() {
  try {
    const data = await fetchJson("/api/models");
    state.models = data.models || [];
    const model = state.models.find((item) => item.id === LOCKED_MODEL_ID);
    const label = model?.name ? `${model.name} (${LOCKED_MODEL_ID})` : `${LOCKED_MODEL_LABEL} (${LOCKED_MODEL_ID})`;
    $("modelSelect").innerHTML = "";
    const option = document.createElement("option");
    option.value = LOCKED_MODEL_ID;
    option.textContent = label;
    $("modelSelect").appendChild(option);
    $("modelSelect").value = LOCKED_MODEL_ID;
    $("modelSelect").disabled = true;
    $("modelStatus").textContent = data.configured
      ? `Model locked: ${LOCKED_MODEL_LABEL}`
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
    // Drop selections for chats that no longer exist (deleted elsewhere/refresh).
    if (state.selectedIds.size) {
      const live = new Set(rows.map((r) => r.id));
      state.selectedIds.forEach((id) => {
        if (!live.has(id)) state.selectedIds.delete(id);
      });
    }
    renderConversationList(rows);
    updateBulkBar();
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
  container.className = state.selectMode ? "conv-list select-mode" : "conv-list";
  container.innerHTML = all
    .map((row) => {
      const id = escapeHtml(row.id);
      const title = escapeHtml(row.title || "Untitled");
      const isActive = row.id === state.activeConversationId || row.id === state.activeViewToken;
      const isLoading = Boolean(row.__pending) || Boolean(run && run.conversationId && row.id === run.conversationId);
      // In select mode, saved (non-pending, non-loading) rows become checkbox
      // rows. Loading/pending rows stay as normal rows — you can't delete a chat
      // that's still optimizing.
      const selectable = !row.__pending && !isLoading;
      if (state.selectMode && selectable) {
        const checked = state.selectedIds.has(row.id);
        return `
          <div class="conv-item ${checked ? "selected" : ""}" data-conv-id="${id}">
            <label class="conv-item-select" title="${title}">
              <input type="checkbox" class="conv-check" data-check-id="${id}" ${checked ? "checked" : ""} />
              <span class="conv-item-title">${title}</span>
              <span class="conv-item-count">${row.turn_count || 0}</span>
            </label>
          </div>
        `;
      }
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
  container.querySelectorAll(".conv-check").forEach((cb) => {
    cb.addEventListener("change", () => {
      const id = cb.dataset.checkId;
      if (cb.checked) state.selectedIds.add(id);
      else state.selectedIds.delete(id);
      cb.closest(".conv-item")?.classList.toggle("selected", cb.checked);
      updateBulkBar();
    });
  });
}

// Enter/leave multi-select mode. Leaving clears the current selection.
function toggleSelectMode(force) {
  state.selectMode = typeof force === "boolean" ? force : !state.selectMode;
  if (!state.selectMode) state.selectedIds.clear();
  $("convBulkBar").classList.toggle("is-hidden", !state.selectMode);
  const toggle = $("convSelectToggle");
  toggle.textContent = state.selectMode ? "Done" : "Select";
  toggle.classList.toggle("active", state.selectMode);
  renderConversationList(state.conversations);
  updateBulkBar();
}

// Select or clear every saved chat at once.
function selectAllConversations(checked) {
  state.selectedIds.clear();
  if (checked) state.conversations.forEach((c) => state.selectedIds.add(c.id));
  renderConversationList(state.conversations);
  updateBulkBar();
}

// Keep the bulk bar (count, delete button, select-all tri-state) in sync.
function updateBulkBar() {
  const count = state.selectedIds.size;
  const countEl = $("convSelectedCount");
  if (countEl) countEl.textContent = `${count} selected`;
  const delBtn = $("convDeleteSelected");
  if (delBtn) delBtn.disabled = count === 0;
  const selectAll = $("convSelectAll");
  if (selectAll) {
    const total = state.conversations.length;
    selectAll.checked = total > 0 && count >= total;
    selectAll.indeterminate = count > 0 && count < total;
  }
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
  updateAgentWorkIndicator();
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
    target_model: LOCKED_MODEL_ID,
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
  const versions = $("versionCount").value || 3;
  const hermes = $("useHermes").checked ? "Hermes on" : "Hermes off";
  $("composerSummary").textContent = `${LOCKED_MODEL_LABEL} - ${versions} versions - ${hermes}`;
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
let pendingDeleteIds = [];

function askDeleteConversation(conversationId, title) {
  if (!conversationId) return;
  pendingDeleteIds = [conversationId];
  const name = (title || "").trim();
  $("confirmTitle").textContent = "Delete this chat?";
  $("confirmText").textContent = name
    ? `"${name}" and its optimized prompts will be permanently deleted. This can't be undone.`
    : "This chat and its optimized prompts will be permanently deleted. This can't be undone.";
  $("confirmDeleteLabel").textContent = "Delete chat";
  $("confirmOverlay").classList.remove("is-hidden");
  $("confirmDelete").focus();
}

// Confirm deletion of every currently ticked chat.
function askDeleteSelected() {
  const ids = [...state.selectedIds];
  if (!ids.length) return;
  pendingDeleteIds = ids;
  const n = ids.length;
  $("confirmTitle").textContent = n === 1 ? "Delete this chat?" : `Delete ${n} chats?`;
  $("confirmText").textContent =
    `${n} chat${n === 1 ? "" : "s"} and all their optimized prompts will be permanently deleted. This can't be undone.`;
  $("confirmDeleteLabel").textContent = n === 1 ? "Delete chat" : `Delete ${n}`;
  $("confirmOverlay").classList.remove("is-hidden");
  $("confirmDelete").focus();
}

function hideConfirm() {
  pendingDeleteIds = [];
  $("confirmOverlay").classList.add("is-hidden");
}

async function confirmDeleteNow() {
  const ids = pendingDeleteIds.slice();
  hideConfirm();
  if (!ids.length) return;
  try {
    const results = await Promise.allSettled(
      ids.map((id) =>
        fetchJson(`/api/conversations/${encodeURIComponent(id)}?user_id=${USER_ID}`, { method: "DELETE" })
      )
    );
    const failed = results.filter((r) => r.status === "rejected").length;
    // If a chat we just deleted is the one on screen, drop back to a fresh
    // composer so we're not showing a thread that no longer exists.
    if (ids.includes(state.activeConversationId) || ids.includes(state.activeViewToken)) {
      newConversation();
    }
    // Leave select mode (also clears the selection) after a bulk delete.
    if (state.selectMode) toggleSelectMode(false);
    else state.selectedIds.clear();
    await Promise.all([loadConversations(), loadHistory(), loadMemoryInsights()]);
    const deleted = ids.length - failed;
    if (failed) {
      setStatus(`Deleted ${deleted} chat${deleted === 1 ? "" : "s"}; ${failed} could not be deleted.`);
    } else {
      setStatus(deleted === 1 ? "Chat deleted." : `${deleted} chats deleted.`);
    }
  } catch (error) {
    setStatus(`Could not delete: ${error.message}`);
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
  $("updateNowBtn").addEventListener("click", applyUpdate);
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
  $("convSelectToggle").addEventListener("click", () => toggleSelectMode());
  $("convDeleteSelected").addEventListener("click", askDeleteSelected);
  $("convSelectAll").addEventListener("change", (event) => selectAllConversations(event.target.checked));
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
    if (event.key === "Escape" && state.selectMode) {
      event.preventDefault();
      toggleSelectMode(false);
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
  checkForUpdate();
}

init();
