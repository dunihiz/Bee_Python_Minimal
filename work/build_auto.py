"""Merge isolated auto-spells while preserving the supplied minimap implementation."""
from pathlib import Path
from hashlib import sha256
import json
import tempfile
import zipfile
from auto_spells import _replace_chat_commands, _clean_auto_patch, FORBIDDEN_AUTO_CALLS
from ifix_bytecode import _real_instructions
from ifix_patch import Patch
from hotfix_merge import merge_patch
ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "inputs/minimap-base.zip"
BASE_SHA256 = "45a65ef9c964f706a32efb430a8967d59cc07d63d14d5bb1b435a7fbfdbe747a"
OUTPUT = ROOT / "outputs/auto-intermediate"
ARCHIVE = ROOT / "outputs/Auto_Intermediate.zip"
GUIDE = "Intermediate auto-spell build. Existing features from the supplied baseline are retained. This is not the no-fullskin M5 release."

def _digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _frame_fix(parsed):
    matches = [row for row in parsed["fixes"] if "get_frameSynchr" in row["desc"]]
    if len(matches) != 1:
        raise ValueError(f"Expected one frame fix, got {len(matches)}")
    return matches[0]


def _verify_minimap_unchanged(before_path, after_path):
    before = Patch(before_path, "HeroSkin_2")
    after = Patch(after_path, "HeroSkin_2")
    old_fix = _frame_fix(before.parsed)
    new_fix = _frame_fix(after.parsed)
    if old_fix["method_id"] != new_fix["method_id"]:
        raise ValueError("Minimap method id changed")
    method_id = old_fix["method_id"]
    if before.methods[method_id] != after.methods[method_id]:
        raise ValueError("R6 minimap method changed")
    return method_id


def build(output=OUTPUT, archive=ARCHIVE):
    output, archive = Path(output), Path(archive)
    if output.exists() or archive.exists():
        raise FileExistsError("Refusing to overwrite an existing build")
    if _digest(BASE) != BASE_SHA256:
        raise ValueError("Verified R6 source hash mismatch")

    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(BASE) as base:
        tmp = Path(tmp)
        source1 = tmp / "HeroSkin_1.r6.bytes"
        source2 = tmp / "HeroSkin_2.r6.bytes"
        source1.write_bytes(base.read("Thanos/HeroSkin_1.bytes"))
        source2.write_bytes(base.read("Thanos/HeroSkin_2.bytes"))

        hero1 = tmp / "HeroSkin_1.bytes"
        _replace_chat_commands(source1, hero1)
        clean_auto = tmp / "HeroSkin_2.clean-auto.bytes"
        _clean_auto_patch(clean_auto)
        hero2 = tmp / "HeroSkin_2.bytes"
        merge = merge_patch(source2, clean_auto, hero2, "HeroSkin_2")
        frame_method_id = _verify_minimap_unchanged(source2, hero2)

        payloads = {
            "Thanos/HeroSkin_1.bytes": hero1.read_bytes(),
            "Thanos/HeroSkin_2.bytes": hero2.read_bytes(),
        }

    manifest = {
        "build": "R5-Minimap-Stable-Clean-Auto-R8",
        "base": BASE.name,
        "base_sha256": BASE_SHA256,
        "device_verified": False,
        "runtime_skin": False,
        "required_absent_files": ["HeroSkin_3.bytes", "HeroSkin_4.bytes"],
        "minimap_method_id": frame_method_id,
        "minimap_byte_identical_to_r6": True,
        "auto_defaults": {"trungtri": False, "bocpha": False,
                          "trungtri_target_mode": "all"},
        "removed_from_auto_hook": sorted(FORBIDDEN_AUTO_CALLS),
        "hero2_merge": merge,
        "files": {
            name: {"bytes": len(raw), "sha256": sha256(raw).hexdigest()}
            for name, raw in payloads.items()
        },
    }

    output.mkdir(parents=True)
    for name, raw in payloads.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (output / "HUONG_DAN.txt").write_text(GUIDE, encoding="utf-8")
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(output))
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        byte_files = sorted(name for name in bundle.namelist() if name.endswith(".bytes"))
        if byte_files != ["Thanos/HeroSkin_1.bytes", "Thanos/HeroSkin_2.bytes"]:
            raise ValueError(f"Unexpected runtime files: {byte_files}")
        for name, raw in payloads.items():
            if bundle.read(name) != raw:
                raise ValueError(f"ZIP payload mismatch: {name}")
    manifest["archive"] = str(archive)
    manifest["archive_sha256"] = _digest(archive)
    return manifest

if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
