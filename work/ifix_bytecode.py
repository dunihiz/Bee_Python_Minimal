"""Shared instruction iteration, relocation and exception helpers."""
import struct
from ifix_format import body, BRANCHES

def splice(method, before=None, after=None):
    before, after = before or {}, after or {}
    old = method['instructions']
    entries, locations, result = {}, {}, []
    for index, ins in enumerate(old):
        entries[index] = len(result)
        result.extend(before.get(index, []))
        locations[index] = len(result)
        result.append((ins['code'], ins['operand']))
        result.extend(after.get(index, []))
    for index, ins in enumerate(old):
        if ins['op'] in BRANCHES:
            location = locations[index]
            result[location] = (ins['code'], entries[index + ins['operand']] - location)
    return body(result)

def catches(code,regions):
    """Append IFix Catch=0/CatchTypeId=-1 records; endpoints are exclusive.

    Source: Tencent/InjectFix Source/VSProj/Src/Core/Instruction.cs and
    FileVirtualMachineBuilder.cs / VirtualMachine.cs, preserved in work refs.
    Only plain Br exits are used, since IFix Leave routes through finally code.
    """
    raw=code.finish()[:-4]+struct.pack('<i',len(regions))
    for start,end,handler,handlerend in regions:
        raw+=struct.pack('<6i',0,-1,*(code.labels[key] for key in [start,end,handler,handlerend]))
    return raw

def _real_instructions(method):
    """Skip parser rows that are inline operands of Switch/Ldc_I8/Ldc_R8."""
    skip = 0
    for row in method["instructions"]:
        if skip:
            skip -= 1
            continue
        yield row
        if row["op"] == "Switch":
            skip = (row["operand"] + 1) // 2
        elif row["op"] in {"Ldc_I8", "Ldc_R8"}:
            skip = 1
