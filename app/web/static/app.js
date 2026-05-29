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
  contradictions: "/api/v1/wiki/contradictions",
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
  contradictions: [],
  scanningConflicts: false,
  wikiInsightSlug: null,
  pendingWikiContextSlug: null,
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
  conflictsList: document.querySelector("#conflictsList"),
  emptyConflicts: document.querySelector("#emptyConflicts"),
  scanConflictsBtn: document.querySelector("#scanConflictsBtn"),
  wikiInsightModal: document.querySelector("#wikiInsightModal"),
  wikiInsightCloseBtn: document.querySelector("#wikiInsightCloseBtn"),
  wikiInsightTitle: document.querySelector("#wikiInsightTitle"),
  wikiInsightBody: document.querySelector("#wikiInsightBody"),
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
    await Promise.all([loadWikiPages(), loadSessions(), loadLlmStatus(), loadConflicts()]);
    
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

  const contextPageSlugs = options.contextPageSlugs?.length
    ? options.contextPageSlugs
    : state.pendingWikiContextSlug
      ? [state.pendingWikiContextSlug]
      : [];
  const wikiIntent = options.intent || (contextPageSlugs.length ? "wiki" : "auto");
  if (!options.keepWikiContext) {
    state.pendingWikiContextSlug = null;
  }

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
        context_page_slugs: contextPageSlugs,
        intent: wikiIntent,
        allow_fallback: true,
      }),
    });
    state.currentSessionId = response.session_id || state.currentSessionId;
    updateMessage(assistantId, {
      content: response.answer,
      pending: false,
      citations: response.citations || [],
      usedPages: response.used_pages || [],
      agentTrace: response.agent_trace || [],
      route: response.route,
      difficulty: response.difficulty,
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
  const isEmpty = state.messages.length === 0;
  const titleEl = document.querySelector("#chatBoardTitle");
  if (titleEl) {
    if (isEmpty) {
      titleEl.textContent = "";
    } else if (state.currentSessionId) {
      const currentSession = state.sessions.find((s) => s.id === state.currentSessionId);
      titleEl.textContent = currentSession ? (currentSession.title || "") : "";
    } else {
      titleEl.textContent = "";
    }
  }

  els.chatBoard.innerHTML = "";
  if (isEmpty) {
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
  if (message.pending) node.classList.add("pending");
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
  meta.innerHTML = "";
  if (message.citations?.length) meta.appendChild(chip(`${message.citations.length} citation(s)`));
  if (message.usedPages?.length) {
    for (const slug of message.usedPages) {
      const pageChip = document.createElement("button");
      pageChip.type = "button";
      pageChip.className = "meta-chip meta-chip-link";
      pageChip.textContent = slug;
      pageChip.title = "Open wiki insight";
      pageChip.addEventListener("click", () => openWikiInsight(slug));
      meta.appendChild(pageChip);
    }
  }
  if (message.agentTrace?.length) {
    meta.appendChild(buildRetrievalInsight(message));
  }
  if (!meta.childElementCount) meta.remove();

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

function buildRetrievalInsight(message) {
  const wrap = document.createElement("details");
  wrap.className = "retrieval-insight";
  const summary = document.createElement("summary");
  summary.textContent = "How this answer was retrieved";
  const list = document.createElement("ul");
  for (const trace of message.agentTrace) {
    if (!trace?.agent || !trace?.action) continue;
    const li = document.createElement("li");
    const label = `${trace.agent} · ${trace.action}`;
    li.innerHTML = `<strong>${escapeHtml(label)}</strong>`;
    if (trace.notes) {
      const notes = document.createElement("span");
      notes.textContent = trace.notes;
      li.appendChild(notes);
    }
    if (trace.agent === "knowledge_graph" || trace.agent === "planner") {
      li.classList.add("trace-highlight");
    }
    list.appendChild(li);
  }
  if (message.route) {
    const routeLi = document.createElement("li");
    routeLi.innerHTML = `<strong>route</strong> <span>${escapeHtml(message.route)} (${escapeHtml(message.difficulty || "easy")})</span>`;
    list.prepend(routeLi);
  }
  wrap.appendChild(summary);
  wrap.appendChild(list);
  return wrap;
}

function prefillWikiPrompt(page) {
  state.pendingWikiContextSlug = page.slug;
  const label = page.title || page.slug;
  const prompt = `Summarize "${label}" and Summarize what it is useful for.`;
  els.messageInput.value = prompt;
  resizeTextarea();
  els.messageInput.focus();
  state.openWikiMenuSlug = null;
  renderWikiPages();
  toast(`Wiki context set: ${label}`);
}

async function openWikiInsight(slug) {
  state.wikiInsightSlug = slug;
  els.wikiInsightModal.hidden = false;
  els.wikiInsightBody.innerHTML = `<p class="empty-mini">Loading…</p>`;
  try {
    const page = await apiFetch(`${API.wikiPages}/${slug}`);
    renderWikiInsight(page);
  } catch (error) {
    els.wikiInsightBody.innerHTML = `<p class="inline-error">${escapeHtml(error.message)}</p>`;
  }
}

function closeWikiInsight() {
  els.wikiInsightModal.hidden = true;
  state.wikiInsightSlug = null;
}

function renderWikiInsight(page) {
  const meta = page.meta || {};
  els.wikiInsightTitle.textContent = meta.title || page.slug;
  const entities = meta.entities || [];
  const related = meta.related_slugs || [];
  const entityHtml = entities.length
    ? entities.map((e) => `<span class="entity-chip">${escapeHtml(e)}</span>`).join("")
    : `<span class="muted-text">No entities indexed yet.</span>`;
  const relatedHtml = related.length
    ? related
        .map((relSlug) => {
          const match = state.wikiPages.find((p) => p.slug === relSlug);
          const label = match?.title || relSlug;
          return `<button type="button" class="related-link" data-slug="${escapeHtml(relSlug)}">${escapeHtml(label)}</button>`;
        })
        .join("")
    : `<span class="muted-text">No linked pages yet.</span>`;

  els.wikiInsightBody.innerHTML = `
    <p class="wiki-insight-summary">${escapeHtml(meta.summary || "")}</p>
    <div class="wiki-insight-section">
      <h3>Knowledge graph</h3>
      <div class="entity-chip-row">${entityHtml}</div>
    </div>
    <div class="wiki-insight-section">
      <h3>Related pages</h3>
      <div class="related-link-row">${relatedHtml}</div>
    </div>
    <div class="wiki-insight-actions">
      <button type="button" class="secondary-button" id="wikiInsightAskBtn">Ask about this page</button>
    </div>
  `;
  els.wikiInsightBody.querySelectorAll(".related-link").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-slug");
      if (target) openWikiInsight(target);
    });
  });
  els.wikiInsightBody.querySelector("#wikiInsightAskBtn")?.addEventListener("click", () => {
    closeWikiInsight();
    prefillWikiPrompt({ slug: meta.slug, title: meta.title });
  });
}

