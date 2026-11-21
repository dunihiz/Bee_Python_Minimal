#!/usr/bin/env python3
"""Static IFix verification; never executes game code.

Return arities are explicit audited data, not guessed from the method name.
Custom-return values below are corroborated by their unmodified use followed by
Stloc or another consumer. This verifies stack shape, not the runtime return type.
"""
from __future__ import annotations
import argparse
from collections import deque
import importlib.util
import json
from pathlib import Path

PARSER = Path(__file__).resolve().parent / 'HeroSkin_DumpRepack.py'
CONDITIONAL_1 = {'Brtrue', 'Brfalse'}
CONDITIONAL_2 = {'Beq', 'Bne_Un', 'Bge', 'Bge_Un', 'Bgt', 'Bgt_Un', 'Ble', 'Ble_Un', 'Blt', 'Blt_Un'}
BRANCHES = CONDITIONAL_1 | CONDITIONAL_2 | {'Br', 'Leave'}
# Original HeroSkin_2 extern table (71 entries). Unity setters/actions return void;
# original consumers establish that every remaining non-constructor entry returns
# one evaluation-stack slot. A caller may supply a replacement audited table.
HERO2_VOID = {18, 19, 20, 21, 23, 24, 25, 28, 34, 47, 48, 49, 52}
HERO2_CONSTRUCTORS = {27, 33, 36}
HERO2_EXTERN_RETURNS = {i: (0 if i in HERO2_VOID | HERO2_CONSTRUCTORS else 1) for i in range(71)}

class VerificationError(AssertionError):
    pass


def load_patch(path):
    spec = importlib.util.spec_from_file_location('hero_dump_repack_verifier', PARSER)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    raw = Path(path).read_bytes()
    plain = raw[8:]
    if len(plain) < 8 or raw[:4] == parser.MAGIC_BYTES:
        # HeroSkin_1 uses the encrypted wrapper; HeroSkin_2 is raw at byte 8.
        try:
            plain = parser.decrypt(path, Path(path).name.removesuffix('.bytes'))
        except Exception:
            plain = raw[8:]
    result = parser.parse_patch(plain)
    if result['trailing_bytes']:
        raise VerificationError(f"{result['trailing_bytes']} unparsed trailing bytes")
    return result


def successors(instructions, index):
    ins = instructions[index]
    op, operand = ins['op'], ins['operand']
    if op in {'Ret', 'Throw', 'Rethrow'}:
        return []
    if op in {'Br', 'Leave'}:
        candidates = [index + operand]
    elif op in CONDITIONAL_1 | CONDITIONAL_2:
        candidates = [index + operand, index + 1]
    else:
        candidates = [index + 1]
    for target in candidates:
        if not 0 <= target < len(instructions):
            raise VerificationError(f'{index} {op}: target {target} outside 0..{len(instructions)-1}')
    return candidates


def vm_returns(method):
    values = {i['operand'] for i in method['instructions'] if i['op'] == 'Ret'}
    if len(values) != 1 or not values <= {0, 1}:
        raise VerificationError(f"VM {method.get('index')}: ambiguous return arity {values}")
    return values.pop()


