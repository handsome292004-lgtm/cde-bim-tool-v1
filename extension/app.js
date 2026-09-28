let API = null;
let currentProject = null;
let currentSelection = null;

const DEFAULT_BACKEND_URL = "http://localhost:8000";

function $(id) {
  return document.getElementById(id);
}

function getBackendUrl() {
  return (localStorage.getItem("CDE_BACKEND_URL") || DEFAULT_BACKEND_URL).replace(/\/$/, "");
}

function setMessage(id, text, type = "") {
  const el = $(id);
  el.textContent = text || "";
  el.className = `message ${type}`.trim();
}

function setStatus(text, type = "gray") {
  const el = $("apiStatus");
  el.textContent = text;
  el.className = `badge badge-${type}`;
}

function safeText(value) {
  return value === null || value === undefined || value === "" ? "-" : String(value);
}

function updateSelectionUi(selection) {
  $("projectInfo").textContent = currentProject ? `${currentProject.name || "Project"} (${currentProject.id})` : safeText(selection?.project_id);
  $("modelId").textContent = safeText(selection?.modelId || selection?.model_id);
  $("runtimeId").textContent = safeText(selection?.runtimeId);
  $("ifcGuid").textContent = safeText(selection?.ifcGuid || selection?.ifc_guid);
  $("elementCode").textContent = safeText(selection?.elementCode || selection?.element_code);
  $("elementName").textContent = safeText(selection?.elementName || selection?.element_name);
}

function getProjectId() {
  if (currentProject?.id) return currentProject.id;
  if (currentSelection?.project_id) return currentSelection.project_id;
  return $("manualProjectId").value.trim() || "demo_project";
}

function getSelectionFromEventArg(arg) {
  // Trimble event args are usually { data: ... }. Keep this flexible for API changes.
  const data = arg?.data ?? arg;

  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.modelObjectIds)) return data.modelObjectIds;
  if (Array.isArray(data?.selection)) return data.selection;
  if (Array.isArray(data?.selected)) return data.selected;

  return [];
}

function getRuntimeIds(modelSelection) {
  return (
    modelSelection?.objectRuntimeIds ||
    modelSelection?.runtimeIds ||
    modelSelection?.objectIds ||
    []
  );
}

async function initTrimble() {
  $("backendUrl").value = getBackendUrl();

  if (!window.TrimbleConnectWorkspace || window.parent === window) {
    setStatus("Test ngoài Trimble", "warn");
    setMessage("selectionMessage", "Đang mở ngoài Trimble. Dùng phần 'Chế độ test ngoài Trimble' để test backend.", "warn");
    return;
  }

  try {
    API = await TrimbleConnectWorkspace.connect(window.parent, async (event, arg) => {
      console.log("Trimble event", event, arg);
      if (event === "viewer.onSelectionChanged") {
        await handleSelectionChanged(arg);
      }
    }, 30000);

    currentProject = await API.project.getProject();
    setStatus("Đã kết nối Trimble", "ok");
    updateSelectionUi(currentSelection);
    setMessage("selectionMessage", "Đã kết nối Trimble. Hãy click một cấu kiện trong mô hình.", "ok");

    // If user had already selected something before opening extension, try reading it.
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
    console.warn("Unsupported selection format", selection);
    setMessage("selectionMessage", "Không lấy được modelId hoặc runtimeId từ selection.", "error");
    return;
  }

  const runtimeId = Number(runtimeIds[0]);
  let ifcGuid = null;
  let elementCode = null;
  let elementName = null;

  try {
    const objectIds = await API.viewer.convertToObjectIds(modelId, [runtimeId]);
    ifcGuid = objectIds?.[0];
  } catch (err) {
    console.error(err);
    setMessage("selectionMessage", `Không convert được runtimeId sang IFC GlobalId: ${err.message || err}`, "error");
    return;
  }

  try {
    const props = await API.viewer.getObjectProperties(modelId, [runtimeId]);
    const extracted = extractElementInfoFromProperties(props?.[0]);
    elementCode = extracted.elementCode;
    elementName = extracted.elementName;
  } catch (err) {
    // Properties are useful but not mandatory.
    console.warn("Could not read object properties", err);
  }

  currentSelection = {
    project_id: getProjectId(),
    modelId,
    runtimeId,
    ifcGuid,
    elementCode,
    elementName,
  };

  updateSelectionUi(currentSelection);
  setMessage("selectionMessage", "Đã chọn cấu kiện. Đang tải danh sách PDF...", "ok");
  await loadDocuments();
}

function extractElementInfoFromProperties(objectProperties) {
  const result = { elementCode: null, elementName: null };
  if (!objectProperties) return result;

  // Trimble ObjectProperties shape can differ by model/source.
  // This collector recursively scans name/value-like pairs.
  const pairs = [];

  function walk(node) {
    if (!node) return;
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    if (typeof node === "object") {
      const name = node.name || node.propertyName || node.key || node.label;
      const value = node.value || node.propertyValue || node.val;
      if (name !== undefined && value !== undefined) {
        pairs.push({ name: String(name), value: String(value) });
      }
      Object.values(node).forEach(walk);
    }
  }

  walk(objectProperties);

  const codeKeys = ["mã hiệu", "ma hieu", "ma_hieu", "element_code", "code", "mã cấu kiện", "ma cau kien"];
  const nameKeys = ["name", "tên", "ten", "tên cấu kiện", "ten cau kien", "element_name"];

  for (const pair of pairs) {
    const key = pair.name.trim().toLowerCase();
    if (!result.elementCode && codeKeys.some(k => key.includes(k))) {
      result.elementCode = pair.value;
    }
    if (!result.elementName && nameKeys.some(k => key === k || key.includes(k))) {
      result.elementName = pair.value;
    }
  }

  // Fallbacks commonly present in objectProperties.
  result.elementName = result.elementName || objectProperties.name || objectProperties.Name || null;
  return result;
}

