# CDE BIM PDF Linker - V1

Tool V1 để gắn hồ sơ PDF vào cấu kiện BIM trong Trimble Connect 3D Viewer.

## 1. Kiến trúc

```text
Civil 3D / IFC
    ↓
Trimble Connect 3D Viewer
    ↓ click cấu kiện
HTML/JS Extension
    ↓ Workspace API: modelId + runtimeId → IFC GlobalId
FastAPI Backend
    ↓
SQLite Database
```

## 2. Thư mục

```text
CDE_BIM_TOOL_V1/
├── backend/
│   ├── main.py
│   ├── database.py
│   ├── schemas.py
│   ├── ifc_reader.py
│   ├── pdf_mapper.py
│   ├── requirements.txt
│   ├── run_dev.bat
│   └── run_dev.sh
│
├── extension/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   ├── manifest.json
│   └── icon.svg
│
└── data/
    ├── ifc/
    └── pdf/
```

## 3. Chạy backend

### Windows

```bat
cd backend
run_dev.bat
```

Hoặc chạy thủ công:

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### macOS/Linux

```bash
cd backend
./run_dev.sh
```

Sau khi chạy, mở:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/docs
```

## 4. Test backend bằng Swagger

Mở:

```text
http://127.0.0.1:8000/docs
```

Test API:

```http
POST /api/docs
```

Body mẫu:

```json
{
  "project_id": "demo_project",
  "model_id": "demo_model",
  "ifc_guid": "demo_ifc_guid",
  "element_code": "N5_BV_L1_B01",
  "element_name": "Bo via B01",
  "file_name": "BBNT_N5_BV_L1_B01_Thep_R01.pdf",
  "file_url": "https://example.com/BBNT_N5_BV_L1_B01_Thep_R01.pdf",
  "document_type": "BBNT",
  "revision": "R01"
}
```

Sau đó test:

```http
GET /api/docs?project_id=demo_project&model_id=demo_model&ifc_guid=demo_ifc_guid
```

## 5. Test extension ngoài Trimble

Mở file:

```text
extension/index.html
```

Sau đó:

1. Bấm `Test /health`.
2. Nhập dữ liệu ở phần `Chế độ test ngoài Trimble`.
3. Bấm `Dùng dữ liệu test`.
4. Nhập URL PDF.
5. Bấm `Gắn Link vào Cấu kiện`.

## 6. Nhúng vào Trimble Connect

1. Đẩy toàn bộ thư mục lên GitHub.
2. Bật GitHub Pages.
3. Sửa `extension/manifest.json`:

```json
{
  "url": "https://YOUR_GITHUB_USERNAME.github.io/YOUR_REPOSITORY_NAME/extension/index.html",
  "icon": "https://YOUR_GITHUB_USERNAME.github.io/YOUR_REPOSITORY_NAME/extension/icon.svg"
}
```

4. Mở URL manifest để kiểm tra:

```text
https://YOUR_GITHUB_USERNAME.github.io/YOUR_REPOSITORY_NAME/extension/manifest.json
```

5. Vào Trimble Connect Project → Project Settings → Apps & Capabilities.
6. Add Custom Extension bằng URL của `manifest.json`.
7. Mở 3D Viewer, bật extension.
8. Click cấu kiện để kiểm tra `modelId`, `runtimeId`, `IFC GlobalId`.

## 7. Lưu ý quan trọng về localhost

Trong giai đoạn dev, extension gọi:

```text
http://localhost:8000
```

Cách này chỉ chạy trên máy đang mở Trimble và đồng thời đang chạy FastAPI.

Khi triển khai cho nhiều kỹ sư, phải deploy backend thành URL chung, ví dụ:

```text
https://api-cde.company.vn
```

Sau đó nhập URL đó vào ô `Backend URL` trong extension.

## 8. API chính

### GET /health

Kiểm tra backend.

### GET /api/docs

Query:

```text
project_id
model_id
ifc_guid
```

### POST /api/docs

Gắn tài liệu PDF vào cấu kiện.

### DELETE /api/docs/{document_id}

Xóa tài liệu.

### POST /api/import-ifc

Đọc IFC bằng IfcOpenShell và lưu cấu kiện vào SQLite. Đây là chức năng V1+.

### POST /api/auto-map

Quét thư mục PDF và match theo `element_code`. Đây là chức năng V1+.

## 9. Trạng thái hiện tại

Bản này tập trung vào V1 core:

- Backend FastAPI chạy được.
- SQLite lưu được dữ liệu.
- Extension gọi được backend.
- Extension có logic kết nối Workspace API.
- Click cấu kiện trong Trimble sẽ lấy `modelId`, `runtimeId`, chuyển sang `IFC GlobalId` bằng `convertToObjectIds()`.
- Cho phép gắn/xóa link PDF.

