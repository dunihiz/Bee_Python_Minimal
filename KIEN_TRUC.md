# Kiến trúc hệ thống — Bee Python Minimal

Tài liệu này mô tả source hiện có, luồng dữ liệu và các hợp đồng nội bộ trong
gói. Mục tiêu là giúp người phát triển đọc, sửa hoặc tiếp tục module mà không
giả định rằng tên VM, offset hoặc chuỗi trong một artifact cụ thể dùng lại được
cho mọi phiên bản engine.

## 1. Bản đồ module

| Module | Trách nhiệm |
|---|---|
| `work/HeroSkin_DumpRepack.py` | AES-CBC, suy ra key, giải/mã hoá, parse IFix, OP code và dump |
| `work/ifix_format.py` | Parser dự phòng cho metadata anonymous-storey |
| `work/ifix_patch.py` | Mô hình `Patch`, bảng tham chiếu, emitter `Code` và ghi file |
| `work/ifix_bytecode.py` | Cắt/chèn lệnh, dịch target nhánh và xử lý handler |
| `work/hotfix_merge.py` | Ghép patch và relocate index method/extern/string/field |
| `work/ifix_verify.py` | Kiểm tra stack, local, nhánh, extern và exception handler |
| `work/chat_camera.py` | Sinh handler chat, hook camera và ghi fix |
| `work/chat_passthrough.py` | Gọi handler chat native mà không tạo đệ quy |
| `work/chat_vm.py` | Trình thông dịch nhỏ dùng để test bytecode chat |
| `work/auto_spells.py` | Tách patch auto từ donor và loại nhánh UI/ESP |
| `work/auto_rush.py` | Sinh VM method wrapper cho luồng Rush thử nghiệm |
| `work/build_auto.py` | Ghép patch auto với nền minimap |
| `work/build_m5.py` | Lọc fix, giữ hotfix và đóng gói artifact M5 |
| `work/add_camxa.py` | CLI thêm camera/chat vào file sạch |
| `work/update_hashes.py` | Cập nhật hash an toàn, audit layout và checksum |
| `work/test_*.py` | Regression cho parser, emitter, chat, merge và verifier |

## 2. Định dạng IFix

Một patch có thể ở hai trạng thái:

- **Mã hoá:** bắt đầu bằng magic `22 4A 67 00`, có độ dài plaintext và AES-CBC.
- **Trần:** có 4-byte header khác magic, độ dài plaintext và phần plaintext theo
  định dạng IFix.

Key mã hoá được suy ra từ tên file:

```text
HeroSkin_1.bytes -> key dựa trên "HeroSkin_1"
HeroSkin_2.bytes -> key dựa trên "HeroSkin_2"
```

Thuật toán băm mô phỏng Java:

```text
hash = hash * 31 + ký_tự
```

Sau đó key được tạo bằng cách kết hợp hash với `BASE_KEY` trong
`HeroSkin_DumpRepack.py`.

Plaintext được parse theo thứ tự:

```text
u64 magic
string wrappers bridge
i32 extern_type_count + extern types
i32 method_count + method bodies
i32 extern_method_count + extern method descriptors
i32 intern_string_count + intern strings
i32 field_count + field records
i32 static_field_type_count + static field records
i32 anonymous_storey_count + anonymous storey data
string wrappers_manager
string assembly
i32 fix_count + fix records
i32 new_class_count + new classes
```

Mỗi fix record ánh xạ một method thật của game tới một VM method:

```text
method descriptor + method_id
```

## 3. Mô hình `Patch`

`work/ifix_patch.py` cung cấp lớp `Patch`:

- `plain`: plaintext hiện tại.
- `parsed`: kết quả parse.
- `types`: bảng extern type.
- `methods`: danh sách bytecode của VM method.
- `externs`, `strings`, `fields`: phần dữ liệu mới.
- `arities`: arity trả về của extern mới, phục vụ verifier.

Các API tạo mục mới:

```python
type_id = patch.type("System.String", "mscorlib")
extern_id = patch.extern(declaring_type, "SetInt", [type_text, type_int], 2, 0)
string_id = patch.intern("iFix.AutoBP.Enabled.v1")
field_id = patch.field("fieldName", declaring_type, field_type)
```

