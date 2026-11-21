"""Build a camera-only IFix patch controlled by `/ecam <zoom>`."""
from pathlib import Path
import hashlib
import json
import math
import re
import shutil
import struct
import zipfile

from ifix_format import parse_original
from HeroSkin_DumpRepack import decrypt, encrypt
from ifix_patch import Code, Patch, float_bits, i32, string


CAMERA_KEY = '__ifxChatCameraV1'
ESP_KEY = '__ifxEnemyEspEnabledV1'
HUD_KEY = '__ifxEnemyHudEnabledV1'
SKIN_KEY = '__ifxRuntimeSkinV1'
SKIN_ARM_KEY = '__ifxRuntimeSkinArmedV1'
COMMAND_PREFIX = '/ecam '
SKIN_PREFIX = '/eskin '
MIN_ZOOM = 1.0
MAX_ZOOM = 2.3
DEFAULT_ZOOM = 2.1

WORK = Path(__file__).resolve().parent
ROOT = WORK.parent
DEFAULT_BASE = (Path(__file__).resolve().parent.parent / 'inputs/legacy-camera-fixture/HeroSkin_1.bytes')
DEFAULT_EMPTY_HERO2 = (Path(__file__).resolve().parent.parent / 'inputs/legacy-camera-fixture/HeroSkin_2.bytes')


def parse_ecam(content):
    """Reference behavior used to verify the emitted bytecode contract."""
    if not isinstance(content, str) or not content.startswith(COMMAND_PREFIX):
        return None
    value_text = content[len(COMMAND_PREFIX):]
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', value_text):
        return None
    try:
        value = float(value_text)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return min(MAX_ZOOM, max(MIN_ZOOM, value))


def parse_feature_toggle(content):
    """Reference behavior for the two persisted visibility commands."""
    return {
        '/esp on': (ESP_KEY, 1),
        '/esp off': (ESP_KEY, 0),
        '/hud on': (HUD_KEY, 1),
        '/hud off': (HUD_KEY, 0),
    }.get(content)


def parse_eskin(content):
    """Parse the runtime skin slot accepted by the diagnostic command."""
    if not isinstance(content, str) or not content.startswith(SKIN_PREFIX):
        return None
    value_text = content[len(SKIN_PREFIX):]
    if not re.fullmatch(r'\d+', value_text):
        return None
    value = int(value_text)
    return value if 0 <= value <= 99 else None


def _fix_record(patch, declaring_type, method_name, parameters, method_id):
    return (b'\0' + i32(declaring_type) + string(method_name)
            + i32(len(parameters)) + b''.join(i32(value) for value in parameters)
            + i32(method_id))


def validate_fix_assemblies(parsed):
    """IFix resolves fix IDs only in the patch's own assembly IDMAP."""
    assembly = parsed['assembly'].lstrip(', ').split(',')[0].strip()
    for fix in parsed['fixes']:
        owner = fix['desc'].split('::', 1)[0]
        depth = 0
        for index, char in enumerate(owner):
            if char == '[':
                depth += 1
            elif char == ']':
                depth -= 1
            elif char == ',' and depth == 0:
                target = owner[index + 1:].split(',')[0].strip()
                break
        else:
            raise ValueError('Missing fix assembly: ' + fix['desc'])
        if target != assembly:
            raise ValueError(f"{fix['desc']} belongs to {target}, patch IDMAP is {assembly}")


def _write_with_fixes(patch, output, fix_records):
    """Write updated tables and replace the active fix registry."""
    plain, parsed = patch.plain, patch.parsed
    rebuilt = (
        plain[:parsed['extern_type_count_offset']] + i32(len(patch.types))
        + b''.join(string(value) for value in patch.types)
        + i32(len(patch.methods)) + b''.join(patch.methods)
        + i32(parsed['extern_method_count'] + len(patch.externs))
        + plain[parsed['extern_method_count_offset'] + 4:parsed['intern_string_count_offset']]
        + b''.join(patch.externs)
        + i32(parsed['intern_string_count'] + len(patch.strings))
        + plain[parsed['intern_string_count_offset'] + 4:parsed['field_count_offset']]
        + b''.join(patch.strings)
        + i32(parsed['field_count'] + len(patch.fields))
        + plain[parsed['field_count_offset'] + 4:parsed['static_field_type_count_offset']]
        + b''.join(patch.fields)
        + plain[parsed['static_field_type_count_offset']:parsed['fix_count_offset']]
        + i32(len(fix_records)) + b''.join(fix_records)
        + plain[parsed['new_class_count_offset']:]
    )
    verified = parse_original(rebuilt)
    assert verified['trailing_bytes'] == 0
    validate_fix_assemblies(verified)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if patch.encrypted:
        destination.write_bytes(encrypt(rebuilt, patch.key))
        assert decrypt(destination, patch.key) == rebuilt
    else:
        destination.write_bytes(patch.raw[:4] + i32(len(rebuilt)) + rebuilt)
        assert destination.read_bytes()[8:] == rebuilt
    return verified


