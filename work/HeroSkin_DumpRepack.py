#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, struct
from pathlib import Path
from dataclasses import dataclass
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC_BYTES = bytes.fromhex('22 4A 67 00')
BASE_KEY = bytes.fromhex('99 64 B1 B0 6B 03 8D 7F B7 7D B6 A7 54 90 8B 73')
IV = bytes(16)

OP_NAMES = {
0:'Conv_I1',1:'Ldelem_I',2:'Cgt_Un',3:'Mul_Ovf',4:'Sizeof',5:'Stind_I',6:'Ldftn',7:'Conv_I8',8:'Ldarga',9:'Shr_Un',10:'Readonly',11:'Bgt',12:'Callvirtvirt',13:'Ldloca',14:'Endfilter',15:'Ldind_I4',16:'Ldind_U2',17:'Ble',18:'Cpobj',19:'Conv_Ovf_I4',20:'Shl',21:'Neg',22:'Constrained',23:'Stelem_Any',24:'Isinst',25:'Stelem_I4',26:'Sub_Ovf_Un',27:'Ldelem_I1',28:'Ldc_I8',29:'Conv_Ovf_U4_Un',30:'Bgt_Un',31:'Ldind_I',32:'Initblk',33:'Bge_Un',34:'Ldflda',35:'Conv_U2',36:'Stloc',37:'Conv_U',38:'Mkrefany',39:'Ldstr',40:'Cgt',41:'Stind_I2',42:'Conv_I2',43:'Bne_Un',44:'Stind_I1',45:'Call',46:'Conv_Ovf_I1_Un',47:'Blt',48:'Stelem_I8',49:'Conv_Ovf_I',50:'Conv_Ovf_U',51:'Stind_R8',52:'Ldelem_R4',53:'Ldvirtftn',54:'Conv_Ovf_U_Un',55:'Conv_Ovf_I8',56:'Ldind_I1',57:'Conv_Ovf_I4_Un',58:'Conv_R4',59:'Conv_Ovf_U2',60:'Ldsfld',61:'Conv_Ovf_U1',62:'Starg',63:'Conv_Ovf_I2_Un',64:'Conv_Ovf_I_Un',65:'Rethrow',66:'Stelem_I2',67:'Newanon',68:'Conv_R8',69:'Conv_I4',70:'Arglist',71:'Add_Ovf_Un',72:'Ldloc',73:'Newobj',74:'Ldelem_I2',75:'Stfld',76:'Not',77:'Ldind_Ref',78:'Conv_Ovf_U1_Un',79:'Or',80:'Add',81:'Ldind_I2',82:'Ldelem_Any',83:'Ldind_U4',84:'Div',85:'Stsfld',86:'Ldind_I8',87:'Throw',88:'Castclass',89:'Newarr',90:'Xor',91:'Mul_Ovf_Un',92:'Unaligned',93:'Br',94:'Ldtype',95:'Ldtoken',96:'Stobj',97:'Ldsflda',98:'Ldelem_U2',99:'Ldelema',100:'Ldc_R8',101:'Conv_Ovf_I2',102:'Break',103:'Nop',104:'Cpblk',105:'Volatile',106:'Refanytype',107:'Refanyval',108:'Conv_Ovf_U2_Un',109:'Clt',110:'Beq',111:'Blt_Un',112:'Conv_Ovf_U4',113:'Stelem_I1',114:'Tail',115:'Stind_I8',116:'Clt_Un',117:'Ldnull',118:'Conv_I',119:'Stind_Ref',120:'Conv_U8',121:'Stelem_R8',122:'CallExtern',123:'Ldelem_U1',124:'Stelem_R4',125:'Bge',126:'Sub',127:'Brtrue',128:'Pop',129:'Ldelem_Ref',130:'Div_Un',131:'Conv_U1',132:'Ldelem_I8',133:'Unbox_Any',134:'Brfalse',135:'Unbox',136:'Add_Ovf',137:'Ldind_R4',138:'Callvirt',139:'Ldlen',140:'Conv_U4',141:'Ldc_R4',142:'No',143:'Ldc_I4',144:'Dup',145:'Conv_Ovf_I8_Un',146:'StackSpace',147:'Stelem_I',148:'And',149:'Switch',150:'Conv_Ovf_U8_Un',151:'Initobj',152:'Sub_Ovf',153:'Leave',154:'Jmp',155:'Ldind_R8',156:'Ldelem_U4',157:'Ckfinite',158:'Stind_I4',159:'Ldelem_R8',160:'Rem',161:'Box',162:'Ldvirtftn2',163:'Conv_Ovf_I1',164:'Ldarg',165:'Stind_R4',166:'Ceq',167:'Ldfld',168:'Ldind_U1',169:'Shr',170:'Ldelem_I4',171:'Rem_Un',172:'Ldobj',173:'Ret',174:'Conv_R_Un',175:'Stelem_Ref',176:'Ble_Un',177:'Endfinally',178:'Conv_Ovf_U8',179:'Mul',180:'Localloc'}

