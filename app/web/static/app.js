const API = {
  me: "/api/v1/auth/me",
  login: "/api/v1/auth/login",
  register: "/api/v1/auth/register",
  verify: "/api/v1/auth/verify-email",
  resend: "/api/v1/auth/resend-code",
  chat: "/api/v1/chat",
  sessions: "/api/v1/chat/sessions",
  upload: "/api/v1/sources/upload",
  wikiPages: "/api/v1/wiki/pages",
  compact: "/api/v1/wiki/compact",
};

const AUTH_KEY = "knowforge.auth.v1";
const ACTIVE_SESSION_KEY = "knowforge.session.v1";
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const THINKING_STEPS = [
  "Understanding your question",
  "Rewriting vague references",
  "Checking your wiki memory",
  "Selecting the best document context",
  "Asking the answer agent",
  "Verifying support and citations",
];

const state = {
  token: null,
  user: null,
  currentSessionId: null,
  messages: [],
  sessions: [],
  openSessionMenuId: null,
  editingSessionId: null,
  editingSessionTitle: "",
  pendingReplyTo: null,
  pendingCommentFor: null,
  pendingMode: "message",
  sending: false,
  thinkingTimers: new Map(),
};

const els = {
  authScreen: document.querySelector("#authScreen"),
  authError: document.querySelector("#authError"),
  showLoginBtn: document.querySelector("#showLoginBtn"),
  showRegisterBtn: document.querySelector("#showRegisterBtn"),
  loginForm: document.querySelector("#loginForm"),
  registerForm: document.querySelector("#registerForm"),
  verifyForm: document.querySelector("#verifyForm"),
  loginEmail: document.querySelector("#loginEmail"),
  loginPassword: document.querySelector("#loginPassword"),
  registerName: document.querySelector("#registerName"),
  registerEmail: document.querySelector("#registerEmail"),
  registerPassword: document.querySelector("#registerPassword"),
  verifyEmail: document.querySelector("#verifyEmail"),
  verifyCode: document.querySelector("#verifyCode"),
  resendCodeBtn: document.querySelector("#resendCodeBtn"),
  chatBoard: document.querySelector("#chatBoard"),
  chatForm: document.querySelector("#chatForm"),
  messageInput: document.querySelector("#messageInput"),
  sendBtn: document.querySelector("#sendBtn"),
  template: document.querySelector("#messageTemplate"),
  replyBanner: document.querySelector("#replyBanner"),
  replyLabel: document.querySelector("#replyLabel"),
  cancelReplyBtn: document.querySelector("#cancelReplyBtn"),
  pdfInput: document.querySelector("#pdfInput"),
  dropZone: document.querySelector("#dropZone"),
  uploadState: document.querySelector("#uploadState"),
  uploadError: document.querySelector("#uploadError"),
  wikiList: document.querySelector("#wikiList"),
  emptyWiki: document.querySelector("#emptyWiki"),
  sessionList: document.querySelector("#sessionList"),
  emptySessions: document.querySelector("#emptySessions"),
  refreshWikiBtn: document.querySelector("#refreshWikiBtn"),
  refreshSessionsBtn: document.querySelector("#refreshSessionsBtn"),
  newChatBtn: document.querySelector("#newChatBtn"),
  compactWikiBtn: document.querySelector("#compactWikiBtn"),
  logoutBtn: document.querySelector("#logoutBtn"),
  networkState: document.querySelector("#networkState"),
};

function uid() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function getGreeting() {
  const hour = new Date().getHours();
  let greetings = [];

  if (hour >= 5 && hour < 12) {
    greetings = [
      "Good morning! Ready to explore your knowledge?",
      "Rise and shine! What can KnowForge answer for you today?",
      "Good morning! Let's build something great today."
    ];
  } else if (hour >= 12 && hour < 17) {
    greetings = [
      "Good afternoon! How can I help you today?",
      "Good afternoon! Ask me anything about your docs.",
      "Hello! Hope your afternoon is productive."
    ];
  } else if (hour >= 17 && hour < 22) {
    greetings = [
      "Good evening! Wrapping up the day? How can I help?",
      "Good evening! Need to find something in your wiki?",
      "Good evening! Let's do some research."
    ];
  } else {
    greetings = [
      "Burning the midnight oil? KnowForge is here to assist.",
      "Late night thoughts? What are we working on tonight?",
      "Hello night owl! Ready for some quiet research?"
    ];
  }

  const randomIndex = Math.floor(Math.random() * greetings.length);
  return greetings[randomIndex];
}

