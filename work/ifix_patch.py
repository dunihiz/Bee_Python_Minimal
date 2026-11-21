"""IFix table declarations and bytecode emitter."""
from pathlib import Path
import struct
from ifix_format import body, parse_original
from HeroSkin_DumpRepack import decrypt, encrypt, OP_NAMES

OP = {name: code for code, name in OP_NAMES.items()}


def i32(value):
    return struct.pack('<i', value)


def string(value):
    raw = value.encode('utf-8')
    length, prefix = len(raw), bytearray()
    while length >= 128:
        prefix.append((length & 127) | 128)
        length >>= 7
    prefix.append(length)
    return bytes(prefix) + raw


def float_bits(value):
    return struct.unpack('<i', struct.pack('<f', value))[0]


class Patch:
    def __init__(self, path, key):
        self.path, self.key = Path(path), key
        self.raw = self.path.read_bytes()
        self.encrypted = self.raw[:4] == bytes.fromhex('224a6700')
        self.plain = decrypt(self.path, key) if self.encrypted else self.raw[8:]
        self.parsed = parse_original(self.plain)
        self.types = list(self.parsed['extern_types'])
        self.methods = [self.plain[m['count_offset']:m['eh_end']] for m in self.parsed['methods']]
        self.externs, self.strings, self.fields, self.arities = [], [], [], {}

    def type(self, name, assembly):
        for index, existing in enumerate(self.types):
            if existing.split(',')[0] == name:
                return index
        self.types.append(name + ', ' + assembly)
        return len(self.types) - 1

    def extern(self, declaring_type, method, parameters, argc, returns):
        index = self.parsed['extern_method_count'] + len(self.externs)
        raw = b'\0' + i32(declaring_type) + string(method) + i32(len(parameters))
        self.externs.append(raw + b''.join(i32(p) for p in parameters))
        self.arities[index] = returns
        return (argc << 16) | index

    def field(self, name, declaring_type, field_type=None):
        index = self.parsed['field_count'] + len(self.fields)
        raw = bytes([field_type is not None]) + i32(declaring_type) + string(name)
        if field_type is not None:
            raw += i32(field_type) + i32(-1)
        self.fields.append(raw)
        return index

    def intern(self, value):
        index = self.parsed['intern_string_count'] + len(self.strings)
        self.strings.append(string(value))
        return index

    def write(self, output):
        p, d = self.plain, self.parsed
        plain = (
            p[:d['extern_type_count_offset']] + i32(len(self.types))
            + b''.join(string(t) for t in self.types)
            + i32(len(self.methods)) + b''.join(self.methods)
            + i32(d['extern_method_count'] + len(self.externs))
            + p[d['extern_method_count_offset'] + 4:d['intern_string_count_offset']]
            + b''.join(self.externs)
            + i32(d['intern_string_count'] + len(self.strings))
            + p[d['intern_string_count_offset'] + 4:d['field_count_offset']]
            + b''.join(self.strings)
            + i32(d['field_count'] + len(self.fields))
            + p[d['field_count_offset'] + 4:d['static_field_type_count_offset']]
            + b''.join(self.fields)
            + p[d['static_field_type_count_offset']:]
        )
        verified = parse_original(plain)
        assert verified['trailing_bytes'] == 0
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(encrypt(plain, self.key) if self.encrypted else self.raw[:4] + i32(len(plain)) + plain)
        return verified


class Code:
    def __init__(self, locals_, stack):
        self.instructions = [('StackSpace', (locals_ << 16) | stack)]
        self.labels = {}

    def emit(self, op, operand=0):
        self.instructions.append((op, operand))

    def label(self, name):
        assert name not in self.labels
        self.labels[name] = len(self.instructions)

    def finish(self):
        result = []
        for index, (op, operand) in enumerate(self.instructions):
            if isinstance(operand, str):
                operand = self.labels[operand] - index
            result.append((OP[op], operand))
        return body(result)
