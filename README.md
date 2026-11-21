# Bee Python Minimal

Bee Python Minimal là bộ công cụ Python dùng để đọc, phân tích, kiểm tra,
tạo và ghép patch IFix cho các file `HeroSkin_*.bytes`.

> Repo chỉ chứa source công cụ, không chứa IPA, binary game, donor, ZIP nền,
> tài nguyên được bảo vệ hoặc file `.bytes` đã dựng sẵn. Bạn chỉ nên dùng
> những file mà bạn sở hữu hoặc được phép phân tích.

---

## 1. Điều kiện

- Windows 10/11, macOS hoặc Linux.
- Python 3.10 trở lên.
- PowerShell hoặc Terminal UTF-8.
- Quyền ghi thư mục dự án.
- Với luồng build cụ thể: file game/ZIP nền hợp lệ do bạn tự cung cấp.

Tài liệu mặc định dùng đường dẫn Windows:

```text
C:\Bee_Python_Minimal
```

Thay đường dẫn này bằng thư mục repo thực tế của bạn.

---

## 2. Cài đặt trên Windows

Mở PowerShell và clone repo:

```powershell
git clone https://github.com/dunihiz/Bee_Python_Minimal.git C:\Bee_Python_Minimal
cd C:\Bee_Python_Minimal
```

Tạo môi trường ảo:

```powershell
py -3.10 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Khi môi trường đã được kích hoạt, dòng PowerShell có thể bắt đầu bằng
`(.venv)`. Kiểm tra Python:

```powershell
python --version
python -m pip show cryptography
```

### Cài đặt trên macOS/Linux

```bash
cd /duong-dan/Bee_Python_Minimal
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

---

## 3. Cấu trúc repo

```text
Bee_Python_Minimal/
├── README.md
├── KIEN_TRUC.md
├── requirements.txt
├── SHA256SUMS.txt
└── work/
    ├── HeroSkin_DumpRepack.py
    ├── ifix_format.py
    ├── ifix_patch.py
    ├── ifix_bytecode.py
    ├── ifix_verify.py
    ├── hotfix_merge.py
    ├── chat_camera.py
    ├── chat_passthrough.py
    ├── chat_vm.py
    ├── auto_spells.py
    ├── auto_rush.py
    ├── build_auto.py
    ├── build_m5.py
    ├── add_camxa.py
    ├── update_hashes.py
    └── test_*.py
```

---

## 4. Chạy test

Chạy từ thư mục gốc:

```powershell
python -m unittest discover -s work -p "test_*.py" -v
```

Một số test tích hợp cần file `inputs/` thật. Khi thiếu input, test có thể báo
`FileNotFoundError`; đó không phải do việc cài package bị hỏng.

Chạy các test không phụ thuộc binary game:

```powershell
cd work
python -m unittest test_update_hashes test_auto_rush test_chat_camera.CommandTests -v
```

Chạy một file test cụ thể:

```powershell
cd C:\Bee_Python_Minimal
python work\test_auto_rush.py
python work\test_update_hashes.py
```

---

## 5. Luồng phổ biến nhất: thêm camera/chat

Chuẩn bị:

```text
HeroSkin_1.bytes   // bắt buộc
HeroSkin_2.bytes   // tùy chọn
```

Bạn có thể truyền chính file H1 hoặc thư mục chứa H1/H2:

### Cách A: truyền file H1

```powershell
cd C:\Bee_Python_Minimal
python work\add_camxa.py "D:\game\HeroSkin_1.bytes" -o "D:\output\camxa"
```

Script tự tìm `D:\output\HeroSkin_2.bytes` hay chính xác là
`D:\game\HeroSkin_2.bytes` nếu file được truyền là đường dẫn H1. Nó tìm H2
cùng thư mục với H1.

### Cách B: truyền thư mục

```powershell
python work\add_camxa.py "D:\game" -o "D:\output\camxa"
```

Script tìm:

```text
D:\game\HeroSkin_1.bytes
D:\game\HeroSkin_2.bytes
```

### Kết quả

```text
D:\output\camxa\
├── Thanos\
│   ├── HeroSkin_1.bytes
│   └── HeroSkin_2.bytes   // nếu có H2
├── HUONG_DAN.txt
├── manifest.json
└── camxa.zip
```

Để không tạo ZIP:

```powershell
python work\add_camxa.py "D:\game" -o "D:\output\camxa" --no-zip
```