async function loadConflicts() {
  try {
    state.contradictions = await apiFetch(`${API.contradictions}?open_only=true`);
  } catch {
    state.contradictions = [];
  }
  renderConflicts();
  renderWikiPages();
}

function renderConflicts() {
  if (!els.conflictsList) return;
  els.conflictsList.innerHTML = "";
  els.emptyConflicts.hidden = state.contradictions.length > 0;
  for (const item of state.contradictions) {
    const card = document.createElement("article");
    card.className = `conflict-card severity-${item.severity}`;
    card.innerHTML = `
      <div class="conflict-head">
        <span class="severity-pill">${escapeHtml(item.severity)}</span>
        <strong>${escapeHtml(item.topic)}</strong>
      </div>
      <p class="conflict-pages">${escapeHtml(item.title_a || item.slug_a)} ↔ ${escapeHtml(item.title_b || item.slug_b)}</p>
      <div class="conflict-claims">
        <p><span>A</span> ${escapeHtml(item.claim_a)}</p>
        <p><span>B</span> ${escapeHtml(item.claim_b)}</p>
      </div>
      ${item.rationale ? `<p class="conflict-rationale">${escapeHtml(item.rationale)}</p>` : ""}
      <div class="conflict-actions">
        <button type="button" class="text-button conflict-open-a" data-slug="${escapeHtml(item.slug_a)}">Open A</button>
        <button type="button" class="text-button conflict-open-b" data-slug="${escapeHtml(item.slug_b)}">Open B</button>
        <button type="button" class="text-button conflict-dismiss" data-id="${escapeHtml(item.id)}">Dismiss</button>
      </div>
    `;
    card.querySelector(".conflict-open-a")?.addEventListener("click", () => openWikiInsight(item.slug_a));
    card.querySelector(".conflict-open-b")?.addEventListener("click", () => openWikiInsight(item.slug_b));
    card.querySelector(".conflict-dismiss")?.addEventListener("click", () => dismissConflict(item.id));
    els.conflictsList.appendChild(card);
  }
}

async function scanConflicts() {
  if (state.scanningConflicts) return;
  state.scanningConflicts = true;
  setButtonLoading(els.scanConflictsBtn, true, "…");
  try {
    const response = await apiFetch(`${API.contradictions}/scan`, {
      method: "POST",
      timeout: 300000,
    });
    state.contradictions = response.contradictions || [];
    renderConflicts();
    renderWikiPages();
    toast(
      `Scanned ${response.scanned_pairs} pair(s). ${response.new_conflicts} new, ${response.open_conflicts} open.`,
    );
  } catch (error) {
    toast(error.message, "error");
  } finally {
    state.scanningConflicts = false;
    setButtonLoading(els.scanConflictsBtn, false);
  }
}