def _chat_command(patch, camera_key, toggle_keys=None, skin_key=None,
                  skin_arm_key=None, native_passthrough=False,
                  extra_toggle_commands=()):
    single = patch.type('System.Single', 'mscorlib')
    single_ref = patch.type('System.Single&', 'mscorlib')
    text = patch.type('System.String', 'mscorlib')
    integer = patch.type('System.Int32', 'mscorlib')
    integer_ref = patch.type('System.Int32&', 'mscorlib') if skin_key else None
    number_styles = patch.type('System.Globalization.NumberStyles', 'mscorlib')
    format_provider = patch.type('System.IFormatProvider', 'mscorlib')
    culture = patch.type('System.Globalization.CultureInfo', 'mscorlib')
    prefs = patch.type('UnityEngine.PlayerPrefs', 'UnityEngine.CoreModule')
    mathf = patch.type('UnityEngine.Mathf', 'UnityEngine.CoreModule')
    chat_view = patch.type('InBattleMsgInputView', 'Project_d')
    camera_system = patch.type('CameraSystem', 'Project_d')
    camera_singleton = patch.type(
        'MonoSingleton`1[[CameraSystem, Project_d, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null]]',
        'Project.Plugins_d, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null')

    set_float = patch.extern(prefs, 'SetFloat', [text, single], 2, 0)
    clamp = patch.extern(mathf, 'Clamp', [single, single, single], 3, 1)
    starts_with = patch.extern(text, 'StartsWith', [text], 2, 1)
    substring = patch.extern(text, 'Substring', [integer], 2, 1)
    invariant = patch.extern(culture, 'get_InvariantCulture', [], 0, 1)
    try_parse = patch.extern(single, 'TryParse',
                             [text, number_styles, format_provider, single_ref], 4, 1)
    is_nan = patch.extern(single, 'IsNaN', [single], 1, 1)
    is_infinity = patch.extern(single, 'IsInfinity', [single], 1, 1)
    camera_instance = patch.extern(camera_singleton, 'GetInstance', [], 0, 1)
    refresh_camera = patch.extern(camera_system, 'OnCameraHeightChanged', [], 1, 0)
    set_int = equal = try_parse_int = None
    toggle_strings = []
    if toggle_keys or extra_toggle_commands or skin_key:
        set_int = patch.extern(prefs, 'SetInt', [text, integer], 2, 0)
    if toggle_keys:
        equal = patch.extern(text, 'op_Equality', [text, text], 2, 1)
        configured = []
        for name in ('esp', 'hud'):
            if name not in toggle_keys:
                continue
            configured.extend((
                (f'/{name} on', toggle_keys[name], 1),
                (f'/{name} off', toggle_keys[name], 0),
            ))
        for command_text, key_name, enabled in configured:
            toggle_strings.append((patch.intern(command_text),
                                   patch.intern(key_name), enabled))
    for command_text, key_name, enabled in extra_toggle_commands:
        if equal is None:
            equal = patch.extern(text, 'op_Equality', [text, text], 2, 1)
        toggle_strings.append((patch.intern(command_text),
                               patch.intern(key_name), enabled))
    skin_prefix = skin_pref_key = skin_arm_pref_key = None
    if skin_key:
        assert skin_arm_key
        try_parse_int = patch.extern(integer, 'TryParse', [text, integer_ref], 2, 1)
        skin_prefix = patch.intern(SKIN_PREFIX)
        skin_pref_key = patch.intern(skin_key)
        skin_arm_pref_key = patch.intern(skin_arm_key)
    key = patch.intern(camera_key)
    prefix = patch.intern(COMMAND_PREFIX)
    command = Code(8 if native_passthrough else (3 if skin_key else 2), 5)
    command.emit('Ldarg', 1)
    command.emit('Brfalse', 'done')
    for index, (command_text, key_name, enabled) in enumerate(toggle_strings):
        next_toggle = f'toggle_next_{index}'
        command.emit('Ldarg', 1)
        command.emit('Ldstr', command_text)
        command.emit('CallExtern', equal)
        command.emit('Brfalse', next_toggle)
        command.emit('Ldstr', key_name)
        command.emit('Ldc_I4', enabled)
        command.emit('CallExtern', set_int)
        command.emit('Br', 'done')
        command.label(next_toggle)
    if skin_key:
        command.emit('Ldarg', 1)
        command.emit('Ldstr', skin_prefix)
        command.emit('CallExtern', starts_with)
        command.emit('Brfalse', 'camera')
        command.emit('Ldarg', 1)
        command.emit('Ldc_I4', len(SKIN_PREFIX))
        command.emit('CallExtern', substring)
        command.emit('Ldloca', 2)
        command.emit('CallExtern', try_parse_int)
        command.emit('Brfalse', 'done')
        command.emit('Ldloc', 2)
        command.emit('Ldc_I4', 0)
        command.emit('Blt', 'done')
        command.emit('Ldloc', 2)
        command.emit('Ldc_I4', 99)
        command.emit('Bgt', 'done')
        command.emit('Ldstr', skin_pref_key)
        command.emit('Ldloc', 2)
        command.emit('CallExtern', set_int)
        command.emit('Ldstr', skin_arm_pref_key)
        command.emit('Ldc_I4', 1)
        command.emit('CallExtern', set_int)
        command.emit('Br', 'done')
        command.label('camera')
    command.emit('Ldarg', 1)
    command.emit('Ldstr', prefix)
    command.emit('CallExtern', starts_with)
    command.emit('Brfalse', 'normal_chat' if native_passthrough else 'done')
    command.emit('Ldarg', 1)
    command.emit('Ldc_I4', len(COMMAND_PREFIX))
    command.emit('CallExtern', substring)
    # Allow decimal points consistently even when the phone's locale uses commas.
    command.emit('Ldc_I4', 36)  # AllowLeadingSign | AllowDecimalPoint
    command.emit('CallExtern', invariant)
    command.emit('Ldloca', 0)
    command.emit('CallExtern', try_parse)
    command.emit('Brfalse', 'done')
    command.emit('Ldloc', 0)
    command.emit('CallExtern', is_nan)
    command.emit('Brtrue', 'done')
    command.emit('Ldloc', 0)
    command.emit('CallExtern', is_infinity)
    command.emit('Brtrue', 'done')
    command.emit('Ldloc', 0)
    command.emit('Ldc_R4', float_bits(MIN_ZOOM))
    command.emit('Ldc_R4', float_bits(MAX_ZOOM))
    command.emit('CallExtern', clamp)
    command.emit('Stloc', 0)
    command.emit('Ldstr', key)
    command.emit('Ldloc', 0)
    command.emit('CallExtern', set_float)
    command.emit('CallExtern', camera_instance)
    command.emit('Stloc', 1)
    command.emit('Ldloc', 1)
    command.emit('Brfalse', 'done')
    command.emit('Ldloc', 1)
    command.emit('CallExtern', refresh_camera)
    command.label('done')
    command.emit('Ret', 0)
    if native_passthrough:
        from chat_passthrough import native_chat_tail
        return native_chat_tail(patch,command), chat_view, text
    return command.finish(), chat_view, text


