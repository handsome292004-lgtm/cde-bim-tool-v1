# CDE BIM Tool - Auto Mapping IFC + PDF

## 1. Chuẩn bị dữ liệu

Đặt IFC vào:

```text
data/ifc/model.ifc
```

Đặt PDF nghiệm thu vào:

```text
data/pdf/
```

Tên PDF phải chứa đúng mã hiệu cấu kiện, ví dụ:

```text
KDPS_NO5_ZZ_RP_S0_B01_Bien_ban_nghiem_thu.pdf
KDPS_NO5_ZZ_RP_S0_B01_Thong_bao_kiem_tra.pdf
KDPS_NO5_ZZ_RP_S0_B02_Bao_cao_hoan_thanh.pdf
```

## 2. Chạy backend

```bat
cd C:\Users\ASUS\Downloads\CDE_BIM_TOOL_V1\CDE_BIM_TOOL_V1\backend
.venv\Scripts\activate
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## 3. Tạo HTTPS tunnel

Dùng Cloudflare Tunnel hoặc ngrok. Backend public URL cần trỏ về port 8000.

Ví dụ Cloudflare:

```bat
cloudflared tunnel --url http://localhost:8000
```

Giả sử link nhận được là:

```text
https://abc.trycloudflare.com
```

PDF sẽ được serve tại:

```text
https://abc.trycloudflare.com/pdf/<ten-file-pdf>
```

## 4. Lấy Project ID và Model ID trong Trimble

Mở extension trong Trimble, click một cấu kiện. Copy:

```text
Project ID
Model ID
```

## 5. Chạy auto mapping

Mở CMD mới trong thư mục `backend` và chạy:

```bat
.venv\Scripts\activate
python run_auto_map.py ^
  --project-id "PASTE_PROJECT_ID" ^
  --model-id "PASTE_MODEL_ID" ^
  --ifc "..\data\ifc\model.ifc" ^
  --pdf-folder "..\data\pdf" ^
  --base-url "https://abc.trycloudflare.com/pdf" ^
  --pset-name "Thong_tin_BIM" ^
  --code-property "Mã hiệu"
```

Nếu property trong IFC là `Ma_hieu` thay vì `Mã hiệu`, đổi dòng cuối thành:

```bat
  --code-property "Ma_hieu"
```

## 6. Kiểm tra trong Trimble

Sau khi auto mapping xong:

1. Trong extension, tab Cấu hình nhập Backend URL: `https://abc.trycloudflare.com`
2. Bấm Test /health
3. Click cấu kiện trong model
4. Vào tab Hồ sơ PDF
5. PDF có mã hiệu trùng cấu kiện sẽ hiện ra
