"""IFix parser fallback and instruction encoding."""
import struct
from HeroSkin_DumpRepack import R, parse_method, parse_patch, method_desc

BRANCHES = {'Br', 'Brtrue', 'Brfalse', 'Beq', 'Bne_Un', 'Bge', 'Bge_Un',
            'Bgt', 'Bgt_Un', 'Ble', 'Ble_Un', 'Blt', 'Blt_Un'}


def parse_original(plain):
    """The supplied parser misreads anonymous-storey slot data in HeroSkin_1.

    Keep that section verbatim. Locate the assembly suffix and validate every
    fix record, method index, and the exact end of the file independently.
    """
    try:
        return parse_patch(plain)
    # Newer game updates may contain anonymous-storey metadata in the
    # untouched tail.  The legacy parser raises OverflowError when it reaches
    # that section because it does not know the interface table layout.  The
    # fallback below deliberately keeps that section byte-for-byte and locates
    # the active fix registry from the final assembly token.
    except (IndexError, ValueError, OverflowError, struct.error) as error:
        frame = error.__traceback__
        while frame and frame.tb_frame.f_code.co_name != 'parse_patch':
            frame = frame.tb_next
        if not frame or 'fields' not in frame.tb_frame.f_locals['out']:
            raise
        parsed = frame.tb_frame.f_locals['out']
        suffix = b'PublicKeyToken=null'
        offset = plain.rfind(suffix) + len(suffix)
        assert offset > parsed['field_count_offset']
        # Recover both length-prefixed strings as well: the failed parser's
        # values may include the entire fix registry after misreading slot data.
        wrapper = parsed['bridge'].replace('IFix.ILFixInterfaceBridge',
                                           'IFix.WrappersManagerImpl')
        wrapper_raw = wrapper.encode('utf8')
        if len(wrapper_raw) >= 128:
            raise ValueError('Unsupported wrapper string length')
        marker = bytes([len(wrapper_raw)]) + wrapper_raw
        wrapper_offset = plain.find(marker, parsed['static_field_type_count_offset'], offset)
        if wrapper_offset < 0:
            raise ValueError('Cannot locate validated wrapper metadata') from error
        tail = R(plain); tail.p = wrapper_offset
        wrappers, _, _ = tail.s()
        assembly_offset = tail.p
        assembly, _, _ = tail.s()
        if tail.p != offset or assembly != parsed['bridge'][parsed['bridge'].index(','):]:
            raise ValueError('Invalid wrapper/assembly metadata boundary') from error
        parsed.update(wrappers_manager=wrappers, wrappers_manager_offset=wrapper_offset,
                      assembly=assembly, assembly_offset=assembly_offset)
        reader = R(plain)
        reader.p = offset
        count = reader.i32()
        assert 0 <= count <= 100
        fixes = []
        for index in range(count):
            start = reader.p
            descriptor = parse_method(reader)
            method_id = reader.i32()
            assert 0 <= method_id < parsed['method_count']
            fixes.append(dict(index=index, offset=start, record_end=reader.p,
                              method_id=method_id,
                              desc=method_desc(descriptor, parsed['extern_types'])))
        new_class_offset = reader.p
        assert reader.i32() == 0 and reader.p == len(plain)
        parsed.update(fix_count=count, fix_count_offset=offset, fixes=fixes,
                      new_class_count=0, new_class_count_offset=new_class_offset,
                      parsed_end=reader.p, trailing_bytes=0)
        return parsed


def body(instructions):
    return (struct.pack('<i', len(instructions))
            + b''.join(struct.pack('<ii', *instruction) for instruction in instructions)
            + struct.pack('<i', 0))