def stack_effect(ins, patch, extern_returns):
    op, operand = ins['op'], ins['operand']
    if op in {'StackSpace', 'Nop', 'Br', 'Leave'}:
        return 0, 0
    if op in {'Ldarg', 'Ldarga', 'Ldloc', 'Ldloca', 'Ldc_I4', 'Ldc_I8', 'Ldc_R4', 'Ldc_R8', 'Ldstr', 'Ldnull', 'Ldtype', 'Ldtoken', 'Ldsfld', 'Ldsflda'}:
        return 0, 1
    if op in {'Stloc', 'Starg', 'Stsfld', 'Pop', 'Initobj'}:
        return 1, 0
    if op in {'Ldfld', 'Ldflda', 'Ldobj', 'Ldlen', 'Newarr', 'Box', 'Unbox', 'Unbox_Any', 'Castclass', 'Isinst', 'Neg', 'Not'} or op.startswith('Conv_') or op.startswith('Ldind_'):
        return 1, 1
    if op.startswith('Stelem'):
        return 3, 0
    if op.startswith('Ldelem'):
        return 2, 1
    if op == 'Dup':
        return 1, 2
    if op in {'Stfld', 'Stobj'} or op.startswith('Stind_'):
        return 2, 0
    if op in {'Add', 'Add_Ovf', 'Add_Ovf_Un', 'Sub', 'Sub_Ovf', 'Sub_Ovf_Un', 'Mul', 'Mul_Ovf', 'Mul_Ovf_Un', 'Div', 'Div_Un', 'Rem', 'Rem_Un', 'And', 'Or', 'Xor', 'Shl', 'Shr', 'Shr_Un', 'Ceq', 'Cgt', 'Cgt_Un', 'Clt', 'Clt_Un'}:
        return 2, 1
    if op in CONDITIONAL_1:
        return 1, 0
    if op in CONDITIONAL_2:
        return 2, 0
    if op == 'Ret':
        return operand, 0
    if op == 'Throw':
        return 1, 0
    if op in {'CallExtern', 'Newobj'}:
        argc, extern_id = (operand >> 16) & 0xffff, operand & 0xffff
        if extern_id >= len(patch['extern_methods']):
            raise VerificationError(f'{op}: nonexistent extern {extern_id}')
        if op == 'Newobj':
            if patch['extern_methods'][extern_id]['method_name'] != '.ctor':
                raise VerificationError(f'Newobj extern {extern_id} is not a constructor')
            return argc, 1
        if extern_id not in extern_returns:
            raise VerificationError(f'No audited return arity for extern {extern_id}')
        return argc, extern_returns[extern_id]
    if op in {'Call', 'Callvirt'}:
        argc, method_id = (operand >> 16) & 0xffff, operand & 0xffff
        if method_id >= len(patch['methods']):
            raise VerificationError(f'{op}: nonexistent VM method {method_id}')
        return argc, vm_returns(patch['methods'][method_id])
    raise VerificationError(f'Unsupported opcode {op}; cannot certify stack shape')


def verify_method(patch, method_id, extern_returns):
    method = patch['methods'][method_id]
    instructions = method['instructions']
    if not instructions:
        raise VerificationError(f'VM {method_id}: empty method')
    handlers=method.get('exception_handlers',[])
    # Support the deliberately small catch-only subset used by passive HUD.
    # IFix resets the evaluation stack and pushes the exception at handler entry.
    regions=[]
    for handler in handlers:
        ts,te,hs,he=(handler[k] for k in ['try_start','try_end','handler_start','handler_end'])
        if handler['handler_type']!=0 or handler['catch_type_id']!=-1:
            raise VerificationError('Only flat catch-all handlers are supported')
        if not 1<=ts<te<=hs<he<=len(instructions):
            raise VerificationError(f'Invalid catch bounds: {(ts,te,hs,he)}')
        if instructions[hs-1]['op'] not in {'Br','Ret','Throw','Rethrow'}:
            raise VerificationError('Normal control flow falls into a catch handler')
        regions.append((ts,te,hs,he))
    for i,a in enumerate(regions):
        for b in regions[i+1:]:
            if max(a[0],b[0])<min(a[3],b[3]):
                raise VerificationError('Overlapping/nested catch regions are not supported')
    # Every branch is checked, including currently unreachable code.
    for index, ins in enumerate(instructions):
        if ins['op'] in BRANCHES:
            for target in successors(instructions,index):
                for ts,te,hs,he in regions:
                    if hs<=target<he and not hs<=index<he:
                        raise VerificationError('Normal flow enters a catch handler')
                    if ts<target<te and not ts<=index<te:
                        raise VerificationError('Normal flow enters the middle of a try block')
    pending = deque([(0, 0)]+[(h['handler_start'],1) for h in handlers])
    depths, externs, calls, fields = {}, set(), set(), set()
    max_depth = 0
    local_count = (instructions[0]['operand'] >> 16) & 0xffff if instructions[0]['op'] == 'StackSpace' else None
    while pending:
        index, depth = pending.popleft()
        if index in depths:
            if depths[index] != depth:
                raise VerificationError(f'VM {method_id} instruction {index}: incompatible incoming stack depths {depths[index]} and {depth}')
            continue
        depths[index] = depth
        ins = instructions[index]
        if ins['op'] in {'Ldloc', 'Ldloca', 'Stloc'} and local_count is not None and not 0 <= ins['operand'] < local_count:
            raise VerificationError(f'VM {method_id} instruction {index}: local {ins["operand"]} outside declared {local_count}')
        pop, push = stack_effect(ins, patch, extern_returns)
        if depth < pop:
            raise VerificationError(f'VM {method_id} instruction {index} {ins["op"]}: stack underflow ({depth} < {pop})')
        new_depth = depth - pop + push
        max_depth = max(max_depth, new_depth)
        if ins['op'] == 'Ret' and new_depth != 0:
            raise VerificationError(f'VM {method_id} instruction {index}: Ret leaves {new_depth} stack slots')
        if ins['op'] in {'Ldfld', 'Stfld', 'Ldflda', 'Ldsfld', 'Stsfld', 'Ldsflda'}:
            if 'fields' in patch and not 0 <= ins['operand'] < len(patch['fields']):
                raise VerificationError(f'VM {method_id} instruction {index}: nonexistent field {ins["operand"]}')
            fields.add(ins['operand'])
        if ins['op'] in {'CallExtern', 'Newobj'}:
            externs.add(ins['operand'] & 0xffff)
        elif ins['op'] in {'Call', 'Callvirt'}:
            calls.add(ins['operand'] & 0xffff)
        for target in successors(instructions, index):
            pending.append((target, new_depth))
    return {'method_id': method_id, 'reachable_instructions': len(depths), 'max_stack_depth': max_depth, 'extern_ids': sorted(externs), 'vm_calls': sorted(calls), 'field_ids': sorted(fields)}