async function dismissConflict(id) {
  try {
    await apiFetch(`${API.contradictions}/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "dismissed" }),
    });
    state.contradictions = state.contradictions.filter((item) => item.id !== id);
    renderConflicts();
    renderWikiPages();
    toast("Conflict dismissed.");
  } catch (error) {
    toast(error.message, "error");
  }
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
    renderWikiPageSelectionForTemplate();
  } catch (error) {
    state.wikiPages = [];
    renderWikiPages();
    renderWikiPageSelectionForTemplate();
    els.emptyWiki.hidden = false;
    els.emptyWiki.textContent = error.message;
  }
}

function renderWikiPageSelectionForTemplate() {
  const container = document.getElementById("rtPageScopeList");
  if (!container) return;
  container.innerHTML = "";
  if (!state.wikiPages || !state.wikiPages.length) {
    container.innerHTML = `<span class="muted" style="font-size:12px; font-style:italic;">No wiki pages available in this workspace.</span>`;
    return;
  }
  for (const page of state.wikiPages) {
    const item = document.createElement("label");
    item.className = "rt-page-scope-item";
    item.innerHTML = `
      <input type="checkbox" name="rtScopeSlug" value="${escapeHtml(page.slug)}" />
      <span>${escapeHtml(page.title || page.slug)}</span>
    `;
    container.appendChild(item);
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
            <div class="wiki-badges">
              ${page.related_count ? `<span class="wiki-badge" title="Related pages">${page.related_count} linked</span>` : ""}
              ${page.entity_count ? `<span class="wiki-badge muted" title="Entities">${page.entity_count} entities</span>` : ""}
              ${page.open_conflict_count ? `<span class="wiki-badge warn" title="Open conflicts">${page.open_conflict_count} conflict${page.open_conflict_count === 1 ? "" : "s"}</span>` : ""}
            </div>
            <span>${escapeHtml(page.summary || page.slug)}</span>
          </div>
          <div class="session-actions">
            <button type="button" class="icon-button wiki-menu-btn" title="Wiki page actions">⋮</button>
          </div>
        </div>
        <div class="session-menu ${state.openWikiMenuSlug === page.slug ? "visible" : ""}">
          <button type="button" class="session-action details">Details</button>
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
      item.querySelector(".session-action.details").addEventListener("click", (event) => {
        event.stopPropagation();
        state.openWikiMenuSlug = null;
        openWikiInsight(page.slug);
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
    await loadConflicts();
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
      await Promise.all([loadWikiPages(), loadSessions(), loadConflicts()]);
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
  els.refreshWikiBtn.addEventListener("click", async () => {
    await loadWikiPages();
    await loadConflicts();
  });
  els.scanConflictsBtn?.addEventListener("click", scanConflicts);
  els.wikiInsightCloseBtn?.addEventListener("click", closeWikiInsight);
  els.wikiInsightModal?.addEventListener("click", (event) => {
    if (event.target === els.wikiInsightModal) closeWikiInsight();
  });
  els.refreshSessionsBtn.addEventListener("click", loadSessions);
  els.newChatBtn.addEventListener("click", () => {
    state.currentSessionId = null;
    state.pendingWikiContextSlug = null;
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
    if (event.key !== "Escape") return;
    if (!els.wikiInsightModal.hidden) closeWikiInsight();
    if (!els.llmModal.hidden) closeLlmModal();
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

// Hydrate auth synchronously to completely eliminate split-second login page flashes
loadAuth();
if (state.token) {
  showApp(true);
} else {
  showApp(false);
}
bootstrapAuth();

// =============================================================================
// TIER 2 — Workspace Switcher
// =============================================================================
const API_WORKSPACES = "/api/v1/workspaces";
const API_PROMOTIONS = "/api/v1/promotions";
const API_REPORTS = "/api/v1/reports";

let tier2State = {
  workspaces: [],
  activeWorkspaceId: null,
  wsDropdownOpen: false,
  // Versions
  versionsSlug: null,
  versionsList: [],
  diffFromVersion: null,
  // Save to wiki
  pendingSaveContent: null,
  // Reports
  reportTemplates: [],
  reportJobs: [],
  activeReportTab: "templates",
  editingTemplateId: null,
};

function bindTier2Events() {
  // Workspace switcher
  const switcher = document.getElementById("workspaceSwitcher");
  const dropdown = document.getElementById("workspaceDropdown");
  if (switcher) {
    switcher.addEventListener("click", (e) => {
      e.stopPropagation();
      tier2State.wsDropdownOpen = !tier2State.wsDropdownOpen;
      dropdown.hidden = !tier2State.wsDropdownOpen;
    });
  }
  document.getElementById("newWorkspaceBtn")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    const name = prompt("New workspace name:");
    if (!name?.trim()) return;
    try {
      const newWs = await apiFetch(API_WORKSPACES, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() }),
      });
      await loadWorkspaces();
      toast("Workspace created.");
      
      // Auto-switch to the new workspace
      if (newWs && newWs.id) {
        await apiFetch(`${API_WORKSPACES}/switch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ workspace_id: newWs.id }),
        });
        tier2State.activeWorkspaceId = newWs.id;
        renderWorkspaceSwitcher();
        
        // Clear active session
        state.currentSessionId = null;
        state.messages = [];
        localStorage.removeItem(ACTIVE_SESSION_KEY);
        renderChat();
        
        await Promise.all([loadWikiPages(), loadConflicts(), loadSessions()]);
        toast(`Switched to "${newWs.name}".`);
      }
    } catch (err) { toast(err.message, "error"); }
  });

  // Reports button
  document.getElementById("reportsBtn")?.addEventListener("click", () => openReportsModal());

  // Versions modal
  document.getElementById("versionsCloseBtn")?.addEventListener("click", () => {
    document.getElementById("versionsModal").hidden = true;
  });
  document.getElementById("versionsModal")?.addEventListener("click", (e) => {
    if (e.target === document.getElementById("versionsModal"))
      document.getElementById("versionsModal").hidden = true;
  });
  document.getElementById("diffBackBtn")?.addEventListener("click", () => {
    document.getElementById("versionsList").hidden = false;
    document.getElementById("versionsDiff").hidden = true;
  });

  // Save to wiki modal
  document.getElementById("saveWikiCloseBtn")?.addEventListener("click", () => {
    document.getElementById("saveWikiModal").hidden = true;
  });
  document.getElementById("saveWikiModal")?.addEventListener("click", (e) => {
    if (e.target === document.getElementById("saveWikiModal"))
      document.getElementById("saveWikiModal").hidden = true;
  });
  document.getElementById("saveWikiSubmitBtn")?.addEventListener("click", submitPromotion);

  // Reports modal
  document.getElementById("reportsCloseBtn")?.addEventListener("click", closeReportsModal);
  document.getElementById("reportsModal")?.addEventListener("click", (e) => {
    if (e.target === document.getElementById("reportsModal"))
      closeReportsModal();
  });
  document.getElementById("reportTabTemplates")?.addEventListener("click", () => switchReportTab("templates"));
  document.getElementById("reportTabGenerate")?.addEventListener("click", () => switchReportTab("generate"));
  document.getElementById("reportTabJobs")?.addEventListener("click", () => switchReportTab("jobs"));
  document.getElementById("rtAddCol")?.addEventListener("click", addColumnRow);
  document.getElementById("rtSave")?.addEventListener("click", saveReportTemplate);
  document.getElementById("rtCancelEdit")?.addEventListener("click", cancelEditTemplate);
  document.getElementById("genRunBtn")?.addEventListener("click", runReportGeneration);
  document.getElementById("refreshJobsBtn")?.addEventListener("click", () => loadReportJobs());

  // Global close dropdown
  window.addEventListener("click", () => {
    if (tier2State.wsDropdownOpen) {
      tier2State.wsDropdownOpen = false;
      if (dropdown) dropdown.hidden = true;
    }
  });

  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    document.getElementById("versionsModal").hidden = true;
    document.getElementById("saveWikiModal").hidden = true;
    document.getElementById("deleteWsModal").hidden = true;
    closeReportsModal();
  });

  // Delete Workspace modal
  document.getElementById("deleteWsCloseBtn")?.addEventListener("click", closeDeleteWsModal);
  document.getElementById("deleteWsCancelBtn")?.addEventListener("click", closeDeleteWsModal);
  document.getElementById("deleteWsModal")?.addEventListener("click", (e) => {
    if (e.target === document.getElementById("deleteWsModal")) closeDeleteWsModal();
  });
  
  const deleteInput = document.getElementById("deleteWsInput");
  const deleteConfirmBtn = document.getElementById("deleteWsConfirmBtn");
  deleteInput?.addEventListener("input", () => {
    if (deleteConfirmBtn) {
      deleteConfirmBtn.disabled = deleteInput.value.trim().toLowerCase() !== "delete";
    }
  });
  deleteConfirmBtn?.addEventListener("click", confirmDeleteWorkspace);
}

async function loadWorkspaces() {
  try {
    const data = await apiFetch(API_WORKSPACES);
    tier2State.workspaces = data.workspaces || [];
    tier2State.activeWorkspaceId = data.active_workspace_id;
    renderWorkspaceSwitcher();
  } catch { /* silently ignore if workspaces not supported */ }
}

