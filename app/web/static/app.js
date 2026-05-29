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
  llmKeys: "/api/v1/llm/keys",
};

const AUTH_KEY = "knowforge.auth.v1";
const ACTIVE_SESSION_KEY = "knowforge.session.v1";
const SIDEBAR_LAYOUT_KEY = "knowforge.sidebar.v1";
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const SIDEBAR_DEFAULT_WIDTH = 340;
const SIDEBAR_COLLAPSED_WIDTH = 72;
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
  wikiPages: [],
  openWikiMenuSlug: null,
  editingWikiSlug: null,
  editingWikiTitle: "",
  sidebarCollapsed: false,
  sidebarWidth: SIDEBAR_DEFAULT_WIDTH,
  sidebarResizing: false,
  llmProviderTouched: false,
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
  appShell: document.querySelector(".app-shell"),
  sidebar: document.querySelector("#sidebar"),
  sidebarCloseBtn: document.querySelector("#sidebarCloseBtn"),
  sidebarOpenBtn: document.querySelector("#sidebarOpenBtn"),
  sidebarResizer: document.querySelector("#sidebarResizer"),
  sidebarLogoWrap: document.querySelector("#sidebarLogoWrap"),
  llmSettingsBtn: document.querySelector("#llmSettingsBtn"),
  llmModal: document.querySelector("#llmModal"),
  llmModalCloseBtn: document.querySelector("#llmModalCloseBtn"),
  llmProviderSelect: document.querySelector("#llmProviderSelect"),
  llmProviderLogo: document.querySelector("#llmProviderLogo"),
  llmApiKeyInput: document.querySelector("#llmApiKeyInput"),
  llmConnectBtn: document.querySelector("#llmConnectBtn"),
  llmDisconnectBtn: document.querySelector("#llmDisconnectBtn"),
  llmSaveModelBtn: document.querySelector("#llmSaveModelBtn"),
  llmStatusPill: document.querySelector("#llmStatusPill"),
  llmError: document.querySelector("#llmError"),
  llmModelSelect: document.querySelector("#llmModelSelect"),
  llmCustomModelRow: document.querySelector("#llmCustomModelRow"),
  llmCustomModelInput: document.querySelector("#llmCustomModelInput"),
};

const PROVIDER_LOGOS = {
  openrouter: "https://cdn.simpleicons.org/openrouter/94A3B8",
  // Use jsDelivr SVG to avoid occasional simpleicons rendering issues.
  openai: "https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/openai.svg",
  anthropic: "https://cdn.simpleicons.org/anthropic",
  gemini: "https://cdn.simpleicons.org/googlegemini",
};

const PROVIDER_KEY_PLACEHOLDERS = {
  openrouter: "Paste your OpenRouter key",
  openai: "Paste your OpenAI API key",
  anthropic: "Paste your Anthropic API key",
  gemini: "Paste your Gemini API key",
};

