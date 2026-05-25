const API = {
  chat: "/api/v1/chat",
  upload: "/api/v1/sources/upload",
  wikiPages: "/api/v1/wiki/pages",
  wikiIndex: "/api/v1/wiki/index",
  compact: "/api/v1/wiki/compact",
};

const STORAGE_KEY = "knowforge.chatboard.v3";
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

const state = {
  messages: [],
  pendingReplyTo: null,
  pendingCommentFor: null,
  sending: false,
};

const els = {
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
  refreshWikiBtn: document.querySelector("#refreshWikiBtn"),
  newChatBtn: document.querySelector("#newChatBtn"),
  compactWikiBtn: document.querySelector("#compactWikiBtn"),
  networkState: document.querySelector("#networkState"),
};

function uid() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    state.messages = Array.isArray(saved.messages) ? saved.messages : [];
  } catch {
    state.messages = [];
  }
}

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ messages: state.messages.slice(-120) }));
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
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const contentType = response.headers.get("content-type") || "";
    const body = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    if (!response.ok) {
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

function addMessage(message) {
  state.messages.push({
    id: uid(),
    createdAt: new Date().toISOString(),
    comments: [],
    ...message,
  });
  saveState();
  renderChat();
}

function updateMessage(id, patch) {
  const item = state.messages.find((message) => message.id === id);
  if (!item) return;
  Object.assign(item, patch);
  saveState();
  renderChat();
}

function addComment(parentId, role, content) {
  const parent = state.messages.find((message) => message.id === parentId);
  if (!parent) return;
  parent.comments = parent.comments || [];
  parent.comments.push({
    id: uid(),
    role,
    content,
    createdAt: new Date().toISOString(),
  });
  saveState();
  renderChat();
}

function compactHistoryForApi() {
  return state.messages
    .filter((message) => !message.pending)
    .slice(-24)
    .map((message) => ({
      role: message.role === "assistant" ? "assistant" : "user",
      content: message.content,
    }));
}

async function sendMessage(content) {
  if (!content.trim() || state.sending) return;
  const parentId = state.pendingReplyTo || state.pendingCommentFor;
  const isComment = Boolean(state.pendingCommentFor);
  clearReplyMode();

  if (isComment && parentId) {
    addComment(parentId, "user", content);
  } else {
    addMessage({ role: "user", content, parentId });
  }

  const assistantId = uid();
  state.messages.push({
    id: assistantId,
    role: "assistant",
    content: "Thinking...",
    pending: true,
    parentId,
    comments: [],
    createdAt: new Date().toISOString(),
  });
  state.sending = true;
  els.sendBtn.disabled = true;
  saveState();
  renderChat();

  try {
    const question = parentId
      ? `Replying in thread to message ${parentId}:\n\n${content}`
      : content;
    const response = await apiFetch(API.chat, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        messages: compactHistoryForApi(),
        allow_fallback: true,
      }),
    });
    updateMessage(assistantId, {
      content: response.answer,
      pending: false,
      citations: response.citations || [],
      usedPages: response.used_pages || [],
      agentTrace: response.agent_trace || [],
    });
    renderInspector(response);
  } catch (error) {
    updateMessage(assistantId, {
      content: `I could not complete that request.\n\n${error.message}`,
      pending: false,
      failed: true,
    });
    toast(error.message, "error");
  } finally {
    state.sending = false;
    els.sendBtn.disabled = false;
  }
}

function renderChat() {
  els.chatBoard.innerHTML = "";
  if (!state.messages.length) {
    const welcome = document.createElement("div");
    welcome.className = "welcome-card";
    welcome.innerHTML = `
      <h3>Start a KnowForge conversation</h3>
      <p>
        Ask a direct question, upload a PDF to build the wiki, or reply/comment on any answer.
        KnowForge answers naturally, and uses your wiki with citations when source context exists.
      </p>
    `;
    els.chatBoard.appendChild(welcome);
    return;
  }

  for (const message of state.messages) {
    const node = els.template.content.firstElementChild.cloneNode(true);
    node.classList.add(message.role === "assistant" ? "assistant" : "user");
    if (message.failed) node.classList.add("failed");
    node.querySelector(".message-author").textContent =
      message.role === "assistant" ? "KnowForge Assistant" : "You";
    node.querySelector(".message-time").textContent = new Date(message.createdAt).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
    node.querySelector(".message-body").innerHTML = message.pending
      ? '<p class="empty-mini">Thinking through wiki, fallback, and agent checks...</p>'
      : renderMarkdown(message.content);
    node.querySelector(".copy-btn").addEventListener("click", () => {
      navigator.clipboard?.writeText(message.content);
      toast("Message copied.");
    });
    node.querySelector(".reply-btn").addEventListener("click", () => setReplyMode(message.id, false));
    node.querySelector(".comment-btn").addEventListener("click", () => setReplyMode(message.id, true));

    const meta = node.querySelector(".message-meta-row");
    if (message.citations?.length) {
      meta.appendChild(chip(`${message.citations.length} citation(s)`));
    } else {
      meta.remove();
    }

    const thread = node.querySelector(".comment-thread");
    for (const comment of message.comments || []) {
      const item = document.createElement("div");
      item.className = "comment";
      item.innerHTML = `<strong>${comment.role === "assistant" ? "KnowForge" : "You"}</strong>${renderMarkdown(
        comment.content,
      )}`;
      thread.appendChild(item);
    }
    if (!(message.comments || []).length) thread.remove();
    els.chatBoard.appendChild(node);
  }
  els.chatBoard.scrollTop = els.chatBoard.scrollHeight;
}

function chip(label) {
  const item = document.createElement("span");
  item.className = "message-chip";
  item.textContent = label;
  return item;
}

function renderInspector(response) {
  void response;
}

function setReplyMode(messageId, commentMode) {
  state.pendingReplyTo = commentMode ? null : messageId;
  state.pendingCommentFor = commentMode ? messageId : null;
  els.replyLabel.textContent = commentMode
    ? "Commenting under selected message"
    : "Replying in selected thread";
  els.replyBanner.hidden = false;
  els.messageInput.focus();
}

function clearReplyMode() {
  state.pendingReplyTo = null;
  state.pendingCommentFor = null;
  els.replyLabel.textContent = "";
  els.replyBanner.hidden = true;
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
        sendMessage(`Summarize the wiki page "${page.slug}" and explain what it is useful for.`),
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
    showUploadError("PDF is larger than 5 MB.");
    return;
  }

  const form = new FormData();
  form.append("file", file);
  els.uploadState.textContent = "Uploading";
  els.uploadState.classList.remove("muted");
  try {
    const response = await apiFetch(API.upload, {
      method: "POST",
      body: form,
      timeout: 90000,
    });
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

function bindEvents() {
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
  els.newChatBtn.addEventListener("click", () => {
    state.messages = [];
    saveState();
    renderChat();
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
}

function resizeTextarea() {
  els.messageInput.style.height = "auto";
  els.messageInput.style.height = `${Math.min(180, els.messageInput.scrollHeight)}px`;
}

loadState();
bindEvents();
renderChat();
loadWikiPages();
