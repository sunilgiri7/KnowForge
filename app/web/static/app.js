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
  timeline: "/api/v1/wiki/facts/timeline",
  health: "/api/v1/wiki/health",
  healthRecalculate: "/api/v1/wiki/health/recalculate",
  notifications: "/api/v1/notifications",
  digests: "/api/v1/digests",
  flashcards: "/api/v1/flashcards",
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
  timeline: { items: [], counts: {}, status: "all" },
  health: null,
  notifications: { items: [], unread_count: 0 },
  digest: null,
  flashcards: { due: [], stats: null, currentIndex: 0, showingAnswer: false },
  wikiView: "pages",
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
  reportModeActive: false,
  llmKeysConnected: false,
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
  chatReportModeBtn: document.querySelector("#chatReportModeBtn"),
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
  healthScoreValue: document.querySelector("#healthScoreValue"),
  healthTrendPill: document.querySelector("#healthTrendPill"),
  healthBreakdown: document.querySelector("#healthBreakdown"),
  healthActions: document.querySelector("#healthActions"),
  pulseExpiringCount: document.querySelector("#pulseExpiringCount"),
  pulseConflictCount: document.querySelector("#pulseConflictCount"),
  pulseDueCount: document.querySelector("#pulseDueCount"),
  pulseReviewBtn: document.querySelector("#pulseReviewBtn"),
  timelineList: document.querySelector("#timelineList"),
  emptyTimeline: document.querySelector("#emptyTimeline"),
  refreshTimelineBtn: document.querySelector("#refreshTimelineBtn"),
  notificationBellBtn: document.querySelector("#notificationBellBtn"),
  notificationBadge: document.querySelector("#notificationBadge"),
  notificationPopover: document.querySelector("#notificationPopover"),
  notificationList: document.querySelector("#notificationList"),
  emptyNotifications: document.querySelector("#emptyNotifications"),
  generateDigestBtn: document.querySelector("#generateDigestBtn"),
  digestModal: document.querySelector("#digestModal"),
  digestCloseBtn: document.querySelector("#digestCloseBtn"),
  digestBody: document.querySelector("#digestBody"),
  reviewFlashcardsBtn: document.querySelector("#reviewFlashcardsBtn"),
  flashcardDueBadge: document.querySelector("#flashcardDueBadge"),
  flashcardModal: document.querySelector("#flashcardModal"),
  flashcardCloseBtn: document.querySelector("#flashcardCloseBtn"),
  generateFlashcardsBtn: document.querySelector("#generateFlashcardsBtn"),
  flashcardStatsText: document.querySelector("#flashcardStatsText"),
  flashcardBody: document.querySelector("#flashcardBody"),
  markTimelineReadBtn: document.querySelector("#markTimelineReadBtn"),
  knowledgeHealthScoreMirror: document.querySelector("#knowledgeHealthScoreMirror"),
  knowledgeHealthTrendMirror: document.querySelector("#knowledgeHealthTrendMirror"),
  knowledgeInsightText: document.querySelector("#knowledgeInsightText"),
  knowledgeRiskCount: document.querySelector("#knowledgeRiskCount"),
  knowledgeConflictCount: document.querySelector("#knowledgeConflictCount"),
  knowledgeDueCount: document.querySelector("#knowledgeDueCount"),
  knowledgeHealthBreakdown: document.querySelector("#knowledgeHealthBreakdown"),
  knowledgeActionsList: document.querySelector("#knowledgeActionsList"),
  knowledgeDigestPreview: document.querySelector("#knowledgeDigestPreview"),
  knowledgeDigestBtn: document.querySelector("#knowledgeDigestBtn"),
  knowledgeOpenDigestBtn: document.querySelector("#knowledgeOpenDigestBtn"),
  knowledgeReviewBtn: document.querySelector("#knowledgeReviewBtn"),
  knowledgeDueCardBtn: document.querySelector("#knowledgeDueCardBtn"),
  knowledgeGenerateCardsBtn: document.querySelector("#knowledgeGenerateCardsBtn"),
  knowledgeStartReviewBtn: document.querySelector("#knowledgeStartReviewBtn"),
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
  llmApiKeyRow: document.querySelector("#llmApiKeyRow"),
  llmAccessKeyInput: document.querySelector("#llmAccessKeyInput"),
  llmAccessKeyRow: document.querySelector("#llmAccessKeyRow"),
  llmSecretKeyInput: document.querySelector("#llmSecretKeyInput"),
  llmSecretKeyRow: document.querySelector("#llmSecretKeyRow"),
  llmBedrockOptionalRow: document.querySelector("#llmBedrockOptionalRow"),
  llmBedrockRegionSelect: document.querySelector("#llmBedrockRegionSelect"),
  llmBedrockInfoNote: document.querySelector("#llmBedrockInfoNote"),
  llmModelOptionalNote: document.querySelector("#llmModelOptionalNote"),
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
  // AWS official smile logo (orange)
  bedrock: "https://cdn.simpleicons.org/amazonaws/FF9900",
};

const PROVIDER_KEY_PLACEHOLDERS = {
  openrouter: "Paste your OpenRouter key",
  openai: "Paste your OpenAI API key",
  anthropic: "Paste your Anthropic API key",
  gemini: "Paste your Gemini API key",
  bedrock: "AWS Access Key ID (AKIA...)",
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
  // Bedrock is dynamic — built per-region in buildBedrockModels()
  bedrock: [],
};

/** Returns 'us', 'eu', or 'ap' inference profile prefix for a given AWS region. */
function getBedrockRegionPrefix(region) {
  if (!region) return "ap";
  if (region.startsWith("eu-")) return "eu";
  if (region.startsWith("ap-")) return "ap";
  return "us"; // us-*, ca-*, sa-* all use US inference profiles
}

/**
 * Builds the Bedrock model dropdown for a given region.
 * Uses the correct inference profile prefix (us./eu./ap.) automatically.
 */
function buildBedrockModels(region) {
  const p = getBedrockRegionPrefix(region);
  const lbl = p.toUpperCase();

  // Direct model IDs first. These are simpler than inference profiles and
  // match the Bedrock model shape used elsewhere in the project.
  const direct = [
    { group: "Meta Llama (Direct)", id: "meta.llama3-70b-instruct-v1:0", label: "Llama 3 70B Instruct" },
    { group: "Meta Llama (Direct)", id: "meta.llama3-8b-instruct-v1:0", label: "Llama 3 8B Instruct" },
    { group: "Amazon Titan (Direct)", id: "amazon.titan-text-express-v1", label: "Titan Text Express" },
    { group: "Amazon Titan (Direct)", id: "amazon.titan-text-lite-v1", label: "Titan Text Lite" },
  ];

  // Cross-region inference profile models (region/account dependent)
  const crossRegion = [
    { group: `Anthropic Claude (${lbl} Profile)`, id: `${p}.anthropic.claude-3-5-sonnet-20241022-v2:0`, label: "Claude 3.5 Sonnet" },
    { group: `Anthropic Claude (${lbl} Profile)`, id: `${p}.anthropic.claude-3-5-haiku-20241022-v1:0`, label: "Claude 3.5 Haiku" },
    { group: `Anthropic Claude (${lbl} Profile)`, id: `${p}.anthropic.claude-3-opus-20240229-v1:0`,      label: "Claude 3 Opus" },
    { group: `Anthropic Claude (${lbl} Profile)`, id: `${p}.anthropic.claude-3-sonnet-20240229-v1:0`,    label: "Claude 3 Sonnet" },
    { group: `Meta Llama (${lbl} Profile)`,        id: `${p}.meta.llama3-1-70b-instruct-v1:0`,           label: "Llama 3.1 70B" },
    { group: `Meta Llama (${lbl} Profile)`,        id: `${p}.meta.llama3-1-8b-instruct-v1:0`,            label: "Llama 3.1 8B" },
  ];

  // US-only models (Nova, Llama 3.3/4, Mistral — not yet in EU/AP)
  const usOnly = p === "us" ? [
    { group: "Amazon Nova (US Profile)", id: "us.amazon.nova-pro-v1:0",                        label: "Nova Pro" },
    { group: "Amazon Nova (US Profile)", id: "us.amazon.nova-lite-v1:0",                       label: "Nova Lite" },
    { group: "Amazon Nova (US Profile)", id: "us.amazon.nova-micro-v1:0",                      label: "Nova Micro" },
    { group: "Meta Llama (US Profile)",  id: "us.meta.llama3-3-70b-instruct-v1:0",             label: "Llama 3.3 70B" },
    { group: "Meta Llama (US Profile)",  id: "us.meta.llama4-maverick-17b-instruct-v1:0",      label: "Llama 4 Maverick 17B" },
    { group: "Meta Llama (US Profile)",  id: "us.meta.llama4-scout-17b-instruct-v1:0",         label: "Llama 4 Scout 17B" },
    { group: "Mistral AI (US Profile)",  id: "us.mistral.mistral-large-2402-v1:0",             label: "Mistral Large" },
    { group: "Mistral AI (US Profile)",  id: "us.mistral.mixtral-8x7b-instruct-v0:1",          label: "Mixtral 8x7B" },
  ] : [];

  const custom = [
    { group: "Custom", id: "__custom__", label: "Custom model ID..." },
  ];

  return [...direct, ...crossRegion, ...usOnly, ...custom];
}

