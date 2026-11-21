"""Small IFix chat VM fixture used by build-time validation."""
import math
from chat_camera import CAMERA_KEY, ESP_KEY, HUD_KEY, SKIN_KEY, SKIN_ARM_KEY

class ChatNative:
    """Model native edit semantics independently of command parsing."""
    def __init__(self):
        self.prefs = {}
        self.sent = []
        self.normal_edits = []
        self.blocked = False
        self.input_text = ''
        self.input_visible = True
        self.camp = 1
        self.refreshes = 0
        self.wrapper = object()
        self.slot = 0x2882
        self.wrappers = [None] * (self.slot + 2)
        self.wrappers[self.slot] = self.wrapper
        self.wrappers[self.slot + 1] = object()
        self.fail_native = False
        self.native_slot_states = []

    def normal_edit(self, view, text):
        self.normal_edits.append(text)
        self.input_text = ''
        if self.blocked:
            return
        if text and text.strip():
            self.sent.append((text, self.camp))
            self.input_visible = False

    def call(self, descriptor, args):
        name = descriptor['method_name']
        owner = descriptor['desc'].split(',')[0]
        if owner == 'System.Type':
            if name == 'GetType': return args[0]
            if name == 'GetField':
                assert args[0] == 'IFix.ILFixDynamicMethodWrapper, Project_d'
                assert args[1] == 'wrapperArray'
                return args[1]
            if name == 'GetMethod':
                assert args[0] == 'InBattleMsgInputView, Project_d'
                assert args[1] == 'On_EndEdit'
                return args[1]
        if owner == 'System.Enum' and name == 'Parse':
            assert args == ['IFix.IDMAP0, Project_d','InBattleMsgInputView-On_EndEdit0']
            return self.slot
        if owner == 'System.Convert' and name == 'ToInt32': return int(args[0])
        if owner == 'System.Reflection.FieldInfo' and name == 'GetValue': return self.wrappers
        if owner == 'System.Array':
            if name == 'get_Length': return len(args[0])
            if name == 'GetValue': return args[0][args[1]]
            if name == 'SetValue': args[0][args[2]] = args[1]; return
        if owner == 'System.Reflection.MethodBase' and name == 'Invoke':
            assert args[0] == 'On_EndEdit'
            self.native_slot_states.append(self.wrappers[self.slot])
            if self.wrappers[self.slot] is not None: raise AssertionError('recursive hook dispatch')
            if self.fail_native: raise RuntimeError('native send failed')
            self.normal_edit(args[1],args[2][0])
            return None
        if owner == 'System.String':
            if name == 'StartsWith': return args[0].startswith(args[1])
            if name == 'Substring': return args[0][args[1]:]
            if name == 'op_Equality': return args[0] == args[1]
        if owner == 'System.Globalization.CultureInfo': return object()
        if owner in {'System.Int32', 'System.Single'} and name == 'TryParse':
            try:
                value = int(args[0]) if owner.endswith('Int32') else float(args[0])
            except ValueError:
                return False
            args[-1](value)
            return True
        if name == 'IsNaN': return math.isnan(args[0])
        if name == 'IsInfinity': return math.isinf(args[0])
        if owner == 'UnityEngine.PlayerPrefs':
            if name in {'SetInt', 'SetFloat'}:
                self.prefs[args[0]] = args[1]
                return
        if owner == 'UnityEngine.Mathf' and name == 'Clamp':
            return max(args[1], min(args[2], args[0]))
        if name == 'GetInstance' and 'CameraSystem' in owner: return object()
        if name == 'OnCameraHeightChanged':
            self.refreshes += 1
            return
        # Re-entering this native method is valid only if the fix is bypassed;
        # implementations must separately prove that they avoid recursion.
        if owner == 'InBattleMsgInputView' and name == 'On_EndEdit':
            return self.normal_edit(*args)
        raise AssertionError(f'Unmodeled native chat call {owner}::{name}')


def execute_chat(patch, method_id, view, text, native):
    """Small interpreter with real byref local writes for TryParse."""
    import struct
    code = patch['methods'][method_id]['instructions']
    arguments, stack, local, pc = [view, text], [], {}, 0
    void = {'SetInt', 'SetFloat', 'OnCameraHeightChanged', 'On_EndEdit', 'SetValue'}
    for _ in range(2000):
        ins = code[pc]
        op, value = ins['op'], ins['operand']
        next_pc = pc + 1
        try:
            if op in {'StackSpace', 'Nop'}: pass
            elif op == 'Ldarg': stack.append(arguments[value])
            elif op == 'Ldstr': stack.append(patch['intern_strings'][value]['value'])
            elif op == 'Ldnull': stack.append(None)
            elif op == 'Ldc_I4': stack.append(value)
            elif op == 'Ldc_R4': stack.append(struct.unpack('<f', struct.pack('<i', value))[0])
            elif op == 'Stloc': local[value] = stack.pop()
            elif op == 'Ldloc': stack.append(local[value])
            elif op == 'Ldloca': stack.append(lambda item, slot=value: local.__setitem__(slot, item))
            elif op == 'Pop': stack.pop()
            elif op == 'Castclass': pass
            elif op == 'Newarr': stack.append([None]*stack.pop())
            elif op == 'Stelem_Ref':
                item,index,array=stack.pop(),stack.pop(),stack.pop();array[index]=item
            elif op == 'CallExtern':
                count, index = value >> 16, value & 0xffff
                args = stack[-count:] if count else []
                if count: del stack[-count:]
                desc = patch['extern_methods'][index]
                result = native.call(desc, args)
                if desc['method_name'] not in void: stack.append(result)
            elif op == 'Br': next_pc = pc + value
            elif op in {'Brfalse', 'Brtrue'}:
                if bool(stack.pop()) == (op == 'Brtrue'): next_pc = pc + value
            elif op in {'Blt', 'Bgt', 'Bge'}:
                right, left = stack.pop(), stack.pop()
                if ({'Blt':left < right,'Bgt':left > right,'Bge':left >= right}[op]): next_pc = pc + value
            elif op == 'Ret':
                assert not stack
                return
            else: raise AssertionError(f'Unmodeled chat opcode {op}')
        except RuntimeError as error:
            handler=next((h for h in patch['methods'][method_id]['exception_handlers']
                          if h['try_start'] <= pc < h['try_end']),None)
            if handler is None: raise
            stack[:]=[error]
            next_pc=handler['handler_start']
        pc = next_pc
    raise AssertionError('Command execution did not terminate')