FIX_NAMES = [
 'com.tencent.pandora.Pandora.GetHOKDeviceDefaultLevel()',
 'Assets.Scripts.GameSystem.CLiveEventSystem.get_HasRealPlayedIntroVideo()',
 'Assets.Scripts.GameSystem.CLiveEventSystem.FinishIntroVideo()',
 'Assets.Scripts.GameSystem.CLobbySystem.CChatUTEnterLobby()',
 'Assets.Scripts.GameSystem.CLobbySystem.IsReturnBattleLobbyTips()',
 'Assets.Scripts.GameSystem.MatchingTeamPlayerView.refreshFriendInfo()',
 'Assets.Scripts.GameSystem.PVELoadingView.OnEnter()',
 'Assets.Scripts.GameSystem.PatSystem.FackSendChat()',
 'Assets.Scripts.GameLogic.BattleLogic.OnPrepareFight()',
]
FIX_VM_IDS = [0,1,3,4,5,6,8,10,11]

class R:
    def __init__(self,b): self.b=b; self.p=0
    def u8(self): x=self.b[self.p]; self.p+=1; return x
    def i32(self): x=struct.unpack_from('<i',self.b,self.p)[0]; self.p+=4; return x
    def u32(self): x=struct.unpack_from('<I',self.b,self.p)[0]; self.p+=4; return x
    def u64(self): x=struct.unpack_from('<Q',self.b,self.p)[0]; self.p+=8; return x
    def boolean(self): return bool(self.u8())
    def s(self):
        start=self.p; n=0; shift=0
        while True:
            q=self.u8(); n |= (q & 0x7f)<<shift
            if not(q&0x80): break
            shift += 7
        raw=self.b[self.p:self.p+n]; self.p+=n
        return raw.decode('utf-8','replace'), start, self.p


def read_7bit_at(b,p):
    n=0; shift=0; start=p
    while True:
        q=b[p]; p+=1; n|=(q&0x7f)<<shift
        if not(q&0x80): break
        shift+=7
    return n,p,start

def write_7bit(f,v):
    while v>=0x80:
        f.write(bytes([(v&0x7f)|0x80])); v>>=7
    f.write(bytes([v]))

def key_for(name):
    h=0
    for ch in name:
        c=ord(ch)
        if 97<=c<=122: c-=32
        h=((h*31)+c)&0xffffffff
    hb=[h&255,(h>>8)&255,(h>>16)&255,(h>>24)&255]
    return bytes(BASE_KEY[i]^hb[i&3] for i in range(16))

def unpad(d):
    n=d[-1]
    if not n or n>16 or d[-n:]!=bytes([n])*n: raise ValueError('bad PKCS7')
    return d[:-n]

def decrypt(path,name):
    raw=Path(path).read_bytes()
    if raw[:4]!=MAGIC_BYTES: raise ValueError('bad header')
    n=struct.unpack_from('<I',raw,4)[0]
    dec=Cipher(algorithms.AES(key_for(name)),modes.CBC(IV)).decryptor()
    plain=unpad(dec.update(raw[8:])+dec.finalize())
    if len(plain)!=n: raise ValueError(f'header len {n}, got {len(plain)}')
    return plain

def encrypt(plain,name):
    n=16-(len(plain)%16)
    padded=plain+bytes([n])*n
    enc=Cipher(algorithms.AES(key_for(name)),modes.CBC(IV)).encryptor()
    return MAGIC_BYTES+struct.pack('<I',len(plain))+(enc.update(padded)+enc.finalize())

def parse_method(r):
    start=r.p
    generic=r.boolean()
    decl_id=r.i32()
    decl_name=None
    method_name=None
    param_count=None
    params=[]
    generic_args=[]
    if generic:
        method_name,_,_=r.s()
        gac=r.i32()
        generic_args=[r.i32() for _ in range(gac)]
        pc=r.i32(); param_count=pc
        for _ in range(pc):
            isg=r.boolean()
            params.append({'generic':isg,'value':r.s()[0] if isg else r.i32()})
    else:
        method_name,_,_=r.s(); pc=r.i32(); param_count=pc
        params=[r.i32() for _ in range(pc)]
    return {'start':start,'end':r.p,'generic':generic,'decl_type_id':decl_id,'method_name':method_name,'generic_args':generic_args,'params':params,'param_count':param_count}