function updateProviderLogo() {
  const provider = els.llmProviderSelect.value;
  const src = PROVIDER_LOGOS[provider] || "";
  if (els.llmProviderLogo) {
    if (provider === "bedrock") {
      // Use inline SVG data URI for crisp AWS logo — avoids CORS/simpleicons caching issues
      els.llmProviderLogo.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23FF9900' d='M13.234 15.945L12 16.806l-1.234-.861V13.08l1.234-.86 1.234.86v2.865zM3.798 10.435l1.234.86v2.867l-1.234.86-1.234-.86v-2.867l1.234-.86zm0-4.435l1.234.86v2.866l-1.234.86-1.234-.86V6.86l1.234-.86zM12 0L1.386 6v12L12 24l10.614-6V6L12 0zm8.202 10.435l1.234.86v2.867l-1.234.86-1.234-.86v-2.867l1.234-.86zm-8.202 5.51l-1.234-.86V12.22L12 11.36l1.234.86v2.866L12 15.945zm1.234-8.36L12 8.445 10.766 7.584V4.72L12 3.86l1.234.86v2.865zM5.035 16.806l1.234-.861V13.08l-1.234-.86-1.233.86v2.865l1.233.861zm13.93 0l1.233-.861V13.08l-1.233-.86-1.234.86v2.865l1.234.861z'/%3E%3C/svg%3E";
      els.llmProviderLogo.alt = "AWS Bedrock logo";
    } else {
      els.llmProviderLogo.src = src;
      els.llmProviderLogo.alt = `${provider} logo`;
    }
  }
}

function updateApiKeyPlaceholder() {
  const provider = els.llmProviderSelect.value;
  const placeholder = PROVIDER_KEY_PLACEHOLDERS[provider] || "Paste your API key";
  if (els.llmApiKeyInput) els.llmApiKeyInput.placeholder = placeholder;
}

/** Toggle visibility of Bedrock-specific vs standard credential fields. */
function updateBedrockFieldVisibility() {
  const isBedrock = els.llmProviderSelect.value === "bedrock";
  // Standard API key row — hide for Bedrock
  if (els.llmApiKeyRow) els.llmApiKeyRow.hidden = isBedrock;
  // Bedrock-specific credential rows
  if (els.llmAccessKeyRow) els.llmAccessKeyRow.hidden = !isBedrock;
  if (els.llmSecretKeyRow) els.llmSecretKeyRow.hidden = !isBedrock;
  if (els.llmBedrockOptionalRow) els.llmBedrockOptionalRow.hidden = !isBedrock;
  if (els.llmBedrockInfoNote) els.llmBedrockInfoNote.hidden = !isBedrock;
  // Show the optional note on model label for bedrock
  if (els.llmModelOptionalNote) els.llmModelOptionalNote.hidden = !isBedrock;
}

function updateModelOptions({ provider, selectedModel }) {
  // For Bedrock: build model list dynamically based on the selected region
  const models = provider === "bedrock"
    ? buildBedrockModels(els.llmBedrockRegionSelect?.value || "us-east-1")
    : (PROVIDER_MODELS[provider] || []);
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

function updateServiceStatus(apiOk = true, errorMsg = "") {
  if (!els.networkState) return;
  els.networkState.classList.remove("text-danger");
  if (!apiOk) {
    els.networkState.textContent = errorMsg || "Offline / API Issue";
    els.networkState.classList.add("text-danger");
    return;
  }
  if (state.llmKeysConnected) {
    els.networkState.textContent = "Custom LLM Key Active";
  } else {
    els.networkState.textContent = "Default LLM Active";
  }
}



function setLlmUi({ connected, provider }) {
  els.llmError.hidden = true;
  els.llmError.textContent = "";
  els.llmDisconnectBtn.disabled = !connected;
  els.llmConnectBtn.disabled = connected;
  els.llmProviderSelect.disabled = connected;
  // Disable credential inputs based on provider type
  const isBedrock = provider === "bedrock";
  if (isBedrock) {
    if (els.llmAccessKeyInput) els.llmAccessKeyInput.disabled = connected;
    if (els.llmSecretKeyInput) els.llmSecretKeyInput.disabled = connected;
    if (els.llmBedrockRegionSelect) els.llmBedrockRegionSelect.disabled = connected;
  } else {
    els.llmApiKeyInput.disabled = connected;
  }
  els.llmSaveModelBtn.disabled = !connected;
  els.llmStatusPill.textContent = connected ? `Connected (${provider})` : "Not connected";
  els.llmStatusPill.classList.toggle("muted", !connected);
  els.llmStatusPill.classList.toggle("connected", !!connected);
  els.llmStatusPill.classList.toggle("disconnected", !connected);
  updateProviderLogo();
  updateApiKeyPlaceholder();
  updateBedrockFieldVisibility();
}


async function loadLlmStatus(options = {}) {
  const { preferActiveProvider = false } = options;
  try {
    const items = await apiFetch(API.llmKeys);
    
    // Highlight the settings button with green if any provider is connected, red if none.
    const anyConnected = Array.isArray(items) ? items.some((x) => x.connected) : false;
    state.llmKeysConnected = anyConnected;
    updateServiceStatus(true);
    
    if (els.llmSettingsBtn) {
      els.llmSettingsBtn.classList.toggle("llm-connected", anyConnected);
      els.llmSettingsBtn.classList.toggle("llm-disconnected", !anyConnected);
    }

    const active = Array.isArray(items) ? items.find((x) => x.active) : null;
    if ((preferActiveProvider && active?.provider) || (!state.llmProviderTouched && active?.provider)) {
      els.llmProviderSelect.value = active.provider;
    }
    const provider = els.llmProviderSelect.value;
    const current = Array.isArray(items) ? items.find((x) => x.provider === provider) : null;
    setLlmUi({ connected: !!current?.connected, provider });
    updateModelOptions({ provider, selectedModel: current?.model || "" });
  } catch (error) {
    state.llmKeysConnected = false;
    updateServiceStatus(true);
    if (els.llmSettingsBtn) {
      els.llmSettingsBtn.classList.remove("llm-connected");
      els.llmSettingsBtn.classList.add("llm-disconnected");
    }
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
    const headingHtml = `<p><strong>${renderInlineMarkdown(text)}</strong></p>`;
    if (lines.length > 1) {
      return headingHtml + renderMarkdown(lines.slice(1).join("\n"));
    }
    return headingHtml;
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
    updateServiceStatus(true);
    return body;
  } catch (error) {
    if (error.name === "AbortError") {
      updateServiceStatus(false, "Request timed out");
      throw new Error("Request timed out. The AI model or system took too long to respond. Please try again.");
    }
    updateServiceStatus(false, "API connection issue");
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
    loadTier4().catch((error) => console.warn("Tier 4 failed during bootstrap", error));
    
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

  const generateReport = !!state.reportModeActive;
  if (state.reportModeActive) {
    state.reportModeActive = false;
    updateReportModeUI();
  }

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
        generate_report: generateReport,
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
    const knowledgeBoard = document.querySelector("#knowledgeBoard");
    if (knowledgeBoard && !knowledgeBoard.hidden) {
      titleEl.textContent = "Knowledge Center";
    } else if (isEmpty) {
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

  node.querySelectorAll(".message-body a").forEach(link => {
    const href = link.getAttribute("href");
    if (href && href.includes("/reports/") && href.includes("/download")) {
      link.addEventListener("click", (e) => {
        e.preventDefault();
        const match = href.match(/\/reports\/([^/]+)\/download/);
        if (match) {
          const jobId = match[1];
          const urlParams = new URLSearchParams(href.split("?")[1] || "");
          const format = urlParams.get("format") || "xlsx";
          const token = state.token || "";
          fetch(`/api/v1/reports/${jobId}/download`, { headers: { Authorization: `Bearer ${token}` } })
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
      });
    }
  });

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
  document.querySelector('[data-tab="chats"]')?.click();
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


async function loadTier4() {
  const jobs = [loadHealth(), loadTimeline(), loadNotifications(), loadFlashcardStats()];
  const results = await Promise.allSettled(jobs);
  if (results.some((result) => result.status === "rejected")) {
    console.warn("Some Tier 4 widgets failed to load.", results);
  }
}

function setWikiView(view) {
  if (view === "timeline" || view === "conflicts") view = "risks";
  state.wikiView = view;
  document.querySelectorAll(".wiki-subtab").forEach((btn) => {
    const active = btn.dataset.wikiView === view;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".knowledge-view-panel").forEach((panel) => {
    panel.hidden = panel.dataset.wikiPanel !== view;
  });
}

async function loadHealth() {
  try {
    state.health = await apiFetch(API.health);
  } catch {
    state.health = null;
  }
  renderHealth();
}

function renderHealth() {
  if (!els.healthScoreValue) return;
  const health = state.health;
  const expiredSoon = (state.timeline.counts?.expired || 0) + (state.timeline.counts?.expiring || 0);
  const conflictCount = state.contradictions?.length || health?.counts?.open_conflicts || 0;
  const dueCount = state.flashcards.stats?.due_today || 0;

  if (els.pulseExpiringCount) els.pulseExpiringCount.textContent = String(expiredSoon);
  if (els.pulseConflictCount) els.pulseConflictCount.textContent = String(conflictCount);
  if (els.pulseDueCount) els.pulseDueCount.textContent = String(dueCount);
  if (els.knowledgeRiskCount) els.knowledgeRiskCount.textContent = String(expiredSoon);
  if (els.knowledgeConflictCount) els.knowledgeConflictCount.textContent = String(conflictCount);
  if (els.knowledgeDueCount) els.knowledgeDueCount.textContent = String(dueCount);

  if (!health) {
    els.healthScoreValue.textContent = "--";
    if (els.knowledgeHealthScoreMirror) els.knowledgeHealthScoreMirror.textContent = "--";
    if (els.knowledgeInsightText) els.knowledgeInsightText.textContent = "Health will appear after your workspace loads.";
    els.healthActions.innerHTML = `<button type="button" class="health-action-chip" data-kind="digest">Open digest</button>`;
    els.healthActions.querySelector("[data-kind='digest']")?.addEventListener("click", openDigest);
    renderKnowledgeBreakdown(null);
    renderKnowledgeActions([]);
    return;
  }

  els.healthScoreValue.textContent = String(health.overall_score);
  if (els.knowledgeHealthScoreMirror) els.knowledgeHealthScoreMirror.textContent = String(health.overall_score);
  const trendLabel = `${health.trend || "flat"}${health.trend_delta ? ` ${health.trend_delta > 0 ? "+" : ""}${health.trend_delta}` : ""}`;
  els.healthTrendPill.textContent = trendLabel;
  els.healthTrendPill.className = "status-pill";
  els.healthTrendPill.classList.add(health.trend === "down" ? "warn" : health.trend === "up" ? "success" : "muted");
  if (els.knowledgeHealthTrendMirror) els.knowledgeHealthTrendMirror.textContent = trendLabel;

  const actions = health.action_items || [];
  const insight = actions[0]?.label || (expiredSoon || conflictCount ? "Risks are waiting for review." : "Your workspace is steady today.");
  if (els.knowledgeInsightText) els.knowledgeInsightText.textContent = insight;

  const sidebarActions = actions.filter((item) => item.kind !== "freshness");
  els.healthActions.innerHTML = sidebarActions.length
    ? sidebarActions.slice(0, 2).map((item) => `<button type="button" class="health-action-chip" data-kind="${escapeHtml(item.kind)}">${escapeHtml(item.label)}</button>`).join("")
    : `<span class="sidebar-health-note">Workspace freshness is tracked in Health Breakdown.</span>`;
  els.healthActions.querySelectorAll(".health-action-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const kind = btn.dataset.kind;
      if (kind === "digest") openDigest();
      else setWikiView("risks");
    });
  });
  renderKnowledgeBreakdown(health);
  renderKnowledgeActions(actions);
}

function renderKnowledgeBreakdown(health) {
  if (!els.knowledgeHealthBreakdown) return;
  if (!health) {
    els.knowledgeHealthBreakdown.innerHTML = `<p class="empty-mini">No score yet.</p>`;
    return;
  }
  const rows = [
    ["Freshness", health.freshness_score],
    ["Accuracy", health.accuracy_score],
    ["Completeness", health.completeness_score],
    ["Currency", health.staleness_score],
    ["Integrity", health.integrity_score],
  ];
  els.knowledgeHealthBreakdown.innerHTML = rows.map(([label, score]) => `
    <div class="knowledge-breakdown-row"><span>${escapeHtml(label)}</span><div><i style="width:${score}%"></i></div><strong>${score}</strong></div>
  `).join("");
}

function renderKnowledgeActions(actions) {
  if (!els.knowledgeActionsList) return;
  const actionable = actions.filter((item) => item.kind !== "freshness");
  if (!actionable.length) {
    els.knowledgeActionsList.innerHTML = `<button class="digest-row" type="button" data-action="digest"><strong>Read today's digest</strong><span>Start with a calm daily summary.</span></button>`;
  } else {
    els.knowledgeActionsList.innerHTML = actionable.slice(0, 5).map((item) => `
      <button class="digest-row" type="button" data-action="${escapeHtml(item.kind)}"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.priority || "normal")}</span></button>
    `).join("");
  }
  els.knowledgeActionsList.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.action === "digest") openDigest();
      else setWikiView("risks");
    });
  });
}

