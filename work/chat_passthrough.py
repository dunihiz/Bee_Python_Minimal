"""Delegate ordinary input to the synchronous native edit handler.

Native On_EndEdit has no original/base proxy. Its IFix prologue checks exactly
wrapperArray[IDMAP0.InBattleMsgInputView-On_EndEdit0]. Temporarily clear ONLY
that slot while invoking the native body, then restore on both normal return
and a managed exception. Prepare reflection and arguments before clearing it.
This UI callback runs synchronously on Unity's main thread; never defer/yield
between clear and restore. All native chat restrictions/filtering/routing stay
inside the original handler. No direct chat-network API is called here.
"""
from ifix_patch import Patch
from chat_camera import (CAMERA_KEY,ESP_KEY,HUD_KEY,SKIN_KEY,SKIN_ARM_KEY,
                         _chat_command,_write_with_fixes)


def native_chat_tail(patch,c):
    from ifix_bytecode import catches
    e=c.emit
    t={name:patch.type(full,'mscorlib') for name,full in {
        'type':'System.Type','string':'System.String','object':'System.Object',
        'objects':'System.Object[]','flags':'System.Reflection.BindingFlags',
        'field':'System.Reflection.FieldInfo','method':'System.Reflection.MethodBase',
        'array':'System.Array','int':'System.Int32','enum':'System.Enum',
        'convert':'System.Convert','exception':'System.Exception'}.items()}
    calls={}
    def call(key,owner,name,params,argc,ret):
        calls[key]=patch.extern(t[owner],name,[t[x] for x in params],argc,ret)
    call('type','type','GetType',['string'],1,1)
    call('field','type','GetField',['string','flags'],3,1)
    call('read','field','GetValue',['object'],2,1)
    call('method','type','GetMethod',['string','flags'],3,1)
    call('invoke','method','Invoke',['object','objects'],3,1)
    call('get','array','GetValue',['int'],2,1)
    call('set','array','SetValue',['object','int'],3,0)
    call('length','array','get_Length',[],1,1)
    call('enum','enum','Parse',['type','string'],2,1)
    call('int','convert','ToInt32',['object'],1,1)
    def s(value):e('Ldstr',patch.intern(value))
    def invoke(key):e('CallExtern',calls[key])
    c.label('normal_chat');c.label('chat_prepare')
    s('IFix.IDMAP0, Project_d');invoke('type')
    s('InBattleMsgInputView-On_EndEdit0');invoke('enum');invoke('int');e('Stloc',3)
    e('Ldloc',3);e('Ldc_I4',0);e('Blt','chat_end')
    s('IFix.ILFixDynamicMethodWrapper, Project_d');invoke('type')
    s('wrapperArray');e('Ldc_I4',56);invoke('field');e('Ldnull');invoke('read')
    e('Castclass',t['array']);e('Stloc',4)
    e('Ldloc',4);e('Brfalse','chat_end')
    e('Ldloc',3);e('Ldloc',4);invoke('length');e('Bge','chat_end')
    e('Ldloc',4);e('Ldloc',3);invoke('get');e('Stloc',5)
    e('Ldloc',5);e('Brfalse','chat_end')
    s('InBattleMsgInputView, Project_d');invoke('type');s('On_EndEdit')
    e('Ldc_I4',52);invoke('method');e('Stloc',6)
    e('Ldloc',6);e('Brfalse','chat_end')
    e('Ldc_I4',1);e('Newarr',t['object']);e('Stloc',7)
    e('Ldloc',7);e('Ldc_I4',0);e('Ldarg',1);e('Stelem_Ref')
    # Only the live slot is changed; no array replacement or cached field write.
    e('Ldloc',4);e('Ldnull');e('Ldloc',3);invoke('set')
    c.label('chat_prepare_end');e('Br','chat_native')
    c.label('chat_prepare_catch');e('Pop');e('Br','chat_return')
    c.label('chat_native')
    e('Ldloc',6);e('Ldarg',0);e('Ldloc',7);invoke('invoke');e('Pop')
    c.label('chat_native_end');e('Br','chat_restore')
    c.label('chat_native_catch');e('Pop')
    c.label('chat_restore')
    e('Ldloc',4);e('Ldloc',5);e('Ldloc',3);invoke('set')
    c.label('chat_end');c.label('chat_return');e('Ret',0)
    return catches(c,[('chat_prepare','chat_prepare_end','chat_prepare_catch','chat_native'),
                      ('chat_native','chat_native_end','chat_native_catch','chat_restore')])


def update_confirmed_chat(path):
    """Transform E15 custom H1 after its copy, before official hotfix merge."""
    patch=Patch(path,'HeroSkin_1')
    fix=next(f for f in patch.parsed['fixes'] if 'InBattleMsgInputView' in f['desc'] and 'On_EndEdit' in f['desc'])
    method,_,_=_chat_command(patch,CAMERA_KEY,{'esp':ESP_KEY,'hud':HUD_KEY},SKIN_KEY,SKIN_ARM_KEY,native_passthrough=True)
    patch.methods[fix['method_id']]=method
    records=[patch.plain[f['offset']:f['record_end']] for f in patch.parsed['fixes']]
    return _write_with_fixes(patch,path,records)


def update_pre_match_chat(path, camera_key, toggle_keys=None):
    """Keep camera/toggle commands and delegate every other message natively."""
    patch = Patch(path, 'HeroSkin_1')
    fix = next(f for f in patch.parsed['fixes']
               if 'InBattleMsgInputView' in f['desc'] and 'On_EndEdit' in f['desc'])
    method, _, _ = _chat_command(
        patch, camera_key,
        {'esp': ESP_KEY, 'hud': HUD_KEY} if toggle_keys is None else toggle_keys,
        native_passthrough=True,
    )
    patch.methods[fix['method_id']] = method
    records = [patch.plain[f['offset']:f['record_end']]
               for f in patch.parsed['fixes']]
    return _write_with_fixes(patch, path, records)
