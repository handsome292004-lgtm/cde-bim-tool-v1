# CDE BIM Tool V1 - Trimble Solid PDF Source Patch

Bản này sửa hướng quét PDF từ Trimble Project chắc hơn:

- Không phụ thuộc `data/pdf` local.
- Không dùng auto mapping local.
- Extension lấy Access Token từ Trimble.
- Extension gửi token về backend proxy.
- Backend thử nhiều hướng đọc file PDF:
  - nhiều region/base URL: `app`, `app21`, `app31`
  - API v2.0 và v2.1
  - `/folders/by_path`
  - `/folders/{folderId}/items`
  - `/projects`, `/projects/{id}`
  - các endpoint files/documents fallback
- Có thêm ô `Folder ID tùy chọn`. Nếu Trimble API không tự tìm folder, mở đúng folder PDF trong Trimble Explorer, copy Folder ID từ URL và dán vào ô này.

## Copy file

Copy đè:

```text
backend/main.py
extension/index.html
extension/app.js
extension/style.css
```

vào project hiện tại.

## Chạy backend

```bat
cd /d "C:\Users\ASUS\OneDrive\Thư mục mới\OneDrive\CDE\CDE_BIM_TOOL_V1\CDE_BIM_TOOL_V1\backend"
.venv\Scripts\activate
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Kiểm tra:

```text
http://127.0.0.1:8000/docs
```

Phải thấy version `1.4.0-trimble-solid-source` hoặc route:

```text
POST /api/trimble/scan-pdfs
```

## Push GitHub

```bat
cd /d "C:\Users\ASUS\OneDrive\Thư mục mới\OneDrive\CDE\CDE_BIM_TOOL_V1\CDE_BIM_TOOL_V1"
git add backend/main.py extension/index.html extension/app.js extension/style.css
git commit -m "Robust Trimble PDF source scan"
git pull --rebase origin main
git push
```

## Dùng trong Trimble

1. Mở extension.
2. Vào tab `Nguồn PDF`.
3. Dán Cloudflare URL vào `Backend Proxy URL`.
4. Bấm `Test Backend`.
5. Bấm `Xin quyền Access Token`.
6. Để trống folder filter trước.
7. Bấm `Quét PDF trong Trimble`.
8. Nếu vẫn chưa được, nhập `Folder ID tùy chọn` rồi quét lại.

## Cách lấy Folder ID tùy chọn

Mở Trimble Explorer ở tab riêng, click vào folder chứa PDF. Nếu URL có dạng:

```text
.../data/folder/<FOLDER_ID>
```

copy `<FOLDER_ID>` và dán vào ô `Folder ID tùy chọn`.