async function loadTimeline(status = state.timeline.status || "all") {
  state.timeline.status = status;
  try {
    state.timeline = await apiFetch(`${API.timeline}?days_ahead=90&status=${encodeURIComponent(status)}`);
    state.timeline.status = status;
  } catch {
    state.timeline = { items: [], counts: {}, status };
  }
  renderTimeline();
  renderHealth();
}

function renderTimeline() {
  if (!els.timelineList) return;
  document.querySelectorAll(".timeline-filter").forEach((btn) => btn.classList.toggle("active", btn.dataset.status === state.timeline.status));
  els.timelineList.innerHTML = "";
  const items = state.timeline.items || [];
  els.emptyTimeline.hidden = items.length > 0;
  if (els.markTimelineReadBtn) {
    const hasUnreviewed = items.some((fact) => fact.status !== "reviewed");
    els.markTimelineReadBtn.disabled = !hasUnreviewed || state.timeline.status === "reviewed";
  }
  for (const fact of items) {
    const row = document.createElement("article");
    row.className = `timeline-card status-${fact.status}`;
    const dateText = fact.expiration_date ? new Date(fact.expiration_date).toLocaleDateString() : "No expiry";
    row.innerHTML = `
      <div class="timeline-card-head">
        <span class="timeline-status-dot"></span>
        <strong>${escapeHtml(fact.subject || "Fact")}</strong>
        <span class="timeline-date">${escapeHtml(dateText)}</span>
      </div>
      <p class="timeline-fact-line">${escapeHtml(fact.predicate || "relates to")} ${escapeHtml(fact.object_val || "")}</p>
      <p class="timeline-quote">${escapeHtml(fact.source_quote || fact.page_slug)}</p>
      <div class="timeline-actions">
        <button type="button" class="text-button timeline-open" data-slug="${escapeHtml(fact.page_slug)}">Go to Page</button>
        ${fact.status !== "reviewed" ? `<button type="button" class="text-button timeline-review" data-id="${escapeHtml(fact.id)}">Mark Reviewed</button>` : `<span class="wiki-badge">Reviewed</span>`}
      </div>
    `;
    row.querySelector(".timeline-open")?.addEventListener("click", () => openWikiInsight(fact.page_slug));
    row.querySelector(".timeline-review")?.addEventListener("click", () => markFactReviewed(fact.id));
    els.timelineList.appendChild(row);
  }
}

async function markVisibleTimelineReviewed() {
  const status = state.timeline.status || "all";
  if (status === "reviewed") {
    toast("These facts are already reviewed.");
    return;
  }
  setButtonLoading(els.markTimelineReadBtn, true, "Marking...");
  try {
    const result = await apiFetch("/api/v1/wiki/facts/review-bulk", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status,
        days_ahead: 90,
        review_note: `Bulk reviewed from ${status} timeline view`,
      }),
    });
    state.timeline = { ...result, status };
    renderTimeline();
    await loadHealth();
    toast(`Marked ${result.reviewed_count || 0} fact(s) as reviewed.`);
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setButtonLoading(els.markTimelineReadBtn, false);
  }
}

async function markFactReviewed(factId) {
  try {
    const result = await apiFetch(`/api/v1/wiki/facts/${factId}/review`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review_note: "Reviewed from timeline" }),
    });
    state.timeline = { ...result, status: state.timeline.status };
    renderTimeline();
    await loadHealth();
    toast("Fact marked reviewed.");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function loadNotifications() {
  try {
    state.notifications = await apiFetch(API.notifications);
  } catch {
    state.notifications = { items: [], unread_count: 0 };
  }
  renderNotifications();
}

function renderNotifications() {
  if (!els.notificationBadge) return;
  const unread = state.notifications.unread_count || 0;
  els.notificationBadge.hidden = unread === 0;
  els.notificationBadge.textContent = String(unread);
  els.notificationList.innerHTML = "";
  const items = state.notifications.items || [];
  els.emptyNotifications.hidden = items.length > 0;
  for (const item of items) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `notification-item ${item.read_at ? "read" : "unread"}`;
    row.innerHTML = `<strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.body || "")}</span>`;
    row.addEventListener("click", async () => {
      await markNotificationRead(item.id);
      if (item.target_type === "digest") await openDigest(item.target_id);
    });
    els.notificationList.appendChild(row);
  }
}

