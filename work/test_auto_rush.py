"""Kiểm thử emitter `auto_rush` — không cần file game.

Ta dựng một `FakePatch` có sẵn bảng extern giống donor (get_Count/get_Item,
GetCampHeroActors, RequestUseSkill...) để:

* kiểm tra `bind_apis` tái sử dụng extern đúng và chỉ khai báo phần thiếu;
* giải mã bytecode do `Code.finish()` sinh ra;
* chạy `ifix_verify.verify_method` để chứng minh stack/nhánh/local hợp lệ.

Đây là kiểm tra hình dạng bytecode, không phải xác nhận game thực thi đúng.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from auto_rush import (
    AUTO_RUSH_KEY,
    DISTANCE_LIMIT_SQ,
    MAX_STACK,
    RUSH_MARKER,
    build_rush_method,
    build_rush_patch,
    decode_method,
)
from ifix_format import body
from ifix_patch import OP, Patch, float_bits, i32, string
from ifix_verify import verify_method


EXISTING_EXTERNS = (
    ("NucleusDrive.Statistics.CPlayerLocationStat, Project_d",
     "get_HostActor", 0),
    ("LActorRoot, Project_d", "get_SkillControl", 0),
    ("Assets.Scripts.GameLogic.SkillComponent, Project_d", "GetSkillSlot", 1),
    ("LActorRoot, Project_d", "get_Camp", 0),
    ("NucleusDrive.Logic.LGameActorMgr, Project.Plugins_d",
     "GetCampHeroActors", 1),
    ("System.Collections.Generic.List`1[[LActorRoot, Project_d]], mscorlib",
     "get_Count", 0),
    ("System.Collections.Generic.List`1[[LActorRoot, Project_d]], mscorlib",
     "get_Item", 1),
    ("LActorRoot, Project_d", "get_position", 0),
    ("Assets.Scripts.GameLogic.SkillSlot, Project_d", "RequestUseSkill", 0),
)


class FakePatch:
    """Bề mặt tối thiểu mà auto_rush dùng: type/extern/field/intern + parsed."""

    def __init__(self):
        self.types: list[str] = []
        self.arities: dict[int, int] = {}
        self.new_externs: list[dict] = []
        self.new_fields: list[dict] = []
        self.new_strings: list[str] = []
        existing = [
            {"index": index, "method_name": name, "param_count": params,
             "desc": f"{owner}::{name}(" + ", ".join(["arg"] * params) + ")"}
            for index, (owner, name, params) in enumerate(EXISTING_EXTERNS)
        ]
        self.parsed = {
            "extern_type_count": 0,
            "extern_method_count": len(existing),
            "intern_string_count": 0,
            "field_count": 0,
            "extern_types": [],
            "extern_methods": existing,
            "fields": [],
        }
        self.methods = [b""]

    def type(self, name: str, assembly: str) -> int:
        for index, value in enumerate(self.types):
            if value.split(",")[0] == name:
                return index
        self.types.append(f"{name}, {assembly}")
        return len(self.types) - 1

    def extern(self, declaring: int, method: str, parameters, argc: int,
               returns: int) -> int:
        index = self.parsed["extern_method_count"] + len(self.new_externs)
        desc = (f"{self.types[declaring]}::{method}("
                + ", ".join(self.types[p] for p in parameters) + ")")
        self.new_externs.append({"index": index, "method_name": method,
                                 "param_count": len(parameters), "desc": desc})
        self.arities[index] = returns
        return (argc << 16) | index

    def field(self, name: str, declaring_type: int, field_type: int) -> int:
        index = self.parsed["field_count"] + len(self.new_fields)
        record = {"index": index, "name": name,
                  "decl_type": self.types[declaring_type]}
        self.new_fields.append(record)
        self.parsed["fields"].append(record)
        return index

    def intern(self, value: str) -> int:
        index = self.parsed["intern_string_count"] + len(self.new_strings)
        self.new_strings.append(value)
        return index


def build():
    patch = FakePatch()
    raw, bound, warnings = build_rush_method(patch, original_vm=0)
    return patch, raw, bound, warnings


class BindingTests(unittest.TestCase):
    def test_reuses_existing_and_declares_only_missing(self):
        patch, _, bound, _ = build()
        self.assertTrue(bound["get_host_actor"].reused)
        self.assertTrue(bound["get_enemy_actors"].reused)
        self.assertTrue(bound["request_use_skill"].reused)
        self.assertTrue(bound["list_count"].reused)
        self.assertIn("get_Count", bound["list_count"].desc)
        self.assertFalse(bound["prefs_get_int"].reused)
        self.assertEqual(len(patch.new_externs), 1)
        self.assertEqual(patch.new_externs[0]["method_name"], "GetInt")

    def test_list_pair_comes_from_one_owner(self):
        _, _, bound, _ = build()
        count_owner = bound["list_count"].desc.split("::")[0]
        item_owner = bound["list_item"].desc.split("::")[0]
        self.assertEqual(count_owner, item_owner)

    def test_marker_and_flag_strings_are_interned(self):
        patch, _, _, _ = build()
        self.assertEqual(patch.new_strings, [RUSH_MARKER, AUTO_RUSH_KEY])


class BytecodeTests(unittest.TestCase):
    def setUp(self):
        self.patch, self.raw, self.bound, self.warnings = build()
        self.ops = decode_method(self.raw)

    def test_calls_original_update_logic_once(self):
        calls = [operand for op, operand in self.ops if op == "Call"]
        self.assertEqual(calls, [(2 << 16) | 0])

    def test_distance_guard_uses_squared_limit(self):
        self.assertEqual(DISTANCE_LIMIT_SQ, 250000.0)
        limits = [operand for op, operand in self.ops if op == "Ldc_R4"]
        self.assertIn(float_bits(DISTANCE_LIMIT_SQ), limits)

    def test_request_use_skill_is_called_once_after_distance_guard(self):
        target = self.bound["request_use_skill"].operand
        indexes = [i for i, (op, operand) in enumerate(self.ops)
                   if op == "CallExtern" and operand == target]
        self.assertEqual(len(indexes), 1)
        index = indexes[0]
        self.assertEqual(self.ops[index + 1][0], "Br")
        guard = [i for i in range(index)
                 if self.ops[i][0] == "Bge"
                 and i + self.ops[i][1] > index]
        self.assertTrue(guard, "RequestUseSkill phải nằm sau nhánh Bge khoảng cách")

    def test_loop_walks_enemy_list(self):
        count_target = self.bound["list_count"].operand
        item_target = self.bound["list_item"].operand
        called = [operand for op, operand in self.ops if op == "CallExtern"]
        self.assertIn(count_target, called)
        self.assertIn(item_target, called)
        self.assertTrue(any(op == "Br" and operand < 0
                            for op, operand in self.ops), "thiếu nhánh lùi của vòng lặp")

    def test_every_branch_target_stays_inside_method(self):
        for index, (op, operand) in enumerate(self.ops):
            if op in {"Br", "Brfalse", "Brtrue", "Bge", "Blt", "Bgt", "Beq"}:
                target = index + operand
                self.assertTrue(0 <= target < len(self.ops),
                                f"{op} tại {index} nhảy ra ngoài ({target})")

    def test_stack_shape_passes_project_verifier(self):
        instructions = [{"index": i, "op": op, "operand": operand}
                        for i, (op, operand) in enumerate(self.ops)]
        view = {
            "methods": [
                {"index": 0,
                 "instructions": [{"op": "Ret", "operand": 0}],
                 "exception_handlers": []},
                {"index": 1, "instructions": instructions,
                 "exception_handlers": []},
            ],
            "extern_methods": (self.patch.parsed["extern_methods"]
                               + self.patch.new_externs),
            "fields": self.patch.new_fields,
            "extern_type_count": len(self.patch.types),
        }
        arities = dict(self.patch.arities)
        for item in self.bound.values():
            arities[item.operand & 0xFFFF] = item.returns
        report = verify_method(view, 1, arities)
        self.assertEqual(report["method_id"], 1)
        self.assertLessEqual(report["max_stack_depth"], MAX_STACK)
        self.assertGreater(report["reachable_instructions"], 30)
        self.assertIn(self.bound["request_use_skill"].operand & 0xFFFF,
                      report["extern_ids"])


def _extern(decl: int, name: str, params: tuple[int, ...]) -> bytes:
    return (b"\0" + i32(decl) + string(name) + i32(len(params))
            + b"".join(i32(value) for value in params))


def make_hero2() -> bytes:
    """File IFix tối giản (không mã hoá) có đủ bảng extern cho auto_rush."""
    types = [
        "NucleusDrive.Statistics.CPlayerLocationStat, Project_d",
        "System.Int32, mscorlib",
        "LActorRoot, Project_d",
        "Assets.Scripts.GameLogic.SkillComponent, Project_d",
        "SkillSlotType, Project_d",
        "NucleusDrive.Logic.LGameActorMgr, Project.Plugins_d",
        "System.Collections.Generic.List`1[[LActorRoot, Project_d]], mscorlib",
        "Assets.Scripts.GameLogic.SkillSlot, Project_d",
    ]
    externs = [
        _extern(0, "get_HostActor", ()),
        _extern(2, "get_SkillControl", ()),
        _extern(3, "GetSkillSlot", (4,)),
        _extern(2, "get_Camp", ()),
        _extern(5, "GetCampHeroActors", (1,)),
        _extern(6, "get_Count", ()),
        _extern(6, "get_Item", (1,)),
        _extern(2, "get_position", ()),
        _extern(7, "RequestUseSkill", ()),
    ]
    update_logic = body([(OP["StackSpace"], 0), (OP["Ret"], 0)])
    fix = (b"\0" + i32(0) + string("UpdateLogic") + i32(1) + i32(1) + i32(0))
    plain = (
        struct.pack("<Q", 0x1234) + string("IFix.ILFixInterfaceBridge, Project_d")
        + i32(len(types)) + b"".join(string(value) for value in types)
        + i32(1) + update_logic
        + i32(len(externs)) + b"".join(externs)
        + i32(0)          # intern strings
        + i32(0)          # fields
        + i32(0)          # static_field_type_count
        + i32(0)          # anonymous_storey_count
        + string("IFix.WrappersManagerImpl") + string(", Project_d")
        + i32(1) + fix    # fix registry
        + i32(0)          # new_class_count
    )
    return b"\0\0\0\0" + i32(len(plain)) + plain


class EndToEndTests(unittest.TestCase):
    def test_build_rush_patch_rewrites_fix_and_keeps_original_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "HeroSkin_2.bytes"
            destination = Path(tmp) / "HeroSkin_2.rush.bytes"
            source.write_bytes(make_hero2())
            info = build_rush_patch(source, destination)

            self.assertEqual(info["original_vm"], 0)
            self.assertEqual(info["new_vm"], 1)
            original = Patch(source, "HeroSkin_2")
            written = Patch(destination, "HeroSkin_2")
            self.assertEqual(written.methods[:1], original.methods)
            self.assertEqual(len(written.parsed["methods"]), 2)

            fix = next(row for row in written.parsed["fixes"]
                       if "UpdateLogic" in row["desc"])
            self.assertEqual(fix["method_id"], 1)
            self.assertEqual(len(written.parsed["fixes"]), 1)
            strings = {row["value"] for row in written.parsed["intern_strings"]}
            self.assertIn(RUSH_MARKER, strings)
            self.assertIn(AUTO_RUSH_KEY, strings)
            # Bảng extern mới chỉ thêm GetInt; các extern còn lại được tái dùng.
            names = [row["method_name"] for row in written.parsed["extern_methods"]]
            self.assertEqual(names.count("GetInt"), 1)
            self.assertEqual(len(names), len(EXISTING_EXTERNS) + 1)

    def test_refuses_to_wrap_twice_and_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "HeroSkin_2.bytes"
            source.write_bytes(make_hero2())
            first = Path(tmp) / "first.bytes"
            build_rush_patch(source, first)
            with self.assertRaises(FileExistsError):
                build_rush_patch(source, first)
            with self.assertRaises(ValueError):
                build_rush_patch(first, Path(tmp) / "second.bytes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