def add_chat_control(source, output, camera_key, toggle_keys=None, skin_key=None,
                     skin_arm_key=None):
    """Add `/ecam` to an existing dynamic-camera patch without changing its fixes."""
    patch = Patch(source, 'HeroSkin_1')
    assert not any('InBattleMsgInputView' in fix['desc'] and 'On_EndEdit' in fix['desc']
                   for fix in patch.parsed['fixes'])
    camera_fix = next(fix for fix in patch.parsed['fixes']
                      if 'CameraSystem' in fix['desc'] and 'GetZoomRate' in fix['desc'])
    camera_strings = [patch.parsed['intern_strings'][instruction['operand']]['value']
                      for instruction in patch.parsed['methods'][camera_fix['method_id']]['instructions']
                      if instruction['op'] == 'Ldstr']
    assert camera_key in camera_strings
    command, chat_view, text = _chat_command(
        patch, camera_key, toggle_keys, skin_key, skin_arm_key)
    command_id = len(patch.methods)
    patch.methods.append(command)
    fix_records = [patch.plain[fix['offset']:fix['record_end']]
                   for fix in patch.parsed['fixes']]
    fix_records.append(_fix_record(patch, chat_view, 'On_EndEdit', [text], command_id))
    return _write_with_fixes(patch, output, fix_records)