async function markNotificationRead(id) {
  try {
    await apiFetch(`${API.notifications}/${id}/read`, { method: "PATCH" });
    await loadNotifications();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function generateDigest() {
  setButtonLoading(els.generateDigestBtn, true, "…");
  try {
    state.digest = await apiFetch(`${API.digests}/generate`, { method: "POST", timeout: 90000 });
    renderDigest();
    els.digestModal.hidden = false;
    document.body.classList.add("modal-open");
    await loadNotifications();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setButtonLoading(els.generateDigestBtn, false);
  }
}

async function openDigest() {
  try {
    state.digest = await apiFetch(`${API.digests}/latest`);
    if (!state.digest) state.digest = await apiFetch(`${API.digests}/generate`, { method: "POST", timeout: 90000 });
    renderDigest();
    els.digestModal.hidden = false;
    document.body.classList.add("modal-open");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderDigest() {
  const content = state.digest?.content || {};
  const section = (title, rows, render) => `
    <section class="digest-section"><h3>${escapeHtml(title)}</h3>
      ${rows && rows.length ? rows.slice(0, 8).map(render).join("") : `<p class="empty-mini">Nothing here today.</p>`}
    </section>`;
  els.digestBody.innerHTML = `
    <div class="digest-insight">${escapeHtml(content.insight_of_the_day || "Your digest is ready.")}</div>
    ${section("Expiring Facts", content.expiring_facts || [], (f) => `<button class="digest-row" data-slug="${escapeHtml(f.page_slug || "")}"><strong>${escapeHtml(f.subject || "Fact")}</strong><span>${escapeHtml(f.object_val || f.predicate || "")}</span></button>`)}
    ${section("Conflicts", content.new_conflicts || [], (c) => `<button class="digest-row" data-slug="${escapeHtml(c.slug_a || "")}"><strong>${escapeHtml(c.topic || "Conflict")}</strong><span>${escapeHtml(c.severity || "medium")}</span></button>`)}
    ${section("Changed Pages", content.changed_pages || [], (p) => `<button class="digest-row" data-slug="${escapeHtml(p.slug || "")}"><strong>${escapeHtml(p.title || p.slug || "Page")}</strong><span>${escapeHtml(p.updated_at || "")}</span></button>`)}
    ${section("Suggested Re-reads", content.suggested_review_pages || [], (p) => `<button class="digest-row" data-slug="${escapeHtml(p.slug || "")}"><strong>${escapeHtml(p.title || p.slug || "Page")}</strong><span>${escapeHtml(p.reason || "")}</span></button>`)}
  `;
  els.digestBody.querySelectorAll(".digest-row").forEach((btn) => {
    btn.addEventListener("click", () => {
      const slug = btn.dataset.slug;
      if (slug) openWikiInsight(slug);
    });
  });
  renderKnowledgeDigestPreview();
}

function renderKnowledgeDigestPreview() {
  if (!els.knowledgeDigestPreview) return;
  const content = state.digest?.content;
  if (!content) {
    els.knowledgeDigestPreview.innerHTML = `<p class="empty-mini">Generate a digest to see the day’s priorities.</p>`;
    return;
  }
  const rows = [
    ...(content.expiring_facts || []).slice(0, 2).map((item) => ({ label: item.subject || "Expiring fact", detail: item.object_val || item.predicate || "Needs review", slug: item.page_slug })),
    ...(content.new_conflicts || []).slice(0, 2).map((item) => ({ label: item.topic || "Conflict", detail: item.severity || "open", slug: item.slug_a })),
    ...(content.changed_pages || []).slice(0, 2).map((item) => ({ label: item.title || item.slug, detail: "Changed recently", slug: item.slug })),
  ];
  els.knowledgeDigestPreview.innerHTML = rows.length
    ? rows.slice(0, 4).map((row) => `<button class="digest-row" type="button" data-slug="${escapeHtml(row.slug || "")}"><strong>${escapeHtml(row.label)}</strong><span>${escapeHtml(row.detail)}</span></button>`).join("")
    : `<p class="empty-mini">Nothing urgent in today’s digest.</p>`;
  els.knowledgeDigestPreview.querySelectorAll("[data-slug]").forEach((btn) => {
    btn.addEventListener("click", () => btn.dataset.slug && openWikiInsight(btn.dataset.slug));
  });
}

async function loadFlashcardStats() {
  try {
    state.flashcards.stats = await apiFetch(`${API.flashcards}/stats`);
  } catch {
    state.flashcards.stats = null;
  }
  renderFlashcardBadge();
}

function renderFlashcardBadge() {
  const due = state.flashcards.stats?.due_today || 0;
  if (els.flashcardDueBadge) els.flashcardDueBadge.textContent = String(due);
  if (els.pulseDueCount) els.pulseDueCount.textContent = String(due);
  if (els.knowledgeDueCount) els.knowledgeDueCount.textContent = String(due);
}

async function openFlashcards() {
  els.flashcardModal.hidden = false;
  document.body.classList.add("modal-open");
  els.flashcardStatsText.textContent = "Loading review queue...";
  els.flashcardBody.innerHTML = `<div class="flashcard-loading"><span class="thinking-spinner"></span><strong>Preparing your review queue</strong><small>This does not call an AI model.</small></div>`;
  try {
    const [due, stats] = await Promise.all([
      apiFetch(`${API.flashcards}/due`, { timeout: 12000 }),
      apiFetch(`${API.flashcards}/stats`, { timeout: 12000 }),
    ]);
    state.flashcards = { due, stats, currentIndex: 0, showingAnswer: false };
    renderFlashcards();
  } catch (error) {
    state.flashcards = { due: [], stats: state.flashcards.stats, currentIndex: 0, showingAnswer: false };
    els.flashcardStatsText.textContent = "Review queue unavailable";
    els.flashcardBody.innerHTML = `<div class="flashcard-error"><strong>Could not load review cards.</strong><span>${escapeHtml(error.message || "Please try again.")}</span><button type="button" class="secondary-button" id="retryFlashcardsBtn">Retry</button></div>`;
    els.flashcardBody.querySelector("#retryFlashcardsBtn")?.addEventListener("click", openFlashcards);
  }
}

function renderFlashcards() {
  const stats = state.flashcards.stats || {};
  const totalDue = state.flashcards.due.length;
  const index = state.flashcards.currentIndex;
  const progressText = totalDue ? `${Math.min(index + 1, totalDue)} of ${totalDue}` : "0 of 0";
  els.flashcardStatsText.innerHTML = `
    <strong>${stats.due_today || 0}</strong> due
    <span>${stats.total_cards || 0} total</span>
    <span>${stats.mastery_percent || 0}% mastery</span>
  `;
  const card = state.flashcards.due[index];
  if (!card) {
    els.flashcardBody.innerHTML = `
      <div class="flashcard-empty-state">
        <strong>No cards due right now</strong>
        <span>Generate cards from your wiki or come back when the next review is due.</span>
        <div class="flashcard-empty-actions">
          <button type="button" class="secondary-button" id="emptyGenerateCardsBtn">Generate Cards</button>
          <button type="button" class="primary-button" id="emptyCloseReviewBtn">Done</button>
        </div>
      </div>
    `;
    els.flashcardBody.querySelector("#emptyGenerateCardsBtn")?.addEventListener("click", generateFlashcards);
    els.flashcardBody.querySelector("#emptyCloseReviewBtn")?.addEventListener("click", () => {
      els.flashcardModal.hidden = true;
      document.body.classList.remove("modal-open");
    });
    return;
  }
  const pct = totalDue ? Math.round((index / totalDue) * 100) : 0;
  els.flashcardBody.innerHTML = `
    <div class="study-session-shell">
      <div class="study-progress-row">
        <span>${escapeHtml(progressText)}</span>
        <div class="study-progress-track"><i style="width:${pct}%"></i></div>
        <button type="button" class="text-button flashcard-source-btn">Source</button>
      </div>
      <article class="study-card ${state.flashcards.showingAnswer ? "show-answer" : ""}">
        <div class="study-card-kicker">${state.flashcards.showingAnswer ? "Answer" : "Question"}</div>
        <h2>${escapeHtml(state.flashcards.showingAnswer ? card.answer : card.question)}</h2>
        <p>${escapeHtml(state.flashcards.showingAnswer ? (card.source_quote || "Review the linked source page for more context.") : "Try to answer from memory, then reveal the answer.")}</p>
      </article>
      ${state.flashcards.showingAnswer ? `
        <div class="study-review-panel">
          <button type="button" data-result="again" class="study-rating again"><strong>Again</strong><span>I missed it</span></button>
          <button type="button" data-result="hard" class="study-rating hard"><strong>Hard</strong><span>I partly knew it</span></button>
          <button type="button" data-result="easy" class="study-rating easy"><strong>Easy</strong><span>I knew it</span></button>
        </div>
      ` : `
        <div class="study-reveal-panel">
          <button type="button" class="primary-button" id="revealFlashcardBtn">Reveal Answer</button>
        </div>
      `}
    </div>
  `;
  els.flashcardBody.querySelector("#revealFlashcardBtn")?.addEventListener("click", () => {
    state.flashcards.showingAnswer = true;
    renderFlashcards();
  });
  els.flashcardBody.querySelector(".flashcard-source-btn")?.addEventListener("click", () => {
    if (card.page_slug) openWikiInsight(card.page_slug);
  });
  els.flashcardBody.querySelectorAll("[data-result]").forEach((btn) => {
    btn.addEventListener("click", () => reviewFlashcard(card.id, btn.dataset.result));
  });
}

async function generateFlashcards() {
  setButtonLoading(els.generateFlashcardsBtn, true, "Generating...");
  try {
    const result = await apiFetch(`${API.flashcards}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      timeout: 20000,
      body: JSON.stringify({ page_slugs: [] }),
    });
    toast(`Generated ${result.created} flashcard(s)${result.limited ? " from the first 30 pages" : ""}.`);
    await openFlashcards();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setButtonLoading(els.generateFlashcardsBtn, false);
  }
}

async function reviewFlashcard(cardId, result) {
  if (state.flashcards.reviewing) return;
  state.flashcards.reviewing = true;
  const currentIndex = state.flashcards.currentIndex;
  const actionButtons = els.flashcardBody.querySelectorAll("[data-result]");
  actionButtons.forEach((btn) => {
    btn.disabled = true;
    btn.classList.add("loading");
  });
  try {
    await apiFetch(`${API.flashcards}/${cardId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      timeout: 10000,
      body: JSON.stringify({ result }),
    });
    state.flashcards.currentIndex = currentIndex + 1;
    state.flashcards.showingAnswer = false;
    renderFlashcards();
    loadFlashcardStats().catch(() => {});
  } catch (error) {
    state.flashcards.currentIndex = currentIndex;
    state.flashcards.showingAnswer = true;
    renderFlashcards();
    toast(error.message || "Could not save review. Please retry.", "error");
  } finally {
    state.flashcards.reviewing = false;
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
    await loadTier4();
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
        await loadTier4();
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
      item.querySelector(".wiki-card-row").addEventListener("click", () => openWikiInsight(page.slug));
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
    await loadTier4();
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
      loadTier4().catch((error) => console.warn("Tier 4 failed after login", error));
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

  els.chatReportModeBtn?.addEventListener("click", () => {
    state.reportModeActive = !state.reportModeActive;
    updateReportModeUI();
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
    await loadTier4();
  });
  els.scanConflictsBtn?.addEventListener("click", scanConflicts);
  document.querySelectorAll("[data-wiki-view]").forEach((btn) => {
    btn.addEventListener("click", () => setWikiView(btn.dataset.wikiView || "overview"));
  });
  els.pulseReviewBtn?.addEventListener("click", openFlashcards);
  document.querySelectorAll(".timeline-filter").forEach((btn) => {
    btn.addEventListener("click", () => loadTimeline(btn.dataset.status || "all"));
  });
  els.refreshTimelineBtn?.addEventListener("click", () => loadTimeline(state.timeline.status || "all"));
  els.markTimelineReadBtn?.addEventListener("click", markVisibleTimelineReviewed);
  els.notificationBellBtn?.addEventListener("click", (event) => {
    event.stopPropagation();
    els.notificationPopover.hidden = !els.notificationPopover.hidden;
    if (!els.notificationPopover.hidden) loadNotifications();
  });
  els.notificationPopover?.addEventListener("click", (event) => event.stopPropagation());
  els.generateDigestBtn?.addEventListener("click", generateDigest);
  els.knowledgeDigestBtn?.addEventListener("click", generateDigest);
  els.knowledgeOpenDigestBtn?.addEventListener("click", openDigest);
  els.knowledgeReviewBtn?.addEventListener("click", openFlashcards);
  els.knowledgeDueCardBtn?.addEventListener("click", openFlashcards);
  els.knowledgeGenerateCardsBtn?.addEventListener("click", generateFlashcards);
  els.knowledgeStartReviewBtn?.addEventListener("click", openFlashcards);
  els.digestCloseBtn?.addEventListener("click", () => {
    els.digestModal.hidden = true;
    document.body.classList.remove("modal-open");
  });
  els.digestModal?.addEventListener("click", (event) => {
    if (event.target === els.digestModal) {
      els.digestModal.hidden = true;
      document.body.classList.remove("modal-open");
    }
  });
  els.reviewFlashcardsBtn?.addEventListener("click", openFlashcards);
  els.flashcardCloseBtn?.addEventListener("click", () => {
    els.flashcardModal.hidden = true;
    document.body.classList.remove("modal-open");
  });
  els.flashcardModal?.addEventListener("click", (event) => {
    if (event.target === els.flashcardModal) {
      els.flashcardModal.hidden = true;
      document.body.classList.remove("modal-open");
    }
  });
  els.generateFlashcardsBtn?.addEventListener("click", generateFlashcards);
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
    if (els.digestModal && !els.digestModal.hidden) els.digestModal.hidden = true;
    if (els.flashcardModal && !els.flashcardModal.hidden) els.flashcardModal.hidden = true;
    if (!els.llmModal.hidden) closeLlmModal();
  });

  els.llmProviderSelect.addEventListener("change", async () => {
    state.llmProviderTouched = true;
    updateProviderLogo();
    updateApiKeyPlaceholder();
    updateBedrockFieldVisibility();
    updateModelOptions({ provider: els.llmProviderSelect.value, selectedModel: "" });
    await loadLlmStatus({ preferActiveProvider: false });
  });

  els.llmModelSelect.addEventListener("change", () => {
    const custom = els.llmModelSelect.value === "__custom__";
    els.llmCustomModelRow.hidden = !custom;
    if (custom) els.llmCustomModelInput.focus();
  });

  // Rebuild model list when region changes (Bedrock-specific)
  if (els.llmBedrockRegionSelect) {
    els.llmBedrockRegionSelect.addEventListener("change", () => {
      if (els.llmProviderSelect.value === "bedrock") {
        updateModelOptions({ provider: "bedrock", selectedModel: "" });
      }
    });
  }

  els.llmConnectBtn.addEventListener("click", async () => {
    const provider = els.llmProviderSelect.value;
    const isBedrock = provider === "bedrock";
    els.llmError.hidden = true;

    let requestBody;
    if (isBedrock) {
      // Bedrock: two credential fields
      const accessKeyId = (els.llmAccessKeyInput?.value || "").trim();
      const secretKey = (els.llmSecretKeyInput?.value || "").trim();
      const region = els.llmBedrockRegionSelect?.value || "us-east-1";
      const model = els.llmModelSelect.value === "__custom__"
        ? els.llmCustomModelInput.value.trim()
        : els.llmModelSelect.value;
      if (!accessKeyId) {
        els.llmError.textContent = "AWS Access Key ID is required.";
        els.llmError.hidden = false;
        return;
      }
      if (!secretKey) {
        els.llmError.textContent = "AWS Secret Access Key is required.";
        els.llmError.hidden = false;
        return;
      }
      requestBody = {
        provider,
        api_key: accessKeyId,
        aws_secret_access_key: secretKey,
        aws_region: region,
        model: model || "meta.llama3-70b-instruct-v1:0",
      };
    } else {
      // Standard providers
      const apiKey = els.llmApiKeyInput.value.trim();
      const model = els.llmModelSelect.value === "__custom__"
        ? els.llmCustomModelInput.value.trim()
        : els.llmModelSelect.value;
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
      requestBody = { provider, api_key: apiKey, model };
    }

    setButtonLoading(els.llmConnectBtn, true, "Connecting...");
    try {
      await apiFetch(API.llmKeys, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
        timeout: 45000,
      });
      // Clear sensitive inputs
      if (isBedrock) {
        if (els.llmAccessKeyInput) els.llmAccessKeyInput.value = "";
        if (els.llmSecretKeyInput) els.llmSecretKeyInput.value = "";
      } else {
        els.llmApiKeyInput.value = "";
      }
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
    if (els.notificationPopover && !els.notificationPopover.hidden) els.notificationPopover.hidden = true;
  });
}

function resizeTextarea() {
  els.messageInput.style.height = "auto";
  els.messageInput.style.height = `${Math.min(180, els.messageInput.scrollHeight)}px`;
}

function updateReportModeUI() {
  if (state.reportModeActive) {
    els.chatReportModeBtn?.classList.add("active");
    els.messageInput.placeholder = "Describe the report you want to generate (e.g. 'Summarize procurement policies in PDF')...";
  } else {
    els.chatReportModeBtn?.classList.remove("active");
    els.messageInput.placeholder = "Ask KnowForge, reply to a message, or continue a thread...";
  }
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

// =============================================================================
// RESEARCH INTELLIGENCE ENGINE (Tier 3)
// =============================================================================
(function initResearchIntelligence() {
  const researchState = {
    papers: [],
    summary: null,
    selectedPaperIds: new Set(),
    activeSubtab: "details",
    activePaperId: null,
    activePaperDetails: null,
    lastComparison: null,
    lastGaps: null
  };

  API.researchPapers = "/api/v1/research/papers";
  API.researchSummary = "/api/v1/research/summary";
  API.researchGraph = "/api/v1/research/graph";
  API.researchCompare = "/api/v1/research/compare";
  API.researchGaps = "/api/v1/research/gaps";

  const elements = {
    researchList: document.querySelector("#researchList"),
    emptyResearch: document.querySelector("#emptyResearch"),
    refreshResearchBtn: document.querySelector("#refreshResearchBtn"),
    researchGraphBtn: document.querySelector("#researchGraphBtn"),
    researchCompareBtn: document.querySelector("#researchCompareBtn"),
    researchGapsBtn: document.querySelector("#researchGapsBtn"),
    researchBoardGraphBtn: document.querySelector("#researchBoardGraphBtn"),
    researchBoardCompareBtn: document.querySelector("#researchBoardCompareBtn"),
    researchBoardGapsBtn: document.querySelector("#researchBoardGapsBtn"),
    researchOpenDetailsBtn: document.querySelector("#researchOpenDetailsBtn"),
    researchClearSelectionBtn: document.querySelector("#researchClearSelectionBtn"),
    researchModal: document.querySelector("#researchModal"),
    researchModalCloseBtn: document.querySelector("#researchModalCloseBtn"),
    paperDetailsContent: document.querySelector("#paperDetailsContent"),
    compareQueryInput: document.querySelector("#compareQueryInput"),
    runCompareBtn: document.querySelector("#runCompareBtn"),
    compareMatrixResult: document.querySelector("#compareMatrixResult"),
    runGapsBtn: document.querySelector("#runGapsBtn"),
    gapsResult: document.querySelector("#gapsResult"),
    subtabs: document.querySelectorAll(".research-sub-tab"),
    researchUploadArea: document.querySelector("#researchUploadArea"),
    researchPdfInput: document.querySelector("#researchPdfInput"),
    researchUploadDefault: document.querySelector("#researchUploadDefault"),
    researchUploadActive: document.querySelector("#researchUploadActive"),
    researchUploadMessage: document.querySelector("#researchUploadMessage"),
    researchFocusContent: document.querySelector("#researchFocusContent"),
    researchSelectionList: document.querySelector("#researchSelectionList"),
    researchMapPreview: document.querySelector("#researchMapPreview"),
    researchStudioInsight: document.querySelector("#researchStudioInsight"),
    researchSelectedCount: document.querySelector("#researchSelectedCount"),
    researchAnalyzedCount: document.querySelector("#researchAnalyzedCount"),
    researchProcessingCount: document.querySelector("#researchProcessingCount"),
    researchTotalCount: document.querySelector("#researchTotalCount"),
    researchReadyCount: document.querySelector("#researchReadyCount"),
    researchClaimCount: document.querySelector("#researchClaimCount"),
    researchMethodCount: document.querySelector("#researchMethodCount"),
    panels: {
      details: document.querySelector("#researchDetailsPanel"),
      graph: document.querySelector("#researchGraphPanel"),
      compare: document.querySelector("#researchComparePanel"),
      gaps: document.querySelector("#researchGapsPanel")
    }
  };

  window.refreshResearchPapers = loadResearchPapers;

  let pollInterval = null;

  function statusLabel(status) {
    if (status === "failed") return "Failed";
    if (status === "completed" || status === "done") return "Ready";
    return "Processing";
  }

  function isReady(paper) {
    return paper.status === "completed" || paper.status === "done";
  }

  function selectedPapers() {
    return researchState.papers.filter((paper) => researchState.selectedPaperIds.has(paper.id));
  }

  function setText(el, value) {
    if (el) el.textContent = String(value);
  }

  async function loadResearchPapers() {
    if (!state.token) {
      stopPolling();
      return;
    }
    if (!elements.researchList) return;

    const isFirstLoad = elements.researchList.innerHTML === "" ||
      elements.researchList.querySelector(".empty-mini") ||
      elements.researchList.querySelector(".inline-error");

    if (isFirstLoad) {
      elements.researchList.innerHTML = `<p class="empty-mini">Loading papers…</p>`;
    }

    try {
      const [papers, summary] = await Promise.all([
        apiFetch(API.researchPapers),
        apiFetch(API.researchSummary).catch(() => null)
      ]);
      researchState.papers = papers || [];
      researchState.summary = summary;
      researchState.selectedPaperIds.forEach((id) => {
        if (!researchState.papers.some((paper) => paper.id === id)) researchState.selectedPaperIds.delete(id);
      });
      if (!researchState.activePaperId && researchState.papers.length) {
        const firstReady = researchState.papers.find(isReady) || researchState.papers[0];
        researchState.activePaperId = firstReady.id;
      }
      renderResearchPapers();
      renderResearchDashboard();
      renderGraphPreview();
      if (researchState.activePaperId && (!researchState.activePaperDetails || researchState.activePaperDetails.id !== researchState.activePaperId)) {
        await loadPaperDetails(researchState.activePaperId, { openModal: false });
      }

      const hasProcessing = researchState.papers.some((p) => p.status === "pending" || p.status === "processing");
      hasProcessing ? startPolling() : stopPolling();
    } catch (e) {
      if (isFirstLoad) elements.researchList.innerHTML = `<p class="inline-error">${escapeHtml(e.message)}</p>`;
      renderResearchDashboard();
    }
  }

  function startPolling() {
    if (pollInterval) return;
    pollInterval = setInterval(loadResearchPapers, 5000);
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  }

  function renderResearchPapers() {
    if (!elements.researchList) return;
    elements.researchList.innerHTML = "";
    const hasPapers = researchState.papers.length > 0;
    if (elements.emptyResearch) elements.emptyResearch.hidden = hasPapers;
    if (!hasPapers) return;

    researchState.papers.forEach((paper) => {
      const item = document.createElement("div");
      const isSelected = researchState.selectedPaperIds.has(paper.id);
      const isActive = researchState.activePaperId === paper.id;
      const authorsList = paper.authors && paper.authors.length
        ? paper.authors.slice(0, 2).join(", ") + (paper.authors.length > 2 ? " et al." : "")
        : "Unknown authors";
      const pillClass = paper.status === "failed" ? "warn" : isReady(paper) ? "" : "muted";

      item.className = `paper-item ${isActive ? "active" : ""}`;
      item.innerHTML = `
        <div class="paper-card-top">
          <strong class="paper-title">${escapeHtml(paper.title)}</strong>
          <div class="paper-card-actions">
            <input type="checkbox" class="paper-select-checkbox" data-id="${paper.id}" ${isSelected ? "checked" : ""} title="Select for comparison" />
            <button class="paper-delete-btn" data-id="${paper.id}" title="Delete paper" type="button">✕</button>
          </div>
        </div>
        <div class="paper-authors">${escapeHtml(authorsList)}</div>
        <div class="paper-meta">
          <span>${escapeHtml(paper.venue || "No venue")}</span>
          <span>${escapeHtml(paper.publication_year ? String(paper.publication_year) : "Year unknown")}</span>
          <span class="wiki-badge ${pillClass}" title="${escapeHtml(paper.error_message || "")}">${statusLabel(paper.status)}</span>
        </div>
        <div class="paper-counts">
          <span class="paper-count-pill">${paper.method_count || 0} methods</span>
          <span class="paper-count-pill">${paper.claim_count || 0} claims</span>
          <span class="paper-count-pill">${paper.section_count || 0} sections</span>
        </div>
      `;

      const checkbox = item.querySelector(".paper-select-checkbox");
      checkbox.addEventListener("click", (e) => {
        e.stopPropagation();
        if (checkbox.checked) researchState.selectedPaperIds.add(paper.id);
        else researchState.selectedPaperIds.delete(paper.id);
        renderResearchPapers();
        renderResearchDashboard();
      });

      item.querySelector(".paper-delete-btn").addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete "${paper.title}" from the research library?`)) return;
        try {
          await apiFetch(`${API.researchPapers}/${paper.id}`, { method: "DELETE" });
          toast(`Deleted paper: ${paper.title}`);
          researchState.selectedPaperIds.delete(paper.id);
          if (researchState.activePaperId === paper.id) {
            researchState.activePaperId = null;
            researchState.activePaperDetails = null;
          }
          await loadResearchPapers();
        } catch (err) {
          toast(`Failed to delete: ${err.message}`, "error");
        }
      });

      item.addEventListener("click", async () => {
        researchState.activePaperId = paper.id;
        renderResearchPapers();
        await loadPaperDetails(paper.id, { openModal: false });
      });

      elements.researchList.appendChild(item);
    });
  }

  function renderResearchDashboard() {
    const summary = researchState.summary || {};
    const total = summary.total_papers ?? researchState.papers.length;
    const ready = summary.analyzed_papers ?? researchState.papers.filter(isReady).length;
    const processing = summary.processing_papers ?? researchState.papers.filter((p) => p.status === "pending" || p.status === "processing").length;
    const failed = summary.failed_papers ?? researchState.papers.filter((p) => p.status === "failed").length;
    const claims = summary.claim_count ?? researchState.papers.reduce((sum, p) => sum + (p.claim_count || 0), 0);
    const methods = summary.method_count ?? researchState.papers.reduce((sum, p) => sum + (p.method_count || 0), 0);
    const selected = researchState.selectedPaperIds.size;

    setText(elements.researchSelectedCount, selected);
    setText(elements.researchAnalyzedCount, ready);
    setText(elements.researchProcessingCount, processing);
    setText(elements.researchTotalCount, total);
    setText(elements.researchReadyCount, ready);
    setText(elements.researchClaimCount, claims);
    setText(elements.researchMethodCount, methods);

    if (elements.researchStudioInsight) {
      if (!total) elements.researchStudioInsight.textContent = "Upload papers to extract abstracts, methods, claims, datasets, and contradictions.";
      else if (processing) elements.researchStudioInsight.textContent = `${processing} paper${processing === 1 ? " is" : "s are"} still processing. Ready papers can already be compared.`;
      else if (failed) elements.researchStudioInsight.textContent = `${failed} paper${failed === 1 ? " needs" : "s need"} attention, but the rest of your library is usable.`;
      else elements.researchStudioInsight.textContent = `${ready} analyzed paper${ready === 1 ? "" : "s"}, ${claims} claims, and ${methods} methods are ready for synthesis.`;
    }

    renderSelectionList();
    const activeDetails = researchState.activePaperDetails;
    if (activeDetails) renderPaperFocus(activeDetails);
    else renderPaperFocusPlaceholder();
  }

  function renderSelectionList() {
    if (!elements.researchSelectionList) return;
    const selected = selectedPapers();
    if (!selected.length) {
      elements.researchSelectionList.innerHTML = `<p class="empty-mini">Select papers in the sidebar to make a comparison set.</p>`;
      return;
    }
    elements.researchSelectionList.innerHTML = selected.map((paper) => `
      <div class="research-selection-item">
        <strong>${escapeHtml(paper.title)}</strong>
        <div class="paper-meta"><span>${escapeHtml(paper.publication_year ? String(paper.publication_year) : "Year unknown")}</span><span>${paper.method_count || 0} methods</span><span>${paper.claim_count || 0} claims</span></div>
      </div>
    `).join("");
  }

  function renderPaperFocusPlaceholder() {
    if (!elements.researchFocusContent) return;
    if (!researchState.papers.length) {
      elements.researchFocusContent.innerHTML = `<p class="empty-mini">Upload research PDFs to start a literature workspace.</p>`;
    } else {
      elements.researchFocusContent.innerHTML = `<p class="empty-mini">Choose a paper from the library to see its abstract, methods, and strongest claims.</p>`;
    }
  }

  function renderPaperFocus(paper) {
    if (!elements.researchFocusContent) return;
    const authors = paper.authors && paper.authors.length ? paper.authors.join(", ") : "Unknown authors";
    const methods = (paper.methods || []).slice(0, 4);
    const claims = (paper.claims || []).slice(0, 5);
    elements.researchFocusContent.innerHTML = `
      <div class="research-focus-hero">
        <div>
          <h3>${escapeHtml(paper.title)}</h3>
          <div class="research-focus-meta"><span>${escapeHtml(authors)}</span><span>${escapeHtml(paper.venue || "No venue")}</span><span>${escapeHtml(paper.publication_year ? String(paper.publication_year) : "Year unknown")}</span></div>
        </div>
        <div class="research-abstract-box">${escapeHtml(paper.abstract || "No abstract extracted yet.")}</div>
        <div class="research-mini-grid">
          <div class="research-mini-section">
            <h4>Methods</h4>
            <div class="research-mini-list">${methods.length ? methods.map((m) => `<div class="research-mini-item"><strong>${escapeHtml(m.name)}</strong><br>${escapeHtml(m.description || "No description extracted.")}</div>`).join("") : `<p class="empty-mini">No methods extracted yet.</p>`}</div>
          </div>
          <div class="research-mini-section">
            <h4>Claims</h4>
            <div class="research-mini-list">${claims.length ? claims.map((c) => `<div class="research-mini-item"><span class="research-claim-tag ${escapeHtml(c.category || "finding")}">${escapeHtml(c.category || "finding")}</span><br>${escapeHtml(c.claim_text)}</div>`).join("") : `<p class="empty-mini">No claims extracted yet.</p>`}</div>
          </div>
        </div>
      </div>
    `;
  }

  async function loadPaperDetails(paperId, opts = {}) {
    if (elements.paperDetailsContent) elements.paperDetailsContent.innerHTML = `<p class="empty-mini">Loading paper details…</p>`;
    try {
      const details = await apiFetch(`${API.researchPapers}/${paperId}`);
      researchState.activePaperDetails = details;
      renderPaperDetails(details);
      renderPaperFocus(details);
      if (opts.openModal) openResearchModal("details");
    } catch (e) {
      const msg = `<p class="inline-error">${escapeHtml(e.message)}</p>`;
      if (elements.paperDetailsContent) elements.paperDetailsContent.innerHTML = msg;
      if (elements.researchFocusContent) elements.researchFocusContent.innerHTML = msg;
    }
  }

  function renderPaperDetails(paper) {
    if (!elements.paperDetailsContent) return;
    const authors = paper.authors && paper.authors.length ? paper.authors.join(", ") : "Unknown authors";
    const sectionsHtml = paper.sections && paper.sections.length
      ? paper.sections.map((s) => `
          <div class="research-section-box">
            <div class="research-section-head"><strong>${escapeHtml(s.heading)}</strong><span class="wiki-badge muted">${escapeHtml(s.section_type || "section")}</span></div>
            <div class="research-section-content">${escapeHtml(s.content)}</div>
          </div>
        `).join("")
      : `<p class="empty-mini">No structural sections parsed.</p>`;

    const methodsHtml = paper.methods && paper.methods.length
      ? `<div class="research-table-wrap"><table class="research-table"><thead><tr><th>Method or model</th><th>Description</th><th>Dataset</th></tr></thead><tbody>${paper.methods.map((m) => `<tr><td><strong>${escapeHtml(m.name)}</strong></td><td>${escapeHtml(m.description || "N/A")}</td><td>${escapeHtml(m.dataset_used || "N/A")}</td></tr>`).join("")}</tbody></table></div>`
      : `<p class="empty-mini">No methodology entities extracted.</p>`;

    const claimsHtml = paper.claims && paper.claims.length
      ? paper.claims.map((c) => {
          const categoryClass = c.category || "finding";
          return `
            <div class="research-claim-card ${escapeHtml(categoryClass)}">
              <div class="research-claim-head"><span class="research-claim-tag ${escapeHtml(categoryClass)}">${escapeHtml(c.category || "finding")}</span><span class="wiki-badge ${c.grounding_level === "fully_supported" ? "" : "warn"}">${escapeHtml(c.grounding_level || "partially_supported")}</span></div>
              <p>${escapeHtml(c.claim_text)}</p>
              ${c.evidence ? `<small>Evidence: ${escapeHtml(c.evidence)}</small>` : ""}
            </div>
          `;
        }).join("")
      : `<p class="empty-mini">No claims or limitations extracted.</p>`;

    elements.paperDetailsContent.innerHTML = `
      <div class="research-detail-header">
        <h3>${escapeHtml(paper.title)}</h3>
        <div class="research-detail-meta"><span>${escapeHtml(authors)}</span><span>${escapeHtml(paper.venue || "No venue")}</span><span>${escapeHtml(paper.publication_year ? String(paper.publication_year) : "Year unknown")}</span><span>DOI: ${escapeHtml(paper.doi || "N/A")}</span></div>
      </div>
      <div class="research-detail-grid">
        <section class="research-detail-section"><h4>Abstract</h4><div class="research-abstract-box">${escapeHtml(paper.abstract || "No abstract extracted.")}</div></section>
        <section class="research-detail-section"><h4>Methods and datasets</h4>${methodsHtml}</section>
        <section class="research-detail-section"><h4>Claims and evidence</h4>${claimsHtml}</section>
        <section class="research-detail-section"><h4>Parsed sections</h4>${sectionsHtml}</section>
      </div>
    `;
  }

  function openResearchModal(subtab = "details") {
    if (!elements.researchModal) return;
    elements.researchModal.hidden = false;
    if (subtab === "details" && researchState.activePaperId && !researchState.activePaperDetails) {
      loadPaperDetails(researchState.activePaperId);
    }
    switchSubtab(subtab);
  }

  function closeResearchModal() {
    if (elements.researchModal) elements.researchModal.hidden = true;
  }

  function switchSubtab(subtabId) {
    researchState.activeSubtab = subtabId;
    elements.subtabs.forEach((tab) => tab.classList.toggle("active", tab.getAttribute("data-subtab") === subtabId));
    Object.entries(elements.panels).forEach(([panelId, panel]) => {
      if (panel) panel.hidden = panelId !== subtabId;
    });
    if (subtabId === "graph") renderCitationGraph("#researchGraphCanvas");
  }

  async function renderCitationGraph(targetSelector = "#researchGraphCanvas") {
    const canvas = document.querySelector(targetSelector);
    if (!canvas) return;
    canvas.innerHTML = `<p class="empty-mini">Loading research map…</p>`;
    try {
      const data = await apiFetch(API.researchGraph);
      canvas.innerHTML = buildGraphSvg(data, targetSelector === "#researchMapPreview" ? 240 : 420);
    } catch (e) {
      canvas.innerHTML = `<p class="inline-error">${escapeHtml(e.message)}</p>`;
    }
  }

  function renderGraphPreview() {
    if (!elements.researchMapPreview) return;
    renderCitationGraph("#researchMapPreview");
  }

  function buildGraphSvg(data, height) {
    if (!data.nodes || !data.nodes.length) return `<p class="empty-mini">No papers mapped yet.</p>`;
    const width = 760;
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.max(70, Math.min(width, height) / 2 - 45);
    const coords = {};
    data.nodes.forEach((node, idx) => {
      const angle = (2 * Math.PI * idx) / data.nodes.length;
      coords[node.id] = {
        x: centerX + radius * Math.cos(angle),
        y: centerY + radius * Math.sin(angle),
        label: node.label || "Untitled"
      };
    });
    const lines = (data.links || []).map((link) => {
      const src = coords[link.source];
      const tgt = coords[link.target];
      if (!src || !tgt) return "";
      const bad = link.relation_type === "contradicts";
      return `<line x1="${src.x}" y1="${src.y}" x2="${tgt.x}" y2="${tgt.y}" stroke="${bad ? "var(--danger)" : "var(--accent)"}" stroke-width="2" stroke-dasharray="${bad ? "5 5" : "0"}" />`;
    }).join("");
    const nodes = Object.entries(coords).map(([id, node]) => `
      <g class="graph-node-group" style="cursor:pointer" data-paper-id="${id}">
        <circle cx="${node.x}" cy="${node.y}" r="10" fill="var(--accent)" stroke="var(--surface)" stroke-width="3" />
        <text x="${node.x + 14}" y="${node.y + 4}" font-size="11" font-weight="700" fill="var(--ink)">${escapeHtml(node.label.slice(0, 24))}${node.label.length > 24 ? "..." : ""}</text>
      </g>
    `).join("");
    return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img" aria-label="Research graph">${lines}${nodes}</svg>`;
  }

  function tableToMarkdown(headers, rows) {
    let md = `| ${headers.join(" | ")} |\n`;
    md += `| ${headers.map(() => "---").join(" | ")} |\n`;
    rows.forEach((row) => {
      md += `| ${row.map((cell) => String(cell).replace(/\|/g, "\\|")).join(" | ")} |\n`;
    });
    return md;
  }

  function gapsToMarkdown(gaps) {
    let md = `# Literature Gaps and Workspace Analysis\n\n`;
    (gaps.contradictions || []).forEach((c) => { md += `## Contradiction\n\n- ${c.paper_a}: ${c.claim_a}\n- ${c.paper_b}: ${c.claim_b}\n- Explanation: ${c.explanation}\n\n`; });
    (gaps.untested_combinations || []).forEach((combo) => { md += `## Untested Combination\n\n- Method: ${combo.method} (${combo.paper})\n- Dataset: ${combo.dataset} (${combo.dataset_paper})\n- Value: ${combo.potential_benefit}\n\n`; });
    (gaps.open_challenges || []).forEach((challenge) => { md += `## Open Challenge\n\n- ${challenge.challenge}\n- Implication: ${challenge.implication}\n\n`; });
    return md;
  }

  function downloadTextFile(filename, text) {
    const element = document.createElement("a");
    element.setAttribute("href", "data:text/markdown;charset=utf-8," + encodeURIComponent(text));
    element.setAttribute("download", filename);
    element.style.display = "none";
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  }

  async function generateComparisonMatrix() {
    if (researchState.selectedPaperIds.size === 0) {
      elements.compareMatrixResult.innerHTML = `<p class="inline-error">Select at least one paper in the Research Library.</p>`;
      return;
    }

    elements.compareMatrixResult.innerHTML = `<p class="empty-mini">Synthesizing comparison matrix…</p>`;
    try {
      const result = await apiFetch(API.researchCompare, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paper_ids: Array.from(researchState.selectedPaperIds), query: elements.compareQueryInput.value || null }),
        timeout: 90000
      });
      if (!result.headers || !result.rows) throw new Error("Comparison response was incomplete.");
      researchState.lastComparison = result;
      elements.compareMatrixResult.innerHTML = `
        <div class="research-export-bar"><button id="copyMatrixBtn" class="secondary-button" type="button">Copy Markdown</button><button id="downloadMatrixBtn" class="secondary-button" type="button">Download MD</button></div>
        <div class="research-table-wrap"><table class="research-table"><thead><tr>${result.headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead><tbody>${result.rows.map((row) => `<tr>${row.map((cell, idx) => `<td>${idx === 0 ? `<strong>${escapeHtml(cell)}</strong>` : escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
      `;
      document.getElementById("copyMatrixBtn").addEventListener("click", () => {
        navigator.clipboard.writeText(tableToMarkdown(result.headers, result.rows));
        toast("Comparison matrix copied as Markdown.");
      });
      document.getElementById("downloadMatrixBtn").addEventListener("click", () => downloadTextFile("comparison_matrix.md", tableToMarkdown(result.headers, result.rows)));
    } catch (e) {
      elements.compareMatrixResult.innerHTML = `<p class="inline-error">${escapeHtml(e.message)}</p>`;
    }
  }

  async function generateLiteratureGaps() {
    if (researchState.selectedPaperIds.size === 0) {
      elements.gapsResult.innerHTML = `<p class="inline-error">Select at least one paper in the Research Library.</p>`;
      return;
    }

    elements.gapsResult.innerHTML = `<p class="empty-mini">Analyzing claims, methods, and gaps…</p>`;
    try {
      const result = await apiFetch(API.researchGaps, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paper_ids: Array.from(researchState.selectedPaperIds) }),
        timeout: 90000
      });
      researchState.lastGaps = result;
      const sections = [];
      (result.contradictions || []).forEach((c) => sections.push(`<div class="research-claim-card limitation"><div class="research-claim-head"><span class="research-claim-tag limitation">Contradiction</span></div><p><strong>${escapeHtml(c.paper_a)}</strong>: ${escapeHtml(c.claim_a)}</p><p><strong>${escapeHtml(c.paper_b)}</strong>: ${escapeHtml(c.claim_b)}</p><small>${escapeHtml(c.explanation)}</small></div>`));
      (result.untested_combinations || []).forEach((combo) => sections.push(`<div class="research-claim-card hypothesis"><div class="research-claim-head"><span class="research-claim-tag hypothesis">Untested pair</span></div><p>Try <strong>${escapeHtml(combo.method)}</strong> from ${escapeHtml(combo.paper)} on <strong>${escapeHtml(combo.dataset)}</strong> from ${escapeHtml(combo.dataset_paper)}.</p><small>${escapeHtml(combo.potential_benefit)}</small></div>`));
      (result.open_challenges || []).forEach((challenge) => sections.push(`<div class="research-claim-card gap"><div class="research-claim-head"><span class="research-claim-tag gap">Open challenge</span></div><p>${escapeHtml(challenge.challenge)}</p><small>${escapeHtml(challenge.implication)}</small></div>`));
      elements.gapsResult.innerHTML = sections.length
        ? `<div class="research-export-bar"><button id="copyGapsBtn" class="secondary-button" type="button">Copy Report</button><button id="downloadGapsBtn" class="secondary-button" type="button">Download MD</button></div>${sections.join("")}`
        : `<p class="empty-mini">No notable contradictions or gaps found across this selection.</p>`;
      if (sections.length) {
        document.getElementById("copyGapsBtn").addEventListener("click", () => {
          navigator.clipboard.writeText(gapsToMarkdown(result));
          toast("Literature gaps report copied.");
        });
        document.getElementById("downloadGapsBtn").addEventListener("click", () => downloadTextFile("literature_gaps_report.md", gapsToMarkdown(result)));
      }
    } catch (e) {
      elements.gapsResult.innerHTML = `<p class="inline-error">${escapeHtml(e.message)}</p>`;
    }
  }

  function setUploadBusy(isBusy, message = "Uploading document...") {
    if (elements.researchUploadDefault) elements.researchUploadDefault.style.display = isBusy ? "none" : "grid";
    if (elements.researchUploadActive) elements.researchUploadActive.style.display = isBusy ? "grid" : "none";
    if (elements.researchUploadMessage) elements.researchUploadMessage.textContent = message;
    if (elements.researchUploadArea) elements.researchUploadArea.disabled = isBusy;
  }

  function showResearchUploadError(msg) {
    toast(msg, "error");
    setUploadBusy(true, `Error: ${msg}`);
    setTimeout(() => setUploadBusy(false), 4000);
  }

  async function uploadResearchPdf(file) {
    if (!file) return;
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      showResearchUploadError("Please choose a PDF file.");
      return;
    }
    setUploadBusy(true, "Uploading document...");
    const form = new FormData();
    form.append("file", file);
    try {
      const response = await apiFetch(`${API.upload}?force_research=true`, { method: "POST", body: form, timeout: 120000 });
      toast(`Uploaded ${response.filename}. Analysis started.`);
      setUploadBusy(true, "Analyzing paper...");
      if (window.loadWikiPages) await window.loadWikiPages();
      await loadResearchPapers();
      setTimeout(() => setUploadBusy(false), 1500);
    } catch (error) {
      showResearchUploadError(error.message);
    } finally {
      if (elements.researchPdfInput) elements.researchPdfInput.value = "";
    }
  }

  function openCompare() {
    openResearchModal("compare");
  }

  function openGaps() {
    openResearchModal("gaps");
  }

  function openGraph() {
    openResearchModal("graph");
  }

  if (elements.refreshResearchBtn) elements.refreshResearchBtn.addEventListener("click", loadResearchPapers);
  if (elements.researchModalCloseBtn) elements.researchModalCloseBtn.addEventListener("click", closeResearchModal);
  if (elements.researchGraphBtn) elements.researchGraphBtn.addEventListener("click", openGraph);
  if (elements.researchCompareBtn) elements.researchCompareBtn.addEventListener("click", openCompare);
  if (elements.researchGapsBtn) elements.researchGapsBtn.addEventListener("click", openGaps);
  if (elements.researchBoardGraphBtn) elements.researchBoardGraphBtn.addEventListener("click", openGraph);
  if (elements.researchBoardCompareBtn) elements.researchBoardCompareBtn.addEventListener("click", openCompare);
  if (elements.researchBoardGapsBtn) elements.researchBoardGapsBtn.addEventListener("click", openGaps);
  if (elements.runCompareBtn) elements.runCompareBtn.addEventListener("click", generateComparisonMatrix);
  if (elements.runGapsBtn) elements.runGapsBtn.addEventListener("click", generateLiteratureGaps);
  if (elements.researchOpenDetailsBtn) elements.researchOpenDetailsBtn.addEventListener("click", () => openResearchModal("details"));
  if (elements.researchClearSelectionBtn) {
    elements.researchClearSelectionBtn.addEventListener("click", () => {
      researchState.selectedPaperIds.clear();
      renderResearchPapers();
      renderResearchDashboard();
    });
  }

  elements.subtabs.forEach((tab) => tab.addEventListener("click", () => switchSubtab(tab.getAttribute("data-subtab"))));

  if (elements.researchUploadArea && elements.researchPdfInput) {
    elements.researchUploadArea.addEventListener("click", () => elements.researchPdfInput.click());
    elements.researchPdfInput.addEventListener("change", (e) => uploadResearchPdf(e.target.files[0]));
  }
})();