function loadAuth() {
  try {
    const saved = JSON.parse(localStorage.getItem(AUTH_KEY) || "{}");
    state.token = saved.token || null;
  } catch {
    state.token = null;
  }
}

function saveAuth(token) {
  state.token = token;
  if (token) localStorage.setItem(AUTH_KEY, JSON.stringify({ token }));
  else localStorage.removeItem(AUTH_KEY);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderMarkdown(markdown) {
  const codeBlocks = [];
  let html = escapeHtml(markdown || "");
  html = html.replace(/```([\s\S]*?)```/g, (_, code) => {
    const index = codeBlocks.push(`<pre><code>${code.trim()}</code></pre>`) - 1;
    return `@@CODE_BLOCK_${index}@@`;
  });
  html = html
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
    .replace(/\[(wiki|source):([^\]]+)\]/g, '<span class="message-chip">$1:$2</span>');

  const paragraphs = html
    .split(/\n{2,}/)
    .map((part) => {
      if (part.startsWith("@@CODE_BLOCK_")) return part;
      const withBreaks = part.replace(/\n/g, "<br />");
      if (/^#{1,3}\s/.test(withBreaks)) {
        return `<p><strong>${withBreaks.replace(/^#{1,3}\s/, "")}</strong></p>`;
      }
      if (/^[-*]\s/m.test(withBreaks)) {
        const items = withBreaks
          .split("<br />")
          .filter(Boolean)
          .map((line) => `<li>${line.replace(/^[-*]\s/, "")}</li>`)
          .join("");
        return `<ul>${items}</ul>`;
      }
      return `<p>${withBreaks}</p>`;
    })
    .join("");

  return codeBlocks.reduce(
    (result, block, index) => result.replace(`@@CODE_BLOCK_${index}@@`, block),
    paragraphs,
  );
}

function toast(message, type = "info") {
  let stack = document.querySelector(".toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.className = "toast-stack";
    document.body.appendChild(stack);
  }
  const item = document.createElement("div");
  item.className = `toast ${type}`;
  item.textContent = message;
  stack.appendChild(item);
  setTimeout(() => item.remove(), 4200);
}

