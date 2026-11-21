"""M4 variant with all custom skin entry points unregistered.

Keep official hotfixes, including official PersonalButton fixes. Preserve
method/table indices; dormant skin helpers cannot be reached from retained
custom hooks. No skin preference is deleted or read by the active graph.
"""
from hashlib import sha256
from pathlib import Path
import json
import tempfile
import zipfile

from chat_camera import _write_with_fixes, CAMERA_KEY, ESP_KEY
from ifix_patch import Patch
from ifix_bytecode import _real_instructions
from auto_spells import AUTO_BP_KEY, AUTO_SMITE_KEY
from chat_vm import ChatNative, execute_chat

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT/'inputs/prematch-base.zip'
OUTPUT = ROOT/'outputs/m5'
ARCHIVE = ROOT/'outputs/M5.zip'
OFFICIAL = {
    1: ((Path(__file__).resolve().parent.parent / 'inputs/official/HeroSkin_1.bytes'),
        '0bcd607e298576ba81004ab76aa4dd1772d2ec01344bd76401d8563c002adcce'),
    2: ((Path(__file__).resolve().parent.parent / 'inputs/official/HeroSkin_2.bytes'),
        'f6e39cbbcc068e705a8f7234d8383002c786ce81b118bcaea31503aa73434cfc'),
}
KEEP_CUSTOM = {
    1: {('CameraSystem','GetZoomRate'), ('InBattleMsgInputView','On_EndEdit')},
    2: {('NucleusDrive.Logic.LFramework','get_frameSynchr'),
        ('NucleusDrive.Statistics.CPlayerLocationStat','UpdateLogic')},
}
GUIDE = '''M5 — KHÔNG FULL SKIN, KHÔNG MENU

Skin do game xử lý theo quyền sở hữu và quyền dùng thử/chia sẻ hợp lệ.
Đã gỡ các hook mở khóa, chọn skin mod, ép skin actor, preload, hiệu ứng,
animation, nút chiêu và thông báo hạ gục. Giữ hotfix chính thức của game.
Thiết lập skin mod đã lưu không được các hook còn hoạt động đọc hay áp dụng.

CÒN LẠI
/ecam 2.1 (từ 1.0 đến 2.3)
/esp on hoặc /esp off
/trungtri on hoặc /trungtri off
/bocpha on hoặc /bocpha off
Giá trị camera và bật/tắt đã lưu vẫn có hiệu lực.

CÀI
Đóng hẳn game. Sao lưu rồi thay đủ hai file trong thư mục Thanos/ của ZIP.
Tiếp tục để HeroSkin_3.bytes và HeroSkin_4.bytes ở trạng thái đã xóa.
Mở lại game, chọn skin tài khoản có quyền sử dụng.

Đã kiểm tra registry, đồ thị gọi và lệnh chat trên Mac. Chưa thử M5 trên
iPhone, chưa xác nhận độ ổn định thực tế. Bản M4 cũ vẫn được giữ riêng.
'''


def identity(f):
    owner, method = f['desc'].split('::')
    return owner.split(',')[0], method.split('(')[0]


def reachable(parsed, roots):
    seen=set(); pending=list(roots)
    while pending:
        mid=pending.pop()
        if mid in seen: continue
        seen.add(mid)
        for r in _real_instructions(parsed['methods'][mid]):
            if r['op'] in {'Call','Callvirt'}: pending.append(r['operand'] & 65535)
            if r['op'] in {'Newanon','Callvirtvirt','Ldvirtftn2','Jmp'}:
                raise ValueError('Unreviewed indirect call in retained custom code')
    return seen


