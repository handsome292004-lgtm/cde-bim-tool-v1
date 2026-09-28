let API = null;
let currentProject = null;
let currentSelection = null;
let accessToken = null;
let pdfCache = [];

const PDF_CACHE_KEY_PREFIX = "CDE_TRIMBLE_PDF_CACHE_V1";
const DEFAULT_CORE_API = "https://app.connect.trimble.com/tc/api/2.0";

function $(id) { return document.getElementById(id); }

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
function safeText(value) { return value === null || value === undefined || value === "" ? "-" : String(value); }
function sanitizeCode(value) { return String(value || "").trim(); }
function getCoreApiBase() { return ($("coreApiBase").value.trim() || DEFAULT_CORE_API).replace(/\/$/, ""); }
function cacheKey() { return `${PDF_CACHE_KEY_PREFIX}:${currentProject?.id || "no_project"}`; }

function setActiveTab(tabName) {
  document.querySelectorAll(".tab-button").forEach(btn => btn.classList.toggle("active", btn.dataset.tab === tabName));
  document.querySelectorAll(".tab-panel").forEach(panel => panel.classList.toggle("active", panel.id === `tab-${tabName}`));
}
function initTabs() {
  document.querySelectorAll(".tab-button").forEach(btn => btn.addEventListener("click", () => setActiveTab(btn.dataset.tab)));
}

function savePdfCache() {
  if (!currentProject?.id) return;
  localStorage.setItem(cacheKey(), JSON.stringify({ scannedAt: new Date().toISOString(), files: pdfCache }));
  updateSourceStats();
}
function loadPdfCache() {
  if (!currentProject?.id) return;
  try {
    const raw = localStorage.getItem(cacheKey());
    if (!raw) return;
    const data = JSON.parse(raw);
    pdfCache = Array.isArray(data.files) ? data.files : [];
    $("lastScanInfo").textContent = data.scannedAt ? new Date(data.scannedAt).toLocaleString() : "-";
    updateSourceStats();
  } catch (err) {
    console.warn("Could not load PDF cache", err);
  }
}
function updateSourceStats() {
  $("pdfCount").textContent = String(pdfCache.length || 0);
  $("tokenStatus").textContent = accessToken ? "Đã có token" : "Chưa có token";
  if (pdfCache.length && currentSelection?.elementCode) renderDocumentsForSelection();
}

function updateSelectionUi(selection) {
  $("projectInfo").textContent = currentProject ? `${currentProject.name || "Project"} (${currentProject.id})` : safeText(selection?.project_id);
  $("modelId").textContent = safeText(selection?.modelId || selection?.model_id);
  $("runtimeId").textContent = safeText(selection?.runtimeId);
  $("ifcGuid").textContent = safeText(selection?.ifcGuid || selection?.ifc_guid);
  $("elementCode").textContent = safeText(selection?.elementCode || selection?.element_code);
  $("elementName").textContent = safeText(selection?.elementName || selection?.element_name);
}

function getSelectionFromEventArg(arg) {
  const data = arg?.data ?? arg;
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.modelObjectIds)) return data.modelObjectIds;
  if (Array.isArray(data?.selection)) return data.selection;
  if (Array.isArray(data?.selected)) return data.selected;
  return [];
}
function getRuntimeIds(modelSelection) {
  return modelSelection?.objectRuntimeIds || modelSelection?.runtimeIds || modelSelection?.objectIds || [];
}

async function initTrimble() {
  $("coreApiBase").value = localStorage.getItem("CDE_CORE_API_BASE") || DEFAULT_CORE_API;
  $("folderFilter").value = localStorage.getItem("CDE_TRIMBLE_PDF_FOLDER_FILTER") || $("folderFilter").value;

  if (!window.TrimbleConnectWorkspace || window.parent === window) {
    setStatus("Test ngoài Trimble", "warn");
    setMessage("selectionMessage", "Đang mở ngoài Trimble. Vào tab Test để kiểm tra bằng mã hiệu.", "warn");
    updateSourceStats();
    return;
  }

  try {
    API = await TrimbleConnectWorkspace.connect(window.parent, async (event, arg) => {
      if (event === "viewer.onSelectionChanged") await handleSelectionChanged(arg);
      if (event === "extension.accessToken") handleAccessTokenEvent(arg);
    }, 30000);

    currentProject = await API.project.getProject();
    setStatus("Đã kết nối Trimble", "ok");
    updateSelectionUi(currentSelection);
    loadPdfCache();
    setMessage("selectionMessage", "Đã kết nối Trimble. Hãy click cấu kiện.", "ok");

    try {
      const existingSelection = await API.viewer.getSelection();
      await handleSelectionChanged(existingSelection);
    } catch (err) {
      console.warn("Could not read initial selection", err);
    }
  } catch (err) {
    console.error(err);
    setStatus("Lỗi Trimble API", "danger");
    setMessage("selectionMessage", `Không kết nối được Workspace API: ${err.message || err}`, "error");
  }
}