Lưu ý:

- `patch.extern` trả operand đóng gói `(argc << 16) | extern_id`.
- Với lời gọi instance, `argc` gồm cả `this`.
- Một extern không thể trùng tên mà thiếu chữ ký hoặc arity nhất quán.
- Sau khi ghép patch, mọi index tham chiếu phải được relocate.

## 4. Emitter `Code`

`Code` tạo method bằng opcode và operand.

```python
from ifix_patch import Code

code = Code(locals=8, stack=5)
code.emit("Ldarg", 1)
code.emit("Brfalse", "done")

code.label("done")
code.emit("Ret", 0)
raw = code.finish()
```

`finish()` chuyển nhãn thành offset tương đối:

```text
target = instruction_index + operand
```

Đối với nhánh nhảy lùi trong vòng lặp, operand là số âm. Trình verify phải chứng
minh mọi target nằm trong method và stack không âm ở mọi tuyến đường khả thi.

## 5. Ghi patch

Luồng ghi tiêu chuẩn trong `chat_camera.py`:

1. Parse patch gốc.
2. Tạo hoặc thay thế fix record.
3. Dựng lại bảng type/method/extern/string/field theo thứ tự.
4. Giữ static metadata và anonymous-storey nếu chúng tồn tại.
5. Ghi fix registry.
6. Giữ `new_class_count` và bảng class.
7. Mã hoá lại nếu file gốc dùng mã hoá.
8. Parse lại file vừa ghi.
9. Assert assembly của fix, roundtrip và thống nhất dữ liệu.

Không nên nối byte thô hai patch hoặc sao toàn bộ method mà bỏ qua bảng tham
chiếu. `hotfix_merge.py` là nơi chuẩn để ghép patch và xử lý relocation.

## 6. Kiểm tra bytecode

`ifix_verify.py` có hai hàm chính:

- `verify_patch(view)`: kiểm tra toàn bộ patch.
- `verify_method(view, method_id, arities)`: kiểm tra một method.

Verifier phân tích:

- độ cao stack tối đa;
- local slot được đọc/ghi hợp lệ;
- target branch không vượt quá method;
- exception handler có vùng catch hợp lệ;
- extern ID tồn tại;
- arity trả về được khai báo.

Một method có thể vượt qua unit test nhưng vẫn sai layout engine. Vì vậy test chỉ
chứng minh shape bytecode, không thay thế test trên môi trường game thực tế.

## 7. Luồng camera và chat

```text
H1 gốc
  -> Patch.parse
  -> emitter sinh fix GetZoomRate
  -> emitter sinh handler On_EndEdit
  -> patch extern/string/field
  -> _write_with_fixes
  -> H1 mới
```

Handler chat:

1. Kiểm chuỗi chat rỗng.
2. So khớp các lệnh bật/tắt.
3. Ghi PlayerPrefs bằng extern tương ứng.
4. Với `/ecam`, parse số hữu hạn bằng InvariantCulture.
5. Clamp giá trị camera trong khoảng builder đã định.
6. Ghi preference và gọi singleton/tái tính camera khi hook hỗ trợ.
7. Chuyển chat không khớp hoặc xử lý native qua passthrough.

`chat_passthrough.py` tạm gỡ slot IFix, gọi handler native, rồi khôi phục slot
trong `catch`. Hành vi bắt buộc là luôn khôi phục slot kể cả khi handler ném lỗi.

## 8. Luồng build M5

`build_m5.py` không tự phát sinh một logic auto mới. Nó yêu cầu nền
`prematch-base.zip` đã có fix/hook mong muốn và một cặp official để đối chiếu.

Luồng:

```text
Kiểm SHA256 prematch
  -> mở ZIP nền
  -> parse HeroSkin_1 và HeroSkin_2
  -> parse official HeroSkin_1 và HeroSkin_2
  -> chọn fix official + fix custom
  -> giữ nguyên method body
  -> ghi fix registry mới
  -> kiểm khả đạt của VM
  -> kiểm chat bằng ChatNative
  -> ghi manifest
  -> đóng outputs/M5.zip
  -> mở lại ZIP và roundtrip
```

Đầu ra:

```text
Thanos/HeroSkin_1.bytes
Thanos/HeroSkin_2.bytes
HUONG_DAN.txt
manifest.json
```