def type_name(types,i):
    return types[i] if isinstance(i,int) and 0<=i<len(types) else f'<type#{i}>'

def method_desc(m,types):
    d=f"{type_name(types,m['decl_type_id'])}::{m['method_name']}"
    if m['generic']:
        d += '<' + ','.join(type_name(types,x) for x in m['generic_args']) + '>'
    ps=[]
    for p in m['params']:
        if isinstance(p,dict): ps.append(str(p['value']))
        else: ps.append(str(type_name(types,p)))
    return d+'('+', '.join(ps)+')'

def parse_patch(plain):
    r=R(plain)
    out={'file_size':len(plain)}
    out['magic']=r.u64(); out['magic_offset']=0
    out['bridge'],out['bridge_offset'],out['bridge_end']=r.s()
    tc_off=r.p; tc=r.i32(); out['extern_type_count']=tc; out['extern_type_count_offset']=tc_off
    types=[]
    for i in range(tc):
        s,so,se=r.s(); types.append(s)
    out['extern_types']=types
    out['extern_types_offset']=tc_off+4
    mc_off=r.p; mc=r.i32(); out['method_count']=mc; out['method_count_offset']=mc_off
    methods=[]
    for j in range(mc):
        count_off=r.p; cs=r.i32(); code_start=r.p; ins=[]
        for k in range(cs):
            off=r.p; code=r.i32(); operand=r.i32()
            ins.append({'index':k,'file_offset':off,'code_offset':off,'operand_offset':off+4,'code':code,'op':OP_NAMES.get(code,f'OP_{code}'),'operand':operand})
        ehc_off=r.p; ehc=r.i32(); eh_start=r.p; ehs=[]
        for _ in range(ehc):
            eo=r.p; vals=[r.i32() for _ in range(6)]; ehs.append({'offset':eo,'handler_type':vals[0],'catch_type_id':vals[1],'try_start':vals[2],'try_end':vals[3],'handler_start':vals[4],'handler_end':vals[5]})
        methods.append({'index':j,'count_offset':count_off,'code_size':cs,'code_start':code_start,'code_end':code_start+8*cs,'eh_count_offset':ehc_off,'eh_count':ehc,'eh_start':eh_start,'eh_end':r.p,'instructions':ins,'exception_handlers':ehs})
    out['methods']=methods
    emo=r.p; emc=r.i32(); out['extern_method_count']=emc; out['extern_method_count_offset']=emo
    em=[]
    for i in range(emc):
        mm=parse_method(r); mm['index']=i; mm['desc']=method_desc(mm,types); em.append(mm)
    out['extern_methods']=em
    iso=r.p; isc=r.i32(); out['intern_string_count']=isc; out['intern_string_count_offset']=iso
    strings=[]
    for i in range(isc):
        s,so,se=r.s(); strings.append({'index':i,'offset':so,'end':se,'value':s})
    out['intern_strings']=strings
    fc_off=r.p; fc=r.i32(); out['field_count']=fc; out['field_count_offset']=fc_off
    fields=[]
    for i in range(fc):
        start=r.p; isnew=r.boolean(); did=r.i32(); name,no,ne=r.s(); rec={'index':i,'offset':start,'is_new':isnew,'decl_type_id':did,'decl_type':type_name(types,did),'name':name,'name_offset':no,'name_end':ne}
        if isnew:
            ft=r.i32(); mid=r.i32(); rec.update({'field_type_id':ft,'field_type':type_name(types,ft),'method_id':mid})
        fields.append(rec)
    out['fields']=fields
    sfo=r.p; sfc=r.i32(); out['static_field_type_count']=sfc; out['static_field_type_count_offset']=sfo
    sfields=[]
    for i in range(sfc):
        off=r.p; tid=r.i32(); cid=r.i32(); sfields.append({'index':i,'offset':off,'type_id':tid,'type':type_name(types,tid),'cctor_id':cid})
    out['static_fields']=sfields
    # anonymous storey section
    aco=r.p; acc=r.i32(); out['anonymous_storey_count']=acc; out['anonymous_storey_count_offset']=aco
    stores=[]
    # interface slot mapping needs max ID unknown; but parse structure exactly
    # derive max ID from dump's IDMAP is not available here, but we can still parse counts by reading ints; interface sections encode (itf id, method id per method).
    for i in range(acc):
        st=r.p; fnum=r.i32(); ftypes=[r.i32() for _ in range(fnum)]; ctor=r.i32(); cparam=r.i32(); icount=r.i32(); interfaces=[]
        for _ in range(icount):
            iid=r.i32(); # number of methods for interface is unknown without reflection; cannot safely skip exact count here
            # This build has 0 anonymous storey entries, so this branch is unused.
            interfaces.append(iid)
            raise ValueError('Nonzero anonymous storey count needs interface metadata to parse')
        stores.append({'index':i,'offset':st,'field_num':fnum,'field_type_ids':ftypes,'ctor_id':ctor,'ctor_param_num':cparam,'interfaces':interfaces})
    out['anonymous_storeys']=stores
    wo=r.p; wrappers,wo1,woend=r.s(); out['wrappers_manager']=wrappers; out['wrappers_manager_offset']=wo
    ao=r.p; assembly,ao1,aoend=r.s(); out['assembly']=assembly; out['assembly_offset']=ao
    fco=r.p; fixc=r.i32(); out['fix_count']=fixc; out['fix_count_offset']=fco
    fixes=[]
    for i in range(fixc):
        start=r.p; fm=parse_method(r); fid=r.i32(); fm['index']=i; fm['method_id']=fid; fm['desc']=method_desc(fm,types); fixes.append({'index':i,'offset':start,'method_id':fid,'desc':fm['desc'],'record_end':r.p})
    out['fixes']=fixes
    nco=r.p; ncc=r.i32(); out['new_class_count']=ncc; out['new_class_count_offset']=nco; nc=[]
    for i in range(ncc):
        s,so,se=r.s(); nc.append({'index':i,'offset':so,'end':se,'value':s})
    out['new_classes']=nc
    out['parsed_end']=r.p
    if r.p!=len(plain):
        out['trailing_bytes']=len(plain)-r.p
    else: out['trailing_bytes']=0
    # Resolve instruction references
    for m in methods:
        for ins in m['instructions']:
            op=ins['op']; v=ins['operand']; ref=None
            if op in ('CallExtern','Callvirtvirt'):
                if 0<=v<len(em): ref={'kind':'extern_method','index':v,'value':em[v]['desc']}
            elif op=='Ldstr':
                if 0<=v<len(strings): ref={'kind':'intern_string','index':v,'value':strings[v]['value']}
            elif op in ('Ldfld','Ldsfld','Stfld','Stsfld','Ldflda','Ldsflda'):
                if 0<=v<len(fields):
                    f=fields[v]; ref={'kind':'field','index':v,'value':f"{f['decl_type']}.{f['name']}"}
            elif op in ('Call','Callvirt','Newobj','Ldftn','Ldvirtftn','Ldvirtftn2','Jmp'):
                # IFix uses compact method/type IDs; preserve raw plus a best-effort breakdown.
                ref={'kind':'method_token','raw':v,'type_id':(v>>16)&0xffff,'method_id':v&0xffff}
            elif op=='Constrained':
                ref={'kind':'type_id','index':v,'value':type_name(types,v)}
            elif op in ('Box','Unbox','Unbox_Any','Ldtype','Initobj','Newarr','Stelem_Any','Ldelem_Any','Ldtoken'):
                ref={'kind':'type_id','index':v,'value':type_name(types,v)}
            if ref: ins['ref']=ref
    return out