function handleAccessTokenEvent(arg) {
  const data = arg?.data ?? arg;
  const token = typeof data === "string" ? data : (data?.accessToken || data?.token || data?.value);
  if (token) {
    accessToken = token;
    updateSourceStats();
    setMessage("sourceMessage", "Đã nhận Access Token từ Trimble.", "ok");
  }
}

async function requestAccessToken() {
  if (!API?.extension) {
    setMessage("sourceMessage", "Chỉ xin token được khi tool đang chạy trong Trimble.", "error");
    return null;
  }
  if (accessToken) return accessToken;
  try {
    if (API.extension.requestPermission) {
      const result = await API.extension.requestPermission("accesstoken");
      if (typeof result === "string" && result.length > 50 && result.split(".").length >= 2) {
        accessToken = result;
      } else {
        setMessage("sourceMessage", `Đã gửi yêu cầu quyền token: ${result}. Nếu có hộp thoại hiện ra, hãy bấm Allow/Cho phép.`, "warn");
      }
    } else if (API.extension.getPermission) {
      accessToken = await API.extension.getPermission("accesstoken");
    }
  } catch (err) {
    setMessage("sourceMessage", `Không lấy được token: ${err.message || err}`, "error");
  }
  updateSourceStats();
  return accessToken;
}

async function handleSelectionChanged(arg) {
  const selection = getSelectionFromEventArg(arg);
  if (!selection.length) {
    currentSelection = null;
    updateSelectionUi(null);
    renderDocuments([]);
    setMessage("selectionMessage", "Chưa chọn cấu kiện hoặc selection rỗng.", "warn");
    return;
  }

  const first = selection[0];
  const modelId = first.modelId || first.model_id || first.modelID;
  const runtimeIds = getRuntimeIds(first);
  if (!modelId || !runtimeIds.length) {
    setMessage("selectionMessage", "Không lấy được modelId hoặc runtimeId từ selection.", "error");
    return;
  }

  const runtimeId = Number(runtimeIds[0]);
  let ifcGuid = null, elementCode = null, elementName = null;
  try {
    const objectIds = await API.viewer.convertToObjectIds(modelId, [runtimeId]);
    ifcGuid = objectIds?.[0];
  } catch (err) {
    console.warn("Cannot convert runtime id", err);
  }

  try {
    const props = await API.viewer.getObjectProperties(modelId, [runtimeId]);
    const extracted = extractElementInfoFromProperties(props?.[0]);
    elementCode = extracted.elementCode;
    elementName = extracted.elementName;
  } catch (err) {
    console.warn("Could not read object properties", err);
  }

  currentSelection = { project_id: currentProject?.id || null, modelId, runtimeId, ifcGuid, elementCode, elementName };
  updateSelectionUi(currentSelection);

  if (!elementCode) {
    renderDocuments([]);
    setMessage("selectionMessage", "Đã chọn cấu kiện nhưng chưa đọc được Mã hiệu từ Thong_tin_BIM.", "warn");
    return;
  }

  setMessage("selectionMessage", `Đã chọn cấu kiện: ${elementCode}.`, "ok");
  renderDocumentsForSelection();
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
      const value = node.value || node.propertyValue || node.val;
      if (name !== undefined && value !== undefined) pairs.push({ name: String(name), value: String(value) });
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

async function scanTrimblePdfs() {
  localStorage.setItem("CDE_CORE_API_BASE", getCoreApiBase());
  localStorage.setItem("CDE_TRIMBLE_PDF_FOLDER_FILTER", $("folderFilter").value.trim());

  if (!currentProject?.id) {
    setMessage("sourceMessage", "Chưa có Project ID. Hãy mở tool trong Trimble Project.", "error");
    return;
  }
  const token = await requestAccessToken();
  if (!token) return;

  setMessage("sourceMessage", "Đang quét file PDF trong Trimble Project...", "warn");
  try {
    const files = await fetchTrimbleProjectFiles(currentProject.id, token);
    const folderFilter = normalizeForMatch($("folderFilter").value.trim());
    const pdfs = files
      .filter(f => String(f.name || "").toLowerCase().endsWith(".pdf"))
      .filter(f => {
        if (!folderFilter) return true;
        const path = normalizeForMatch([f.path, f.folderPath, f.location, f.folderName].filter(Boolean).join(" / "));
        return path.includes(folderFilter) || normalizeForMatch(f.name).includes(folderFilter);
      })
      .map(normalizeTrimbleFile);

    pdfCache = dedupeByNameAndId(pdfs);
    savePdfCache();
    $("lastScanInfo").textContent = new Date().toLocaleString();
    setMessage("sourceMessage", `Đã quét ${pdfCache.length} file PDF từ Trimble Project.`, pdfCache.length ? "ok" : "warn");
    renderDocumentsForSelection();
  } catch (err) {
    console.error(err);
    setMessage("sourceMessage", `Lỗi khi quét Trimble PDF: ${err.message || err}`, "error");
  }
}

async function trimbleApiFetch(url, token, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("Accept", "application/json, application/pdf, */*");
  return fetch(url, { ...options, headers });
}

async function fetchTrimbleProjectFiles(projectId, token) {
  const base = getCoreApiBase();
  const encodedProject = encodeURIComponent(projectId);
  const candidates = [
    `${base}/projects/${encodedProject}/files?fullyLoaded=true&pageSize=1000`,
    `${base}/projects/${encodedProject}/files?includeFolders=true&pageSize=1000`,
    `${base}/projects/${encodedProject}/files?pageSize=1000`,
    `${base}/projects/${encodedProject}/files`
  ];

  let lastError = null;
  for (const url of candidates) {
    try {
      const res = await trimbleApiFetch(url, token);
      if (!res.ok) {
        lastError = new Error(`${res.status} ${res.statusText} at ${url}`);
        continue;
      }
      const data = await res.json();
      const items = collectFileLikeObjects(data);
      if (items.length) return items;
      lastError = new Error(`API trả về 0 file tại ${url}`);
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError || new Error("Không đọc được danh sách file từ Trimble Core API.");
}

function collectFileLikeObjects(data) {
  const output = [];
  const seen = new WeakSet();
  function walk(node, inheritedPath = "") {
    if (!node) return;
    if (Array.isArray(node)) return node.forEach(x => walk(x, inheritedPath));
    if (typeof node !== "object") return;
    if (seen.has(node)) return;
    seen.add(node);

    const name = node.name || node.fileName || node.title || node.displayName;
    const type = String(node.type || node.objectType || node.itemType || "").toLowerCase();
    const path = node.path || node.folderPath || node.location || inheritedPath;
    if (name && (type.includes("file") || String(name).includes("."))) output.push({ ...node, name, path });

    const nextPath = name && (type.includes("folder") || node.children || node.items) ? [inheritedPath, name].filter(Boolean).join("/") : inheritedPath;
    for (const value of Object.values(node)) walk(value, nextPath);
  }
  walk(data, "");
  return output;
}

function normalizeTrimbleFile(f) {
  const id = f.id || f.fileId || f.identifier || f.fileIdentifier || f.file_id || f.objectId || f.versionId || f.version_id;
  const name = f.name || f.fileName || f.title || f.displayName;
  const path = f.path || f.folderPath || f.location || f.parentPath || "";
  const directUrl = f.downloadUrl || f.url || f.webUrl || f.viewerUrl || f?.links?.download?.href || f?._links?.download?.href || f?.links?.self?.href || f?._links?.self?.href || "";
  return { id, name, path, directUrl, raw: f };
}
function dedupeByNameAndId(files) {
  const map = new Map();
  for (const f of files) map.set(`${f.id || "noid"}:${f.name}:${f.path}`, f);
  return [...map.values()].sort((a,b) => String(a.name).localeCompare(String(b.name)));
}
function normalizeForMatch(text) {
  return String(text || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9_\-./ ]/g, "");
}
function findDocsByCode(elementCode) {
  const code = normalizeForMatch(elementCode);
  if (!code) return [];
  return pdfCache.filter(f => normalizeForMatch(f.name).includes(code));
}
function renderDocumentsForSelection() {
  if (!currentSelection?.elementCode) {
    renderDocuments([]);
    return;
  }
  const docs = findDocsByCode(currentSelection.elementCode);
  renderDocuments(docs);
  const msg = docs.length
    ? `Tìm thấy ${docs.length} PDF khớp Mã hiệu ${currentSelection.elementCode}.`
    : `Chưa thấy PDF khớp Mã hiệu ${currentSelection.elementCode}. Hãy quét lại nguồn PDF hoặc kiểm tra tên file.`;
  setMessage("documentsMessage", msg, docs.length ? "ok" : "warn");
}
function renderDocuments(docs) {
  const box = $("documentsList");
  if (!currentSelection) {
    box.className = "documents empty";
    box.innerHTML = "Chưa có cấu kiện được chọn.";
    return;
  }
  if (!docs.length) {
    box.className = "documents empty";
    box.innerHTML = "Cấu kiện này chưa có hồ sơ PDF khớp Mã hiệu.";
    return;
  }
  box.className = "documents";
  box.innerHTML = docs.map((doc, index) => `
    <article class="doc-item">
      <div class="doc-title"><span>${escapeHtml(doc.name)}</span><span>#${index + 1}</span></div>
      <div class="doc-meta">${escapeHtml(doc.path || "Trimble Project")}</div>
      <div class="doc-actions">
        <button class="small" type="button" onclick="openTrimblePdf(${index})">Mở PDF</button>
        <button class="small secondary" type="button" onclick="copyFileName(${index})">Copy tên</button>
      </div>
    </article>`).join("");
  window.__lastDocs = docs;
}

async function openTrimblePdf(index) {
  const docs = window.__lastDocs || [];
  const doc = docs[index];
  if (!doc) return;
  const token = accessToken || await requestAccessToken();
  if (!token) {
    setMessage("documentsMessage", "Cần Access Token để mở PDF từ Trimble API.", "error");
    return;
  }
  const urls = buildDownloadCandidates(doc);
  for (const url of urls) {
    try {
      const res = await trimbleApiFetch(url, token);
      if (!res.ok) continue;
      const contentType = res.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        const data = await res.json();
        const nextUrl = data.url || data.downloadUrl || data.href || data?.links?.download?.href || data?._links?.download?.href;
        if (nextUrl) window.open(nextUrl, "_blank", "noopener,noreferrer");
        return;
      }
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      window.open(blobUrl, "_blank", "noopener,noreferrer");
      return;
    } catch (err) {
      console.warn("PDF open candidate failed", url, err);
    }
  }
  if (doc.directUrl) window.open(doc.directUrl, "_blank", "noopener,noreferrer");
  else setMessage("documentsMessage", "Không mở được PDF. API không trả download URL hợp lệ.", "error");
}
function buildDownloadCandidates(doc) {
  const base = getCoreApiBase();
  const projectId = encodeURIComponent(currentProject?.id || "");
  const id = encodeURIComponent(doc.id || "");
  return [
    doc.directUrl,
    id ? `${base}/projects/${projectId}/files/${id}/download` : null,
    id ? `${base}/projects/${projectId}/files/${id}/content` : null,
    id ? `${base}/files/${id}/download?projectId=${projectId}` : null,
    id ? `${base}/files/${id}/download` : null,
    id ? `${base}/files/${id}` : null
  ].filter(Boolean);
}
function copyFileName(index) {
  const docs = window.__lastDocs || [];
  const doc = docs[index];
  if (doc?.name) navigator.clipboard?.writeText(doc.name);
}
function useManualSelection() {
  currentProject = currentProject || { id: "manual_project", name: "Manual Test" };
  currentSelection = { elementCode: $("manualElementCode").value.trim(), elementName: null, ifcGuid: "manual", modelId: "manual", runtimeId: "manual" };
  updateSelectionUi(currentSelection);
  renderDocumentsForSelection();
  setActiveTab("docs");
}
function clearPdfCache() {
  pdfCache = [];
  if (currentProject?.id) localStorage.removeItem(cacheKey());
  updateSourceStats();
  renderDocumentsForSelection();
  setMessage("sourceMessage", "Đã xóa cache PDF.", "ok");
}
function escapeHtml(value) {
  return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}
window.openTrimblePdf = openTrimblePdf;
window.copyFileName = copyFileName;

window.addEventListener("DOMContentLoaded", () => {
  initTabs();
  $("requestTokenBtn").addEventListener("click", requestAccessToken);
  $("scanTrimblePdfBtn").addEventListener("click", scanTrimblePdfs);
  $("clearPdfCacheBtn").addEventListener("click", clearPdfCache);
  $("refreshMatchBtn").addEventListener("click", renderDocumentsForSelection);
  $("manualSelectBtn").addEventListener("click", useManualSelection);
  initTrimble();
});