`device_verified` trong manifest mặc định là `false`; MANIFEST không chứng minh
tương thích trên mọi thiết bị hay mọi bản engine.

## 9. Luồng ghép auto

`auto_spells.py` đọc một donor, tìm các hook đã biết, sửa preference và loại
các nhánh UI/ESP không mong muốn. `build_auto.py` ghép phần kết quả với nền
minimap do người dùng cung cấp.

Luồng tổng quát:

```text
donor H2
  -> parse fix UpdateLogic
  -> thay preference mặc định
  -> loại các vùng UI/ESP cố định
  -> phát/hợp nhất patch
  -> relocate index
  -> ghép vào minimap-base.zip
  -> ghi Auto_Intermediate.zip
```

Không nên xem output của bước ghép là một binary ổn định nếu hash hoặc layout
donor đã thay đổi. Builder phải chạy audit và test trước.

## 10. Luồng bảo trì hash

`update_hashes.py` dùng `Pin` để gắn một input với:

- đường dẫn input;
- file source chứa literal hash;
- regex neo theo ngữ cảnh;
- nhãn mô tả.

Khi chạy:

1. Tìm đúng một regex trong source.
2. Tính SHA256 của input.
3. So với literal hiện tại.
4. Báo `ok`, `drift`, `missing` hoặc `error`.
5. Chỉ ghi khi dùng `--apply`.
6. Tạo backup trừ khi có `--no-backup`.
7. Kiểm xác nhận sau khi ghi.

Audit `.bytes` đọc:

- số method;
- số extern;
- số intern string;
- số field;
- danh sách fix;
- VM của `UpdateLogic`;
- VM guard;
- exception handler.

Audit chỉ phát hiện sai khác layout; nó không tự biến layout mới thành layout
tương thích. Không đổi hash để né lỗi parser nếu file đã thay cấu trúc.

## 11. Điểm gãy khi engine thay đổi

| Vị trí | Giả định hiện tại | Triệu chứng |
|---|---|---|
| `build_m5.py` | Hash prematch/offical cố định | Dừng bằng lỗi hash |
| `build_m5.py` | Tập hook custom đúng hai fix mỗi file | Assertion tập identity |
| `build_m5.py` | Method official khớp từng byte | Assertion roundtrip |
| `auto_spells.py` | Hash donor cố định | `ValueError` |
| `auto_spells.py` | `UpdateLogic` nằm VM 3 | Fix sai hoặc `StopIteration` |
| `auto_spells.py` | Layout donor có 1033 lệnh và 0 EH | Assertion layout |
| `auto_spells.py` | Các vùng ESP/UI nằm offset đã audit | Nop lệch vùng |
| `chat_camera.py` | Tên assembly/type hook còn giữ nguyên | Validate fix assembly |
| `hotfix_merge.py` | Patch custom/base không tạo static/new-class xung đột | `ValueError` |
| `ifix_verify.py` | Bảng arity extern đầy đủ | `No audited return arity` |

Nếu engine thay đổi định dạng, update:

1. parser trong `ifix_format.py` hoặc `HeroSkin_DumpRepack.py`;
2. model trong `ifix_patch.py`;
3. giả định splice trong `ifix_bytecode.py`;
4. relocation trong `hotfix_merge.py`;
5. test layout và verifier;
6. literal hash cuối cùng.

Không cập nhật hash trước khi hoàn thành audit layout.

## 12. Quy trình phát triển an toàn

```bash
# 1. Tạo môi trường
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# 2. Chạy test
python -m unittest discover -s work -p "test_*.py" -v

# 3. Kiểm tra hash
python work/update_hashes.py --check

# 4. Chỉ build với input hợp lệ
python work/build_m5.py

# 5. Kiểm tra lại artifact
python work/HeroSkin_DumpRepack.py --help
```

Trước khi commit, kiểm tra:

- Không có binary game hoặc tài nguyên độc quyền.
- Không có API key, token hoặc đường dẫn máy cá nhân.
- Không có file backup chứa dữ liệu nhạy cảm.
- `SHA256SUMS.txt` khớp source được commit.
- Test PASS và tài liệu khớp tên hàm hiện có.
