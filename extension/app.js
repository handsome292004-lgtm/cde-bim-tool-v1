let API = null;
let currentProject = null;
let currentSelection = null;
let libraryDocs = [];
let currentLinkedDocs = [];

const DB_NAME = "CDE_BIM_HOSO_DB_V1";
const DB_VERSION = 1;
const DOC_STORE = "docs";
const LINK_STORE = "links";

function $(id) { return document.getElementById(id); }
function safeText(v) { return v === null || v === undefined || v === "" ? "-" : String(v); }
function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
function setMessage(id, text, type = "") {
  const el = $(id);
  if (!el) return;
  el.textContent = text || "";
  el.className = `message ${type}`.trim();
}
function setStatus(text, type = "gray") {
  const el = $("apiStatus");
  el.textContent = text;
  el.className = `badge badge-${type}`;
}
function setActiveTab(name) {
  document.querySelectorAll(".tab-button")
    .forEach(btn => btn.classList.toggle("active", btn.dataset.tab === name));
  document.querySelectorAll(".tab-panel")
    .forEach(panel => panel.classList.toggle("active", panel.id === `tab-${name}`));
}
function initTabs() {
  document.querySelectorAll(".tab-button")
    .forEach(btn => btn.addEventListener("click", () => setActiveTab(btn.dataset.tab)));
}

/* ---------------- IndexedDB ---------------- */

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(DOC_STORE)) {
        db.createObjectStore(DOC_STORE, { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains(LINK_STORE)) {
        db.createObjectStore(LINK_STORE, { keyPath: "objectKey" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function dbGetAll(storeName) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readonly");
    const req = tx.objectStore(storeName).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
    tx.oncomplete = () => db.close();
  });
}
async function dbGet(storeName, key) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readonly");
    const req = tx.objectStore(storeName).get(key);
    req.onsuccess = () => resolve(req.result || null);
    req.onerror = () => reject(req.error);
    tx.oncomplete = () => db.close();
  });
}
async function dbPut(storeName, value) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readwrite");
    tx.objectStore(storeName).put(value);
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = () => reject(tx.error);
  });
}
async function dbDelete(storeName, key) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readwrite");
    tx.objectStore(storeName).delete(key);
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = () => reject(tx.error);
  });
}
async function dbClear(storeName) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readwrite");
    tx.objectStore(storeName).clear();
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = () => reject(tx.error);
  });
}

/* ---------------- PDF library ---------------- */

