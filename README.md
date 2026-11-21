# YangJiii Python Minimal

Bộ công cụ Python nhỏ gọn để đọc, phân tích, kiểm tra và xây dựng các patch
`HeroSkin_*.bytes` sử dụng cơ chế IFix. Dự án tập trung vào tác vụ xử lý bytecode,
ghép patch, kiểm tra hash và kiểm thử emitter mà không đi kèm file nhị phân game,
donor, IPA, ZIP nền hoặc tài nguyên độc quyền.

> **Giới hạn quan trọng:** thư mục này chỉ chứa source công cụ. Các file
> `HeroSkin_*.bytes`, ZIP nền, bản dump và tài nguyên game phải do người dùng
> cung cấp hợp pháp. Builder cũng yêu cầu đúng layout/hash mà nó đã được kiểm
> định; việc thay thế file chỉ dựa trên tên hoặc SHA256 không đảm bảo tương thích.

## Tính năng

- Đọc và ghi lại file IFix mã hoá hoặc file trần.
- Phân tích bảng type, extern, field, string, method và fix registry.
- Tạo bytecode cho hook camera/chat bằng emitter `Code`.
- Ghép patch đồng thời relocate extern, method và các index tham chiếu.
- Kiểm tra stack, nhánh, local và exception handler trước khi ghi.
- Kiểm tra và đồng bộ SHA256 cho các file đầu vào.
- Chạy regression bằng Python `unittest` mà không cần game chạy trực tiếp.

## Yêu cầu

- Python 3.10 trở lên.
- `cryptography==38.0.4`.
- Terminal hỗ trợ UTF-8 để hiển thị đầy đủ tiếng Việt.

## Cài đặt

### Windows PowerShell

```powershell
cd C:\duong-dan\YangJiii_Python_Minimal
py -3.10 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### macOS hoặc Linux

```bash
cd /duong-dan/YangJiii_Python_Minimal
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Cấu trúc thư mục

```text
.
├── README.md
├── KIEN_TRUC.md
├── requirements.txt
├── SHA256SUMS.txt
└── work/
    ├── HeroSkin_DumpRepack.py  Parser/dump/repack IFix
    ├── ifix_format.py          Parser dự phòng và định dạng method
    ├── ifix_patch.py           Mô hình Patch, emitter và mã hoá
    ├── ifix_bytecode.py        Cắt/chèn và cập nhật nhánh bytecode
    ├── ifix_verify.py          Kiểm tra stack, local, nhánh và handler
    ├── hotfix_merge.py         Ghép patch và relocate index
    ├── chat_camera.py          Sinh hook camera và handler chat
    ├── chat_passthrough.py     Gọi xử lý chat native an toàn
    ├── chat_vm.py              Trình thông dịch chat dùng trong test
    ├── auto_spells.py          Trích và làm sạch patch auto từ donor
    ├── auto_rush.py            Emitter cho patch auto Rush thử nghiệm
    ├── build_auto.py           Ghép patch auto vào nền minimap
    ├── build_m5.py             Xây dựng artifact M5 đã kiểm định
    ├── add_camxa.py            CLI camera/chat đơn giản
    ├── update_hashes.py         Tính và đồng bộ SHA256
    └── test_*.py               Các bộ kiểm thử
```

## Kiểm thử

Chạy toàn bộ test ở thư mục gốc:

```bash
python -m unittest discover -s work -p "test_*.py" -v
```

Chạy riêng một module:

```bash
python -m unittest work.test_chat_camera -v
python -m unittest work.test_auto_rush -v
```

Các test tạo dữ liệu tạm và fixture giả. Chúng kiểm tra hình dạng bytecode,
đồng nhất bảng tham chiếu, độ sâu stack, mục tiêu nhánh và luồng end-to-end,
không cần file game thật.

## Sử dụng nhanh

Các lệnh sau cần chạy từ thư mục gốc, nơi có `README.md`.

### 1. Thêm camera và chat vào HeroSkin sạch

Chuẩn bị một `HeroSkin_1.bytes` chưa có hook camera/chat. Tùy chọn có thể đặt
`HeroSkin_2.bytes` cùng thư mục để công cụ giữ nguyên file thứ hai.

```bash
python work/add_camxa.py "C:\duong-dan\HeroSkin_1.bytes" -o camxa-output
```

Lệnh này:

1. kiểm tra file đầu vào;
2. thêm fix cho `CameraSystem.GetZoomRate`;
3. thêm handler cho `InBattleMsgInputView.On_EndEdit`;
4. tạo thư mục `camxa-output`;
5. mã hoá lại theo đúng tên HeroSkin khi file gốc là file mã hoá.

Nếu thư mục đầu ra đã tồn tại hoặc HeroSkin đã có hook camera/chat, công cụ sẽ
dừng thay vì ghi đè dữ liệu.

### 2. Build M5

Builder M5 yêu cầu ba file đầu vào ở vị trí tương đối sau:

