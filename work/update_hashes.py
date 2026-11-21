#!/usr/bin/env python3
"""Đồng bộ các hằng SHA256 khi engine sinh lại file nhị phân đầu vào.

Vì sao không hardcode "hash cũ": script tìm *vị trí* của literal 64 ký tự hex
bằng regex neo vào đường dẫn input (ví dụ `inputs/official/HeroSkin_1.bytes`),
rồi thay đúng literal đang nằm ở vị trí đó. Nhờ vậy:

* chạy lại nhiều lần vẫn đúng (idempotent), không phụ thuộc bản trước;
* không "đoán" hash nào thuộc input nào, tránh thay nhầm;
* nếu file nguồn đã bị sửa cấu trúc (regex không còn khớp), script báo lỗi
  thay vì ghi bừa.

Cách dùng (chạy từ thư mục project, nơi có README.md):

    python work/update_hashes.py                  # chỉ báo lệch (mặc định)
    python work/update_hashes.py --check          # như trên, exit 1 nếu lệch
    python work/update_hashes.py --apply          # ghi thật + backup
    python work/update_hashes.py --apply ^
        --hero1 new/HeroSkin_1.bytes --hero2 new/HeroSkin_2.bytes ^
        --prematch new/prematch-base.zip --donor new/donor-HeroSkin_2.bytes ^
        --minimap new/minimap-base.zip

`--apply --readme` cập nhật luôn bảng hash trong README.md.
`--apply --sums` cập nhật SHA256SUMS.txt cho các file source vừa sửa.

LƯU Ý QUAN TRỌNG: hash chỉ là cổng kiểm tra toàn vẹn. Đổi hash KHÔNG làm
builder tương thích với layout mới. Sau khi đổi, hãy đọc phần audit mà script
in ra: các assert/hardcode trong build_m5.py và auto_spells.py vẫn có thể
chặn build (xem KIEN_TRUC.md, mục "Điểm gãy khi engine đổi cấu trúc").
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path


# ---------------------------------------------------------------------------
# Khai báo "pin": mỗi pin là một literal hash gắn với một input cụ thể
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Pin:
    name: str                    # khoá logic, cũng là tên tham số CLI (--official-1 ...)
    input_rel: str               # đường dẫn input tương đối với project root
    module_rel: str              # file source chứa literal cần thay
    regex: str                   # regex có đúng 1 group là hash hiện tại
    label: str                   # mô tả cho người đọc
    optional: bool = False       # True: bỏ qua nếu regex không khớp (README)


# Regex cố tình "neo" vào ngữ cảnh thay vì vào giá trị hash.
_M5_OFFICIAL = (r"inputs/official/HeroSkin_%s\.bytes'\)"
                r"[\s\S]{0,160}?'([0-9a-f]{64})'")
PINS: tuple[Pin, ...] = (
    Pin("official-1",
        "inputs/official/HeroSkin_1.bytes",
        "work/build_m5.py",
        _M5_OFFICIAL % "1",
        "build_m5.OFFICIAL[1] (HeroSkin_1 nền chính thức)"),
    Pin("official-2",
        "inputs/official/HeroSkin_2.bytes",
        "work/build_m5.py",
        _M5_OFFICIAL % "2",
        "build_m5.OFFICIAL[2] (HeroSkin_2 nền chính thức)"),
    Pin("prematch",
        "inputs/prematch-base.zip",
        "work/build_m5.py",
        r"sha256\(BASE\.read_bytes\(\)\)\.hexdigest\(\)\s*==\s*'([0-9a-f]{64})'",
        "build_m5.build(): assert hash của prematch-base.zip"),
    Pin("donor",
        "inputs/donor/HeroSkin_2.bytes",
        "work/auto_spells.py",
        r'DONOR_HASHES\s*=\s*\{"HeroSkin_2\.bytes":\s*"([0-9a-f]{64})"\}',
        "auto_spells.DONOR_HASHES (donor auto R8)"),
    Pin("minimap",
        "inputs/minimap-base.zip",
        "work/build_auto.py",
        r'BASE_SHA256\s*=\s*"([0-9a-f]{64})"',
        "build_auto.BASE_SHA256 (nền minimap)"),
)

# README.md có bảng hash đầu vào; chỉ sửa khi truyền --readme.
README_PINS: tuple[Pin, ...] = (
    Pin("readme-official-1",
        "inputs/official/HeroSkin_1.bytes", "README.md",
        r"\|\s*`inputs/official/HeroSkin_1\.bytes`\s*\|\s*`([0-9a-f]{64})`\s*\|",
        "README bảng input: HeroSkin_1", True),
    Pin("readme-official-2",
        "inputs/official/HeroSkin_2.bytes", "README.md",
        r"\|\s*`inputs/official/HeroSkin_2\.bytes`\s*\|\s*`([0-9a-f]{64})`\s*\|",
        "README bảng input: HeroSkin_2", True),
    Pin("readme-prematch",
        "inputs/prematch-base.zip", "README.md",
        r"\|\s*`inputs/prematch-base\.zip`\s*\|\s*`([0-9a-f]{64})`\s*\|",
        "README bảng input: prematch-base.zip", True),
    Pin("readme-donor",
        "inputs/donor/HeroSkin_2.bytes", "README.md",
        r"`inputs/donor/HeroSkin_2\.bytes`\s*\(SHA256\s*`([0-9a-f]{64})`\)",
        "README mục 10: donor R8", True),
    Pin("readme-minimap",
        "inputs/minimap-base.zip", "README.md",
        r"`inputs/minimap-base\.zip`\s*\(SHA256\s*`([0-9a-f]{64})`\)",
        "README mục 10: minimap-base.zip", True),
)

# File .bytes nào được audit cấu trúc, dùng key nào để giải mã.
AUDIT_KEYS = {
    "official-1": "HeroSkin_1",
    "official-2": "HeroSkin_2",
    "donor": "HeroSkin_2",
}


class MaintenanceError(RuntimeError):
    """Lỗi cấu hình/định dạng khiến không thể thay hash an toàn."""


@dataclass
class Change:
    pin: Pin
    module_path: Path
    input_path: Path
    old: str
    new: str

    @property
    def status(self) -> str:
        if not self.input_path.is_file():
            return "missing"
        return "ok" if self.old == self.new else "drift"


@dataclass
class Report:
    changes: list[Change] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def drift(self) -> list[Change]:
        return [c for c in self.changes if c.status == "drift"]

    @property
    def missing(self) -> list[Change]:
        return [c for c in self.changes if c.status == "missing"]


# ---------------------------------------------------------------------------
# Tính hash & thu thập kế hoạch
# ---------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _find_one(text: str, pattern: str) -> re.Match:
    matches = list(re.finditer(pattern, text))
    if not matches:
        raise MaintenanceError(
            "regex không khớp — file nguồn đã đổi cấu trúc, không thay hash mù")
    if len(matches) > 1:
        raise MaintenanceError(
            f"regex khớp {len(matches)} lần — không xác định được literal cần thay")
    return matches[0]


def collect(root: Path, pins: tuple[Pin, ...] = PINS,
            inputs: dict[str, Path] | None = None) -> Report:
    """Tính hash mới và tìm hash cũ cho từng pin. Không ghi file."""
    root = Path(root)
    inputs = inputs or {}
    report = Report()
    for pin in pins:
        module_path = root / pin.module_rel
        if not module_path.is_file():
            report.errors.append(f"{pin.name}: thiếu file nguồn {pin.module_rel}")
            continue
        input_path = inputs.get(pin.name) or (root / pin.input_rel)
        text = module_path.read_text(encoding="utf-8")
        try:
            match = _find_one(text, pin.regex)
        except MaintenanceError as error:
            if pin.optional:
                continue
            report.errors.append(f"{pin.name}: {error}")
            continue
        old = match.group(1)
        new = sha256_file(input_path) if input_path.is_file() else old
        report.changes.append(Change(pin, module_path, input_path, old, new))
    return report


# ---------------------------------------------------------------------------
# Ghi file
# ---------------------------------------------------------------------------
def _backup_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return path.with_name(f"{path.name}.bak-{stamp}")


def apply_changes(report: Report, backup: bool = True) -> list[str]:
    """Thay literal theo từng module, ghi atomically. Trả về module đã sửa."""
    touched: list[str] = []
    by_module: dict[Path, list[Change]] = {}
    for change in report.drift:
        by_module.setdefault(change.module_path, []).append(change)
    for module_path, changes in by_module.items():
        text = module_path.read_text(encoding="utf-8")
        for change in changes:
            match = _find_one(text, change.pin.regex)
            if match.group(1) != change.old:
                raise MaintenanceError(
                    f"{change.pin.name}: literal đã đổi trong lúc chạy")
            # Hash luôn dài 64 ký tự nên offset các pin khác không bị xô lệch.
            text = text[:match.start(1)] + change.new + text[match.end(1):]
        temporary = module_path.with_name(module_path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        if backup:
            module_path.replace(_backup_path(module_path))
        os.replace(temporary, module_path)
        if changes[0].pin.module_rel not in touched:
            touched.append(changes[0].pin.module_rel)
    return touched


def refresh_sums(root: Path, module_rels: list[str]) -> list[str]:
    """Cập nhật lại entry SHA256SUMS.txt của các module vừa sửa."""
    sums = Path(root) / "SHA256SUMS.txt"
    if not sums.is_file():
        return []
    wanted = set(module_rels)
    lines = sums.read_text(encoding="utf-8").splitlines()
    changed = []
    for index, line in enumerate(lines):
        match = re.match(r"^([0-9a-f]{64})  (.+)$", line)
        if not match or match.group(2) not in wanted:
            continue
        target = Path(root) / match.group(2)
        if not target.is_file():
            continue
        lines[index] = f"{sha256_file(target)}  {match.group(2)}"
        changed.append(match.group(2))
    if changed:
        temporary = sums.with_name(sums.name + ".tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, sums)
    return changed


def stale_occurrences(root: Path, values: set[str],
                      skip: set[Path] | None = None) -> list[tuple[str, int, str]]:
    """Tìm hash cũ còn sót trong *.py/*.md/*.txt (ví dụ README chưa cập nhật)."""
    root = Path(root)
    skip = {Path(p).resolve() for p in (skip or set())}
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".py", ".md", ".txt"}:
            continue
        if path.resolve() in skip or ".bak-" in path.name:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            for value in values:
                if value in line:
                    found.append((str(path.relative_to(root)), number, value))
    return found


# ---------------------------------------------------------------------------
# Audit cấu trúc file .bytes (cảnh báo layout, không chặn việc đổi hash)
# ---------------------------------------------------------------------------
def audit_bytes(path: Path, key: str) -> dict:
    """Đọc file IFix bằng parser của project và trả về các mốc layout."""
    from ifix_patch import Patch  # import trễ: cần cryptography

    patch = Patch(path, key)
    parsed = patch.parsed
    info = {
        "methods": parsed["method_count"],
        "externs": parsed["extern_method_count"],
        "strings": parsed["intern_string_count"],
        "fields": parsed["field_count"],
        "fixes": [{"desc": row["desc"], "vm": row["method_id"]}
                  for row in parsed["fixes"]],
    }
    update = next((row for row in parsed["fixes"]
                   if "CPlayerLocationStat" in row["desc"]
                   and "UpdateLogic" in row["desc"]), None)
    if update is not None:
        method = parsed["methods"][update["method_id"]]
        info["update_logic"] = {
            "vm": update["method_id"],
            "instructions": len(method["instructions"]),
            "exception_handlers": len(method["exception_handlers"]),
        }
    guards = {}
    for vm in (19, 20):
        if vm < parsed["method_count"]:
            body = parsed["methods"][vm]["instructions"]
            guards[vm] = [row["op"] for row in body]
    info["guards"] = guards
    return info


def print_audit(name: str, info: dict) -> None:
    print(f"  [{name}] methods={info['methods']} externs={info['externs']} "
          f"strings={info['strings']} fixes={len(info['fixes'])}")
    for row in info["fixes"]:
        print(f"      VM {row['vm']:>3}  {row['desc']}")
    warnings = []
    if name in {"official-2", "donor"}:
        update = info.get("update_logic")
        if update is None:
            warnings.append("không còn hook CPlayerLocationStat::UpdateLogic")
        else:
            if update["vm"] != 3:
                warnings.append(f"UpdateLogic là VM {update['vm']}, "
                                "auto_spells giả định VM 3")
            if update["instructions"] != 1033:
                warnings.append(f"UpdateLogic có {update['instructions']} lệnh, "
                                "_clean_auto_patch giả định 1033")
            if update["exception_handlers"]:
                warnings.append("UpdateLogic có exception handler, "
                                "_clean_auto_patch giả định 0")
        for vm, ops in info.get("guards", {}).items():
            if ops != ["Ret"]:
                warnings.append(f"guard VM {vm} không phải no-op "
                                f"({len(ops)} lệnh), _donor_auto_patch sẽ ghi đè")
    if name == "official-1":
        hooks = {(row["desc"].split("::")[0].split(",")[0].strip(),
                  row["desc"].split("::")[1].split("(")[0])
                 for row in info["fixes"]}
        for wanted in (("CameraSystem", "GetZoomRate"),
                       ("InBattleMsgInputView", "On_EndEdit")):
            if wanted not in hooks:
                warnings.append(f"thiếu hook {wanted[0]}::{wanted[1]}")
    for warning in warnings:
        print(f"      ! {warning}")
    if warnings:
        print("      ! Layout khác giả định — đổi hash thôi chưa đủ để build.")


def run_audit(root: Path, inputs: dict[str, Path]) -> None:
    for name, key in AUDIT_KEYS.items():
        path = inputs.get(name) or (root / next(
            pin.input_rel for pin in PINS if pin.name == name))
        if not path.is_file():
            continue
        print(f"  audit {path}:")
        try:
            print_audit(name, audit_bytes(path, key))
        except Exception as error:  # parse lỗi: vẫn cho đổi hash, nhưng báo
            print(f"      ! không parse được ({type(error).__name__}: {error})")
            print("      ! engine có thể đã đổi cả định dạng, không chỉ hash.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Tính SHA256 mới và thay hash cũ trong builder")
    parser.add_argument("--root", type=Path, default=None,
                        help="project root (mặc định: thư mục cha của work/)")
    parser.add_argument("--apply", action="store_true",
                        help="ghi thay đổi (mặc định chỉ báo cáo)")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 nếu có hash lệch")
    parser.add_argument("--readme", action="store_true",
                        help="cập nhật cả bảng hash trong README.md")
    parser.add_argument("--sums", action="store_true",
                        help="cập nhật SHA256SUMS.txt cho module vừa sửa")
    parser.add_argument("--no-backup", action="store_true",
                        help="không tạo .bak-<timestamp>")
    parser.add_argument("--no-audit", action="store_true",
                        help="bỏ qua audit cấu trúc .bytes")
    for name, label in (("hero1", "HeroSkin_1.bytes"),
                        ("hero2", "HeroSkin_2.bytes"),
                        ("prematch", "prematch-base.zip"),
                        ("donor", "donor/HeroSkin_2.bytes"),
                        ("minimap", "minimap-base.zip")):
        parser.add_argument(f"--{name}", type=Path, default=None,
                            help=f"đường dẫn file mới cho {label}")
    return parser.parse_args(argv)


def _utf8_console() -> None:
    """Console Windows mặc định cp1252; đổi sang UTF-8 để in tiếng Việt."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _utf8_console()
    args = _parse_args(argv)
    root = (args.root or Path(__file__).resolve().parent.parent).resolve()
    override = {
        "official-1": args.hero1, "official-2": args.hero2,
        "prematch": args.prematch, "donor": args.donor,
        "minimap": args.minimap,
    }
    inputs = {key: Path(value).expanduser().resolve()
              for key, value in override.items() if value}
    pins = PINS + README_PINS if args.readme else PINS

    print(f"project root: {root}")
    report = collect(root, pins, inputs)
    if report.errors:
        print("\nLỖI:")
        for error in report.errors:
            print(f"  - {error}")
        return 2

    width = max((len(c.pin.name) for c in report.changes), default=0)
    print("\nKẾT QUẢ:")
    for change in report.changes:
        marker = {"ok": "OK   ", "drift": "DRIFT", "missing": "MISS "}[change.status]
        print(f"  {marker} {change.pin.name:<{width}}  {change.old} -> {change.new}")
        print(f"        input: {change.input_path}")
    for change in report.missing:
        print(f"  ! thiếu input cho {change.pin.name}: {change.input_path}")

    if not args.no_audit:
        print("\nAUDIT CẤU TRÚC:")
        run_audit(root, inputs)

    if report.missing:
        return 2

    touched: list[str] = []
    if args.apply and not report.drift:
        print("\nKhông có hash nào lệch — không ghi.")
    if args.apply and report.drift:
        print("\nGHI FILE:")
        touched = apply_changes(report, backup=not args.no_backup)
        for relative in touched:
            print(f"  updated {relative}")
        if args.sums:
            updated = refresh_sums(root, touched)
            if updated:
                print(f"  SHA256SUMS.txt: {', '.join(updated)}")
        # Xác nhận lại sau khi ghi.
        confirmed = collect(root, pins, inputs)
        still = [c for c in confirmed.changes if c.status != "ok"]
        if still:
            print("\nLỖI: sau khi ghi vẫn còn lệch:")
            for change in still:
                print(f"  - {change.pin.name}: {change.status}")
            return 2

    old_values = {change.old for change in report.drift}
    if old_values:
        leftovers = stale_occurrences(root, old_values,
                                      skip={c.module_path for c in report.drift})
        if leftovers:
            print("\nHASH CŨ CÒN SÓT (không tự sửa):")
            for rel, number, value in leftovers[:40]:
                print(f"  {rel}:{number}  {value}")

    if report.drift and not args.apply:
        print("\nChưa ghi gì. Thêm --apply để cập nhật.")
        return 1 if args.check else 0
    if args.apply and touched:
        print("\nHoàn tất. Nhớ chạy lại audit/test trước khi build.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