function renderWorkspaceSwitcher() {
  const nameEl = document.getElementById("activeWorkspaceName");
  const listEl = document.getElementById("workspaceList");
  if (!nameEl || !listEl) return;
  const active = tier2State.workspaces.find(w => w.id === tier2State.activeWorkspaceId);
  nameEl.textContent = active?.name || "Personal";
  listEl.innerHTML = "";
  for (const ws of tier2State.workspaces) {
    const item = document.createElement("div");
    item.className = `ws-item ${ws.id === tier2State.activeWorkspaceId ? "active" : ""}`;
    item.innerHTML = `
      <div class="ws-item-left">
        <span>⬡</span>
        <span>${escapeHtml(ws.name)}</span>
        ${ws.your_role ? `<small style="color:var(--muted)">${escapeHtml(ws.your_role)}</small>` : ""}
      </div>
      ${(tier2State.workspaces.length > 1 && (ws.your_role === 'owner' || ws.your_role === 'admin')) ? `
        <button class="ws-delete-btn" type="button" title="Delete workspace">🗑</button>
      ` : ''}
    `;

    item.addEventListener("click", async (e) => {
      if (e.target.classList.contains("ws-delete-btn")) {
        e.stopPropagation();
        openDeleteWsModal(ws);
        return;
      }
      e.stopPropagation();
      if (ws.id === tier2State.activeWorkspaceId) { document.getElementById("workspaceDropdown").hidden = true; return; }
      try {
        await apiFetch(`${API_WORKSPACES}/switch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ workspace_id: ws.id }),
        });
        tier2State.activeWorkspaceId = ws.id;
        document.getElementById("workspaceDropdown").hidden = true;
        tier2State.wsDropdownOpen = false;
        renderWorkspaceSwitcher();
        
        // Clear active session
        state.currentSessionId = null;
        state.messages = [];
        localStorage.removeItem(ACTIVE_SESSION_KEY);
        renderChat();

        await Promise.all([loadWikiPages(), loadConflicts(), loadSessions()]);
        toast(`Switched to "${ws.name}".`);
      } catch (err) { toast(err.message, "error"); }
    });
    listEl.appendChild(item);
  }
}

let deletingWorkspaceId = null;

function openDeleteWsModal(ws) {
  deletingWorkspaceId = ws.id;
  const nameEl = document.getElementById("deleteWsNameText");
  if (nameEl) nameEl.textContent = ws.name;
  const inputEl = document.getElementById("deleteWsInput");
  if (inputEl) inputEl.value = "";
  const confirmBtn = document.getElementById("deleteWsConfirmBtn");
  if (confirmBtn) confirmBtn.disabled = true;
  const errEl = document.getElementById("deleteWsError");
  if (errEl) errEl.hidden = true;
  const modal = document.getElementById("deleteWsModal");
  if (modal) modal.hidden = false;
  
  // Hide dropdown
  document.getElementById("workspaceDropdown").hidden = true;
  tier2State.wsDropdownOpen = false;
}

function closeDeleteWsModal() {
  deletingWorkspaceId = null;
  const modal = document.getElementById("deleteWsModal");
  if (modal) modal.hidden = true;
}

async function confirmDeleteWorkspace() {
  if (!deletingWorkspaceId) return;
  const inputVal = document.getElementById("deleteWsInput").value.trim().toLowerCase();
  if (inputVal !== "delete") return;

  const btn = document.getElementById("deleteWsConfirmBtn");
  const errEl = document.getElementById("deleteWsError");
  if (errEl) errEl.hidden = true;
  setButtonLoading(btn, true, "Deleting…");

  try {
    await apiFetch(`${API_WORKSPACES}/${deletingWorkspaceId}`, { method: "DELETE" });
    toast("Workspace deleted successfully.");
    closeDeleteWsModal();
    
    // Switch to topmost/first remaining workspace
    await loadWorkspaces();

    // Clear active session and refresh
    state.currentSessionId = null;
    state.messages = [];
    localStorage.removeItem(ACTIVE_SESSION_KEY);
    renderChat();

    await Promise.all([loadWikiPages(), loadConflicts(), loadSessions()]);
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message;
      errEl.hidden = false;
    }
  } finally {
    setButtonLoading(btn, false);
  }
}

// =============================================================================
// TIER 2 — Versions Modal
// =============================================================================
async function openVersionsModal(slug) {
  tier2State.versionsSlug = slug;
  document.getElementById("versionsTitle").textContent = `Version History — ${slug}`;
  document.getElementById("versionsList").hidden = false;
  document.getElementById("versionsDiff").hidden = true;
  document.getElementById("versionsModal").hidden = false;
  document.getElementById("versionsList").innerHTML = `<p class="empty-mini">Loading…</p>`;
  try {
    const versions = await apiFetch(`/api/v1/wiki/pages/${encodeURIComponent(slug)}/versions`);
    tier2State.versionsList = versions;
    renderVersionsList(versions, slug);
  } catch (err) {
    document.getElementById("versionsList").innerHTML = `<p class="inline-error">${escapeHtml(err.message)}</p>`;
  }
}

function renderVersionsList(versions, slug) {
  const el = document.getElementById("versionsList");
  if (!versions.length) { el.innerHTML = `<p class="empty-mini">No versions recorded yet.</p>`; return; }
  el.innerHTML = "";
  for (const v of versions) {
    const row = document.createElement("div");
    row.className = "version-row";
    const ts = v.created_at ? new Date(v.created_at).toLocaleString() : "";
    row.innerHTML = `
      <span class="version-badge">v${v.version_number}</span>
      <div class="version-meta">
        <strong>${escapeHtml(v.created_reason)}</strong>
        <span>${escapeHtml(v.created_by_name || "system")} · ${ts}</span>
      </div>
      <div class="version-actions">
        ${v.version_number > 1 ? `<button class="text-button diff-btn" data-v="${v.version_number}">Diff ↔ prev</button>` : ""}
      </div>
    `;
    row.querySelector(".diff-btn")?.addEventListener("click", () =>
      loadDiff(slug, v.version_number - 1, v.version_number)
    );
    el.appendChild(row);
  }
}

async function loadDiff(slug, fromV, toV) {
  document.getElementById("versionsList").hidden = true;
  document.getElementById("versionsDiff").hidden = false;
  document.getElementById("diffLabel").textContent = `v${fromV} → v${toV}`;
  document.getElementById("diffSemantic").innerHTML = `<p class="empty-mini">Computing semantic diff…</p>`;
  document.getElementById("diffHunks").innerHTML = "";
  try {
    const diff = await apiFetch(`/api/v1/wiki/pages/${encodeURIComponent(slug)}/diff?from=${fromV}&to=${toV}`);
    const riskClass = diff.risk_level === "high" ? "diff-risk-high" : diff.risk_level === "medium" ? "diff-risk-medium" : "";
    const semantic = document.getElementById("diffSemantic");
    semantic.className = `diff-semantic ${riskClass}`;
    let semHtml = `<strong>Risk: ${escapeHtml(diff.risk_level?.toUpperCase() || "LOW")}</strong><br>${escapeHtml(diff.semantic_summary || "No semantic summary available.")}`;
    if (diff.changed_facts?.length) {
      semHtml += `<ul>${diff.changed_facts.map(f => `<li>${escapeHtml(f)}</li>`).join("")}</ul>`;
    }
    semantic.innerHTML = semHtml;

    const hunksEl = document.getElementById("diffHunks");
    hunksEl.innerHTML = "";
    for (const hunk of diff.line_hunks || []) {
      if (hunk.kind === "equal") continue; // skip unchanged lines in hunk view
      const block = document.createElement("div");
      block.className = `diff-hunk-${hunk.kind}`;
      if (hunk.kind === "delete" || hunk.kind === "replace") {
        for (const line of hunk.old_lines || []) {
          const l = document.createElement("div");
          l.className = "diff-hunk-delete";
          l.textContent = `- ${line}`;
          block.appendChild(l);
        }
      }
      if (hunk.kind === "insert" || hunk.kind === "replace") {
        for (const line of hunk.new_lines || []) {
          const l = document.createElement("div");
          l.className = "diff-hunk-insert";
          l.textContent = `+ ${line}`;
          block.appendChild(l);
        }
      }
      hunksEl.appendChild(block);
    }
  } catch (err) {
    document.getElementById("diffSemantic").innerHTML = `<p class="inline-error">${escapeHtml(err.message)}</p>`;
  }
}

// Make "Versions" appear in the wiki page menu
const _origRenderWikiPages = typeof renderWikiPages === "function" ? renderWikiPages : null;
// Patch the wiki page menu to add "Versions" action after DOM builds

// =============================================================================
// TIER 2 — Save to Wiki (Promotion)
// =============================================================================
function openSaveToWikiModal(content) {
  tier2State.pendingSaveContent = content;
  document.getElementById("saveWikiTitleInput").value = "";
  document.getElementById("saveWikiTagsInput").value = "";
  document.getElementById("saveWikiTargetInput").value = "";
  document.getElementById("saveWikiStatus").hidden = true;
  document.getElementById("saveWikiModal").hidden = false;
}

async function submitPromotion() {
  const title = document.getElementById("saveWikiTitleInput").value.trim();
  const tagsRaw = document.getElementById("saveWikiTagsInput").value.trim();
  const target = document.getElementById("saveWikiTargetInput").value.trim();
  const statusEl = document.getElementById("saveWikiStatus");
  if (!title) { statusEl.textContent = "Page title is required."; statusEl.hidden = false; return; }
  const tags = tagsRaw ? tagsRaw.split(",").map(t => t.trim()).filter(Boolean) : [];
  try {
    await apiFetch(API_PROMOTIONS, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        proposed_title: title,
        proposed_content: tier2State.pendingSaveContent || "",
        proposed_tags: tags,
        target_page_slug: target || null,
      }),
    });
    document.getElementById("saveWikiModal").hidden = true;
    toast("Submitted for review. An admin will approve it.");
  } catch (err) {
    statusEl.textContent = err.message;
    statusEl.hidden = false;
  }
}

// Wire "Save to Wiki" on assistant messages
function wireMessageSaveBtn(articleEl, message) {
  if (message.role !== "assistant") return;
  const btn = articleEl.querySelector(".save-wiki-btn");
  if (!btn) return;
  btn.hidden = false;
  btn.addEventListener("click", () => openSaveToWikiModal(message.content));
}

// =============================================================================
// TIER 2 — Reports Modal (fully working)
// =============================================================================

let reportPollTimer = null;  // interval handle for auto-refresh

function openReportsModal() {
  document.getElementById("reportsModal").hidden = false;
  switchReportTab("templates");
  loadReportTemplates();
  renderWikiPageSelectionForTemplate();
}

function closeReportsModal() {
  document.getElementById("reportsModal").hidden = true;
  // Stop polling when modal is closed
  if (reportPollTimer) { clearInterval(reportPollTimer); reportPollTimer = null; }
}

function switchReportTab(tab) {
  tier2State.activeReportTab = tab;
  ["templates", "generate", "jobs"].forEach(t => {
    const btn = document.getElementById(`reportTab${t.charAt(0).toUpperCase() + t.slice(1)}`);
    const panel = document.getElementById(`reportPanel${t.charAt(0).toUpperCase() + t.slice(1)}`);
    if (btn) btn.classList.toggle("active", t === tab);
    if (panel) panel.hidden = t !== tab;
  });
  if (tab === "generate") {
    loadReportTemplatesIntoSelect();
    // Reset generate UI
    const statusEl = document.getElementById("genStatus");
    if (statusEl) statusEl.hidden = true;
    const genBtn = document.getElementById("genRunBtn");
    if (genBtn) { genBtn.disabled = false; genBtn.textContent = "Generate Report"; }
  }
  if (tab === "jobs") {
    loadReportJobs();
    // Start polling every 4s while on jobs tab
    if (reportPollTimer) clearInterval(reportPollTimer);
    reportPollTimer = setInterval(() => {
      if (tier2State.activeReportTab === "jobs" && !document.getElementById("reportsModal").hidden) {
        loadReportJobs(true);  // silent refresh
      } else {
        clearInterval(reportPollTimer);
        reportPollTimer = null;
      }
    }, 4000);
  } else {
    if (reportPollTimer) { clearInterval(reportPollTimer); reportPollTimer = null; }
  }
}

// ---------- Templates ----------

async function loadReportTemplates() {
  const el = document.getElementById("reportTemplateList");
  if (!el) return;
  try {
    const templates = await apiFetch(`${API_REPORTS}/templates`);
    tier2State.reportTemplates = templates;
    renderReportTemplates(templates);
  } catch (err) {
    el.innerHTML = `<p class="inline-error">Failed to load templates: ${escapeHtml(err.message)}</p>`;
  }
}

function renderReportTemplates(templates) {
  const el = document.getElementById("reportTemplateList");
  if (!el) return;
  if (!templates.length) {
    el.innerHTML = `<p class="empty-mini">No templates yet — create one below ↓</p>`;
    return;
  }
  el.innerHTML = "";
  for (const t of templates) {
    const row = document.createElement("div");
    row.className = "report-template-row";
    const colNames = (t.columns || []).map(c => c.label).join(", ") || "—";
    row.innerHTML = `
      <div class="rt-info">
        <strong>${escapeHtml(t.name)}</strong>
        <span class="rt-cols-preview" title="${escapeHtml(colNames)}">${t.columns?.length || 0} column${t.columns?.length !== 1 ? "s" : ""}: ${escapeHtml(colNames.slice(0, 60))}${colNames.length > 60 ? "…" : ""}</span>
        ${t.description ? `<span class="rt-desc">${escapeHtml(t.description)}</span>` : ""}
      </div>
      <div class="rt-actions">
        <button class="secondary-button rt-edit-btn" type="button">Edit ✎</button>
        <button class="secondary-button rt-use-btn" data-id="${escapeHtml(t.id)}" data-name="${escapeHtml(t.name)}" type="button">Use →</button>
        <button class="icon-button rt-del-btn" data-id="${escapeHtml(t.id)}" data-name="${escapeHtml(t.name)}" type="button" title="Delete template">🗑</button>
      </div>
    `;
    row.querySelector(".rt-edit-btn").addEventListener("click", () => {
      startEditTemplate(t);
    });
    row.querySelector(".rt-use-btn").addEventListener("click", () => {
      switchReportTab("generate");
      const sel = document.getElementById("genTemplateSelect");
      if (sel) sel.value = t.id;
    });
    row.querySelector(".rt-del-btn").addEventListener("click", async () => {
      if (!confirm(`Delete template "${t.name}"? This cannot be undone.`)) return;
      try {
        await apiFetch(`${API_REPORTS}/templates/${t.id}`, { method: "DELETE" });
        toast("Template deleted.");
        await loadReportTemplates();
      } catch (err) { toast(err.message, "error"); }
    });
    el.appendChild(row);
  }
}

function addColumnRow() {
  const container = document.getElementById("rtColumns");
  const row = document.createElement("div");
  row.className = "rt-col-row";
  row.innerHTML = `
    <input class="rt-col-key" type="text" placeholder="key (e.g. salary)" title="Unique identifier, no spaces" />
    <input class="rt-col-label" type="text" placeholder="Column label (e.g. Salary)" />
    <input class="rt-col-instr" type="text" placeholder="Instruction (e.g. Find the annual salary)" />
    <button class="rt-remove-col icon-button" type="button" title="Remove column">✕</button>
  `;
  row.querySelector(".rt-remove-col").addEventListener("click", () => {
    // Don't allow removing the last column
    const allRows = container.querySelectorAll(".rt-col-row");
    if (allRows.length <= 1) { toast("At least one column is required.", "error"); return; }
    row.remove();
  });
  container.appendChild(row);
}

async function saveReportTemplate() {
  const name = document.getElementById("rtName").value.trim();
  const desc = document.getElementById("rtDesc").value.trim();
  const errEl = document.getElementById("rtError");
  const btn = document.getElementById("rtSave");
  errEl.hidden = true;

  if (!name) { errEl.textContent = "Template name is required."; errEl.hidden = false; return; }

  // Read selected page scope checkboxes
  const selectedCheckboxes = document.querySelectorAll('input[name="rtScopeSlug"]:checked');
  const scope_slugs = Array.from(selectedCheckboxes).map(cb => cb.value);

  const colRows = document.querySelectorAll("#rtColumns .rt-col-row");
  const columns = [];
  let hasError = false;
  for (const row of colRows) {
    const key = row.querySelector(".rt-col-key").value.trim().replace(/\s+/g, "_").toLowerCase();
    const label = row.querySelector(".rt-col-label").value.trim();
    const instr = row.querySelector(".rt-col-instr").value.trim();
    if (!key || !label || !instr) {
      errEl.textContent = "All column fields (key, label, instruction) must be filled in.";
      errEl.hidden = false;
      hasError = true;
      break;
    }
    columns.push({ key, label, instruction: instr });
  }
  if (hasError || !columns.length) {
    if (!hasError) { errEl.textContent = "At least one column is required."; errEl.hidden = false; }
    return;
  }

  const isEditing = !!tier2State.editingTemplateId;
  const url = isEditing 
    ? `${API_REPORTS}/templates/${tier2State.editingTemplateId}`
    : `${API_REPORTS}/templates`;
  const method = isEditing ? "PUT" : "POST";

  setButtonLoading(btn, true, isEditing ? "Updating…" : "Saving…");
  try {
    await apiFetch(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description: desc, columns, scope_slugs }),
    });
    toast(isEditing ? `Template "${name}" updated!` : `Template "${name}" saved!`);
    await loadReportTemplates();
    
    // Clear and reset edit state
    tier2State.editingTemplateId = null;
    const summaryTitle = document.getElementById("rtSummaryTitle");
    if (summaryTitle) summaryTitle.textContent = "+ New Template";
    if (btn) btn.textContent = "Save Template";
    const cancelBtn = document.getElementById("rtCancelEdit");
    if (cancelBtn) cancelBtn.hidden = true;

    // Reset form
    document.getElementById("rtName").value = "";
    document.getElementById("rtDesc").value = "";
    resetColRows();
    // Clear page scope checkboxes
    document.querySelectorAll('input[name="rtScopeSlug"]').forEach(cb => cb.checked = false);
    // Close the details
    document.querySelector(".report-new-template")?.removeAttribute("open");
  } catch (err) {
    errEl.textContent = err.message;
    errEl.hidden = false;
  } finally {
    setButtonLoading(btn, false);
  }
}

function resetColRows() {
  const container = document.getElementById("rtColumns");
  if (!container) return;
  container.innerHTML = `<div class="rt-col-row">
    <input class="rt-col-key" type="text" placeholder="key (e.g. salary)" title="Unique identifier, no spaces" />
    <input class="rt-col-label" type="text" placeholder="Column label (e.g. Salary)" />
    <input class="rt-col-instr" type="text" placeholder="Instruction (e.g. Find the annual salary)" />
    <button class="rt-remove-col icon-button" type="button" title="Remove column">✕</button>
  </div>`;
  // Wire the first row remove btn
  container.querySelector(".rt-remove-col").addEventListener("click", () => {
    toast("At least one column is required.", "error");
  });
}

function startEditTemplate(t) {
  tier2State.editingTemplateId = t.id;
  
  // Update UI headers
  const summaryTitle = document.getElementById("rtSummaryTitle");
  if (summaryTitle) summaryTitle.textContent = `✎ Edit Template: ${t.name}`;
  
  const saveBtn = document.getElementById("rtSave");
  if (saveBtn) saveBtn.textContent = "Update Template";
  
  const cancelBtn = document.getElementById("rtCancelEdit");
  if (cancelBtn) cancelBtn.hidden = false;
  
  // Open details block if not already open
  const detailsEl = document.querySelector(".report-new-template");
  if (detailsEl) detailsEl.setAttribute("open", "");
  
  // Fill text fields
  document.getElementById("rtName").value = t.name || "";
  document.getElementById("rtDesc").value = t.description || "";
  
  // Fill page scope checkboxes
  const scopes = t.scope_slugs || [];
  document.querySelectorAll('input[name="rtScopeSlug"]').forEach(cb => {
    cb.checked = scopes.includes(cb.value);
  });
  
  // Populate columns
  const container = document.getElementById("rtColumns");
  if (container) {
    container.innerHTML = "";
    const columns = t.columns || [];
    if (columns.length === 0) {
      resetColRows();
    } else {
      for (const col of columns) {
        const row = document.createElement("div");
        row.className = "rt-col-row";
        row.innerHTML = `
          <input class="rt-col-key" type="text" placeholder="key (e.g. salary)" title="Unique identifier, no spaces" value="${escapeHtml(col.key)}" />
          <input class="rt-col-label" type="text" placeholder="Column label (e.g. Salary)" value="${escapeHtml(col.label)}" />
          <input class="rt-col-instr" type="text" placeholder="Instruction (e.g. Find the annual salary)" value="${escapeHtml(col.instruction)}" />
          <button class="rt-remove-col icon-button" type="button" title="Remove column">✕</button>
        `;
        row.querySelector(".rt-remove-col").addEventListener("click", () => {
          const allRows = container.querySelectorAll(".rt-col-row");
          if (allRows.length <= 1) { toast("At least one column is required.", "error"); return; }
          row.remove();
        });
        container.appendChild(row);
      }
    }
  }
}

function cancelEditTemplate() {
  tier2State.editingTemplateId = null;
  
  const summaryTitle = document.getElementById("rtSummaryTitle");
  if (summaryTitle) summaryTitle.textContent = "+ New Template";
  
  const saveBtn = document.getElementById("rtSave");
  if (saveBtn) saveBtn.textContent = "Save Template";
  
  const cancelBtn = document.getElementById("rtCancelEdit");
  if (cancelBtn) cancelBtn.hidden = true;
  
  // Reset fields
  document.getElementById("rtName").value = "";
  document.getElementById("rtDesc").value = "";
  document.querySelectorAll('input[name="rtScopeSlug"]').forEach(cb => cb.checked = false);
  resetColRows();
  
  // Close the details panel
  const detailsEl = document.querySelector(".report-new-template");
  if (detailsEl) detailsEl.removeAttribute("open");
}

// ---------- Generate ----------

function loadReportTemplatesIntoSelect() {
  const sel = document.getElementById("genTemplateSelect");
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = "";
  if (!tier2State.reportTemplates.length) {
    sel.innerHTML = `<option value="">— No templates yet, create one first —</option>`;
    return;
  }
  for (const t of tier2State.reportTemplates) {
    const opt = document.createElement("option");
    opt.value = t.id;
    opt.textContent = `${t.name} (${t.columns?.length || 0} cols)`;
    sel.appendChild(opt);
  }
  if (prev) sel.value = prev;
}

async function runReportGeneration() {
  const templateId = document.getElementById("genTemplateSelect").value;
  const exportFormat = document.getElementById("genFormatSelect").value;
  const statusEl = document.getElementById("genStatus");
  const genBtn = document.getElementById("genRunBtn");
  statusEl.hidden = true;

  if (!templateId) {
    statusEl.textContent = "Please select a template first.";
    statusEl.style.color = "var(--danger)";
    statusEl.hidden = false;
    return;
  }

  setButtonLoading(genBtn, true, "Starting…");
  try {
    const job = await apiFetch(`${API_REPORTS}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template_id: templateId, export_format: exportFormat }),
    });

    // Show success and switch to jobs tab immediately
    statusEl.textContent = `✓ Job started! ID: ${job.id.slice(0, 8)}… Switching to Jobs tab…`;
    statusEl.style.color = "var(--accent)";
    statusEl.hidden = false;

    // Track job ID for polling
    tier2State.activeJobId = job.id;

    setTimeout(() => {
      switchReportTab("jobs");
    }, 800);

  } catch (err) {
    statusEl.textContent = err.message;
    statusEl.style.color = "var(--danger)";
    statusEl.hidden = false;
  } finally {
    setButtonLoading(genBtn, false);
  }
}