function makeDocId(file) {
  const raw = `${file.name}|${file.size}|${file.lastModified}|${file.webkitRelativePath || ""}`;
  let h = 2166136261;
  for (let i = 0; i < raw.length; i++) {
    h ^= raw.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return `pdf_${(h >>> 0).toString(16)}`;
}
function isPdf(file) {
  return file && (
    file.type === "application/pdf" ||
    String(file.name || "").toLowerCase().endsWith(".pdf")
  );
}
function formatBytes(bytes) {
  const n = Number(bytes || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}
function normalize(value) {
  return String(value || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\.pdf$/i, "")
    .replace(/[^a-z0-9_\-./ ]/g, "")
    .trim();
}
function matchDocsByCode(code) {
  const c = normalize(code);
  if (!c) return [];
  const exact = [];
  const partial = [];
  for (const doc of libraryDocs) {
    const name = normalize(doc.name);
    if (name === c) exact.push(doc);
    else if (name.includes(c)) partial.push(doc);
  }
  return [...exact, ...partial];
}
async function importFiles(fileList) {
  const files = [...fileList].filter(isPdf);
  if (!files.length) {
    setMessage("libraryMessage", "Không có file PDF hợp lệ.", "warn");
    return;
  }
  let added = 0;
  for (const file of files) {
    const doc = {
      id: makeDocId(file),
      name: file.name,
      size: file.size,
      type: file.type || "application/pdf",
      lastModified: file.lastModified,
      relativePath: file.webkitRelativePath || "",
      blob: file,
      addedAt: new Date().toISOString(),
    };
    await dbPut(DOC_STORE, doc);
    added++;
  }
  await refreshLibrary();
  setMessage("libraryMessage", `Đã thêm ${added} file PDF vào thư viện.`, "ok");
}
async function refreshLibrary() {
  libraryDocs = await dbGetAll(DOC_STORE);
  libraryDocs.sort((a, b) => String(a.name).localeCompare(String(b.name), "vi"));
  $("summaryDocs").textContent = String(libraryDocs.length);
  renderLibrary();
  renderQuickMatches();
}
function renderLibrary() {
  const list = $("libraryList");
  const q = normalize($("librarySearch")?.value || "");
  const docs = q
    ? libraryDocs.filter(d => normalize(`${d.name} ${d.relativePath}`).includes(q))
    : libraryDocs;

  if (!docs.length) {
    list.innerHTML = `<div class="empty-state">${
      libraryDocs.length ? "Không có hồ sơ phù hợp từ khóa." : "Chưa có PDF trong thư viện."
    }</div>`;
    return;
  }

  list.innerHTML = docs.map(doc => `
    <div class="file-item">
      <div>
        <div class="file-name">${escapeHtml(doc.name)}</div>
        <div class="file-meta">${escapeHtml(doc.relativePath || "Hồ sơ nghiệm thu")} · ${formatBytes(doc.size)}</div>
      </div>
      <div class="file-actions">
        <button class="icon-btn open" type="button" onclick="openLibraryDoc('${doc.id}')">Mở</button>
        <button class="icon-btn remove" type="button" onclick="removeLibraryDoc('${doc.id}')">Xóa</button>
      </div>
    </div>
  `).join("");
}
async function openLibraryDoc(id) {
  const doc = await dbGet(DOC_STORE, id);
  if (!doc?.blob) return;
  const url = URL.createObjectURL(doc.blob);
  window.open(url, "_blank", "noopener,noreferrer");
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
async function removeLibraryDoc(id) {
  await dbDelete(DOC_STORE, id);
  await refreshLibrary();
  await loadCurrentLinks();
  setMessage("libraryMessage", "Đã xóa hồ sơ khỏi thư viện.", "ok");
}
async function clearLibrary() {
  if (!confirm("Xóa toàn bộ PDF trong thư viện dashboard?")) return;
  await dbClear(DOC_STORE);
  await dbClear(LINK_STORE);
  await refreshLibrary();
  await loadCurrentLinks();
  setMessage("libraryMessage", "Đã xóa toàn bộ thư viện và liên kết.", "ok");
}

/* ---------------- Trimble selection ---------------- */

function getSelectionFromEventArg(arg) {
  const data = arg?.data ?? arg;
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.modelObjectIds)) return data.modelObjectIds;
  if (Array.isArray(data?.selection)) return data.selection;
  if (Array.isArray(data?.selected)) return data.selected;
  return [];
}
function getRuntimeIds(modelSelection) {
  return modelSelection?.objectRuntimeIds ||
    modelSelection?.runtimeIds ||
    modelSelection?.objectIds || [];
}
function extractElementInfoFromProperties(objectProperties) {
  const result = { elementCode: null, elementName: null };
  if (!objectProperties) return result;
  const pairs = [];
  function walk(node) {
    if (!node) return;
    if (Array.isArray(node)) return node.forEach(walk);
    if (typeof node === "object") {
      const name = node.name || node.propertyName || node.key || node.label;
      const value = node.value ?? node.propertyValue ?? node.val;
      if (name !== undefined && value !== undefined) {
        pairs.push({ name: String(name), value: String(value) });
      }
      Object.values(node).forEach(walk);
    }
  }
  walk(objectProperties);

  const codeKeys = ["mã hiệu", "ma hieu", "ma_hieu", "element_code", "mã cấu kiện", "ma cau kien"];
  const nameKeys = ["name", "tên", "ten", "tên cấu kiện", "ten cau kien", "element_name"];

  for (const pair of pairs) {
    const key = pair.name.trim().toLowerCase();
    if (!result.elementCode && codeKeys.some(k => key.includes(k))) result.elementCode = pair.value;
    if (!result.elementName && nameKeys.some(k => key === k || key.includes(k))) result.elementName = pair.value;
  }
  result.elementName = result.elementName || objectProperties.name || objectProperties.Name || null;
  return result;
}
function updateSelectionUi() {
  $("elementCode").textContent = safeText(currentSelection?.elementCode);
  $("elementName").textContent = safeText(currentSelection?.elementName);
  $("ifcGuid").textContent = safeText(currentSelection?.ifcGuid);
  $("summaryCode").textContent = safeText(currentSelection?.elementCode);
}
function currentObjectKey() {
  if (!currentSelection) return null;
  const project = currentProject?.id || "project";
  const model = currentSelection.modelId || "model";
  const object = currentSelection.ifcGuid || currentSelection.runtimeId || "object";
  return `${project}::${model}::${object}`;
}

async function initTrimble() {
  if (!window.TrimbleConnectWorkspace || window.parent === window) {
    setStatus("Mở ngoài Trimble", "warn");
    setMessage("selectionMessage", "Dashboard đang mở ngoài Trimble.", "warn");
    return;
  }

  try {
    API = await TrimbleConnectWorkspace.connect(window.parent, async (event, arg) => {
      if (event === "viewer.onSelectionChanged") await handleSelectionChanged(arg);
    }, 30000);

    currentProject = await API.project.getProject();
    setStatus("Đã kết nối Trimble", "ok");
    setMessage("selectionMessage", "Đã kết nối. Hãy click một cấu kiện.", "ok");

    try {
      const existing = await API.viewer.getSelection();
      await handleSelectionChanged(existing);
    } catch (e) {
      console.warn("Could not read initial selection", e);
    }
  } catch (err) {
    console.error(err);
    setStatus("Lỗi kết nối", "danger");
    setMessage("selectionMessage", `Không kết nối được Trimble: ${err.message || err}`, "error");
  }
}

async function handleSelectionChanged(arg) {
  const selection = getSelectionFromEventArg(arg);
  if (!selection.length) {
    currentSelection = null;
    updateSelectionUi();
    renderQuickMatches();
    await loadCurrentLinks();
    setMessage("selectionMessage", "Chưa chọn cấu kiện.", "warn");
    return;
  }

  const first = selection[0];
  const modelId = first.modelId || first.model_id || first.modelID;
  const runtimeIds = getRuntimeIds(first);
  if (!modelId || !runtimeIds.length) {
    setMessage("selectionMessage", "Không đọc được modelId/runtimeId.", "error");
    return;
  }

  const runtimeId = Number(runtimeIds[0]);
  let ifcGuid = null;
  let elementCode = null;
  let elementName = null;

  try {
    const ids = await API.viewer.convertToObjectIds(modelId, [runtimeId]);
    ifcGuid = ids?.[0] || null;
  } catch (err) {
    console.warn("convertToObjectIds failed", err);
  }

  try {
    const props = await API.viewer.getObjectProperties(modelId, [runtimeId]);
    const info = extractElementInfoFromProperties(props?.[0]);
    elementCode = info.elementCode;
    elementName = info.elementName;
  } catch (err) {
    console.warn("getObjectProperties failed", err);
  }

  currentSelection = {
    modelId,
    runtimeId,
    ifcGuid,
    elementCode,
    elementName,
  };

  updateSelectionUi();
  renderQuickMatches();
  await loadCurrentLinks();

  if (elementCode) {
    setMessage("selectionMessage", `Đã chọn cấu kiện ${elementCode}.`, "ok");
  } else {
    setMessage("selectionMessage", "Đã chọn cấu kiện nhưng chưa đọc được Mã hiệu.", "warn");
  }
}

/* ---------------- Local linking ---------------- */

function renderQuickMatches() {
  const box = $("quickMatches");
  if (!currentSelection?.elementCode) {
    box.className = "empty-state";
    box.innerHTML = "Chưa có cấu kiện hoặc Mã hiệu.";
    return;
  }

  const docs = matchDocsByCode(currentSelection.elementCode);
  if (!docs.length) {
    box.className = "empty-state";
    box.innerHTML = `Không tìm thấy PDF trùng mã <b>${escapeHtml(currentSelection.elementCode)}</b>.`;
    return;
  }

  box.className = "file-list";
  box.innerHTML = docs.map(doc => `
    <div class="file-item">
      <div>
        <div class="file-name">${escapeHtml(doc.name)}</div>
        <span class="match-tag">Khớp ${escapeHtml(currentSelection.elementCode)}</span>
      </div>
      <div class="file-actions">
        <button class="icon-btn open" type="button" onclick="openLibraryDoc('${doc.id}')">Mở</button>
      </div>
    </div>
  `).join("");
}

async function findAndLinkCurrent() {
  if (!currentSelection?.elementCode) {
    setMessage("selectionMessage", "Hãy chọn cấu kiện có Mã hiệu trước.", "warn");
    return;
  }
  if (!libraryDocs.length) {
    setMessage("selectionMessage", "Thư viện chưa có PDF. Hãy thêm hồ sơ trước.", "warn");
    setActiveTab("library");
    return;
  }

  const matches = matchDocsByCode(currentSelection.elementCode);
  if (!matches.length) {
    setMessage("selectionMessage", `Không tìm thấy PDF trùng mã ${currentSelection.elementCode}.`, "warn");
    return;
  }

  const objectKey = currentObjectKey();
  const record = {
    objectKey,
    projectId: currentProject?.id || null,
    modelId: currentSelection.modelId,
    runtimeId: currentSelection.runtimeId,
    ifcGuid: currentSelection.ifcGuid,
    elementCode: currentSelection.elementCode,
    elementName: currentSelection.elementName,
    docIds: matches.map(d => d.id),
    updatedAt: new Date().toISOString(),
  };
  await dbPut(LINK_STORE, record);
  await loadCurrentLinks();
  setMessage(
    "selectionMessage",
    `Đã gắn ${matches.length} hồ sơ với ${currentSelection.elementCode}.`,
    "ok"
  );
  setActiveTab("links");
}

async function loadCurrentLinks() {
  const list = $("linkedList");
  currentLinkedDocs = [];

  const key = currentObjectKey();
  if (!key) {
    $("summaryLinked").textContent = "0";
    list.innerHTML = `<div class="empty-state">Chưa có cấu kiện được chọn.</div>`;
    setMessage("linksMessage", "", "");
    return;
  }

  const record = await dbGet(LINK_STORE, key);
  if (!record?.docIds?.length) {
    $("summaryLinked").textContent = "0";
    list.innerHTML = `<div class="empty-state">Cấu kiện này chưa được gắn hồ sơ.</div>`;
    setMessage("linksMessage", "Bạn có thể bấm “Tìm hồ sơ trùng Mã hiệu và gắn”.", "warn");
    return;
  }

  const docs = [];
  for (const id of record.docIds) {
    const doc = await dbGet(DOC_STORE, id);
    if (doc) docs.push(doc);
  }
  currentLinkedDocs = docs;
  $("summaryLinked").textContent = String(docs.length);

  if (!docs.length) {
    list.innerHTML = `<div class="empty-state">Liên kết có tồn tại nhưng file PDF đã bị xóa khỏi thư viện.</div>`;
    return;
  }

  list.innerHTML = docs.map(doc => `
    <div class="file-item">
      <div>
        <div class="file-name">${escapeHtml(doc.name)}</div>
        <div class="file-meta">Đã gắn với ${escapeHtml(record.elementCode || "-")}</div>
      </div>
      <div class="file-actions">
        <button class="icon-btn open" type="button" onclick="openLibraryDoc('${doc.id}')">Mở PDF</button>
      </div>
    </div>
  `).join("");

  setMessage("linksMessage", `Đã gắn ${docs.length} hồ sơ với cấu kiện này.`, "ok");
}
async function unlinkCurrent() {
  const key = currentObjectKey();
  if (!key) return;
  await dbDelete(LINK_STORE, key);
  await loadCurrentLinks();
  setMessage("linksMessage", "Đã bỏ liên kết hồ sơ của cấu kiện hiện tại.", "ok");
}

/* ---------------- Drag/drop + startup ---------------- */

function setupPickers() {
  $("pickFilesBtn").addEventListener("click", () => $("filePicker").click());
  $("pickFolderBtn").addEventListener("click", () => $("folderPicker").click());

  $("filePicker").addEventListener("change", async e => {
    await importFiles(e.target.files);
    e.target.value = "";
  });
  $("folderPicker").addEventListener("change", async e => {
    await importFiles(e.target.files);
    e.target.value = "";
  });

  const zone = $("dropZone");
  ["dragenter", "dragover"].forEach(name => {
    zone.addEventListener(name, e => {
      e.preventDefault();
      zone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach(name => {
    zone.addEventListener(name, e => {
      e.preventDefault();
      zone.classList.remove("dragover");
    });
  });
  zone.addEventListener("drop", async e => {
    await importFiles(e.dataTransfer.files);
  });
}

window.openLibraryDoc = openLibraryDoc;
window.removeLibraryDoc = removeLibraryDoc;

window.addEventListener("DOMContentLoaded", async () => {
  initTabs();
  setupPickers();

  $("librarySearch").addEventListener("input", renderLibrary);
  $("clearLibraryBtn").addEventListener("click", clearLibrary);
  $("findAndLinkBtn").addEventListener("click", findAndLinkCurrent);
  $("unlinkCurrentBtn").addEventListener("click", unlinkCurrent);

  await refreshLibrary();
  await initTrimble();
});
