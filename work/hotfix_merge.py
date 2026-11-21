"""Retain a game's entire IFix patch and append a same-module custom patch.

No original table index or method body is changed. Appended references are
relocated, including packed calls, generics and exception catch types.
"""
from pathlib import Path
import struct
import tempfile

from HeroSkin_DumpRepack import R, parse_method
from ifix_patch import Patch, i32, string
from chat_camera import _write_with_fixes, validate_fix_assemblies

TYPE_OPS = {'Box', 'Unbox', 'Unbox_Any', 'Castclass', 'Isinst', 'Newarr',
            'Ldtype', 'Ldtoken', 'Constrained', 'Initobj', 'Ldobj', 'Stobj',
            'Cpobj', 'Ldelem_Any', 'Stelem_Any', 'Ldelema', 'Sizeof', 'Refanyval', 'Mkrefany'}
FIELD_OPS = {'Ldfld', 'Ldflda', 'Stfld', 'Ldsfld', 'Stsfld', 'Ldsflda'}


def encode_method(m, type_map):
    out = bytes([m['generic']]) + i32(type_map[m['decl_type_id']]) + string(m['method_name'])
    if m['generic']:
        out += i32(len(m['generic_args'])) + b''.join(i32(type_map[t]) for t in m['generic_args'])
        out += i32(len(m['params']))
        for p in m['params']:
            out += bytes([p['generic']])
            out += string(p['value']) if p['generic'] else i32(type_map[p['value']])
    else:
        out += i32(len(m['params'])) + b''.join(i32(type_map[t]) for t in m['params'])
    return out


def relocate_method(method, plain, maps):
    raw = bytearray(plain[method['count_offset']:method['eh_end']])
    skip = 0
    for ins in method['instructions']:
        if skip:
            skip -= 1
            continue
        op, value = ins['op'], ins['operand']
        if op == 'Switch':
            skip = (value + 1) // 2  # payload is packed int32 offsets, not instructions
        elif op in {'Ldc_I8', 'Ldc_R8'}:
            skip = 1
        elif op in TYPE_OPS:
            if value >= 0: value = maps['type'][value]
        elif op in FIELD_OPS:
            if value < 0: raise ValueError('Anonymous static fields are unsupported')
            value = maps['field'][value]
        elif op == 'Ldstr': value = maps['string'][value]
        elif op in {'CallExtern', 'Newobj'}:
            value = (value & ~65535) | maps['extern'][value & 65535]
        elif op in {'Call', 'Callvirt'}:
            value = (value & ~65535) | maps['method'][value & 65535]
        elif op in {'Ldftn', 'Ldvirtftn'}: value = maps['extern'][value]
        elif op in {'Newanon', 'Callvirtvirt', 'Ldvirtftn2', 'Jmp'}:
            raise ValueError('Unsupported indirect instruction: ' + op)
        struct.pack_into('<i', raw, ins['operand_offset'] - method['count_offset'], value)
    if skip: raise ValueError('Truncated inline instruction payload')
    for eh in method['exception_handlers']:
        if eh['catch_type_id'] >= 0:
            struct.pack_into('<i', raw, eh['offset'] + 4 - method['count_offset'], maps['type'][eh['catch_type_id']])
    return bytes(raw)


def merge_patch(base_path, custom_path, output_path, key):
    base, custom = Patch(base_path, key), Patch(custom_path, key)
    a, b = base.parsed, custom.parsed
    assembly = lambda p: p['assembly'].lstrip(', ').split(',')[0]
    if assembly(a) != assembly(b): raise ValueError('Cannot merge different modules')
    for p in (a, b):
        validate_fix_assemblies(p)
    for count in ('static_field_type_count', 'new_class_count'):
        if a.get(count, 0): raise ValueError('Unsupported base nonempty section: ' + count)
    # The official update may carry anonymous-storey metadata that the old
    # parser cannot decode.  It is part of the untouched tail and is preserved
    # by Patch.write/_write_with_fixes.  A custom patch still must be flat so
    # its method/field tables can be relocated safely.
    for count in ('static_field_type_count', 'anonymous_storey_count', 'new_class_count'):
        if b.get(count, 0): raise ValueError('Unsupported custom nonempty section: ' + count)
    # Active method signatures must be disjoint; do not silently override updates.
    names = lambda p: {(f['desc'].split(',')[0], f['desc'].split('::')[1]) for f in p['fixes']}
    if names(a) & names(b): raise ValueError('Conflicting active patch signatures')
    offsets = {'type': a['extern_type_count'], 'method': a['method_count'],
               'extern': a['extern_method_count'], 'string': a['intern_string_count'], 'field': a['field_count']}
    lengths = {'type': b['extern_type_count'], 'method': b['method_count'],
               'extern': b['extern_method_count'], 'string': b['intern_string_count'], 'field': b['field_count']}
    maps = {k: {i: v + i for i in range(lengths[k])} for k, v in offsets.items()}
    if any(offsets[k] + lengths[k] > 65535 for k in ['method', 'extern']):
        raise ValueError('Packed method index overflow')
    base.types.extend(b['extern_types'])
    base.methods.extend(relocate_method(m, custom.plain, maps) for m in b['methods'])
    base.externs.extend(encode_method(m, maps['type']) for m in b['extern_methods'])
    base.strings.extend(string(s['value']) for s in b['intern_strings'])
    for f in b['fields']:
        rec = bytes([f['is_new']]) + i32(maps['type'][f['decl_type_id']]) + string(f['name'])
        if f['is_new']:
            rec += i32(maps['type'][f['field_type_id']])
            rec += i32(maps['method'][f['method_id']] if f['method_id'] >= 0 else f['method_id'])
        base.fields.append(rec)
    records = [base.plain[f['offset']:f['record_end']] for f in a['fixes']]
    for f in b['fixes']:
        r = R(custom.plain); r.p = f['offset']
        records.append(encode_method(parse_method(r), maps['type']) + i32(maps['method'][f['method_id']]))
    # Complete validation before replacing the requested output.
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / (key + '.bytes')
        base.write(staging)
        combined = Patch(staging, key)
        _write_with_fixes(combined, staging, records)
        verified = Patch(staging, key)
        assert verified.methods[:a['method_count']] == Patch(base_path, key).methods
        assert verified.parsed['fix_count'] == a['fix_count'] + b['fix_count']
        output = Path(output_path); output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(staging.read_bytes())
    return {'maps': maps, 'official_fixes': a['fix_count'], 'custom_fixes': b['fix_count']}