async function apiFetch(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeout || 45000);
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  try {
    const response = await fetch(url, { ...options, headers, signal: controller.signal });
    const contentType = response.headers.get("content-type") || "";
    const body = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    if (!response.ok) {
      if (response.status === 401) logout(false);
      const message = body?.error?.message || body?.detail || body || `Request failed: ${response.status}`;
      throw new Error(Array.isArray(message) ? message.map((item) => item.msg).join(", ") : message);
    }
    els.networkState.textContent = "Connected to local API";
    return body;
  } catch (error) {
    els.networkState.textContent =
      error.name === "AbortError" ? "Request timed out" : "API connection issue";
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function showAuthError(message) {
  els.authError.textContent = message;
  els.authError.hidden = false;
}

function setButtonLoading(button, loading, label) {
  if (!button) return;
  if (loading) {
    button.dataset.originalText = button.textContent;
    button.textContent = label || "Working...";
    button.classList.add("loading");
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.classList.remove("loading");
    button.disabled = false;
  }
}

function setAuthMode(mode) {
  els.authError.hidden = true;
  els.loginForm.hidden = mode !== "login";
  els.registerForm.hidden = mode !== "register";
  els.verifyForm.hidden = mode !== "verify";
  els.showLoginBtn.classList.toggle("active", mode === "login");
  els.showRegisterBtn.classList.toggle("active", mode === "register");
}

function showApp(isAuthed) {
  els.authScreen.hidden = isAuthed;
  document.querySelector(".app-shell").hidden = !isAuthed;
}

async function bootstrapAuth() {
  loadAuth();
  if (!state.token) {
    showApp(false);
    setAuthMode("login");
    return;
  }
  try {
    state.user = await apiFetch(API.me);
    showApp(true);
    await Promise.all([loadWikiPages(), loadSessions()]);
    
    const savedSessionId = localStorage.getItem(ACTIVE_SESSION_KEY);
    if (savedSessionId && state.sessions.some((s) => s.id === savedSessionId)) {
      await loadSession(savedSessionId);
    } else {
      renderChat();
    }
  } catch {
    saveAuth(null);
    localStorage.removeItem(ACTIVE_SESSION_KEY);
    showApp(false);
    setAuthMode("login");
  }
}

function addMessage(message) {
  state.messages.push({
    id: uid(),
    createdAt: new Date().toISOString(),
    interaction: "message",
    ...message,
  });
  renderChat();
}

function updateMessage(id, patch) {
  const item = state.messages.find((message) => message.id === id);
  if (!item) return;
  Object.assign(item, patch);
  renderChat();
}

function startThinking(messageId) {
  stopThinking(messageId);
  let index = 0;
  updateMessage(messageId, { thinkingStep: index });
  const timer = setInterval(() => {
    index = Math.min(index + 1, THINKING_STEPS.length - 1);
    updateMessage(messageId, { thinkingStep: index });
  }, 1600);
  state.thinkingTimers.set(messageId, timer);
}

function stopThinking(messageId) {
  const timer = state.thinkingTimers.get(messageId);
  if (timer) clearInterval(timer);
  state.thinkingTimers.delete(messageId);
}

async function sendMessage(content, options = {}) {
  if (!content.trim() || state.sending) return;
  const parentId = state.pendingReplyTo || state.pendingCommentFor;
  const interaction = state.pendingCommentFor ? "comment" : state.pendingReplyTo ? "reply" : "message";
  clearReplyMode();

  const localUserId = uid();
  addMessage({ id: localUserId, role: "user", content, parentId, interaction });

  const assistantId = uid();
  state.messages.push({
    id: assistantId,
    role: "assistant",
    content: "Thinking...",
    pending: true,
    parentId: interaction === "message" ? null : localUserId,
    interaction,
    createdAt: new Date().toISOString(),
    thinkingStep: 0,
  });
  state.sending = true;
  els.sendBtn.disabled = true;
  renderChat();
  startThinking(assistantId);

  try {
    const response = await apiFetch(API.chat, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: content,
        session_id: state.currentSessionId,
        parent_id: parentId,
        interaction,
        context_page_slugs: options.contextPageSlugs || [],
        intent: options.intent || "auto",
        allow_fallback: true,
      }),
    });
    state.currentSessionId = response.session_id || state.currentSessionId;
    updateMessage(assistantId, {
      content: response.answer,
      pending: false,
      citations: response.citations || [],
      usedPages: response.used_pages || [],
    });
    await loadSessions();
    if (state.currentSessionId) await loadSession(state.currentSessionId, { silent: true });
  } catch (error) {
    updateMessage(assistantId, {
      content: `I could not complete that request.\n\n${error.message}`,
      pending: false,
      failed: true,
    });
    toast(error.message, "error");
  } finally {
    stopThinking(assistantId);
    state.sending = false;
    els.sendBtn.disabled = false;
  }
}

function renderThinking(stepIndex = 0) {
  const safeIndex = Math.max(0, Math.min(stepIndex, THINKING_STEPS.length - 1));
  const steps = THINKING_STEPS.map((label, index) => {
    const stateClass = index < safeIndex ? "done" : index === safeIndex ? "active" : "";
    return `<li class="${stateClass}"><span></span>${escapeHtml(label)}</li>`;
  }).join("");
  return `
    <div class="agent-thinking">
      <div class="thinking-title">
        <span class="thinking-spinner"></span>
        <strong>${escapeHtml(THINKING_STEPS[safeIndex])}</strong>
      </div>
      <ol>${steps}</ol>
    </div>
  `;
}