// ---------- Jobs ----------

async function loadReportJobs(silent = false) {
  const el = document.getElementById("jobsList");
  if (!el) return;

  if (!silent) {
    el.innerHTML = `<div class="jobs-loading"><span class="spinner-sm"></span> Loading jobs…</div>`;
  }

  try {
    const jobs = await apiFetch(`${API_REPORTS}`);
    tier2State.reportJobs = jobs;
    renderJobsList(jobs);
  } catch (err) {
    if (!silent) {
      el.innerHTML = `<p class="inline-error">Failed to load jobs: ${escapeHtml(err.message)}</p>`;
    }
  }
}

function renderJobsList(jobs) {
  const el = document.getElementById("jobsList");
  if (!el) return;
  el.innerHTML = "";

  if (!jobs.length) {
    el.innerHTML = `<div class="jobs-empty">
      <div class="jobs-empty-icon">📋</div>
      <p>No report jobs yet.</p>
      <p style="color:var(--muted);font-size:12px">Go to the Generate tab to create your first report.</p>
    </div>`;
    return;
  }

  for (const job of jobs) {
    const row = document.createElement("div");
    row.className = "job-row";
    row.dataset.jobId = job.id;

    const ts = job.created_at ? new Date(job.created_at).toLocaleString() : "";
    const completedTs = job.completed_at ? new Date(job.completed_at).toLocaleString() : null;

    const statusConfig = {
      done:       { cls: "job-status-done",       icon: "✅", label: "Done" },
      failed:     { cls: "job-status-failed",      icon: "❌", label: "Failed" },
      processing: { cls: "job-status-processing",  icon: "⚙️", label: "Processing…" },
      pending:    { cls: "job-status-pending",      icon: "⏳", label: "Pending…" },
    };
    const sc = statusConfig[job.status] || { cls: "", icon: "❓", label: job.status };

    row.innerHTML = `
      <div class="job-info">
        <div class="job-header-row">
          <span class="job-status-badge ${sc.cls}">${sc.icon} ${sc.label}</span>
          <strong class="job-template-name">${escapeHtml(job.template_name || "Report")}</strong>
          <span class="job-format-badge">${escapeHtml(job.export_format?.toUpperCase() || "—")}</span>
        </div>
        <div class="job-meta">
          <span>ID: <code>${job.id.slice(0, 12)}…</code></span>
          <span>Started: ${ts}</span>
          ${completedTs ? `<span>Finished: ${completedTs}</span>` : ""}
        </div>
        ${job.error_message ? `<div class="job-error-msg">⚠ ${escapeHtml(job.error_message)}</div>` : ""}
      </div>
      <div class="job-actions">
        ${job.status === "done" ? `<button class="primary-button job-download-btn" data-id="${job.id}" data-fmt="${job.export_format}" type="button">⬇ Download</button>` : ""}
        ${(job.status === "processing" || job.status === "pending") ? `<button class="secondary-button job-poll-btn" data-id="${job.id}" type="button">↻ Check</button>` : ""}
      </div>
    `;

    row.querySelector(".job-download-btn")?.addEventListener("click", () => {
      downloadReportFile(job.id, job.export_format);
    });
    row.querySelector(".job-poll-btn")?.addEventListener("click", () => {
      pollSingleJob(job.id);
    });

    el.appendChild(row);
  }
}