Script từ chối ghi đè thư mục đầu ra. Nếu thư mục đã tồn tại, đổi `-o` sang
tên mới; không dùng `--force` ở lệnh này.

### Lệnh trong game

Sau khi thay file hợp lệ:

```text
/ecam 2.1
```

Giá trị cho phép là `1.0` đến `2.3`. Giá trị mặc định là `2.1`.

Kết quả chỉ có camera/chat. Luồng này không thêm ESP, auto, full skin, HUD,
menu hay `/eskin`.

---

## 6. Build M5

Build M5 không tự biến một cặp HeroSkin bất kỳ thành M5. Nó cần nền
`prematch-base.zip` và hai file official đã ghim hash.

Tạo cấu trúc:

```text
C:\Bee_Python_Minimal\
└── inputs\
    ├── official\
    │   ├── HeroSkin_1.bytes
    │   └── HeroSkin_2.bytes
    └── prematch-base.zip
```

PowerShell:

```powershell
cd C:\Bee_Python_Minimal
New-Item -ItemType Directory -Force inputs\official
Copy-Item "D:\nguon\HeroSkin_1.bytes" inputs\official\HeroSkin_1.bytes
Copy-Item "D:\nguon\HeroSkin_2.bytes" inputs\official\HeroSkin_2.bytes
Copy-Item "D:\nguon\prematch-base.zip" inputs\prematch-base.zip
```

Ba hash bắt buộc:

| File | SHA256 |
|---|---|
| `inputs/official/HeroSkin_1.bytes` | `0bcd607e298576ba81004ab76aa4dd1772d2ec01344bd76401d8563c002adcce` |
| `inputs/official/HeroSkin_2.bytes` | `f6e39cbbcc068e705a8f7234d8383002c786ce81b118bcaea31503aa73434cfc` |
| `inputs/prematch-base.zip` | `a1ad917a0479d8f87934ca3bc5ba98c0e80c5feec2352a0e2ab582a5a170a180` |

Kiểm tra trước:

```powershell
Get-FileHash inputs\official\HeroSkin_1.bytes -Algorithm SHA256
Get-FileHash inputs\official\HeroSkin_2.bytes -Algorithm SHA256
Get-FileHash inputs\prematch-base.zip -Algorithm SHA256
python work\update_hashes.py --check
```

Nếu khớp, build:

```powershell
python work\build_m5.py
```

Kết quả:

```text
outputs/M5.zip
outputs/m5/
├── Thanos/
│   ├── HeroSkin_1.bytes
│   └── HeroSkin_2.bytes
├── HUONG_DAN.txt
└── manifest.json
```

Build M5 sẽ từ chối nếu `outputs/m5` hoặc `outputs/M5.zip` đã tồn tại.
Trước build lại:

```powershell
Remove-Item -Recurse -Force outputs\m5
Remove-Item -Force outputs\M5.zip
```

Chỉ xóa thư mục đầu ra cụ thể; không chạy lệnh xóa toàn thư mục repo.

Build giữ hotfix official, hai hook H1, hai hook H2 và kiểm chat bằng
trình mô phỏng nội bộ. Kết quả trong `manifest.json` có `device_verified:
false`; lệnh build không phải bằng chứng đã chạy thử trên iPhone/thiết bị
cụ thể.

### Lệnh M5

```text
/ecam 2.1
/esp on
/esp off
/trungtri on
/trungtri off
/bocpha on
/bocpha off
```

Đây là chuỗi lệnh chính xác. `/bocpha` không ngầm hiểu là `/bocpha on`.

---

## 7. Ghép build auto thử nghiệm

Luồng này cần:

```text
inputs/donor/HeroSkin_2.bytes
inputs/minimap-base.zip
```

Hash đã cấu hình:

| File | SHA256 |
|---|---|
| `inputs/donor/HeroSkin_2.bytes` | `f85e09a6cbd55d805d5c1fbec02119138dbac695e1737f4d454c5b96937ada9c` |
| `inputs/minimap-base.zip` | `45a65ef9c964f706a32efb430a8967d59cc07d63d14d5bb1b435a7fbfdbe747a` |

