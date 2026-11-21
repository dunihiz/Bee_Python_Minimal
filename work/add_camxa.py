#!/usr/bin/env python3
"""Create a camera-only HeroSkin package from a clean HeroSkin file.

Usage:
    python3 add_camxa.py /path/to/HeroSkin_1.bytes
    python3 add_camxa.py /path/to/folder-containing-HeroSkin-files

The input files are never modified.  The output contains only the camera/chat
patch; it does not add the eden, ESP, HUD, full-skin, or runtime-skin hooks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

WORK = Path(__file__).resolve().parent
ROOT = WORK.parent
sys.path.insert(0, str(WORK))

from chat_camera import (  # noqa: E402
    CAMERA_KEY,
    DEFAULT_ZOOM,
    MAX_ZOOM,
    MIN_ZOOM,
    _chat_command,
    _fix_record,
    _write_with_fixes,
)
from ifix_patch import Code, Patch, float_bits  # noqa: E402
from ifix_verify import verify_patch  # noqa: E402


def _records(patch):
    return [patch.plain[fix["offset"]:fix["record_end"]]
            for fix in patch.parsed["fixes"]]


def build_camera_from_clean(source: Path, destination: Path):
    """Add only GetZoomRate and the /ecam chat handler to HeroSkin_1."""
    patch = Patch(source, "HeroSkin_1")
    if any("CameraSystem" in f["desc"] and "GetZoomRate" in f["desc"]
           for f in patch.parsed["fixes"]):
        raise ValueError("Input already contains a camera hook")
    if any("InBattleMsgInputView" in f["desc"] and "On_EndEdit" in f["desc"]
           for f in patch.parsed["fixes"]):
        raise ValueError("Input already contains a chat hook")

    project = "Project_d, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null"
    core = ("UnityEngine.CoreModule, Version=0.0.0.0, Culture=neutral, "
            "PublicKeyToken=null")
    camera_type = patch.type("CameraSystem", project)
    single = patch.type("System.Single", "mscorlib")
    text = patch.type("System.String", "mscorlib")
    prefs = patch.type("UnityEngine.PlayerPrefs", core)
    mathf = patch.type("UnityEngine.Mathf", core)
    base_zoom = patch.extern(camera_type, "get_ZoomRateFromAge", [], 1, 1)
    get_float = patch.extern(prefs, "GetFloat", [text, single], 2, 1)
    clamp = patch.extern(mathf, "Clamp", [single, single, single], 3, 1)
    key = patch.intern(CAMERA_KEY)

    camera = Code(0, 4)
    for op, operand in (
        ("Ldarg", 0), ("CallExtern", base_zoom), ("Ldstr", key),
        ("Ldc_R4", float_bits(DEFAULT_ZOOM)), ("CallExtern", get_float),
        ("Ldc_R4", float_bits(MIN_ZOOM)), ("Ldc_R4", float_bits(MAX_ZOOM)),
        ("CallExtern", clamp), ("Mul_Ovf", 0), ("Ret", 1),
    ):
        camera.emit(op, operand)

    # native_passthrough preserves ordinary chat messages in the original game.
    chat, chat_view, _ = _chat_command(
        patch, CAMERA_KEY, native_passthrough=True)
    camera_id = len(patch.methods)
    patch.methods.append(camera.finish())
    chat_id = len(patch.methods)
    patch.methods.append(chat)
    records = _records(patch)
    records.append(_fix_record(patch, camera_type, "GetZoomRate", [], camera_id))
    records.append(_fix_record(patch, chat_view, "On_EndEdit", [text], chat_id))
    result = _write_with_fixes(patch, destination, records)
    verify_patch(result, extern_returns=patch.arities, roots=[camera_id, chat_id])
    return result


def _resolve_input(value: Path):
    if value.is_dir():
        h1 = value / "HeroSkin_1.bytes"
        h2 = value / "HeroSkin_2.bytes"
    else:
        h1 = value
        h2 = value.with_name("HeroSkin_2.bytes")
    if not h1.is_file():
        raise FileNotFoundError(f"Không tìm thấy {h1}")
    return h1, h2 if h2.is_file() else None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tạo bản HeroSkin chỉ có cam xa + chat")
    parser.add_argument("input", type=Path,
                        help="HeroSkin_1.bytes hoặc thư mục chứa HeroSkin_1/2")
    parser.add_argument("-o", "--output-dir", type=Path,
                        default=Path("camxa-output"),
                        help="thư mục đầu ra (mặc định: camxa-output)")
    parser.add_argument("--no-zip", action="store_true",
                        help="không tạo file ZIP")
    args = parser.parse_args(argv)

    source1, source2 = _resolve_input(args.input.expanduser().resolve())
    out = args.output_dir.expanduser().resolve()
    if out.exists():
        raise FileExistsError(f"Thư mục đầu ra đã tồn tại: {out} (chọn -o khác)")
    thanos = out / "Thanos"
    thanos.mkdir(parents=True)
    output1 = thanos / "HeroSkin_1.bytes"
    build_camera_from_clean(source1, output1)
    copied = []
    if source2:
        output2 = thanos / "HeroSkin_2.bytes"
        shutil.copyfile(source2, output2)
        copied.append(str(output2))

    guide = out / "HUONG_DAN.txt"
    guide.write_text(
        "CAMERA-ONLY\\n\\n"
        "Trong trận nhập /ecam 2.1. Giá trị hợp lệ 1.0–2.3; mặc định 2.1.\\n"
        "Gói này không thêm eden, ESP, HUD, full skin hoặc /eskin.\\n",
        encoding="utf-8",
    )
    archive = None
    if not args.no_zip:
        archive = out.parent / f"{out.name}.zip"
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
            for path in [*thanos.iterdir(), guide]:
                bundle.write(path, path.relative_to(out))
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise ValueError("ZIP integrity check failed")

    manifest = {
        "source": str(source1),
        "hero2_source": str(source2) if source2 else None,
        "output": str(out),
        "archive": str(archive) if archive else None,
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in thanos.iterdir()},
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