async function pollSingleJob(jobId) {
  try {
    const job = await apiFetch(`${API_REPORTS}/${jobId}`);
    // Update this job in local state and re-render
    const idx = tier2State.reportJobs.findIndex(j => j.id === jobId);
    if (idx !== -1) tier2State.reportJobs[idx] = job;
    else tier2State.reportJobs.unshift(job);
    renderJobsList(tier2State.reportJobs);
  } catch (err) {
    toast(`Could not check job: ${err.message}`, "error");
  }
}

function downloadReportFile(jobId, format) {
  // Read token from the correct key
  let token = "";
  try { token = JSON.parse(localStorage.getItem("knowforge.auth.v1") || "{}").token || ""; } catch { }
  const url = `${API_REPORTS}/${jobId}/download`;
  fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    .then(res => {
      if (!res.ok) return res.json().then(d => { throw new Error(d.detail?.message || "Download failed"); });
      return res.blob();
    })
    .then(blob => {
      const ext = format || "bin";
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `report_${jobId.slice(0, 8)}.${ext}`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
      toast("Report downloaded!");
    })
    .catch(err => toast(err.message, "error"));
}


// =============================================================================
// Patch renderWikiPages to inject "Versions" menu item
// =============================================================================
const _origRenderWikiPagesPatched = renderWikiPages;
// Override by patching the wiki page click wiring after each render
const _originalWikiPagesRender = window.renderWikiPages;

