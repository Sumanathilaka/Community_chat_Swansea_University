(() => {
  "use strict";

  // ── DOM refs ──────────────────────────────────────────────────────────
  const root = document.documentElement;
  const sidebar = document.getElementById("sidebar");
  const openSidebarBtn = document.getElementById("openSidebar");
  const closeSidebarBtn = document.getElementById("closeSidebar");
  const themeToggle = document.getElementById("themeToggle");
  const newChatBtn = document.getElementById("newChatBtn");
  const saveChatBtn = document.getElementById("saveChatBtn");
  const saveChatLabel = document.getElementById("saveChatLabel");
  const rebuildIndexBtn = document.getElementById("rebuildIndexBtn");
  const sectionsLabel = document.getElementById("sectionsLabel").querySelector("span");

  const chatList = document.getElementById("chatList");
  const chatListEmpty = document.getElementById("chatListEmpty");
  const accountName = document.getElementById("accountName");
  const accountSub = document.getElementById("accountSub");
  const accountAction = document.getElementById("accountAction");
  const userAvatar = document.getElementById("userAvatar");
  const sidebarFooter = document.getElementById("sidebarFooter");

  const conversation = document.getElementById("conversation");
  const introCard = document.getElementById("introCard");
  const chatScroll = document.getElementById("chatScroll");

  const attachTrigger = document.getElementById("attachTrigger");
  const fileInput = document.getElementById("fileInput");
  const attachList = document.getElementById("attachList");
  const messageInput = document.getElementById("messageInput");
  const toolToggleBtn = document.getElementById("toolToggleBtn");
  const toolInlinePanel = document.getElementById("toolInlinePanel");
  const toolPillGroup = document.getElementById("toolPillGroup");
  const toolVectorStoreBtn = document.getElementById("toolVectorStoreBtn");
  const toolHateSpeechBtn = document.getElementById("toolHateSpeechBtn");
  const vectorStoreOptions = document.getElementById("vectorStoreOptions");
  const vectorStoreCloseBtn = document.getElementById("vectorStoreCloseBtn");
  const toolSelectionSummary = document.getElementById("toolSelectionSummary");
  const vectorStoreOptionInputs = Array.from(document.querySelectorAll("#vectorStoreOptions input[type='checkbox']"));
  const sendBtn = document.getElementById("sendBtn");
  const statusText = document.getElementById("statusText");

  const authModal = document.getElementById("authModal");
  const authModalClose = document.getElementById("authModalClose");
  const authForm = document.getElementById("authForm");
  const authTitle = document.getElementById("authTitle");
  const authSub = document.getElementById("authSub");
  const authError = document.getElementById("authError");
  const authSubmit = document.getElementById("authSubmit").querySelector("span");
  const authSwitchText = document.getElementById("authSwitchText");
  const authSwitchBtn = document.getElementById("authSwitchBtn");
  const authPasswordField = document.getElementById("authPassword");
  const authPasswordToggle = document.getElementById("authPasswordToggle");
  const toastStack = document.getElementById("toastStack");

  // ── App state ─────────────────────────────────────────────────────────
  let currentUser = null;
  let isSaved = false;
  let stagedFiles = [];
  let attachedNames = [];
  let authMode = "login"; // or "signup"
  let isSending = false;
  let toolsOpen = false;
  const selectedTools = {
    vectorStore: false,
    hateSpeechDetector: false,
    vectorStores: []
  };

  // ── Helpers ───────────────────────────────────────────────────────────
  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // Lightweight, safe formatter: escapes HTML first, then supports
  // **bold**, `code`, and paragraph/line breaks. No raw HTML is ever injected.
  function formatMessage(text) {
    if (!text) return "";
    let safe = escapeHtml(text);
    safe = safe.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    safe = safe.replace(/`([^`]+?)`/g, "<code>$1</code>");
    const paragraphs = safe.split(/\n{2,}/).map((p) => {
      const withBreaks = p.replace(/\n/g, "<br>");
      return `<p>${withBreaks}</p>`;
    });
    return paragraphs.join("");
  }

  function toast(message, type = "") {
    const el = document.createElement("div");
    el.className = `toast ${type}`.trim();
    el.textContent = message;
    toastStack.appendChild(el);
    requestAnimationFrame(() => el.classList.add("show"));
    setTimeout(() => {
      el.classList.remove("show");
      setTimeout(() => el.remove(), 220);
    }, 3200);
  }

  function timeLabel() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  async function api(url, options = {}) {
    const res = await fetch(url, { credentials: "same-origin", ...options });
    let data = null;
    try { data = await res.json(); } catch (_) { /* no body */ }
    if (!res.ok) {
      const err = new Error((data && data.error) || `Request failed (${res.status})`);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  // ── Theme ─────────────────────────────────────────────────────────────
  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    themeToggle.textContent = theme === "dark" ? "Light mode" : "Dark mode";
  }
  let currentTheme = root.getAttribute("data-theme") || "dark";
  applyTheme(currentTheme);
  themeToggle.addEventListener("click", () => {
    currentTheme = currentTheme === "dark" ? "light" : "dark";
    applyTheme(currentTheme);
  });

  // ── Sidebar (mobile) ──────────────────────────────────────────────────
  openSidebarBtn?.addEventListener("click", () => sidebar.classList.add("open"));
  closeSidebarBtn?.addEventListener("click", () => sidebar.classList.remove("open"));
  document.addEventListener("click", (event) => {
    if (window.innerWidth > 768) return;
    const insideSidebar = sidebar.contains(event.target) || openSidebarBtn.contains(event.target);
    if (!insideSidebar) sidebar.classList.remove("open");
  });

  // ── Rendering ─────────────────────────────────────────────────────────
  function renderAccount() {
    if (currentUser) {
      sidebarFooter.classList.remove("guest");
      userAvatar.textContent = currentUser.username.slice(0, 2).toUpperCase();
      accountName.textContent = currentUser.username;
      accountSub.textContent = "Logged in";
      accountAction.title = "Log out";
    } else {
      sidebarFooter.classList.add("guest");
      userAvatar.textContent = "G";
      accountName.textContent = "Guest";
      accountSub.textContent = "Not logged in — click to log in";
      accountAction.title = "Log in";
    }
  }

  function renderSavedChats(sessions) {
    chatList.querySelectorAll(".chat-item").forEach((n) => n.remove());
    if (!currentUser) {
      chatListEmpty.textContent = "Log in to save and revisit chats.";
      chatListEmpty.style.display = "block";
      return;
    }
    if (!sessions || sessions.length === 0) {
      chatListEmpty.textContent = "No saved chats yet.";
      chatListEmpty.style.display = "block";
      return;
    }
    chatListEmpty.style.display = "none";
    sessions.forEach((s) => {
      const btn = document.createElement("button");
      btn.className = "chat-item";
      btn.dataset.sessionId = s.id;
      const updated = new Date(s.updated_at);
      btn.innerHTML = `
        <span class="chat-item-text">
          <strong>${escapeHtml(s.title || "Untitled chat")}</strong>
          <span>${updated.toLocaleDateString()} · ${s.message_count} messages</span>
        </span>
        <span class="chat-item-delete" title="Delete chat">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6h16Z"/></svg>
        </span>`;
      btn.addEventListener("click", (e) => {
        if (e.target.closest(".chat-item-delete")) {
          e.stopPropagation();
          deleteSession(s.id);
        } else {
          loadSession(s.id);
        }
      });
      chatList.appendChild(btn);
    });
  }

  function renderSaveButton() {
    saveChatLabel.textContent = isSaved ? "Saved" : "Save chat";
    saveChatBtn.classList.toggle("saved", isSaved);
  }

  function renderAttachList() {
    attachList.innerHTML = "";
    stagedFiles.forEach((file, idx) => {
      const pill = document.createElement("div");
      pill.className = "attachment-preview";
      pill.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path></svg>
        <span>${escapeHtml(file.name)}</span>
        <span class="remove-pill" data-idx="${idx}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </span>`;
      pill.querySelector(".remove-pill").addEventListener("click", () => {
        stagedFiles.splice(idx, 1);
        renderAttachList();
      });
      attachList.appendChild(pill);
    });
    attachedNames.forEach((name) => {
      const pill = document.createElement("div");
      pill.className = "attachment-preview";
      pill.style.opacity = "0.65";
      pill.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>
        <span>${escapeHtml(name)} · indexed</span>`;
      attachList.appendChild(pill);
    });
  }

  // Builds the "extras" block for an assistant message: searched-sections
  // badge, live-web references, and hate-speech moderation annotation.
  function buildAssistantExtrasHtml(pair) {
    let html = "";
    if (pair.searched && pair.searched.length) {
      html += `<div class="searched-badge">🔎 Searched: ${escapeHtml(pair.searched.join(", "))}</div>`;
    }
    if (pair.references && pair.references.length) {
      const items = pair.references.map((url) => {
        const safeUrl = escapeHtml(url);
        return `<li><a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeUrl}</a></li>`;
      }).join("");
      html += `<div class="reference-list"><span class="reference-list-title">Sources</span><ul>${items}</ul></div>`;
    }
    if (pair.moderation && !pair.moderation.error) {
      const mod = pair.moderation;
      const flagged = !!mod.is_hate_speech;
      const cls = flagged ? "moderation-badge flagged" : "moderation-badge clear";
      const label = flagged
        ? `⚠ Hate speech analyzer: flagged (${escapeHtml(mod.severity_tier || "unknown")}${mod.implicit_explicit ? ", " + escapeHtml(mod.implicit_explicit) : ""})`
        : "✓ Hate speech analyzer: no concerns detected";
      html += `<div class="${cls}">${label}</div>`;
    } else if (pair.moderation && pair.moderation.error) {
      html += `<div class="moderation-badge unavailable">Hate speech analyzer: ${escapeHtml(pair.moderation.error)}</div>`;
    }
    return html;
  }

  function messageNode(pair) {
    const wrap = document.createElement("div");
    wrap.className = "message-pair-wrap";

    const userMsg = document.createElement("article");
    userMsg.className = "message user";
    userMsg.innerHTML = `
      <div class="message-head">
        <div class="message-author"><div class="message-icon">U</div>You</div>
        <div class="message-time">${timeLabel()}</div>
      </div>
      <div class="message-body">${formatMessage(pair.user)}</div>`;
    wrap.appendChild(userMsg);

    if (pair.assistant !== null && pair.assistant !== undefined) {
      const botMsg = document.createElement("article");
      botMsg.className = "message assistant";
      botMsg.innerHTML = `
        <div class="message-head">
          <div class="message-author">
            <div class="message-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2 4.5 6v6c0 5 3.4 8.4 7.5 10 4.1-1.6 7.5-5 7.5-10V6L12 2Z"></path></svg></div>
            Community-Chat
          </div>
          <div class="message-time">${timeLabel()}</div>
        </div>
        <div class="message-body">${formatMessage(pair.assistant)}${buildAssistantExtrasHtml(pair)}</div>`;
      wrap.appendChild(botMsg);
    }
    return wrap;
  }

  function renderConversation(chatPairs) {
    conversation.querySelectorAll(".message-pair-wrap").forEach((n) => n.remove());
    introCard.style.display = chatPairs.length ? "none" : "grid";
    chatPairs.forEach((pair) => conversation.appendChild(messageNode(pair)));
    chatScroll.scrollTop = chatScroll.scrollHeight;
  }

  function appendPendingMessage(userText) {
    const wrap = document.createElement("div");
    wrap.className = "message-pair-wrap";
    wrap.id = "pendingPair";
    introCard.style.display = "none";
    wrap.innerHTML = `
      <article class="message user">
        <div class="message-head">
          <div class="message-author"><div class="message-icon">U</div>You</div>
          <div class="message-time">${timeLabel()}</div>
        </div>
        <div class="message-body">${formatMessage(userText)}</div>
      </article>
      <article class="message assistant pending">
        <div class="message-head">
          <div class="message-author">
            <div class="message-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2 4.5 6v6c0 5 3.4 8.4 7.5 10 4.1-1.6 7.5-5 7.5-10V6L12 2Z"></path></svg></div>
            Community-Chat
          </div>
        </div>
        <div class="message-body"><div class="typing-dots"><span></span><span></span><span></span></div></div>
      </article>`;
    conversation.appendChild(wrap);
    chatScroll.scrollTop = chatScroll.scrollHeight;
  }

  function resolvePendingMessage(pair) {
    const pending = document.getElementById("pendingPair");
    if (!pending) return;
    pending.id = "";
    const botBody = pending.querySelector(".assistant .message-body");
    botBody.innerHTML = `${formatMessage(pair.assistant)}${buildAssistantExtrasHtml(pair)}`;
    pending.querySelector(".assistant").classList.remove("pending");
    chatScroll.scrollTop = chatScroll.scrollHeight;
  }

  // ── State loading ─────────────────────────────────────────────────────
  async function loadState() {
    try {
      const data = await api("/api/state");
      if (data.user && data.user.is_admin) {
        window.location.href = "/admin";
        return;
      }
      currentUser = data.user;
      isSaved = data.is_saved;
      attachedNames = data.attached_names || [];
      renderAccount();
      renderSaveButton();
      renderConversation(data.chat_pairs || []);
      renderAttachList();
      renderSavedChats(data.saved_sessions || []);
      sectionsLabel.textContent = data.sections && data.sections.length
        ? `Knowledge base: ${data.sections.join(", ")}` : "No knowledge base loaded";
    } catch (err) {
      toast("Could not load chat state.", "error");
    }
  }

  function updateToolSelectionUI() {
    toolInlinePanel.classList.toggle("open", toolsOpen);
    toolInlinePanel.setAttribute("aria-hidden", String(!toolsOpen));
    toolPillGroup.classList.toggle("open", toolsOpen);
    toolPillGroup.setAttribute("aria-hidden", String(!toolsOpen));
    const hasVectorStoreSelection = selectedTools.vectorStores.length > 0;
    toolVectorStoreBtn.classList.toggle("active", selectedTools.vectorStore || hasVectorStoreSelection);
    toolHateSpeechBtn.classList.toggle("active", selectedTools.hateSpeechDetector);
    vectorStoreOptions.classList.toggle("open", toolsOpen && selectedTools.vectorStore);
    vectorStoreOptions.setAttribute("aria-hidden", String(!(toolsOpen && selectedTools.vectorStore)));

    vectorStoreOptionInputs.forEach((input) => {
      const isSelected = selectedTools.vectorStores.includes(input.value);
      input.checked = isSelected;
      input.disabled = !toolsOpen || !selectedTools.vectorStore;
    });

    const pieces = [];
    if (selectedTools.vectorStore || hasVectorStoreSelection) {
      const stores = selectedTools.vectorStores.length
        ? selectedTools.vectorStores.join(", ")
        : " No vector stores selected";
      pieces.push(`Vector store: ${stores}`);
    }
    if (selectedTools.hateSpeechDetector) {
      pieces.push("Hate speech detector");
    }

    toolSelectionSummary.textContent = pieces.length ? pieces.join(" • ") : "";
  }

  toolToggleBtn.addEventListener("click", () => {
    toolsOpen = !toolsOpen;
    updateToolSelectionUI();
  });

  toolVectorStoreBtn.addEventListener("click", () => {
    selectedTools.vectorStore = !selectedTools.vectorStore;
    if (!selectedTools.vectorStore) {
      selectedTools.vectorStores = [];
    }
    updateToolSelectionUI();
  });

  toolHateSpeechBtn.addEventListener("click", () => {
    selectedTools.hateSpeechDetector = !selectedTools.hateSpeechDetector;
    updateToolSelectionUI();
  });

  vectorStoreCloseBtn.addEventListener("click", () => {
    selectedTools.vectorStore = false;
    updateToolSelectionUI();
  });

  vectorStoreOptionInputs.forEach((input) => {
    input.addEventListener("change", () => {
      if (!selectedTools.vectorStore || !toolsOpen) return;
      const value = input.value;
      if (input.checked) {
        if (!selectedTools.vectorStores.includes(value)) {
          selectedTools.vectorStores.push(value);
        }
      } else {
        selectedTools.vectorStores = selectedTools.vectorStores.filter((item) => item !== value);
      }
      updateToolSelectionUI();
    });
  });

  updateToolSelectionUI();

  // ── Sending messages ──────────────────────────────────────────────────
  async function sendMessage() {
    const text = messageInput.value.trim();
    if ((!text && stagedFiles.length === 0) || isSending) return;

    isSending = true;
    sendBtn.disabled = true;
    const filesToSend = stagedFiles;
    stagedFiles = [];

    if (text) appendPendingMessage(text);
    messageInput.value = "";
    autosizeInput();

    const formData = new FormData();
    formData.append("message", text);
    filesToSend.forEach((f) => formData.append("files", f));
    // Send the current tool selections (Data Stores + Analyzer) alongside
    // the message so the backend knows which sources/tools to trigger.
    formData.append("tools", JSON.stringify({
      vector_stores: selectedTools.vectorStores.slice(),
      hate_speech: !!selectedTools.hateSpeechDetector,
    }));

    try {
      const data = await api("/api/chat", { method: "POST", body: formData });
      attachedNames = data.attached_names || attachedNames;
      renderAttachList();
      if (data.answer !== null && data.answer !== undefined) {
        resolvePendingMessage({
          assistant: data.answer,
          searched: data.searched || [],
          references: data.references || [],
          moderation: data.moderation || null,
        });
        isSaved = !!data.is_saved;
        renderSaveButton();
      } else if (data.note) {
        toast(data.note);
      }
    } catch (err) {
      const pending = document.getElementById("pendingPair");
      if (pending) pending.remove();
      toast(err.message || "Something went wrong.", "error");
    } finally {
      isSending = false;
      sendBtn.disabled = false;
      messageInput.focus();
    }
  }

  sendBtn.addEventListener("click", sendMessage);
  messageInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  function autosizeInput() {
    messageInput.style.height = "auto";
    messageInput.style.height = Math.min(messageInput.scrollHeight, 220) + "px";
  }
  messageInput.addEventListener("input", autosizeInput);

  document.querySelectorAll(".suggestion-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      messageInput.value = chip.dataset.prompt || chip.querySelector("strong").textContent;
      autosizeInput();
      sendMessage();
    });
  });

  // ── Attachments ───────────────────────────────────────────────────────
  attachTrigger.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    const files = Array.from(fileInput.files || []);
    const existing = new Set(stagedFiles.map((f) => f.name));
    files.forEach((f) => {
      if (!existing.has(f.name)) { stagedFiles.push(f); existing.add(f.name); }
    });
    fileInput.value = "";
    renderAttachList();
  });

  // ── New chat ──────────────────────────────────────────────────────────
  newChatBtn.addEventListener("click", async () => {
    try {
      await api("/api/new_chat", { method: "POST" });
      stagedFiles = [];
      attachedNames = [];
      isSaved = false;
      renderSaveButton();
      renderAttachList();
      renderConversation([]);
      sidebar.classList.remove("open");
    } catch (err) {
      toast("Could not start a new chat.", "error");
    }
  });

  // ── Save chat ─────────────────────────────────────────────────────────
  saveChatBtn.addEventListener("click", async () => {
    if (!currentUser) {
      openAuthModal("login", "Log in to save this chat");
      return;
    }
    if (isSaved) { toast("This chat is already saved."); return; }
    try {
      const data = await api("/api/save_chat", { method: "POST" });
      isSaved = true;
      renderSaveButton();
      toast("Chat saved.", "success");
      const sessions = await api("/api/sessions");
      renderSavedChats(sessions.sessions);
    } catch (err) {
      toast(err.message || "Could not save chat.", "error");
    }
  });

  // ── Saved-chat sidebar actions ────────────────────────────────────────
  async function loadSession(id) {
    try {
      const data = await api(`/api/sessions/${id}`);
      isSaved = true;
      attachedNames = [];
      renderSaveButton();
      renderAttachList();
      renderConversation(data.chat_pairs || []);
      sidebar.classList.remove("open");
      document.querySelectorAll(".chat-item").forEach((n) => n.classList.remove("active"));
      const active = chatList.querySelector(`[data-session-id="${id}"]`);
      if (active) active.classList.add("active");
    } catch (err) {
      toast("Could not load that chat.", "error");
    }
  }

  async function deleteSession(id) {
    if (!confirm("Delete this saved chat? This cannot be undone.")) return;
    try {
      await api(`/api/sessions/${id}`, { method: "DELETE" });
      const sessions = await api("/api/sessions");
      renderSavedChats(sessions.sessions);
      toast("Chat deleted.");
    } catch (err) {
      toast("Could not delete chat.", "error");
    }
  }

  // ── Auth modal ────────────────────────────────────────────────────────
  function setPasswordVisibility(isVisible) {
    authPasswordField.type = isVisible ? "text" : "password";
    authPasswordToggle.setAttribute("aria-label", isVisible ? "Hide password" : "Show password");
    authPasswordToggle.title = isVisible ? "Hide password" : "Show password";
    authPasswordToggle.setAttribute("aria-pressed", String(isVisible));
  }

  function openAuthModal(mode, subMessage) {
    authMode = mode;
    authError.textContent = "";
    authForm.reset();
    setPasswordVisibility(false);
    if (mode === "login") {
      authTitle.textContent = "Log in";
      authSub.textContent = subMessage || "Log in to save chats and see your history.";
      authSubmit.textContent = "Log in";
      authSwitchText.textContent = "Don't have an account?";
      authSwitchBtn.textContent = "Sign up";
    } else {
      authTitle.textContent = "Create account";
      authSub.textContent = subMessage || "Sign up to start saving your chats.";
      authSubmit.textContent = "Sign up";
      authSwitchText.textContent = "Already have an account?";
      authSwitchBtn.textContent = "Log in";
    }
    authModal.classList.add("open");
    document.getElementById("authUsername").focus();
  }
  function closeAuthModal() { authModal.classList.remove("open"); }

  authModalClose.addEventListener("click", closeAuthModal);
  authModal.addEventListener("click", (e) => { if (e.target === authModal) closeAuthModal(); });
  authSwitchBtn.addEventListener("click", () => openAuthModal(authMode === "login" ? "signup" : "login"));
  authPasswordToggle.addEventListener("click", () => {
    setPasswordVisibility(authPasswordField.type === "password");
    authPasswordField.focus();
  });

  authForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    authError.textContent = "";
    const username = document.getElementById("authUsername").value.trim();
    const password = document.getElementById("authPassword").value;
    const endpoint = authMode === "login" ? "/api/auth/login" : "/api/auth/register";
    try {
      const data = await api(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      currentUser = data.user;
      if (currentUser && currentUser.is_admin) {
        window.location.href = "/admin";
        return;
      }
      renderAccount();
      closeAuthModal();
      toast(`Welcome, ${currentUser.username}.`, "success");
      const sessions = await api("/api/sessions");
      renderSavedChats(sessions.sessions);
    } catch (err) {
      authError.textContent = err.message || "Something went wrong.";
    }
  });

  accountAction.addEventListener("click", async () => {
    if (currentUser) {
      if (!confirm(`Log out of ${currentUser.username}?`)) return;
      try {
        await api("/api/auth/logout", { method: "POST" });
        currentUser = null;
        renderAccount();
        renderSavedChats([]);
        toast("Logged out.");
      } catch (err) {
        toast("Could not log out.", "error");
      }
    } else {
      openAuthModal("login");
    }
  });
  document.getElementById("accountMeta").addEventListener("click", () => {
    if (!currentUser) openAuthModal("login");
  });

  // ── Boot ──────────────────────────────────────────────────────────────
  loadState();
})();