Checksum phụ dùng cho bảo trì: `inputs/donor/HeroSkin_2.bytes` (SHA256 `f85e09a6cbd55d805d5c1fbec02119138dbac695e1737f4d454c5b96937ada9c`) và `inputs/minimap-base.zip` (SHA256 `45a65ef9c964f706a32efb430a8967d59cc07d63d14d5bb1b435a7fbfdbe747a`).

Chuẩn bị:

```powershell
New-Item -ItemType Directory -Force inputs\donor
Copy-Item "D:\nguon\HeroSkin_2.bytes" inputs\donor\HeroSkin_2.bytes
Copy-Item "D:\nguon\minimap-base.zip" inputs\minimap-base.zip
Get-FileHash inputs\donor\HeroSkin_2.bytes -Algorithm SHA256
Get-FileHash inputs\minimap-base.zip -Algorithm SHA256
```

Chạy:

```powershell
python work\build_auto.py
```

Đầu ra:

```text
outputs/Auto_Intermediate.zip
outputs/auto-intermediate/
├── Thanos/
│   ├── HeroSkin_1.bytes
│   └── HeroSkin_2.bytes
├── HUONG_DAN.txt
└── manifest.json
```

Đây là artifact trung gian để nghiên cứu và ghép. Không coi nó là bản M5
không full skin; build M5 dùng nguồn và quy trình riêng.

---

## 8. Tạo wrapper auto-rush

Script `auto_rush.py` giữ method `UpdateLogic` gốc và tạo wrapper gọi lại
method gốc rồi quét enemy gần. Nó không thay file `HeroSkin_2.bytes` thành
nhánh M5 hoàn chỉnh.

Lệnh:

```powershell
python work\auto_rush.py "D:\nguon\HeroSkin_2.bytes" "D:\output\HeroSkin_2.rush.bytes"
```

Mặc định:

```text
--key HeroSkin_2
```

Nếu cần đổi key:

```powershell
python work\auto_rush.py "D:\nguon\ten-file.bytes" "D:\output\ket-qua.bytes" --key TenTenFile
```

Ghi đè:

```powershell
python work\auto_rush.py "D:\nguon\HeroSkin_2.bytes" "D:\output\HeroSkin_2.rush.bytes" --force
```

In bytecode sinh ra:

```powershell
python work\auto_rush.py "D:\nguon\HeroSkin_2.bytes" "D:\output\HeroSkin_2.rush.bytes" --dump
```

Nếu script báo `RushBindingError`, thường do file không có extern/type/bảng
được script mong đợi hoặc layout đã thay đổi.

---

## 9. Dump và inspect file `.bytes`

Script `HeroSkin_DumpRepack.py` có subcommand:

```text
dump
repack
verify
inspect
```

### Giải mã plaintext

```powershell
python work\HeroSkin_DumpRepack.py dump "D:\game\HeroSkin_1.bytes" "D:\temp\HeroSkin_1.plain" --name HeroSkin_1
```

### Mã hoá lại

```powershell
python work\HeroSkin_DumpRepack.py repack "D:\temp\HeroSkin_1.plain" "D:\temp\HeroSkin_1.bytes" --name HeroSkin_1
```

### Kiểm tra roundtrip

```powershell
python work\HeroSkin_DumpRepack.py verify "D:\game\HeroSkin_1.bytes" --name HeroSkin_1
```

Kết quả mong muốn là:

```text
ROUNDTRIP: PASS
```

### Xuất báo cáo JSON và text

```powershell
python work\HeroSkin_DumpRepack.py inspect "D:\game\HeroSkin_2.bytes" "D:\temp\HeroSkin_2.json" "D:\temp\HeroSkin_2.txt" --name HeroSkin_2
```

Luôn tìm fix bằng `desc`, không hardcode VM ID. VM 3, 6, 13, 36 hay 37
chỉ là số trong artifact cụ thể.

---

## 10. Kiểm tra bytecode bằng verifier

```powershell
python work\ifix_verify.py "D:\game\HeroSkin_2.bytes"
```

Chạy dạng avatar-only:

```powershell
python work\ifix_verify.py "D:\game\HeroSkin_2.bytes" --avatar-only
```

Nếu file dùng extern mới có arity trả stack cần khai báo:

```powershell
@"
{"123": 1, "124": 0}
"@ | Set-Content arity.json -Encoding UTF8

python work\ifix_verify.py "D:\game\HeroSkin_2.bytes" --arity-json arity.json
```

JSON có dạng:

```json
{"extern_id": 0}
```