// We inject Versions into the wiki page dropdown after it renders
document.addEventListener("click", (e) => {
  // If a "versions" action is clicked in the wiki menu
  if (e.target?.classList?.contains("action-versions")) {
    e.stopPropagation();
    const slug = e.target.dataset.slug;
    if (slug) openVersionsModal(slug);
  }
}, true);

// Patch renderWikiPages to include Versions in menu (monkey-patch by wrapping)
(function patchRenderWikiPages() {
  const origRender = window.renderWikiPages;
  if (!origRender) return;
  window.renderWikiPages = function () {
    origRender.apply(this, arguments);
    // Inject Versions button into each wiki session-menu
    document.querySelectorAll(".wiki-page-item .session-menu").forEach((menu) => {
      const parentItem = menu.closest(".wiki-page-item");
      const cardRow = parentItem?.querySelector(".wiki-card-row");
      if (!cardRow) return;
      // Read slug from the prefill click handler doesn't expose it easily
      // Instead, find the title and match
      const titleEl = cardRow.querySelector(".session-title");
      const pageTitle = titleEl?.textContent;
      const page = tier2State.workspaces.length
        ? null  // slug extraction from state
        : null;
      if (!menu.querySelector(".action-versions")) {
        // Find slug from state by title match
        const pageData = (window._state?.wikiPages || []).find(p => p.title === pageTitle);
        if (pageData?.slug) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "session-action action-versions";
          btn.dataset.slug = pageData.slug;
          btn.textContent = "Versions";
          menu.insertBefore(btn, menu.querySelector(".session-action.edit"));
        }
      }
    });
    // Wire Save-to-Wiki on assistant messages
    document.querySelectorAll(".message-card").forEach((card) => {
      const role = card.dataset.role;
      if (role !== "assistant") return;
      const btn = card.querySelector(".save-wiki-btn");
      if (btn && btn.hidden && !btn.dataset.wired) {
        btn.hidden = false;
        btn.dataset.wired = "1";
        const bodyEl = card.querySelector(".message-body");
        btn.addEventListener("click", () => openSaveToWikiModal(bodyEl?.textContent || ""));
      }
    });
  };
})();

// =============================================================================
// Boot Tier 2 after auth
// =============================================================================
const _origBootstrapAuth = bootstrapAuth;
async function bootstrapAuthTier2() {
  await _origBootstrapAuth();
  await loadWorkspaces();
}
// Re-wire save to wiki on every chat render
const _origRenderChat = window.renderChat;
if (_origRenderChat) {
  window.renderChat = function() {
    _origRenderChat.apply(this, arguments);
    // Wire save-to-wiki for newly rendered assistant messages
    document.querySelectorAll(".message-card[data-role='assistant']").forEach((card) => {
      const btn = card.querySelector(".save-wiki-btn");
      if (btn && !btn.dataset.wired) {
        btn.hidden = false;
        btn.dataset.wired = "1";
        const bodyEl = card.querySelector(".message-body");
        btn.addEventListener("click", () => openSaveToWikiModal(bodyEl?.textContent || ""));
      }
    });
  };
}

// Initialize Tier 2
bindTier2Events();
loadWorkspaces();