async function testBackend() {
  const url = `${getBackendUrl()}/health`;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    setMessage("backendMessage", `Backend OK: ${JSON.stringify(data)}`, "ok");
  } catch (err) {
    setMessage("backendMessage", `Không kết nối được backend: ${err.message || err}`, "error");
  }
}

async function loadDocuments() {
  if (!currentSelection?.ifcGuid || !currentSelection?.modelId) {
    renderDocuments([]);
    return;
  }

  const params = new URLSearchParams({
    project_id: getProjectId(),
    model_id: currentSelection.modelId,
    ifc_guid: currentSelection.ifcGuid,
  });

  try {
    const res = await fetch(`${getBackendUrl()}/api/docs?${params.toString()}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();

    if (data.element_code && !currentSelection.elementCode) {
      currentSelection.elementCode = data.element_code;
    }
    if (data.element_name && !currentSelection.elementName) {
      currentSelection.elementName = data.element_name;
    }

    updateSelectionUi(currentSelection);
    renderDocuments(data.documents || []);
    setMessage("selectionMessage", `Đã tải ${data.documents?.length || 0} hồ sơ PDF.`, "ok");
  } catch (err) {
    renderDocuments([]);
    setMessage("selectionMessage", `Lỗi khi tải PDF: ${err.message || err}`, "error");
  }
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
    box.innerHTML = "Cấu kiện này chưa có hồ sơ PDF.";
    return;
  }

  box.className = "documents";
  box.innerHTML = docs.map(doc => {
    const title = doc.file_name || doc.file_url;
    const meta = [doc.document_type, doc.revision, doc.created_at].filter(Boolean).join(" · ");
    return `
      <article class="doc-item">
        <div class="doc-title">
          <span>${escapeHtml(title)}</span>
          <span>#${doc.id}</span>
        </div>
        <div class="doc-meta">${escapeHtml(meta || "Không có metadata")}</div>
        <div class="doc-actions">
          <a href="${escapeAttribute(doc.file_url)}" target="_blank" rel="noopener noreferrer">Mở PDF</a>
          <button class="danger" type="button" onclick="deleteDocument(${doc.id})">Xóa</button>
        </div>
      </article>
    `;
  }).join("");
}

async function attachDocument() {
  setMessage("attachMessage", "");

  if (!currentSelection?.ifcGuid || !currentSelection?.modelId) {
    setMessage("attachMessage", "Bạn cần chọn cấu kiện trước khi gắn PDF.", "error");
    return;
  }

  const fileUrl = $("fileUrl").value.trim();
  if (!fileUrl) {
    setMessage("attachMessage", "Bạn cần nhập URL PDF.", "error");
    return;
  }

  const payload = {
    project_id: getProjectId(),
    model_id: currentSelection.modelId,
    ifc_guid: currentSelection.ifcGuid,
    element_code: currentSelection.elementCode || null,
    element_name: currentSelection.elementName || null,
    file_name: $("fileName").value.trim() || null,
    file_url: fileUrl,
    document_type: $("documentType").value.trim() || null,
    revision: $("revision").value.trim() || null,
  };

  try {
    const res = await fetch(`${getBackendUrl()}/api/docs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);

    $("fileName").value = "";
    $("fileUrl").value = "";
    $("documentType").value = "";
    $("revision").value = "";
    setMessage("attachMessage", "Đã gắn link PDF vào cấu kiện.", "ok");
    await loadDocuments();
  } catch (err) {
    setMessage("attachMessage", `Lỗi khi gắn PDF: ${err.message || err}`, "error");
  }
}

async function deleteDocument(id) {
  try {
    const res = await fetch(`${getBackendUrl()}/api/docs/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    await loadDocuments();
  } catch (err) {
    setMessage("attachMessage", `Lỗi khi xóa: ${err.message || err}`, "error");
  }
}

function useManualSelection() {
  currentProject = {
    id: $("manualProjectId").value.trim() || "demo_project",
    name: "Manual Test Project",
  };
  currentSelection = {
    project_id: currentProject.id,
    modelId: $("manualModelId").value.trim() || "demo_model",
    runtimeId: "manual",
    ifcGuid: $("manualIfcGuid").value.trim() || "demo_ifc_guid",
    elementCode: $("manualElementCode").value.trim() || null,
    elementName: null,
  };
  updateSelectionUi(currentSelection);
  loadDocuments();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}

window.deleteDocument = deleteDocument;

window.addEventListener("DOMContentLoaded", () => {
  $("backendUrl").value = getBackendUrl();
  $("saveBackendBtn").addEventListener("click", () => {
    localStorage.setItem("CDE_BACKEND_URL", $("backendUrl").value.trim() || DEFAULT_BACKEND_URL);
    setMessage("backendMessage", "Đã lưu Backend URL.", "ok");
  });
  $("testBackendBtn").addEventListener("click", testBackend);
  $("attachBtn").addEventListener("click", attachDocument);
  $("manualSelectBtn").addEventListener("click", useManualSelection);
  initTrimble();
});