| File | SHA256 |
|---|---|
| `inputs/official/HeroSkin_1.bytes` | `0bcd607e298576ba81004ab76aa4dd1772d2ec01344bd76401d8563c002adcce` |
| `inputs/official/HeroSkin_2.bytes` | `f6e39cbbcc068e705a8f7234d8383002c786ce81b118bcaea31503aa73434cfc` |
| `inputs/prematch-base.zip` | `a1ad917a0479d8f87934ca3bc5ba98c0e80c5feec2352a0e2ab582a5a170a180` |

Sau khi cung cấp đầy đủ:

```bash
python work/build_m5.py
```

Đầu ra mặc định:

```text
outputs/M5.zip
outputs/m5/
├── Thanos/
│   ├── HeroSkin_1.bytes
│   └── HeroSkin_2.bytes
├── HUONG_DAN.txt
└── manifest.json
```

Builder không ghi đè `outputs/m5` hoặc `outputs/M5.zip`. Hãy chuyển hoặc đổi tên
đầu ra cũ trước khi build lại.

### 3. Ghép patch auto thử nghiệm

Cần hai tài nguyên do người dùng cung cấp:

| File | Vị trí |
|---|---|
| Donor HeroSkin | `inputs/donor/HeroSkin_2.bytes` (SHA256 `f85e09a6cbd55d805d5c1fbec02119138dbac695e1737f4d454c5b96937ada9c`) |
| Nền minimap | `inputs/minimap-base.zip` (SHA256 `45a65ef9c964f706a32efb430a8967d59cc07d63d14d5bb1b435a7fbfdbe747a`) |

Chạy:

```bash
python work/build_auto.py
```

Kết quả mặc định là `outputs/Auto_Intermediate.zip`. Đây là artifact trung gian
để nghiên cứu; không phải đầu ra M5 và không thay thế quy trình build M5.

### 4. Đồng bộ hash sau khi tài nguyên hợp lệ thay đổi

Xem trước thay đổi:

```bash
python work/update_hashes.py
```

Chỉ kiểm tra và trả exit code:

```bash
python work/update_hashes.py --check
```

Cập nhật hash trong source, README và danh sách checksum:

```bash
python work/update_hashes.py --apply --readme --sums
```

Chỉ định file mới thay vì đặt vào thư mục `inputs`:

```bash
python work/update_hashes.py --apply --readme --sums \
  --hero1 "C:\new\HeroSkin_1.bytes" \
  --hero2 "C:\new\HeroSkin_2.bytes" \
  --prematch "C:\new\prematch-base.zip" \
  --donor "C:\new\donor-HeroSkin_2.bytes" \
  --minimap "C:\new\minimap-base.zip"
```

Script mặc định tạo file backup `.bak-<timestamp>` khi ghi. Truyền
`--no-backup` để tắt; truyền `--no-audit` để bỏ qua audit layout `.bytes`.

## Dump và phân tích IFix

Sử dụng parser kèm theo để giải mã, dump hoặc đóng gói:

```bash
python work/HeroSkin_DumpRepack.py --help
```

Luôn xác định method qua fix registry thay vì cứng nhắc dùng VM ID. VM ID chỉ là
chỉ số trong một artifact cụ thể và có thể thay đổi sau mỗi build.

Ví dụ đọc một fix theo tên:

```python
from pathlib import Path
from ifix_patch import Patch

patch = Patch(
    Path("outputs/m5/Thanos/HeroSkin_2.bytes"),
    "HeroSkin_2",
)

fix = next(
    item for item in patch.parsed["fixes"]
    if "CPlayerLocationStat" in item["desc"]
    and "UpdateLogic" in item["desc"]
)

method = patch.parsed["methods"][fix["method_id"]]
print(fix["desc"], "VM", fix["method_id"])
for instruction in method["instructions"]:
    print(instruction)
```

Chạy parser chỉ trên file mà bạn được phép phân tích và lưu trữ.

## Quy tắc bảo trì

1. Không thay hash để ép một file layout mới đi qua builder.
2. Chạy test sau mỗi thay đổi emitter hoặc parser.
3. Chạy `update_hashes.py --check` để phát hiện hash bị lệch.
4. Chạy audit cấu trúc trước khi đổi giả định VM, extern hoặc fix registry.
5. Không nối hay copy thô hai file IFix; mọi index bảng phải được relocate.
6. Kiểm tra file mã hoá/không mã hoá với bộ test riêng.

Chi tiết các bảng dữ liệu, luồng build, dạng file và điểm gãy khi engine đổi
cấu trúc nằm trong [KIEN_TRUC.md](KIEN_TRUC.md).

## Kiểm tra an toàn

Dự án không khẳng định tương thích mọi bản game hay mọi engine. Một số thành phần
sửa đổi hành vi trong game hoặc tài nguyên bản cục bộ nên phải tuân thủ điều khoản
được áp dụng, quyền của chủ sở hữu tài nguyên và luật hiện hành. Chỉ sử dụng file
bạn sở hữu hoặc được phép phân tích.
