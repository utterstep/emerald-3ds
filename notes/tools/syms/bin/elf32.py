"""Minimal little-endian ELF32 reader: sections, symbols, REL relocations."""
import struct

class Section:
    __slots__ = ("idx", "name", "type", "flags", "addr", "offset", "size", "link", "info", "entsize")

class Symbol:
    __slots__ = ("name", "value", "size", "type", "bind", "shndx", "section")
    def __repr__(self):
        return "Sym(%s,%#x,%d,%d)" % (self.name, self.value, self.size, self.type)

STT_NOTYPE, STT_OBJECT, STT_FUNC, STT_SECTION, STT_FILE = 0, 1, 2, 3, 4

class Elf:
    def __init__(self, path):
        self.data = data = open(path, "rb").read()
        assert data[:4] == b"\x7fELF" and data[4] == 1 and data[5] == 1
        (e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags, e_ehsize,
         e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
        self.sections = []
        for i in range(e_shnum):
            s = Section()
            (nm, s.type, s.flags, s.addr, s.offset, s.size, s.link, s.info, _align, s.entsize) = \
                struct.unpack_from("<IIIIIIIIII", data, e_shoff + i * e_shentsize)
            s.idx = i
            s.name = nm
            self.sections.append(s)
        shstr = self.sections[e_shstrndx]
        for s in self.sections:
            s.name = self._str(shstr, s.name)
        self.symbols = []
        for s in self.sections:
            if s.type == 2:  # SHT_SYMTAB
                strtab = self.sections[s.link]
                self.symtab_index = s.idx
                for j in range(s.size // 16):
                    nm, val, size, info, other, shndx = struct.unpack_from("<IIIBBH", data, s.offset + j * 16)
                    sym = Symbol()
                    sym.name = self._str(strtab, nm)
                    sym.value, sym.size, sym.type, sym.bind, sym.shndx = val, size, info & 15, info >> 4, shndx
                    sym.section = self.sections[shndx].name if 0 < shndx < len(self.sections) else None
                    self.symbols.append(sym)

    def _str(self, sec, off):
        d = self.data
        start = sec.offset + off
        end = d.index(b"\0", start)
        return d[start:end].decode("latin-1")

    def relocations(self):
        """Yield (section_name_relocated, r_offset, r_type, symbol) for every SHT_REL section."""
        d = self.data
        for s in self.sections:
            if s.type == 9:  # SHT_REL
                target = self.sections[s.info].name
                for j in range(s.size // 8):
                    off, info = struct.unpack_from("<II", d, s.offset + j * 8)
                    yield target, off, info & 0xff, self.symbols[info >> 8]