def verify_patch(patch, extern_returns=None, roots=None, avatar_only=False, portrait_renderer_externs=()):
    if extern_returns is None:
        extern_returns = HERO2_EXTERN_RETURNS
    if roots is None:
        roots = sorted({f['method_id'] for f in patch['fixes']})
    pending, reports = list(roots), {}
    while pending:
        method_id = pending.pop()
        if method_id in reports:
            continue
        report = verify_method(patch, method_id, extern_returns)
        reports[method_id] = report
        pending.extend(report['vm_calls'])
    all_externs = {e for report in reports.values() for e in report['extern_ids']}
    if avatar_only:
        allowed=set(portrait_renderer_externs)
        for e in allowed:
            method=patch['extern_methods'][e]
            if not method['desc'].startswith('UnityEngine.Renderer,') or method['method_name'] not in {'get_enabled','set_enabled'}:
                raise VerificationError('Portrait renderer allowlist permits enabled getters/setters only')
        forbidden = {e for e in all_externs if e not in allowed and ('LineRenderer' in patch['extern_methods'][e]['desc'] or 'UnityEngine.Renderer' in patch['extern_methods'][e]['desc'])}
        if forbidden:
            raise VerificationError(f'Reachable ESP/health renderer calls: {sorted(forbidden)}')
        forbidden_fields = {f for report in reports.values() for f in report['field_ids']
                            if f < len(patch.get('fields', []))
                            and patch['fields'][f]['name'].startswith(('__ifxHp', '__ifxObjHp'))}
        if forbidden_fields:
            raise VerificationError(f'Reachable extra health renderer state: {sorted(forbidden_fields)}')
        if all_externs & {64, 65, 66}:
            raise VerificationError(f'Reachable jungle/dragon tracking functions: {sorted(all_externs & {64, 65, 66})}')
        # Helper indices are reused by later patch versions. Certify their
        # reachable behavior and fields rather than their former numeric IDs.
        needed = {5, 8, 43, 44, 49, 50, 51, 52}
        missing = needed - all_externs
        if missing:
            raise VerificationError(f'Missing enemy/avatar position/display functions: {sorted(missing)}')
    return {'methods': [reports[i] for i in sorted(reports)], 'externs_reachable': sorted(all_externs), 'avatar_only': avatar_only}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    parser.add_argument('--avatar-only', action='store_true')
    parser.add_argument('--arity-json', type=Path, help='Explicit extern ID to 0/1 returned stack slots')
    args = parser.parse_args()
    arities = {int(k): v for k, v in json.loads(args.arity_json.read_text()).items()} if args.arity_json else None
    try:
        print(json.dumps(verify_patch(load_patch(args.path), arities, avatar_only=args.avatar_only), indent=2))
    except VerificationError as exc:
        parser.exit(1, f'FAIL: {exc}\n')

if __name__ == '__main__':
    main()
