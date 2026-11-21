"""Extract auto-spells and emit their chat commands from the pinned donor."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import tempfile
from chat_camera import CAMERA_KEY, ESP_KEY, _chat_command, _write_with_fixes
from HeroSkin_DumpRepack import encrypt
from ifix_bytecode import splice, _real_instructions
from ifix_patch import Code, OP, Patch, i32
ROOT = Path(__file__).resolve().parent.parent
DONOR = ROOT / "inputs/donor"
DONOR_HASHES = {"HeroSkin_2.bytes": "f85e09a6cbd55d805d5c1fbec02119138dbac695e1737f4d454c5b96937ada9c"}

AUTO_SMITE_KEY = "iFix.AutoSmite.Enabled.v1"


AUTO_SMITE_MODE_KEY = "iFix.AutoSmite.TargetMode.v1"


AUTO_BP_KEY = "iFix.AutoBP.Enabled.v1"


DONOR_ESP_DISABLED_KEY = "iFix.ESP.NativeDisabled.R5.v1"


def _digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _replace_chat_commands(source, target):
    patch = Patch(source, "HeroSkin_1")
    fix = next(
        row for row in patch.parsed["fixes"]
        if "InBattleMsgInputView" in row["desc"] and "On_EndEdit" in row["desc"]
    )
    method, _, _ = _chat_command(
        patch,
        CAMERA_KEY,
        {"esp": ESP_KEY},
        native_passthrough=True,
        extra_toggle_commands=(
            ("/trungtri on", AUTO_SMITE_KEY, 1),
            ("/trungtri off", AUTO_SMITE_KEY, 0),
            ("/bocpha on", AUTO_BP_KEY, 1),
            ("/bocpha off", AUTO_BP_KEY, 0),
        ),
    )
    patch.methods[fix["method_id"]] = method
    records = [patch.plain[row["offset"]:row["record_end"]]
               for row in patch.parsed["fixes"]]
    return _write_with_fixes(patch, target, records)


def _donor_auto_patch(target):
    """Keep donor auto-spells while disabling donor ESP and signature checks."""
    donor = DONOR / "HeroSkin_2.bytes"
    if _digest(donor) != DONOR_HASHES[donor.name]:
        raise ValueError("Donor HeroSkin_2 hash mismatch")
    patch = Patch(donor, "HeroSkin_2")
    method = deepcopy(patch.parsed["methods"][3])
    code = method["instructions"]

    defaults = {
        "iFix.ESP.Enabled.v1": 0,
        AUTO_BP_KEY: 0,
        AUTO_SMITE_KEY: 0,
        AUTO_SMITE_MODE_KEY: 0,
    }
    for key, default in defaults.items():
        matches = [
            row["index"] for row in code[:-2]
            if row["op"] == "Ldstr"
            and 0 <= row["operand"] < len(patch.parsed["intern_strings"])
            and patch.parsed["intern_strings"][row["operand"]]["value"] == key
            and code[row["index"] + 1]["op"] == "Ldc_I4"
            and code[row["index"] + 2]["op"] == "CallExtern"
            and patch.parsed["extern_methods"][
                code[row["index"] + 2]["operand"] & 65535
            ]["method_name"] == "GetInt"
        ]
        if len(matches) != 1:
            raise ValueError(f"Cannot identify donor default for {key}: {matches}")
        index = matches[0]
        code[index + 1]["operand"] = default
        if key == "iFix.ESP.Enabled.v1":
            code[index]["operand"] = patch.intern(DONOR_ESP_DISABLED_KEY)

    patch.methods[3] = splice(method)
    # Every donor fixed method calls VM20 first.  Auto-spell keeps the call but
    # targets this local no-op, so the signed donor pair is not required.
    guard = Code(0, 0)
    guard.emit("Ret", 0)
    patch.methods[19] = guard.finish()
    patch.methods[20] = guard.finish()
    # The donor's sole anonymous static slot belongs to its integrity guard.
    # Once VM20 is a no-op, retaining that slot would make this otherwise-flat
    # helper patch impossible to relocate into the updated R5 module.
    parsed = patch.parsed
    if parsed["static_field_type_count"] != 1 or parsed["anonymous_storey_count"]:
        raise ValueError("Unexpected donor static metadata layout")
    update_fix = next(row for row in patch.parsed["fixes"]
                      if row["method_id"] == 3 and "CPlayerLocationStat" in row["desc"])
    record = patch.plain[update_fix["offset"]:update_fix["record_end"]]
    _write_with_fixes(patch, target, [record])

    # Strip the now-unreferenced static slot only after rebuilding the active
    # fix registry, so every offset used by _write_with_fixes remains valid.
    flat = Patch(target, "HeroSkin_2")
    parsed = flat.parsed
    plain = (
        flat.plain[:parsed["static_field_type_count_offset"]]
        + i32(0)
        + flat.plain[parsed["anonymous_storey_count_offset"]:]
    )
    Path(target).write_bytes(encrypt(plain, "HeroSkin_2"))
    verified = Patch(target, "HeroSkin_2").parsed
    if verified["static_field_type_count"] or verified["anonymous_storey_count"]:
        raise ValueError("Donor static metadata was not removed")
    return verified
FORBIDDEN_AUTO_CALLS = {
    "Find", "SetActive", "Destroy", "get_transform", "GetChild",
    "get_gameObject", "get_childCount", "AddComponent", "set_renderMode",
    "set_sortingOrder", "get_main", "get_width", "get_height",
    "get_bVisible", "get_MapPointerSmall",
}


def _no_op():
    code = Code(0, 0)
    code.emit("Ret", 0)
    return code.finish()


def _nop_range(code, start, end):
    for index in range(start, end + 1):
        code[index]["op"] = "Nop"
        code[index]["code"] = OP["Nop"]
        code[index]["operand"] = 0


def _clean_auto_patch(target):
    """Strip all donor presentation paths from its isolated auto patch."""
    with tempfile.TemporaryDirectory() as tmp:
        isolated = Path(tmp) / "HeroSkin_2.isolated-auto.bytes"
        _donor_auto_patch(isolated)
        patch = Patch(isolated, "HeroSkin_2")
        fixes = [row for row in patch.parsed["fixes"]
                 if "CPlayerLocationStat" in row["desc"]]
        if len(fixes) != 1 or fixes[0]["method_id"] != 3:
            raise ValueError("Unexpected isolated donor auto registry")

        method = deepcopy(patch.parsed["methods"][3])
        if len(method["instructions"]) != 1033 or method["exception_handlers"]:
            raise ValueError("Donor auto method layout changed")
        code = method["instructions"]

        # UI root cleanup and ESP preference. Keep local 5 deterministically 0.
        _nop_range(code, 12, 96)
        code[12]["op"] = "Ldc_I4"
        code[12]["code"] = OP["Ldc_I4"]
        code[13]["op"] = "Stloc"
        code[13]["code"] = OP["Stloc"]
        code[13]["operand"] = 5

        # Canvas/camera/screen setup used only by donor line ESP.
        _nop_range(code, 139, 178)
        # Enemy visibility, line renderers, and MapPointerSmall gate.
        _nop_range(code, 393, 436)
        # ESP helper calls around the auto-BP block.
        _nop_range(code, 450, 454)
        _nop_range(code, 497, 501)
        # Soldier ESP pass after auto-smite completes.
        _nop_range(code, 945, 1031)

        patch.methods[3] = splice(method)
        patch.methods[17] = _no_op()
        record = patch.plain[fixes[0]["offset"]:fixes[0]["record_end"]]
        verified = _write_with_fixes(patch, target, [record])

    active = verified["methods"][3]
    instructions = list(_real_instructions(active))
    extern_names = {
        verified["extern_methods"][row["operand"] & 65535]["method_name"]
        for row in instructions if row["op"] == "CallExtern"
    }
    leaked_calls = extern_names & FORBIDDEN_AUTO_CALLS
    if leaked_calls:
        raise ValueError(f"Donor UI/ESP calls remain active: {sorted(leaked_calls)}")
    strings = {
        verified["intern_strings"][row["operand"]]["value"]
        for row in instructions
        if row["op"] == "Ldstr"
    }
    if any("ESP" in value or "HiddenHeroLines" in value for value in strings):
        raise ValueError("Donor ESP strings remain reachable")
    internal_calls = {
        row["operand"] & 65535 for row in instructions
        if row["op"] in {"Call", "Callvirt"}
    }
    if internal_calls & {4, 5, 14, 15, 17}:
        raise ValueError(f"Donor presentation helper remains active: {internal_calls}")
    if not {AUTO_BP_KEY, AUTO_SMITE_KEY, AUTO_SMITE_MODE_KEY} <= strings:
        raise ValueError("An auto-spell preference was removed")
    if DONOR_ESP_DISABLED_KEY in strings:
        raise ValueError("Disabled donor ESP preference should no longer be read")
    return verified