function renderChat() {
  els.chatBoard.innerHTML = "";
  if (!state.messages.length) {
    const welcome = document.createElement("div");
    welcome.className = "welcome-card";
    welcome.innerHTML = `
      <h3>${escapeHtml(getGreeting())}</h3>
      <p>Ask anything, upload a PDF, or click a wiki page for a grounded summary.</p>
    `;
    els.chatBoard.appendChild(welcome);
    return;
  }

  const children = new Map();
  const byId = new Map(state.messages.map((message) => [message.id, message]));
  for (const message of state.messages) {
    if (!message.parentId) continue;
    if (!children.has(message.parentId)) children.set(message.parentId, []);
    children.get(message.parentId).push(message);
  }
  const roots = state.messages.filter((message) => !message.parentId || !byId.has(message.parentId));
  for (const message of roots) {
    els.chatBoard.appendChild(renderMessageNode(message, children, 0));
  }
  els.chatBoard.scrollTop = els.chatBoard.scrollHeight;
}

function renderMessageNode(message, children, depth) {
  const wrapper = document.createElement("div");
  wrapper.className = `thread-node depth-${Math.min(depth, 4)}`;
  const node = els.template.content.firstElementChild.cloneNode(true);
  node.classList.add(message.role === "assistant" ? "assistant" : "user");
  node.classList.add(`interaction-${message.interaction || "message"}`);
  if (message.failed) node.classList.add("failed");
  node.querySelector(".message-author").textContent =
    message.role === "assistant" ? "KnowForge Assistant" : "You";
  node.querySelector(".message-time").textContent = new Date(message.createdAt).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  const interactionLabel = node.querySelector(".interaction-label");
  interactionLabel.textContent =
    message.interaction === "comment" ? "Comment" : message.interaction === "reply" ? "Reply" : "";
  if (!interactionLabel.textContent) interactionLabel.remove();
  node.querySelector(".message-body").innerHTML = message.pending
    ? renderThinking(message.thinkingStep || 0)
    : renderMarkdown(message.content);
  node.querySelector(".copy-btn").addEventListener("click", () => {
    navigator.clipboard?.writeText(message.content);
    toast("Message copied.");
  });
  node.querySelector(".reply-btn").addEventListener("click", () => setReplyMode(message.id, false));
  node.querySelector(".comment-btn").addEventListener("click", () => setReplyMode(message.id, true));

  const meta = node.querySelector(".message-meta-row");
  if (message.citations?.length) meta.appendChild(chip(`${message.citations.length} citation(s)`));
  else meta.remove();

  const thread = node.querySelector(".comment-thread");
  const childItems = children.get(message.id) || [];
  if (childItems.length) {
    for (const child of childItems) {
      thread.appendChild(renderMessageNode(child, children, depth + 1));
    }
  } else {
    thread.remove();
  }
  wrapper.appendChild(node);
  return wrapper;
}

function chip(label) {
  const item = document.createElement("span");
  item.className = "message-chip";
  item.textContent = label;
  return item;
}

function setReplyMode(messageId, commentMode) {
  state.pendingReplyTo = commentMode ? null : messageId;
  state.pendingCommentFor = commentMode ? messageId : null;
  state.pendingMode = commentMode ? "comment" : "reply";
  const message = state.messages.find((item) => item.id === messageId);
  const excerpt = message?.content ? `: ${message.content.slice(0, 90)}` : "";
  els.replyLabel.textContent = commentMode ? `Commenting${excerpt}` : `Replying${excerpt}`;
  els.replyBanner.hidden = false;
  els.messageInput.focus();
}

function clearReplyMode() {
  state.pendingReplyTo = null;
  state.pendingCommentFor = null;
  state.pendingMode = "message";
  els.replyLabel.textContent = "";
  els.replyBanner.hidden = true;
}

async function loadSessions() {
  const sessions = await apiFetch(API.sessions);
  state.sessions = sessions;
  state.openSessionMenuId = null;
  state.editingSessionId = null;
  state.editingSessionTitle = "";
  renderSessionList();
}