def build():
    if OUTPUT.exists() or ARCHIVE.exists(): raise FileExistsError('M5 already exists')
    assert sha256(BASE.read_bytes()).hexdigest() == 'a1ad917a0479d8f87934ca3bc5ba98c0e80c5feec2352a0e2ab582a5a170a180'
    payloads={};audit={}
    with tempfile.TemporaryDirectory() as td, zipfile.ZipFile(BASE) as z:
        td=Path(td)
        for n in (1,2):
            key=f'HeroSkin_{n}';name=f'Thanos/{key}.bytes'
            src=td/f'{key}.source';src.write_bytes(z.read(name))
            patch=Patch(src,key)
            official_path,expected=OFFICIAL[n]
            assert sha256(official_path.read_bytes()).hexdigest()==expected
            official=Patch(official_path,key)
            official_desc={f['desc'] for f in official.parsed['fixes']}
            selected=[f for f in patch.parsed['fixes'] if f['desc'] in official_desc or identity(f) in KEEP_CUSTOM[n]]
            custom=[f for f in selected if f['desc'] not in official_desc]
            assert {identity(f) for f in custom}==KEEP_CUSTOM[n]
            assert len(selected)==len(official_desc)+len(custom)
            records=[patch.plain[f['offset']:f['record_end']] for f in selected]
            dest=td/f'{key}.bytes';_write_with_fixes(patch,dest,records)
            current=Patch(dest,key)
            assert current.methods==patch.methods
            assert current.methods[:len(official.methods)]==official.methods
            for f in official.parsed['fixes']:
                found=next(r for r in current.parsed['fixes'] if r['desc']==f['desc'])
                assert current.plain[found['offset']:found['record_end']]==official.plain[f['offset']:f['record_end']]
            # Preserve the opaque official anonymous-storey metadata as well.
            a,b=patch.parsed,current.parsed
            assert patch.plain[a['static_field_type_count_offset']:a['fix_count_offset']]==current.plain[b['static_field_type_count_offset']:b['fix_count_offset']]
            live=reachable(current.parsed,[f['method_id'] for f in custom])
            removed=[f for f in patch.parsed['fixes'] if f not in selected]
            assert not live & {f['method_id'] for f in removed}
            strings={current.parsed['intern_strings'][r['operand']]['value']
                     for mid in live for r in _real_instructions(current.parsed['methods'][mid]) if r['op']=='Ldstr'}
            assert not any('SelectedSkin' in s or 'RuntimeSkin' in s or '__ifxR8Menu' in s for s in strings)
            if n==1:
                chat=next(f['method_id'] for f in custom if identity(f)[1]=='On_EndEdit')
                native=ChatNative()
                for cmd,key_name in [('/esp',ESP_KEY),('/trungtri',AUTO_SMITE_KEY),('/bocpha',AUTO_BP_KEY)]:
                    for state,value in [('on',1),('off',0)]:
                        execute_chat(current.parsed,chat,object(),cmd+' '+state,native)
                        assert native.prefs[key_name]==value
                execute_chat(current.parsed,chat,object(),'/ecam 2.1',native)
                assert abs(native.prefs[CAMERA_KEY]-2.1)<1e-5
                execute_chat(current.parsed,chat,object(),'chat thuong',native)
                assert native.sent==[('chat thuong',1)]
            payloads[name]=dest.read_bytes()
            audit[str(n)]={'official_hotfix_count':len(official_desc),
                           'custom_hooks':[f['desc'] for f in custom],
                           'removed_hooks':[f['desc'] for f in removed],
                           'custom_reachable_methods':sorted(live)}
    manifest={'build':'R8-NoFullSkin-NoMenu-M5','device_verified':False,
              'full_skin':False,'menu':False,'audit':audit,
              'files':{name:{'bytes':len(raw),'sha256':sha256(raw).hexdigest()} for name,raw in payloads.items()}}
    OUTPUT.mkdir(parents=True)
    for name,raw in payloads.items():
        path=OUTPUT/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    (OUTPUT/'HUONG_DAN.txt').write_text(GUIDE,encoding='utf8')
    (OUTPUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(ARCHIVE,'x',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(OUTPUT.rglob('*')):
            if path.is_file():z.write(path,path.relative_to(OUTPUT))
    with zipfile.ZipFile(ARCHIVE) as z:
        assert z.testzip() is None
        assert sorted(n for n in z.namelist() if n.endswith('.bytes'))==sorted(payloads)
        for name,raw in payloads.items():assert z.read(name)==raw
    print(ARCHIVE)
    print('Removed skin hooks:',sum(len(a['removed_hooks']) for a in audit.values()))
    print('SHA256:',sha256(ARCHIVE.read_bytes()).hexdigest())
    return manifest


if __name__=='__main__':build()
