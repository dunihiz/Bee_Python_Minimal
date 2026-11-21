#!/usr/bin/env python3
"""Module auto mới: bật cờ -> quét enemy_actors -> RequestUseSkill.

Thiết kế theo đúng khuôn của dự án:

* `_donor_auto_patch` / `_clean_auto_patch` (auto_spells.py) *sửa* thân method
  có sẵn của donor; module này *bọc* thân đó: sinh thêm một VM method mới, cho
  nó gọi lại UpdateLogic gốc rồi mới chạy logic auto, và trỏ lại đúng một fix
  record `CPlayerLocationStat::UpdateLogic(System.Int32)` sang VM mới.
* Bytecode sinh bằng `ifix_patch.Code` + `emit(...)` giống `_chat_command`
  (chat_camera.py) và ví dụ trong README mục 9.
* Logic đọc preference dùng `UnityEngine.PlayerPrefs.GetInt`, cùng quy ước
  với `AUTO_BP_KEY` / `AUTO_SMITE_KEY` (khác 0 = bật, 0 = tắt).

Ngữ nghĩa logic (theo yêu cầu):

    if (PlayerPrefs.GetInt("iFix.AutoRush.Enabled.v1", 0) != 0) {
        foreach (enemy in enemy_actors) {
            if (enemy == null) continue;
            if (distanceXZ(host, enemy) < 500) {   // so sánh bình phương
                skillSlot.RequestUseSkill();       // gọi 1 lần rồi thoát
                break;
            }
        }
    }

Điểm cần biết trước khi chạy thật:

1. Tên API game nằm trong `RUSH_SPECS`. Chúng lấy từ README (mục 6/7) và donor
   đã đối chiếu, nhưng *assembly/overload có thể đổi theo bản game*. Trước khi
   build, dùng đoạn dump ở README mục 11 để xác nhận từng extern.
2. `bind_apis()` ưu tiên *tái sử dụng* extern đã có trong file đích (khớp tên +
   số tham số + owner). Chỉ khi không tìm thấy mới khai báo mới. Nhờ vậy module
   không phụ thuộc số thứ tự bảng extern — đúng loại lỗi hay gặp khi engine
   đổi cấu trúc.
3. Khoảng cách dùng bình phương trên mặt phẳng XZ (giống helper VM 28 của
   donor): `dx*dx + dz*dz < 500*500`, không gọi `sqrt`.
4. RequestUseSkill được gọi tối đa một lần mỗi nhịp UpdateLogic (giống cờ
   `requested` của donor), rồi thoát vòng lặp.

CLI:

    python work/auto_rush.py inputs/donor/HeroSkin_2.bytes out/HeroSkin_2.bytes
    python work/auto_rush.py SRC DST --dump      # in bytecode vừa sinh

Dùng như thư viện:

    from auto_rush import build_rush_patch, AUTO_RUSH_KEY
    info = build_rush_patch("HeroSkin_2.bytes", "HeroSkin_2.rush.bytes")
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from chat_camera import _write_with_fixes
from ifix_patch import Code, Patch, float_bits, i32
from ifix_verify import verify_method

AUTO_RUSH_KEY = "iFix.AutoRush.Enabled.v1"
# Dấu để nhận biết file đã được module này xử lý (tránh bọc hai lần).
RUSH_MARKER = "iFix.AutoRush.v1"

DISTANCE_LIMIT = 500.0
# So sánh bình phương để tránh sqrt; 250000.0 biểu diễn chính xác bằng float32.
DISTANCE_LIMIT_SQ = DISTANCE_LIMIT * DISTANCE_LIMIT
ENEMY_CAMP_MASK = 1          # camp địch = camp của host xor 1 (theo donor)
SKILL_SLOT_INDEX = 5         # ô bổ trợ (SkillSlotType)5 như nhánh Bộc phá

# Vị trí local trong method bọc. Đổi ở đây thì sửa cả emitter.
L_HOST, L_SKILL_CONTROL, L_SKILL_SLOT = 0, 1, 2
L_ENEMIES, L_INDEX, L_ENEMY = 3, 4, 5
L_POS_HOST, L_POS_ENEMY, L_DX, L_DZ = 6, 7, 8, 9
LOCAL_COUNT = 10
MAX_STACK = 8

MSCORLIB = "mscorlib"
CORE = "UnityEngine.CoreModule, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null"
PROJECT = "Project_d, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null"
PLUGINS = "Project.Plugins_d, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null"

PLAYER_STAT = "NucleusDrive.Statistics.CPlayerLocationStat"
ACTOR = "LActorRoot"
SKILL_COMPONENT = "Assets.Scripts.GameLogic.SkillComponent"
SKILL_SLOT = "Assets.Scripts.GameLogic.SkillSlot"
ACTOR_MANAGER = "NucleusDrive.Logic.LGameActorMgr"
VECTOR3 = "UnityEngine.Vector3"


def _param(name: str) -> tuple[str, str]:
    return name, (MSCORLIB if name.startswith("System.") else PROJECT)


@dataclass(frozen=True)
class ExternSpec:
    """Hợp đồng một extern: tên + owner + tham số + argc + arity trả về."""
    key: str
    methods: tuple[str, ...]          # tên method, phần tử đầu là tên chuẩn
    declaring: str                    # type khai báo (không kèm assembly)
    assembly: str
    params: tuple[tuple[str, str], ...]
    argc: int                         # argc của IFix: instance tính cả this
    returns: int                      # số slot đẩy lại (0 = void)


# Thứ tự trong tuple quyết định thứ tự extern mới được thêm vào bảng.
RUSH_SPECS: tuple[ExternSpec, ...] = (
    ExternSpec("prefs_get_int", ("GetInt",), "UnityEngine.PlayerPrefs", CORE,
               (_param("System.String"), _param("System.Int32")), 2, 1),
    ExternSpec("get_host_actor", ("get_HostActor",), PLAYER_STAT, PROJECT,
               (), 1, 1),
    ExternSpec("get_skill_control", ("get_SkillControl", "get_SkillComponent"),
               ACTOR, PROJECT, (), 1, 1),
    ExternSpec("get_skill_slot", ("GetSkillSlot",), SKILL_COMPONENT, PROJECT,
               (_param("System.Int32"),), 2, 1),
    ExternSpec("get_camp", ("get_Camp", "get_CampId", "get_CampID"),
               ACTOR, PROJECT, (), 1, 1),
    ExternSpec("get_enemy_actors", ("GetCampHeroActors",), ACTOR_MANAGER, PLUGINS,
               (_param("System.Int32"),), 1, 1),
    ExternSpec("get_position", ("get_position", "get_Position", "get_location"),
               ACTOR, PROJECT, (), 1, 1),
    ExternSpec("request_use_skill", ("RequestUseSkill",), SKILL_SLOT, PROJECT,
               (), 1, 0),
)

LIST_COUNT_NAMES = ("get_Count",)
LIST_ITEM_NAMES = ("get_Item",)


class RushBindingError(LookupError):
    """Không xác định được extern cần dùng — phải audit dump trước khi build."""


@dataclass(frozen=True)
class Bound:
    key: str
    operand: int        # giá trị nhét vào CallExtern: (argc << 16) | extern_id
    desc: str
    returns: int
    reused: bool


def _owner(desc: str) -> str:
    return desc.split("::", 1)[0]


def _owner_token(desc: str) -> str:
    return _owner(desc).split(",")[0].strip()


def _short(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _pick(pool: list[dict], spec: ExternSpec) -> tuple[dict | None, str | None]:
    """Chọn extern khớp owner; trả về (record, cảnh báo)."""
    exact = [row for row in pool
             if _owner_token(row["desc"]) == _short(spec.declaring)
             or _owner_token(row["desc"]) == spec.declaring]
    if exact:
        warning = (f"{spec.key}: {len(exact)} extern khớp chính xác, dùng "
                   f"{exact[0]['desc']}") if len(exact) > 1 else None
        return exact[0], warning
    near = [row for row in pool
            if _short(_owner_token(row["desc"])) == _short(spec.declaring)]
    if len(near) == 1:
        return near[0], f"{spec.key}: dùng owner gần đúng {near[0]['desc']}"
    if len(pool) == 1:
        return pool[0], f"{spec.key}: chỉ có một extern cùng tên, dùng {pool[0]['desc']}"
    return None, None


def _list_pair(patch) -> tuple[Bound, Bound, str | None]:
    """Tìm cặp get_Count / get_Item của cùng một kiểu danh sách."""
    owners: dict[str, dict[str, dict]] = {}
    for row in patch.parsed["extern_methods"]:
        owner = _owner(row["desc"])
        if row["method_name"] in LIST_COUNT_NAMES and row["param_count"] == 0:
            owners.setdefault(owner, {})["count"] = row
        elif row["method_name"] in LIST_ITEM_NAMES and row["param_count"] == 1:
            owners.setdefault(owner, {})["item"] = row
    pairs = [(owner, rows) for owner, rows in owners.items()
             if "count" in rows and "item" in rows]
    if not pairs:
        raise RushBindingError(
            "Không tìm thấy cặp get_Count/get_Item trong bảng extern. "
            "Donor phải có sẵn kiểu danh sách chứa enemy actor.")
    # Ưu tiên owner trông giống danh sách actor; hoà thì cảnh báo.
    pairs.sort(key=lambda pair: (
        "Actor" in pair[0], "List" in pair[0], -len(pair[0])), reverse=True)
    owner, rows = pairs[0]
    warning = None
    if len(pairs) > 1:
        warning = (f"list accessors: có {len(pairs)} kiểu danh sách, chọn {owner}. "
                   "Kiểm tra lại nếu enemy_actors là kiểu khác.")
    return (Bound("list_count", (1 << 16) | rows["count"]["index"],
                  rows["count"]["desc"], 1, True),
            Bound("list_item", (2 << 16) | rows["item"]["index"],
                  rows["item"]["desc"], 1, True),
            warning)


def bind_apis(patch) -> tuple[dict[str, Bound], list[str]]:
    """Tái sử dụng extern có sẵn, thiếu thì khai báo mới theo RUSH_SPECS."""
    bound: dict[str, Bound] = {}
    warnings: list[str] = []
    bound["list_count"], bound["list_item"], warning = _list_pair(patch)
    if warning:
        warnings.append(warning)

    for spec in RUSH_SPECS:
        pool = [row for row in patch.parsed["extern_methods"]
                if row["method_name"] in spec.methods
                and row["param_count"] == len(spec.params)]
        chosen, warning = _pick(pool, spec)
        if warning:
            warnings.append(warning)
        if chosen is not None:
            bound[spec.key] = Bound(spec.key, (spec.argc << 16) | chosen["index"],
                                    chosen["desc"], spec.returns, True)
            continue
        if pool:
            candidates = ", ".join(row["desc"] for row in pool)
            raise RushBindingError(
                f"{spec.key}: {len(pool)} extern cùng tên/arity nhưng khác owner "
                f"({candidates}); không tự chọn. Sửa RUSH_SPECS.declaring.")
        declaring = patch.type(spec.declaring, spec.assembly)
        parameters = [patch.type(name, assembly) for name, assembly in spec.params]
        operand = patch.extern(declaring, spec.methods[0], parameters,
                               spec.argc, spec.returns)
        bound[spec.key] = Bound(spec.key, operand,
                                spec.declaring + "::" + spec.methods[0],
                                spec.returns, False)
        warnings.append(f"{spec.key}: khai báo extern mới "
                        f"{spec.declaring}::{spec.methods[0]}")
    return bound, warnings


def _fields(patch) -> tuple[int, int]:
    """Field x/z của Vector3, tái sử dụng nếu file đã có."""
    names = {row["name"]: row["index"] for row in patch.parsed["fields"]
             if row["decl_type"].split(".")[-1] == "Vector3"}
    vector = patch.type(VECTOR3, CORE)
    single = patch.type("System.Single", MSCORLIB)
    for axis in ("x", "z"):
        if axis not in names:
            names[axis] = patch.field(axis, vector, single)
    return names["x"], names["z"]


def build_rush_method(patch, original_vm: int
                      ) -> tuple[bytes, dict[str, Bound], list[str]]:
    """Sinh thân VM cho method bọc. Trả về (raw, extern đã bind, cảnh báo)."""
    api, warnings = bind_apis(patch)
    field_x, field_z = _fields(patch)
    marker = patch.intern(RUSH_MARKER)
    key = patch.intern(AUTO_RUSH_KEY)

    def emit(*pairs):
        for op, operand in pairs:
            c.emit(op, operand)

    # StackSpace(locals, max_stack) được Code tự thêm ở lệnh 0.
    c = Code(LOCAL_COUNT, MAX_STACK)

    # Dấu phiên bản: Ldstr + Pop, không ảnh hưởng logic.
    emit(("Ldstr", marker), ("Pop", 0))

    # Gọi lại UpdateLogic gốc trước, để hành vi game không đổi khi cờ tắt.
    emit(("Ldarg", 0), ("Ldarg", 1), ("Call", (2 << 16) | original_vm))

    # if (GetInt(key, 0) == 0) goto done;
    emit(("Ldstr", key), ("Ldc_I4", 0),
         ("CallExtern", api["prefs_get_int"].operand),
         ("Brfalse", "rush_done"))

    # host = this.HostActor; if (host == null) goto done;
    emit(("Ldarg", 0), ("CallExtern", api["get_host_actor"].operand),
         ("Stloc", L_HOST), ("Ldloc", L_HOST), ("Brfalse", "rush_done"))

    # control = host.SkillControl; if (control == null) goto done;
    emit(("Ldloc", L_HOST), ("CallExtern", api["get_skill_control"].operand),
         ("Stloc", L_SKILL_CONTROL),
         ("Ldloc", L_SKILL_CONTROL), ("Brfalse", "rush_done"))

    # slot = control.GetSkillSlot(5); if (slot == null) goto done;
    emit(("Ldloc", L_SKILL_CONTROL), ("Ldc_I4", SKILL_SLOT_INDEX),
         ("CallExtern", api["get_skill_slot"].operand),
         ("Stloc", L_SKILL_SLOT),
         ("Ldloc", L_SKILL_SLOT), ("Brfalse", "rush_done"))

    # enemies = LGameActorMgr.GetCampHeroActors(host.Camp ^ 1);
    emit(("Ldloc", L_HOST), ("CallExtern", api["get_camp"].operand),
         ("Ldc_I4", ENEMY_CAMP_MASK), ("Xor", 0),
         ("CallExtern", api["get_enemy_actors"].operand),
         ("Stloc", L_ENEMIES),
         ("Ldloc", L_ENEMIES), ("Brfalse", "rush_done"))

    # hostPos = host.position; i = 0;
    emit(("Ldloc", L_HOST), ("CallExtern", api["get_position"].operand),
         ("Stloc", L_POS_HOST), ("Ldc_I4", 0), ("Stloc", L_INDEX))
    c.label("rush_loop")

    # while (i < enemies.Count) {
    emit(("Ldloc", L_INDEX), ("Ldloc", L_ENEMIES),
         ("CallExtern", api["list_count"].operand), ("Bge", "rush_done"))

    #     enemy = enemies[i]; if (enemy == null) goto next;
    emit(("Ldloc", L_ENEMIES), ("Ldloc", L_INDEX),
         ("CallExtern", api["list_item"].operand), ("Stloc", L_ENEMY),
         ("Ldloc", L_ENEMY), ("Brfalse", "rush_next"))

    #     enemyPos = enemy.position;
    emit(("Ldloc", L_ENEMY), ("CallExtern", api["get_position"].operand),
         ("Stloc", L_POS_ENEMY))

    #     dx = hostPos.x - enemyPos.x; dz = hostPos.z - enemyPos.z;
    emit(("Ldloc", L_POS_HOST), ("Ldfld", field_x),
         ("Ldloc", L_POS_ENEMY), ("Ldfld", field_x),
         ("Sub", 0), ("Stloc", L_DX))
    emit(("Ldloc", L_POS_HOST), ("Ldfld", field_z),
         ("Ldloc", L_POS_ENEMY), ("Ldfld", field_z),
         ("Sub", 0), ("Stloc", L_DZ))

    #     if (dx*dx + dz*dz >= 500*500) goto next;
    emit(("Ldloc", L_DX), ("Ldloc", L_DX), ("Mul_Ovf", 0),
         ("Ldloc", L_DZ), ("Ldloc", L_DZ), ("Mul_Ovf", 0),
         ("Add", 0), ("Ldc_R4", float_bits(DISTANCE_LIMIT_SQ)),
         ("Bge", "rush_next"))

    #     slot.RequestUseSkill(); break;
    emit(("Ldloc", L_SKILL_SLOT),
         ("CallExtern", api["request_use_skill"].operand),
         ("Br", "rush_done"))

    c.label("rush_next")
    emit(("Ldloc", L_INDEX), ("Ldc_I4", 1), ("Add", 0),
         ("Stloc", L_INDEX), ("Br", "rush_loop"))

    c.label("rush_done")
    emit(("Ret", 0))
    return c.finish(), api, warnings


def _find_update_fix(parsed) -> dict:
    matches = [row for row in parsed["fixes"]
               if "CPlayerLocationStat" in row["desc"]
               and "UpdateLogic" in row["desc"]]
    if len(matches) != 1:
        raise ValueError(f"Cần đúng 1 fix UpdateLogic, thấy {len(matches)}")
    return matches[0]


def install_rush(patch) -> tuple[int, int, list[bytes], dict[str, Bound], list[str]]:
    """Gắn method bọc vào patch. Trả về (vm mới, vm gốc, records, bound, warn)."""
    parsed = patch.parsed
    if any(row["value"] == RUSH_MARKER for row in parsed["intern_strings"]):
        raise ValueError("File đã được auto_rush xử lý (thấy marker)")
    fix = _find_update_fix(parsed)
    original_vm = fix["method_id"]
    method, bound, warnings = build_rush_method(patch, original_vm)
    new_vm = len(patch.methods)
    patch.methods.append(method)

    # Record giữ nguyên chữ ký, chỉ đổi 4 byte method_id ở cuối.
    old_record = patch.plain[fix["offset"]:fix["record_end"]]
    new_record = old_record[:-4] + i32(new_vm)
    records = [patch.plain[row["offset"]:row["record_end"]]
               for row in parsed["fixes"]]
    records[fix["index"]] = new_record
    return new_vm, original_vm, records, bound, warnings


def build_rush_patch(source, destination, key: str = "HeroSkin_2",
                     overwrite: bool = False) -> dict:
    """Đọc file IFix, bọc UpdateLogic bằng logic auto mới, ghi file mới."""
    source, destination = Path(source), Path(destination)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Đầu ra đã tồn tại: {destination}")
    patch = Patch(source, key)
    before = list(patch.methods)
    new_vm, original_vm, records, bound, warnings = install_rush(patch)
    _write_with_fixes(patch, destination, records)

    written = Patch(destination, key)
    # 1) Các method cũ phải còn nguyên từng byte.
    if written.methods[:len(before)] != before:
        destination.unlink(missing_ok=True)
        raise AssertionError("Method gốc bị thay đổi ngoài ý muốn")
    # 2) Fix record phải trỏ sang VM mới, và chỉ record đó đổi.
    fix = _find_update_fix(written.parsed)
    if fix["method_id"] != new_vm:
        destination.unlink(missing_ok=True)
        raise AssertionError("Fix record không trỏ sang VM mới")
    if len(written.parsed["fixes"]) != len(records):
        destination.unlink(missing_ok=True)
        raise AssertionError("Số fix record thay đổi")
    # 3) Kiểm tra stack/nhánh của riêng method mới.
    arities = {item.operand & 0xFFFF: item.returns for item in bound.values()}
    try:
        report = verify_method(written.parsed, new_vm, arities)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {
        "source": str(source), "destination": str(destination), "key": key,
        "original_vm": original_vm, "new_vm": new_vm,
        "fix": fix["desc"],
        "apis": {name: {"desc": item.desc, "reused": item.reused}
                 for name, item in bound.items()},
        "warnings": warnings,
        "verify": report,
    }


def decode_method(raw: bytes) -> list[tuple[int, int]]:
    """Tách (opcode, operand) từ thân method do Code.finish() sinh ra."""
    import struct
    from HeroSkin_DumpRepack import OP_NAMES

    count = struct.unpack_from("<i", raw, 0)[0]
    offset, result = 4, []
    for _ in range(count):
        code, operand = struct.unpack_from("<ii", raw, offset)
        offset += 8
        result.append((OP_NAMES.get(code, f"OP_{code}"), operand))
    return result


def dump_method(raw: bytes, bound: dict[str, Bound]) -> None:
    by_operand = {item.operand: f"{item.desc}{'' if item.reused else ' [new]'}"
                  for item in bound.values()}
    for index, (op, operand) in enumerate(decode_method(raw)):
        extra = ""
        if op == "CallExtern":
            extra = "  -> " + by_operand.get(operand, f"extern[{operand & 0xFFFF}]")
        elif op in {"Br", "Brfalse", "Brtrue", "Bge", "Blt", "Bgt", "Beq"}:
            extra = f"  -> IL_{index + operand:04d}"
        elif op in {"Ldc_R4"}:
            import struct
            extra = f"  ({struct.unpack('<f', struct.pack('<i', operand))[0]!r})"
        print(f"  IL_{index:04d}  {op:<12} {operand:>6}{extra}")


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(
        description="Bọc UpdateLogic bằng logic auto-rush (quét enemy < 500)")
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--key", default="HeroSkin_2")
    parser.add_argument("--force", action="store_true", help="ghi đè đầu ra")
    parser.add_argument("--dump", action="store_true", help="in bytecode đã sinh")
    args = parser.parse_args(argv)
    try:
        info = build_rush_patch(args.source, args.destination,
                                args.key, overwrite=args.force)
    except (RushBindingError, ValueError, FileExistsError) as error:
        print(f"FAIL: {error}")
        return 2
    if args.dump:
        patch = Patch(args.source, args.key)
        # Dựng lại đúng thứ tự extern đã bind để in cho dễ đọc.
        from copy import deepcopy
        mirror = deepcopy(patch)
        original_vm = _find_update_fix(mirror.parsed)["method_id"]
        method, bound, _ = build_rush_method(mirror, original_vm)
        print("BYTECODE:")
        dump_method(method, bound)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