function renderSessionList() {
  els.sessionList.innerHTML = "";
  els.emptySessions.hidden = state.sessions.length > 0;
  for (const session of state.sessions) {
    const item = document.createElement("div");
    item.className = `session-item ${session.id === state.currentSessionId ? "active" : ""}`;

    const isEditing = state.editingSessionId === session.id;
    const titleHtml = isEditing
      ? `<input class="session-title-input" value="${escapeHtml(state.editingSessionTitle)}" />`
      : `<strong class="session-title">${escapeHtml(session.title)}</strong>`;

    if (isEditing) {
      item.innerHTML = `
        <div class="wiki-item session-row editing">
          <div class="session-details">
            ${titleHtml}
            <span>${escapeHtml(session.summary || new Date(session.updated_at).toLocaleString())}</span>
            <div class="edit-controls">
              <button type="button" class="icon-button session-action confirm" title="Save title">✓</button>
              <button type="button" class="icon-button session-action cancel" title="Cancel">✕</button>
            </div>
          </div>
          <div class="session-actions"></div>
        </div>
        <div class="session-menu ${state.openSessionMenuId === session.id ? "visible" : ""}">
          <button type="button" class="session-action edit">Rename</button>
          <button type="button" class="session-action delete">Delete</button>
        </div>
      `;
    } else {
      item.innerHTML = `
        <div class="wiki-item session-row">
          <div class="session-details">
            ${titleHtml}
            <span>${escapeHtml(session.summary || new Date(session.updated_at).toLocaleString())}</span>
          </div>
          <div class="session-actions">
            <button type="button" class="icon-button session-menu-btn" title="Session actions">⋮</button>
          </div>
        </div>
        <div class="session-menu ${state.openSessionMenuId === session.id ? "visible" : ""}">
          <button type="button" class="session-action edit">Rename</button>
          <button type="button" class="session-action delete">Delete</button>
        </div>
      `;
    }

    const row = item.querySelector(".session-row");
    if (row && !isEditing) {
      row.addEventListener("click", (e) => {
        e.stopPropagation();
        loadSession(session.id);
      });
    }

    if (isEditing) {
      const input = item.querySelector(".session-title-input");
      input.addEventListener("input", (event) => {
        state.editingSessionTitle = event.target.value;
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          applySessionRename(session.id);
        }
        if (event.key === "Escape") {
          cancelSessionRename();
        }
      });
      item.querySelector(".session-action.confirm").addEventListener("click", () => applySessionRename(session.id));
      item.querySelector(".session-action.cancel").addEventListener("click", () => cancelSessionRename());
      setTimeout(() => {
        input?.focus();
        try { input?.select(); } catch (e) {}
      }, 0);
    } else {
      item.querySelector(".session-menu-btn").addEventListener("click", (event) => {
        console.log("session menu button clicked", session.id);
        event.stopPropagation();
        toggleSessionMenu(session.id);
      });
      item.querySelector(".session-action.edit").addEventListener("click", (event) => {
        event.stopPropagation();
        startSessionRename(session.id, session.title);
      });
      item.querySelector(".session-action.delete").addEventListener("click", (event) => {
        event.stopPropagation();
        confirmDeleteSession(session.id);
      });
    }

    els.sessionList.appendChild(item);
  }
}

function toggleSessionMenu(sessionId) {
  console.log("toggleSessionMenu before", sessionId, state.openSessionMenuId);
  state.openSessionMenuId = state.openSessionMenuId === sessionId ? null : sessionId;
  console.log("toggleSessionMenu after", state.openSessionMenuId);
  renderSessionList();
}

function startSessionRename(sessionId, currentTitle) {
  state.editingSessionId = sessionId;
  state.editingSessionTitle = currentTitle;
  state.openSessionMenuId = null;
  renderSessionList();
}

function cancelSessionRename() {
  state.editingSessionId = null;
  state.editingSessionTitle = "";
  renderSessionList();
}

