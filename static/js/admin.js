(() => {
  "use strict";

  const sectionSelect = document.getElementById("sectionSelect");
  const newSectionInput = document.getElementById("newSectionInput");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const pendingList = document.getElementById("pendingList");
  const uploadBtn = document.getElementById("uploadBtn");
  const uploadStatus = document.getElementById("uploadStatus");
  const refreshFilesBtn = document.getElementById("refreshFilesBtn");
  const fileTable = document.getElementById("fileTable");
  const folderContentsSub = document.getElementById("folderContentsSub");
  const rebuildBtn = document.getElementById("rebuildBtn");
  const rebuildStatus = document.getElementById("rebuildStatus");
  const logoutBtn = document.getElementById("logoutBtn");
  const toastStack = document.getElementById("toastStack");

  let pendingFiles = [];

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function toast(message, type = "") {
    const el = document.createElement("div");
    el.className = `toast ${type}`.trim();
    el.textContent = message;
    toastStack.appendChild(el);
    requestAnimationFrame(() => el.classList.add("show"));
    setTimeout(() => { el.classList.remove("show"); setTimeout(() => el.remove(), 220); }, 3200);
  }

  async function api(url, options = {}) {
    const res = await fetch(url, { credentials: "same-origin", ...options });
    let data = null;
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      const err = new Error((data && data.error) || `Request failed (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  // ── Guard: admin only ────────────────────────────────────────────────
  async function guard() {
    try {
      const data = await api("/api/auth/me");
      if (!data.user || !data.user.is_admin) {
        window.location.href = "/";
      }
    } catch (_) {
      window.location.href = "/";
    }
  }

  // ── Sections dropdown ────────────────────────────────────────────────
  async function loadSections(selectName) {
    try {
      const data = await api("/api/admin/sections");
      sectionSelect.innerHTML = '<option value="">— Select a folder —</option>';
      data.sections.forEach((s) => {
        const opt = document.createElement("option");
        opt.value = s.name;
        opt.textContent = `${s.name} (${s.pdf_count} PDF${s.pdf_count === 1 ? "" : "s"})`;
        sectionSelect.appendChild(opt);
      });
      if (selectName) sectionSelect.value = selectName;
      if (sectionSelect.value) loadFiles(sectionSelect.value);
    } catch (err) {
      toast("Could not load folders.", "error");
    }
  }

  async function loadFiles(section) {
    if (!section) {
      fileTable.innerHTML = "";
      folderContentsSub.textContent = "Select a folder above to see its PDFs.";
      return;
    }
    folderContentsSub.textContent = `Files in ${section}/`;
    try {
      const data = await api(`/api/admin/pdfs?section=${encodeURIComponent(section)}`);
      renderFileTable(section, data.files || []);
    } catch (err) {
      toast("Could not load files for that folder.", "error");
    }
  }

  function renderFileTable(section, files) {
    fileTable.innerHTML = "";
    if (!files.length) {
      fileTable.innerHTML = '<div class="file-table-empty">No PDFs in this folder yet.</div>';
      return;
    }
    files.forEach((f) => {
      const row = document.createElement("div");
      row.className = "file-row";
      row.innerHTML = `
        <div class="file-meta">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path></svg>
          <span class="file-name">${escapeHtml(f.name)}</span>
          <span>${f.size_kb} KB</span>
        </div>
        <button class="icon-btn delete-file" title="Delete file">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6h16Z"/></svg>
        </button>`;
      row.querySelector(".delete-file").addEventListener("click", async () => {
        if (!confirm(`Delete ${f.name}? This cannot be undone.`)) return;
        try {
          await api("/api/admin/pdfs", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ section, filename: f.name }),
          });
          toast(`Deleted ${f.name}.`);
          loadFiles(section);
          loadSections(section);
        } catch (err) {
          toast(err.message || "Could not delete file.", "error");
        }
      });
      fileTable.appendChild(row);
    });
  }

  sectionSelect.addEventListener("change", () => loadFiles(sectionSelect.value));
  refreshFilesBtn.addEventListener("click", () => loadFiles(sectionSelect.value));

  // ── Drag & drop / file picker ────────────────────────────────────────
  function addPendingFiles(fileListLike) {
    const files = Array.from(fileListLike || []).filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    const existing = new Set(pendingFiles.map((f) => f.name));
    files.forEach((f) => { if (!existing.has(f.name)) { pendingFiles.push(f); existing.add(f.name); } });
    renderPendingList();
  }

  function renderPendingList() {
    pendingList.innerHTML = "";
    pendingFiles.forEach((file, idx) => {
      const pill = document.createElement("div");
      pill.className = "attachment-preview";
      pill.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path></svg>
        <span>${escapeHtml(file.name)}</span>
        <span class="remove-pill" data-idx="${idx}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </span>`;
      pill.querySelector(".remove-pill").addEventListener("click", () => {
        pendingFiles.splice(idx, 1);
        renderPendingList();
      });
      pendingList.appendChild(pill);
    });
  }

  dropzone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => { addPendingFiles(fileInput.files); fileInput.value = ""; });
  ["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.add("dragover"); })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.remove("dragover"); })
  );
  dropzone.addEventListener("drop", (e) => addPendingFiles(e.dataTransfer.files));

  // ── Upload ───────────────────────────────────────────────────────────
  uploadBtn.addEventListener("click", async () => {
    const section = sectionSelect.value;
    const newSection = newSectionInput.value.trim();
    if (!section && !newSection) {
      uploadStatus.textContent = "Choose or name a folder first.";
      return;
    }
    if (!pendingFiles.length) {
      uploadStatus.textContent = "Attach at least one PDF first.";
      return;
    }
    uploadBtn.disabled = true;
    uploadStatus.textContent = "Uploading…";

    const formData = new FormData();
    if (newSection) formData.append("new_section", newSection);
    else formData.append("section", section);
    pendingFiles.forEach((f) => formData.append("files", f));

    try {
      const data = await api("/api/admin/upload", { method: "POST", body: formData });
      let msg = `Uploaded ${data.saved.length} file(s) to ${data.section}/.`;
      if (data.skipped.length) msg += ` Skipped ${data.skipped.length} (already existed).`;
      toast(msg, "success");
      uploadStatus.textContent = "";
      pendingFiles = [];
      newSectionInput.value = "";
      renderPendingList();
      await loadSections(data.section);
    } catch (err) {
      toast(err.message || "Upload failed.", "error");
      uploadStatus.textContent = err.message || "Upload failed.";
    } finally {
      uploadBtn.disabled = false;
    }
  });

  // ── Rebuild index ────────────────────────────────────────────────────
  rebuildBtn.addEventListener("click", async () => {
    rebuildBtn.disabled = true;
    rebuildStatus.textContent = "Rebuilding… this can take a while for large folders.";
    try {
      const data = await api("/api/admin/rebuild_index", { method: "POST" });
      rebuildStatus.textContent = `Done. Sections: ${data.sections.join(", ") || "none"}.`;
      toast("Index rebuilt.", "success");
    } catch (err) {
      rebuildStatus.textContent = err.message || "Rebuild failed.";
      toast(err.message || "Rebuild failed.", "error");
    } finally {
      rebuildBtn.disabled = false;
    }
  });

  // ── Logout ───────────────────────────────────────────────────────────
  logoutBtn.addEventListener("click", async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      window.location.href = "/";
    }
  });

  // ── Boot ─────────────────────────────────────────────────────────────
  guard();
  loadSections();
})();