def semantic_line(ins):
    op=ins['op']; v=ins['operand']; ref=ins.get('ref')
    if ref:
        k=ref['kind']
        if k=='extern_method': return f"{op}({v}) -> {ref['value']}"
        if k=='intern_string': return f"{op}({v}) -> \"{ref['value']}\""
        if k=='field': return f"{op}({v}) -> {ref['value']}"
        if k=='type_id': return f"{op}({v}) -> TYPE {ref['value']}"
        if k=='method_token': return f"{op}({v}) -> method_token type={ref['type_id']} method={ref['method_id']}"
    return f"{op} {v}"

def report(data, title):
    L=[]
    L.append(title); L.append('='*len(title))
    L += [f"Plaintext size: 0x{data['file_size']:X} ({data['file_size']} bytes)",f"Patch magic: 0x{data['magic']:016X}",f"Bridge: {data['bridge']}",""]
    L.append('IMPORTANT: offsets here are offsets in the DECRYPTED plaintext, not the encrypted .bytes file.')
    L.append('The semantic labels tell what each instruction operand refers to; this is the useful view for diagnosis/edit planning.')
    L.append('')
    L.append('PATCH TARGETS')
    for f in data['fixes']:
        L.append(f"  fix[{f['index']}] VM_ID={f['method_id']} -> {f['desc']}")
    L.append('')
    for m in data['methods']:
        target=data['fixes'][m['index']]['desc'] if m['index']<len(data['fixes']) else f'method[{m["index"]}]'
        L.append(f"METHOD BODY {m['index']} -> {target}")
        L.append(f"  code_size={m['code_size']}  code=[0x{m['code_start']:X},0x{m['code_end']:X})")
        for ins in m['instructions']:
            L.append(f"    IL_{ins['index']:04d}  OFF=0x{ins['file_offset']:08X}  OP=0x{ins['code']:08X}  ARG@0x{ins['operand_offset']:08X}  {semantic_line(ins)}")
        L.append('')
    L.append('EXTERN METHODS (operand IDs used by CallExtern/Callvirtvirt)')
    for x in data['extern_methods']:
        L.append(f"  [{x['index']:03d}] file=0x{x['start']:08X}..0x{x['end']:08X}  {x['desc']}")
    L.append('')
    L.append('INTERN STRINGS (IDs used by Ldstr)')
    for x in data['intern_strings']:
        L.append(f"  [{x['index']:03d}] file=0x{x['offset']:08X}  {x['value']!r}")
    L.append('')
    L.append('FIELDS (IDs used by Ldfld/Ldsfld/Stfld/Stsfld/Ldflda/Ldsflda)')
    for x in data['fields']:
        extra=' NEW type='+x.get('field_type','')+f" methodId={x.get('method_id','')}" if x['is_new'] else ''
        L.append(f"  [{x['index']:03d}] file=0x{x['offset']:08X}  {x['decl_type']}.{x['name']}{extra}")
    L.append('')
    L.append(f"Parsed end: 0x{data['parsed_end']:X}; trailing bytes: {data['trailing_bytes']}")
    return '\n'.join(L)+'\n'