async function applySessionRename(sessionId) {
  const title = state.editingSessionTitle.trim();
  if (!title) {
    toast("Chat title cannot be empty.", "error");
    return;
  }

  try {
    await apiFetch(`${API.sessions}/${sessionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    toast("Chat renamed.");
    state.editingSessionId = null;
    state.editingSessionTitle = "";
    await loadSessions();
  } catch (error) {
    toast(error.message, "error");
  }
}

function confirmDeleteSession(sessionId) {
  // close any open session menu before showing confirmation
  state.openSessionMenuId = null;
  renderSessionList();

  showDialog({
    title: "Delete chat?",
    message: "This will remove the selected chat session permanently.",
    confirmText: "Delete",
    cancelText: "Cancel",
    onConfirm: async () => {
      try {
        await apiFetch(`${API.sessions}/${sessionId}`, { method: "DELETE" });
        toast("Chat deleted.");
        if (state.currentSessionId === sessionId) {
          state.currentSessionId = null;
          localStorage.removeItem(ACTIVE_SESSION_KEY);
          state.messages = [];
          renderChat();
        }
        state.openSessionMenuId = null;
        await loadSessions();
      } catch (error) {
        toast(error.message, "error");
      }
    },
  });
}

function showDialog({ title, message, confirmText, cancelText, onConfirm }) {
  const overlay = document.createElement("div");
  overlay.className = "dialog-overlay";
  overlay.innerHTML = `
    <div class="dialog-card">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(message)}</p>
      <div class="dialog-actions">
        <button type="button" class="secondary-button dialog-cancel">${escapeHtml(cancelText)}</button>
        <button type="button" class="primary-button dialog-confirm">${escapeHtml(confirmText)}</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const remove = () => overlay.remove();
  overlay.querySelector(".dialog-cancel").addEventListener("click", () => {
    remove();
  });
  overlay.querySelector(".dialog-confirm").addEventListener("click", async () => {
    remove();
    await onConfirm();
  });
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) remove();
  });
}

async function loadSession(sessionId, options = {}) {
  const payload = await apiFetch(`${API.sessions}/${sessionId}`);
  state.currentSessionId = sessionId;
  localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  state.messages = payload.messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    parentId: message.parent_id,
    interaction: message.interaction || "message",
    route: message.route,
    createdAt: message.created_at,
  }));
  renderChat();
  if (!options.silent) await loadSessions();
}

async function loadWikiPages() {
  try {
    const pages = await apiFetch(API.wikiPages);
    els.wikiList.innerHTML = "";
    els.emptyWiki.hidden = pages.length > 0;
    for (const page of pages) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "wiki-item";
      item.innerHTML = `
        <strong>${escapeHtml(page.title)}</strong>
        <span>${escapeHtml(page.summary || page.slug)}</span>
      `;
      item.addEventListener("click", () =>
        sendMessage(`Summarize the wiki page "${page.slug}" and explain what it is useful for.`, {
          intent: "wiki",
          contextPageSlugs: [page.slug],
        }),
      );
      els.wikiList.appendChild(item);
    }
  } catch (error) {
    els.emptyWiki.hidden = false;
    els.emptyWiki.textContent = error.message;
  }
}

async function uploadPdf(file) {
  els.uploadError.hidden = true;
  if (!file) return;
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    showUploadError("Please choose a PDF file.");
    return;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    showUploadError("PDF is larger than the configured upload limit.");
    return;
  }

  const form = new FormData();
  form.append("file", file);
  els.uploadState.textContent = "Uploading";
  els.uploadState.classList.remove("muted");
  try {
    const response = await apiFetch(API.upload, { method: "POST", body: form, timeout: 90000 });
    toast(`Uploaded ${response.filename}. Wiki page: ${response.wiki_page_slug || "not compiled"}`);
    els.uploadState.textContent = "Ready";
    await loadWikiPages();
  } catch (error) {
    showUploadError(error.message);
    els.uploadState.textContent = "Failed";
  }
}

function showUploadError(message) {
  els.uploadError.textContent = message;
  els.uploadError.hidden = false;
  toast(message, "error");
}

function logout(showToast = true) {
  saveAuth(null);
  state.user = null;
  state.currentSessionId = null;
  localStorage.removeItem(ACTIVE_SESSION_KEY);
  state.messages = [];
  showApp(false);
  setAuthMode("login");
  if (showToast) toast("Logged out.");
}