const PROVIDER_MODELS = {
  openrouter: [
    { id: "openai/gpt-4o-mini", label: "GPT-4o mini (OpenRouter)" },
    { id: "openai/gpt-4o", label: "GPT-4o (OpenRouter)" },
    { id: "anthropic/claude-3.5-sonnet", label: "Claude 3.5 Sonnet (OpenRouter)" },
    { id: "google/gemini-1.5-pro", label: "Gemini 1.5 Pro (OpenRouter)" },
    { id: "deepseek/deepseek-chat", label: "DeepSeek Chat (OpenRouter)" },
    { id: "qwen/qwen-2.5-72b-instruct", label: "Qwen 2.5 72B Instruct (OpenRouter)" },
    { id: "moonshotai/kimi-k2", label: "Kimi (OpenRouter)" },
    { id: "__custom__", label: "Custom model ID…" },
  ],
  openai: [
    { group: "Aliases", id: "gpt-5.5", label: "GPT-5.5" },
    { group: "Aliases", id: "gpt-5.4", label: "GPT-5.4" },
    { group: "Aliases", id: "gpt-5.2", label: "GPT-5.2" },
    { group: "Aliases", id: "gpt-5", label: "GPT-5" },
    { group: "Aliases", id: "gpt-5.4-mini", label: "GPT-5.4 mini" },
    { group: "Pinned snapshots", id: "gpt-5.5-2026-04-23", label: "GPT-5.5 (2026-04-23)" },
    { group: "Pinned snapshots", id: "gpt-5.4-2026-03-05", label: "GPT-5.4 (2026-03-05)" },
    { group: "Pinned snapshots", id: "gpt-5.2-2025-12-11", label: "GPT-5.2 (2025-12-11)" },
    { group: "Pinned snapshots", id: "gpt-5-2025-08-07", label: "GPT-5 (2025-08-07)" },
    { group: "Pinned snapshots", id: "gpt-5.4-mini-2026-03-17", label: "GPT-5.4 mini (2026-03-17)" },
    { group: "Other", id: "__custom__", label: "Custom model ID…" },
  ],
  anthropic: [
    { group: "Current", id: "claude-opus-4-7", label: "Claude Opus 4.7" },
    { group: "Current", id: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
    { group: "Current", id: "claude-opus-4-6", label: "Claude Opus 4.6" },
    { group: "Aliases", id: "claude-opus-4-5", label: "Claude Opus 4.5" },
    { group: "Aliases", id: "claude-haiku-4-5", label: "Claude Haiku 4.5" },
    { group: "Pinned snapshots", id: "claude-opus-4-5-20251101", label: "Claude Opus 4.5 (2025-11-01)" },
    { group: "Pinned snapshots", id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5 (2025-10-01)" },
    { group: "Other", id: "__custom__", label: "Custom model ID…" },
  ],
  gemini: [
    { id: "gemini-3.5-flash", label: "Gemini 3.5 Flash" },
    { id: "gemini-3.1-pro-preview", label: "Gemini 3.1 Pro Preview" },
    { id: "gemini-3-flash-preview", label: "Gemini 3 Flash Preview" },
    { id: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
    { id: "gemini-3.1-flash-lite", label: "Gemini 3.1 Flash-Lite" },
    { id: "__custom__", label: "Custom model ID…" },
  ],
};

function updateProviderLogo() {
  const provider = els.llmProviderSelect.value;
  const src = PROVIDER_LOGOS[provider] || "";
  if (els.llmProviderLogo) {
    els.llmProviderLogo.src = src;
    els.llmProviderLogo.alt = `${provider} logo`;
  }
}

function updateApiKeyPlaceholder() {
  const provider = els.llmProviderSelect.value;
  const placeholder = PROVIDER_KEY_PLACEHOLDERS[provider] || "Paste your API key";
  if (els.llmApiKeyInput) els.llmApiKeyInput.placeholder = placeholder;
}

function updateModelOptions({ provider, selectedModel }) {
  const models = PROVIDER_MODELS[provider] || [];
  els.llmModelSelect.innerHTML = "";
  const hasGroups = models.some((m) => m.group);
  if (hasGroups) {
    const groups = new Map();
    for (const item of models) {
      const group = item.group || "Models";
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(item);
    }
    for (const [group, items] of groups.entries()) {
      const optgroup = document.createElement("optgroup");
      optgroup.label = group;
      for (const item of items) {
        const opt = document.createElement("option");
        opt.value = item.id;
        opt.textContent = item.label;
        optgroup.appendChild(opt);
      }
      els.llmModelSelect.appendChild(optgroup);
    }
  } else {
    for (const item of models) {
      const opt = document.createElement("option");
      opt.value = item.id;
      opt.textContent = item.label;
      els.llmModelSelect.appendChild(opt);
    }
  }
  if (selectedModel) {
    const exists = Array.from(els.llmModelSelect.options).some((o) => o.value === selectedModel);
    if (exists) els.llmModelSelect.value = selectedModel;
    else {
      els.llmModelSelect.value = "__custom__";
      els.llmCustomModelRow.hidden = false;
      els.llmCustomModelInput.value = selectedModel;
    }
  } else {
    els.llmModelSelect.selectedIndex = 0;
  }
  const custom = els.llmModelSelect.value === "__custom__";
  els.llmCustomModelRow.hidden = !custom;
}

function openLlmModal() {
  els.llmModal.hidden = false;
  document.body.classList.add("modal-open");
  state.llmProviderTouched = false;
  loadLlmStatus({ preferActiveProvider: true });
}

function closeLlmModal() {
  els.llmModal.hidden = true;
  document.body.classList.remove("modal-open");
}

function setLlmUi({ connected, provider }) {
  els.llmError.hidden = true;
  els.llmError.textContent = "";
  els.llmDisconnectBtn.disabled = !connected;
  els.llmConnectBtn.disabled = connected;
  els.llmProviderSelect.disabled = connected;
  els.llmApiKeyInput.disabled = connected;
  els.llmSaveModelBtn.disabled = !connected;
  els.llmStatusPill.textContent = connected ? `Connected (${provider})` : "Not connected";
  els.llmStatusPill.classList.toggle("muted", !connected);
  els.llmStatusPill.classList.toggle("connected", !!connected);
  els.llmStatusPill.classList.toggle("disconnected", !connected);
  els.llmSettingsBtn?.classList.toggle("llm-connected", !!connected);
  els.llmSettingsBtn?.classList.toggle("llm-disconnected", !connected);
  updateProviderLogo();
  updateApiKeyPlaceholder();
}

async function loadLlmStatus(options = {}) {
  const { preferActiveProvider = false } = options;
  try {
    const items = await apiFetch(API.llmKeys);
    const active = Array.isArray(items) ? items.find((x) => x.active) : null;
    if ((preferActiveProvider && active?.provider) || (!state.llmProviderTouched && active?.provider)) {
      els.llmProviderSelect.value = active.provider;
    }
    const provider = els.llmProviderSelect.value;
    const current = Array.isArray(items) ? items.find((x) => x.provider === provider) : null;
    setLlmUi({ connected: !!current?.connected, provider });
    updateModelOptions({ provider, selectedModel: current?.model || "" });
  } catch (error) {
    setLlmUi({ connected: false, provider: els.llmProviderSelect.value });
    updateModelOptions({ provider: els.llmProviderSelect.value, selectedModel: "" });
  }
}

function loadSidebarLayout() {
  try {
    const saved = JSON.parse(localStorage.getItem(SIDEBAR_LAYOUT_KEY) || "{}");
    if (typeof saved.collapsed === "boolean") state.sidebarCollapsed = saved.collapsed;
    if (Number.isFinite(saved.width)) state.sidebarWidth = Math.max(SIDEBAR_DEFAULT_WIDTH, Number(saved.width));
  } catch {
    state.sidebarCollapsed = false;
    state.sidebarWidth = SIDEBAR_DEFAULT_WIDTH;
  }
}

function saveSidebarLayout() {
  localStorage.setItem(
    SIDEBAR_LAYOUT_KEY,
    JSON.stringify({
      collapsed: state.sidebarCollapsed,
      width: state.sidebarWidth,
    }),
  );
}

function applySidebarLayout() {
  const viewportMax = Math.floor(window.innerWidth * 0.5);
  const clampedWidth = Math.max(SIDEBAR_DEFAULT_WIDTH, Math.min(state.sidebarWidth, viewportMax));
  state.sidebarWidth = clampedWidth;
  if (state.sidebarCollapsed) {
    els.appShell.style.gridTemplateColumns = `${SIDEBAR_COLLAPSED_WIDTH}px minmax(0, 1fr)`;
    els.sidebar.classList.add("collapsed");
  } else {
    els.appShell.style.gridTemplateColumns = `${clampedWidth}px minmax(0, 1fr)`;
    els.sidebar.classList.remove("collapsed");
  }
}

function setSidebarCollapsed(collapsed) {
  state.sidebarCollapsed = !!collapsed;
  applySidebarLayout();
  saveSidebarLayout();
}

function startSidebarResize(event) {
  if (state.sidebarCollapsed) return;
  event.preventDefault();
  state.sidebarResizing = true;
  document.body.classList.add("resizing-sidebar");
  const onMove = (moveEvent) => {
    if (!state.sidebarResizing) return;
    const max = Math.floor(window.innerWidth * 0.5);
    state.sidebarWidth = Math.max(SIDEBAR_DEFAULT_WIDTH, Math.min(moveEvent.clientX, max));
    applySidebarLayout();
  };
  const onUp = () => {
    state.sidebarResizing = false;
    document.body.classList.remove("resizing-sidebar");
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
    saveSidebarLayout();
  };
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
}

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
  const source = (markdown || "").replace(/\r\n/g, "\n");
  const blocks = source.split(/\n{2,}/).map((part) => part.trim()).filter(Boolean);
  const rendered = blocks.map(renderMarkdownBlock).join("");
  return rendered || `<p>${escapeHtml(source)}</p>`;
}

function renderInlineMarkdown(value) {
  return escapeHtml(value || "")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
    .replace(/\[(wiki|source):([^\]]+)\]/g, '<span class="message-chip">$1:$2</span>');
}

function renderMarkdownBlock(block) {
  if (block.startsWith("```") && block.endsWith("```")) {
    const code = block.slice(3, -3).trim();
    return `<pre><code>${escapeHtml(code)}</code></pre>`;
  }
  const lines = block.split("\n");
  if (lines.every((line) => /^[-*]\s+/.test(line.trim()))) {
    const items = lines.map((line) => `<li>${renderInlineMarkdown(line.trim().replace(/^[-*]\s+/, ""))}</li>`).join("");
    return `<ul>${items}</ul>`;
  }
  if (
    lines.length >= 2 &&
    lines[0].includes("|") &&
    /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(lines[1])
  ) {
    return renderMarkdownTable(lines);
  }
  if (/^#{1,3}\s+/.test(lines[0])) {
    const text = lines[0].replace(/^#{1,3}\s+/, "");
    return `<p><strong>${renderInlineMarkdown(text)}</strong></p>`;
  }
  return `<p>${lines.map((line) => renderInlineMarkdown(line)).join("<br />")}</p>`;
}

function renderMarkdownTable(lines) {
  if (lines.length < 2) return `<p>${renderInlineMarkdown(lines.join("\n"))}</p>`;
  const rows = lines
    .filter((line, index) => index !== 1)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()));
  if (!rows.length) return "";
  const header = rows[0];
  const bodyRows = rows.slice(1);
  const headHtml = `<tr>${header.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join("")}</tr>`;
  const bodyHtml = bodyRows
    .map((row) => `<tr>${row.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join("")}</tr>`)
    .join("");
  return `<div class="table-wrap"><table><thead>${headHtml}</thead><tbody>${bodyHtml}</tbody></table></div>`;
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
    if (error.name === "AbortError") {
      els.networkState.textContent = "Request timed out";
      throw new Error("Request timed out. The AI model or system took too long to respond. Please try again.");
    }
    els.networkState.textContent = "API connection issue";
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
    await Promise.all([loadWikiPages(), loadSessions(), loadLlmStatus()]);
    
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
      timeout: 300000, // 5 minutes to allow complex multi-LLM routing, planning, and verification
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
  state.openSessionMenuId = state.openSessionMenuId === sessionId ? null : sessionId;
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

function prefillWikiPrompt(page) {
  const prompt = `Summarize the wiki page "${page.slug}" and explain what it is useful for.`;
  els.messageInput.value = prompt;
  resizeTextarea();
  els.messageInput.focus();
  state.openWikiMenuSlug = null;
  renderWikiPages();
}

function toggleWikiMenu(slug) {
  state.openWikiMenuSlug = state.openWikiMenuSlug === slug ? null : slug;
  renderWikiPages();
}

function startWikiRename(slug, currentTitle) {
  state.editingWikiSlug = slug;
  state.editingWikiTitle = currentTitle;
  state.openWikiMenuSlug = null;
  renderWikiPages();
}

function cancelWikiRename() {
  state.editingWikiSlug = null;
  state.editingWikiTitle = "";
  renderWikiPages();
}

async function applyWikiRename(slug) {
  const title = state.editingWikiTitle.trim();
  if (!title) {
    toast("Wiki page title cannot be empty.", "error");
    return;
  }
  try {
    await apiFetch(`${API.wikiPages}/${slug}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    toast("Wiki page renamed.");
    state.editingWikiSlug = null;
    state.editingWikiTitle = "";
    await loadWikiPages();
  } catch (error) {
    toast(error.message, "error");
  }
}

function confirmDeleteWikiPage(slug) {
  state.openWikiMenuSlug = null;
  renderWikiPages();
  showDialog({
    title: "Delete wiki page?",
    message: "This will permanently remove the selected wiki page.",
    confirmText: "Delete",
    cancelText: "Cancel",
    onConfirm: async () => {
      try {
        await apiFetch(`${API.wikiPages}/${slug}`, { method: "DELETE" });
        toast("Wiki page deleted.");
        state.editingWikiSlug = null;
        state.editingWikiTitle = "";
        state.openWikiMenuSlug = null;
        await loadWikiPages();
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
    state.wikiPages = pages;
    if (!state.wikiPages.some((page) => page.slug === state.editingWikiSlug)) {
      state.editingWikiSlug = null;
      state.editingWikiTitle = "";
    }
    if (!state.wikiPages.some((page) => page.slug === state.openWikiMenuSlug)) {
      state.openWikiMenuSlug = null;
    }
    renderWikiPages();
  } catch (error) {
    state.wikiPages = [];
    renderWikiPages();
    els.emptyWiki.hidden = false;
    els.emptyWiki.textContent = error.message;
  }
}

function renderWikiPages() {
  els.wikiList.innerHTML = "";
  els.emptyWiki.hidden = state.wikiPages.length > 0;
  for (const page of state.wikiPages) {
    const item = document.createElement("div");
    const isEditing = state.editingWikiSlug === page.slug;
    item.className = `session-item wiki-page-item ${isEditing ? "editing" : ""}`;
    item.innerHTML = isEditing
      ? `
        <div class="wiki-item session-row editing">
          <div class="session-details">
            <input class="session-title-input wiki-title-input" value="${escapeHtml(state.editingWikiTitle)}" />
            <span>${escapeHtml(page.summary || page.slug)}</span>
            <div class="edit-controls">
              <button type="button" class="icon-button wiki-action confirm" title="Save title">✓</button>
              <button type="button" class="icon-button wiki-action cancel" title="Cancel">✕</button>
            </div>
          </div>
          <div class="session-actions"></div>
        </div>
      `
      : `
        <div class="wiki-item session-row wiki-card-row">
          <div class="session-details">
            <strong class="session-title">${escapeHtml(page.title)}</strong>
            <span>${escapeHtml(page.summary || page.slug)}</span>
          </div>
          <div class="session-actions">
            <button type="button" class="icon-button wiki-menu-btn" title="Wiki page actions">⋮</button>
          </div>
        </div>
        <div class="session-menu ${state.openWikiMenuSlug === page.slug ? "visible" : ""}">
          <button type="button" class="session-action edit">Rename</button>
          <button type="button" class="session-action delete">Delete</button>
        </div>
      `;

    if (isEditing) {
      const input = item.querySelector(".wiki-title-input");
      input.addEventListener("input", (event) => {
        state.editingWikiTitle = event.target.value;
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          applyWikiRename(page.slug);
        }
        if (event.key === "Escape") cancelWikiRename();
      });
      item.querySelector(".wiki-action.confirm").addEventListener("click", () => applyWikiRename(page.slug));
      item.querySelector(".wiki-action.cancel").addEventListener("click", cancelWikiRename);
      setTimeout(() => {
        input?.focus();
        try { input?.select(); } catch (e) {}
      }, 0);
    } else {
      item.querySelector(".wiki-card-row").addEventListener("click", () => prefillWikiPrompt(page));
      item.querySelector(".wiki-menu-btn").addEventListener("click", (event) => {
        event.stopPropagation();
        toggleWikiMenu(page.slug);
      });
      item.querySelector(".session-action.edit").addEventListener("click", (event) => {
        event.stopPropagation();
        startWikiRename(page.slug, page.title);
      });
      item.querySelector(".session-action.delete").addEventListener("click", (event) => {
        event.stopPropagation();
        confirmDeleteWikiPage(page.slug);
      });
    }
    els.wikiList.appendChild(item);
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
  els.sidebarCloseBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    setSidebarCollapsed(true);
  });
  els.sidebarOpenBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    setSidebarCollapsed(false);
  });
  els.sidebarLogoWrap.addEventListener("click", () => {
    if (state.sidebarCollapsed) setSidebarCollapsed(false);
  });
  els.sidebarResizer.addEventListener("mousedown", startSidebarResize);
  window.addEventListener("resize", () => {
    applySidebarLayout();
    saveSidebarLayout();
  });

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

  els.llmSettingsBtn.addEventListener("click", () => openLlmModal());
  els.llmModalCloseBtn.addEventListener("click", () => closeLlmModal());
  els.llmModal.addEventListener("click", (event) => {
    if (event.target === els.llmModal) closeLlmModal();
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !els.llmModal.hidden) closeLlmModal();
  });

  els.llmProviderSelect.addEventListener("change", async () => {
    state.llmProviderTouched = true;
    updateProviderLogo();
    updateApiKeyPlaceholder();
    updateModelOptions({ provider: els.llmProviderSelect.value, selectedModel: "" });
    await loadLlmStatus({ preferActiveProvider: false });
  });

  els.llmModelSelect.addEventListener("change", () => {
    const custom = els.llmModelSelect.value === "__custom__";
    els.llmCustomModelRow.hidden = !custom;
    if (custom) els.llmCustomModelInput.focus();
  });

  els.llmConnectBtn.addEventListener("click", async () => {
    const provider = els.llmProviderSelect.value;
    const apiKey = els.llmApiKeyInput.value.trim();
    const model = els.llmModelSelect.value === "__custom__"
      ? els.llmCustomModelInput.value.trim()
      : els.llmModelSelect.value;
    els.llmError.hidden = true;
    if (!apiKey) {
      els.llmError.textContent = "API key is required.";
      els.llmError.hidden = false;
      return;
    }
    if (!model) {
      els.llmError.textContent = "Model is required.";
      els.llmError.hidden = false;
      return;
    }
    setButtonLoading(els.llmConnectBtn, true, "Connecting...");
    try {
      await apiFetch(API.llmKeys, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, api_key: apiKey, model }),
        timeout: 45000,
      });
      els.llmApiKeyInput.value = "";
      toast("LLM provider connected.");
      await loadLlmStatus();
    } catch (error) {
      els.llmError.textContent = error.message;
      els.llmError.hidden = false;
      toast(error.message, "error");
    } finally {
      setButtonLoading(els.llmConnectBtn, false);
    }
  });

  els.llmDisconnectBtn.addEventListener("click", async () => {
    const provider = els.llmProviderSelect.value;
    setButtonLoading(els.llmDisconnectBtn, true, "Disconnecting...");
    try {
      await apiFetch(`${API.llmKeys}/${provider}`, { method: "DELETE" });
      toast("LLM provider disconnected.");
      setLlmUi({ connected: false, provider });
      await loadLlmStatus();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      setButtonLoading(els.llmDisconnectBtn, false);
    }
  });

  els.llmSaveModelBtn.addEventListener("click", async () => {
    const provider = els.llmProviderSelect.value;
    const model = els.llmModelSelect.value === "__custom__"
      ? els.llmCustomModelInput.value.trim()
      : els.llmModelSelect.value;
    if (!model) {
      toast("Model is required.", "error");
      return;
    }
    setButtonLoading(els.llmSaveModelBtn, true, "Saving...");
    try {
      await apiFetch(`${API.llmKeys}/${provider}/model`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model }),
      });
      toast("Model updated.");
      await loadLlmStatus();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      setButtonLoading(els.llmSaveModelBtn, false);
    }
  });

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
    let rerenderSessions = false;
    let rerenderWiki = false;
    if (state.openSessionMenuId) {
      state.openSessionMenuId = null;
      rerenderSessions = true;
    }
    if (state.openWikiMenuSlug) {
      state.openWikiMenuSlug = null;
      rerenderWiki = true;
    }
    if (rerenderSessions) renderSessionList();
    if (rerenderWiki) renderWikiPages();
  });
}

function resizeTextarea() {
  els.messageInput.style.height = "auto";
  els.messageInput.style.height = `${Math.min(180, els.messageInput.scrollHeight)}px`;
}

loadSidebarLayout();
applySidebarLayout();
bindEvents();
showApp(false);
bootstrapAuth();