def main():
    ap=argparse.ArgumentParser()
    sp=ap.add_subparsers(dest='cmd',required=True)
    d=sp.add_parser('dump'); d.add_argument('src',type=Path); d.add_argument('out',type=Path); d.add_argument('--name',required=True)
    e=sp.add_parser('repack'); e.add_argument('plain',type=Path); e.add_argument('out',type=Path); e.add_argument('--name',required=True)
    v=sp.add_parser('verify'); v.add_argument('src',type=Path); v.add_argument('--name',required=True)
    ifx=sp.add_parser('inspect'); ifx.add_argument('src',type=Path); ifx.add_argument('out_json',type=Path); ifx.add_argument('out_txt',type=Path); ifx.add_argument('--name',required=True)
    args=ap.parse_args()
    if args.cmd=='dump':
        plain=decrypt(args.src,args.name); args.out.write_bytes(plain); print(args.out)
    elif args.cmd=='repack':
        plain=args.plain.read_bytes(); args.out.write_bytes(encrypt(plain,args.name)); print(args.out)
    elif args.cmd=='verify':
        raw=args.src.read_bytes(); plain=decrypt(args.src,args.name); rebuilt=encrypt(plain,args.name); print('ROUNDTRIP:', 'PASS' if rebuilt==raw else 'FAIL'); raise SystemExit(0 if rebuilt==raw else 1)
    else:
        plain=decrypt(args.src,args.name)
        if len(plain)==0:
            data={'file_size':0,'magic':None,'bridge':'','extern_types':[],'methods':[],'extern_methods':[],'intern_strings':[],'fields':[],'static_fields':[],'anonymous_storeys':[],'wrappers_manager':'','assembly':'','fixes':[],'new_classes':[],'parsed_end':0,'trailing_bytes':0,'empty_patch':True}
            txt=args.src.name+' - HUMAN SEMANTIC DUMP\n'+'='*(len(args.src.name)+23)+'\nPlaintext size: 0 bytes\n\nThis file decrypts to an empty payload; there are no IFix methods/instructions/tables to edit.\n'
        else:
            data=parse_patch(plain); txt=report(data,args.src.name+' - HUMAN SEMANTIC DUMP')
        args.out_json.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); args.out_txt.write_text(txt,encoding='utf-8'); print(args.out_json); print(args.out_txt)

if __name__=='__main__': main()