function bindEvents() {
  els.showLoginBtn.addEventListener("click", () => setAuthMode("login"));
  els.showRegisterBtn.addEventListener("click", () => setAuthMode("register"));

  els.loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = els.loginForm.querySelector("button[type='submit']");
    setButtonLoading(button, true, "Logging in...");
    try {
      const response = await apiFetch(API.login, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: els.loginEmail.value, password: els.loginPassword.value }),
      });
      saveAuth(response.access_token);
      state.user = response.user;
      showApp(true);
      await Promise.all([loadWikiPages(), loadSessions()]);
      renderChat();
    } catch (error) {
      showAuthError(error.message);
      if (/verify/i.test(error.message)) {
        els.verifyEmail.value = els.loginEmail.value;
        setAuthMode("verify");
      }
    } finally {
      setButtonLoading(button, false);
    }
  });

  els.registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = els.registerForm.querySelector("button[type='submit']");
    setButtonLoading(button, true, "Creating...");
    try {
      await apiFetch(API.register, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: els.registerName.value,
          email: els.registerEmail.value,
          password: els.registerPassword.value,
        }),
      });
      els.verifyEmail.value = els.registerEmail.value;
      setAuthMode("verify");
      toast("Verification code sent.");
    } catch (error) {
      showAuthError(error.message);
    } finally {
      setButtonLoading(button, false);
    }
  });

  els.verifyForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = els.verifyForm.querySelector("button[type='submit']");
    setButtonLoading(button, true, "Verifying...");
    try {
      await apiFetch(API.verify, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: els.verifyEmail.value, code: els.verifyCode.value }),
      });
      els.loginEmail.value = els.verifyEmail.value;
      setAuthMode("login");
      toast("Email verified. Login now.");
    } catch (error) {
      showAuthError(error.message);
    } finally {
      setButtonLoading(button, false);
    }
  });

  els.resendCodeBtn.addEventListener("click", async () => {
    setButtonLoading(els.resendCodeBtn, true, "Sending...");
    try {
      await apiFetch(API.resend, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: els.verifyEmail.value }),
      });
      toast("New verification code sent.");
    } catch (error) {
      showAuthError(error.message);
    } finally {
      setButtonLoading(els.resendCodeBtn, false);
    }
  });

  els.chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = els.messageInput.value.trim();
    els.messageInput.value = "";
    resizeTextarea();
    await sendMessage(content);
  });

  els.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      els.chatForm.requestSubmit();
    }
  });
  els.messageInput.addEventListener("input", resizeTextarea);

  els.cancelReplyBtn.addEventListener("click", clearReplyMode);
  els.refreshWikiBtn.addEventListener("click", loadWikiPages);
  els.refreshSessionsBtn.addEventListener("click", loadSessions);
  els.newChatBtn.addEventListener("click", () => {
    state.currentSessionId = null;
    localStorage.removeItem(ACTIVE_SESSION_KEY);
    state.messages = [];
    renderChat();
    renderSessionList();
    toast("Started a new chat.");
  });
  els.compactWikiBtn.addEventListener("click", async () => {
    try {
      const response = await apiFetch(API.compact, { method: "POST", timeout: 90000 });
      toast(`Compacted ${response.compacted} wiki page(s).`);
    } catch (error) {
      toast(error.message, "error");
    }
  });
  els.logoutBtn.addEventListener("click", () => logout());

  els.pdfInput.addEventListener("change", () => uploadPdf(els.pdfInput.files?.[0]));
  for (const eventName of ["dragenter", "dragover"]) {
    els.dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      els.dropZone.classList.add("dragging");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    els.dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      els.dropZone.classList.remove("dragging");
    });
  }
  els.dropZone.addEventListener("drop", (event) => uploadPdf(event.dataTransfer.files?.[0]));
  window.addEventListener("click", () => {
    if (state.openSessionMenuId) {
      state.openSessionMenuId = null;
      renderSessionList();
    }
  });
}

function resizeTextarea() {
  els.messageInput.style.height = "auto";
  els.messageInput.style.height = `${Math.min(180, els.messageInput.scrollHeight)}px`;
}

bindEvents();
showApp(false);
bootstrapAuth();