def build_chat_camera(source=DEFAULT_BASE,
                      output=ROOT / 'outputs/chat-camera-only/Thanos/HeroSkin_1.bytes',
                      toggle_keys=None, skin_key=None, skin_arm_key=None):
    patch = Patch(source, 'HeroSkin_1')
    original = patch.parsed
    camera_fix = next(fix for fix in original['fixes'] if 'CameraSystem' in fix['desc']
                      and 'GetZoomRate' in fix['desc'])
    original_camera = original['methods'][camera_fix['method_id']]
    base_zoom_call = next(instruction['operand'] for instruction in original_camera['instructions']
                          if instruction['op'] == 'CallExtern')
    single = patch.type('System.Single', 'mscorlib')
    text = patch.type('System.String', 'mscorlib')
    prefs = patch.type('UnityEngine.PlayerPrefs', 'UnityEngine.CoreModule')
    mathf = patch.type('UnityEngine.Mathf', 'UnityEngine.CoreModule')
    get_float = patch.extern(prefs, 'GetFloat', [text, single], 2, 1)
    clamp = patch.extern(mathf, 'Clamp', [single, single, single], 3, 1)
    key = patch.intern(CAMERA_KEY)
    camera = Code(0, 4)
    for op, operand in (
        ('Ldarg', 0), ('CallExtern', base_zoom_call), ('Ldstr', key),
        ('Ldc_R4', float_bits(DEFAULT_ZOOM)), ('CallExtern', get_float),
        ('Ldc_R4', float_bits(MIN_ZOOM)), ('Ldc_R4', float_bits(MAX_ZOOM)),
        ('CallExtern', clamp), ('Mul_Ovf', 0), ('Ret', 1),
    ):
        camera.emit(op, operand)
    command, chat_view, text = _chat_command(
        patch, CAMERA_KEY, toggle_keys, skin_key, skin_arm_key)

    patch.methods = [camera.finish(), command]
    old_record = (patch.plain[camera_fix['offset']:camera_fix['record_end'] - 4]
                  + i32(0))
    chat_record = _fix_record(patch, chat_view, 'On_EndEdit', [text], 1)
    return _write_with_fixes(patch, output, [old_record, chat_record])


def build_bundle(output_dir=ROOT / 'outputs/chat-camera-only'):
    output_dir = Path(output_dir)
    thanos = output_dir / 'Thanos'
    hero1 = thanos / 'HeroSkin_1.bytes'
    hero2 = thanos / 'HeroSkin_2.bytes'
    result = build_chat_camera(DEFAULT_BASE, hero1)
    thanos.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DEFAULT_EMPTY_HERO2, hero2)
    readme = output_dir / 'HUONG_DAN.txt'
    readme.write_text(
        'BAN CAMERA-ONLY 1.64.1\n\n'
        '1. Thay ca hai file trong thu muc Thanos vao game.\n'
        '2. Vao tran, mo khung chat va nhap: /ecam 2.1\n'
        '3. Gia tri hop le duoc gioi han tu 1.0 den 2.3.\n'
        '4. Camera mac dinh khi chua go lenh la 2.1.\n\n'
        'Ban nay khong co pinch hai ngon, full skin, hien dich hay HUD.\n',
        encoding='utf-8',
    )
    archive = output_dir.parent / 'Thanos_Camera_ChatCommand_1.64.1.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in (hero1, hero2, readme):
            bundle.write(path, path.relative_to(output_dir))
    files = {
        path.name: {'bytes': path.stat().st_size,
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in (hero1, hero2, archive)
    }
    return {'fixes': [fix['desc'] for fix in result['fixes']],
            'archive': str(archive), 'files': files}


if __name__ == '__main__':
    print(json.dumps(build_bundle(), ensure_ascii=False, indent=2))