trong đó `0` nghĩa extern không trả giá trị và `1` nghĩa trả một giá trị.

---

## 11. Cập nhật SHA256

Xem tình trạng drift:

```powershell
python work\update_hashes.py
```

Trả exit code 1 khi có drift và không ghi:

```powershell
python work\update_hashes.py --check
```

Tự ghi hash bằng file hiện có trong `inputs/`:

```powershell
python work\update_hashes.py --apply --readme --sums
```

Chỉ định file mới ngoài repo:

```powershell
python work\update_hashes.py --apply --readme --sums `
  --hero1 "D:\new\HeroSkin_1.bytes" `
  --hero2 "D:\new\HeroSkin_2.bytes" `
  --prematch "D:\new\prematch-base.zip" `
  --donor "D:\new\donor-HeroSkin_2.bytes" `
  --minimap "D:\new\minimap-base.zip"
```

Không tạo backup:

```powershell
python work\update_hashes.py --apply --no-backup
```

Bỏ audit layout:

```powershell
python work\update_hashes.py --apply --no-audit
```

Quy tắc quan trọng: đổi hash chỉ cập nhật pin; nó không sửa layout hay làm
file engine mới tương thích. Nếu audit báo layout khác, dừng build và xem lại
parser/emitter trước khi tiếp tục.

---

## 12. Dòng dữ liệu tổng quát

```text
add_camxa
  -> đọc H1 sạch
  -> sinh hook camera/chat
  -> ghi H1 mới

build_auto
  -> đọc minimap-base
  -> trích/clean auto từ donor
  -> merge patch
  -> ghi artifact trung gian

build_m5
  -> đọc prematch-base
  -> chọn fix official + custom
  -> giữ method
  -> verify và đóng ZIP

update_hashes
  -> tính SHA256
  -> thay literal theo regex có neo ngữ cảnh
  -> audit layout
```

---

## 13. Xử lý lỗi thường gặp

### `FileNotFoundError`

- Kiểm tra đúng thư mục `inputs/`.
- Kiểm tra tên chính xác `HeroSkin_1.bytes` hoặc `HeroSkin_2.bytes`.
- Chuyển sang absolute path thay vì relative path.

### `ValueError: hash mismatch`

- File không khớp SHA256 ghim trong source.
- Kiểm tra lại file lấy từ nguồn nào.
- Không thay hash để ép file khác đi qua.

### `FileExistsError`

- Thư mục hoặc ZIP đầu ra đã tồn tại.
- Build M5/chạy camxa/build_auto sẽ không ghi đè.
- Dọn hoặc đổi tên đúng đầu ra cũ.

### `RushBindingError`

- Layout extern hoặc type trong H2 không khớp.
- Chạy dump/inspect file đó để xác định bảng fix.
- Không dùng `--force` để che layout sai.

### `ROUNDTRIP: FAIL`

- File có thể sai key, tên file hoặc định dạng.
- Kiểm tra lại `--name`.
- Dừng re-pack; đừng ghi đè binary gốc.

### Test thiếu input

- Test tích hợp thường cần file game/ZIP nguồn.
- Chạy riêng test pure trong mục 4 trước.

---

## 14. Quy trình làm việc an toàn

Trước khi chạy:

1. Sao lưu file nguồn.
2. Sao lưu thư mục `inputs/`.
3. Chạy test pure.
4. Chạy `update_hashes.py --check`.
5. Chỉ build bằng file đã hash và layout đã audit.
6. Kiểm `manifest.json` và SHA256 output.
7. Giữ ZIP gốc và thư mục test riêng.
8. Không commit binary hoặc tài nguyên cá nhân.

Sau build:

```powershell
Get-FileHash "D:\Bee_Python_Minimal\outputs\M5.zip" -Algorithm SHA256
Get-Content "D:\Bee_Python_Minimal\outputs\m5\manifest.json"
```

Chi tiết định dạng IFix, relocation, verifier và điểm gãy layout nằm trong
[KIEN_TRUC.md](KIEN_TRUC.md).

---

## 15. Cập nhật code

Lấy thay đổi mới:

```powershell
cd C:\Bee_Python_Minimal
git pull --ff-only
```

Sau khi sửa source:

```powershell
git status
git diff
python -m unittest discover -s work -p "test_*.py" -v
git add README.md KIEN_TRUC.md work
git commit -m "Update implementation"
git push origin main
```
