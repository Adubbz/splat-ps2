import struct
from util import options

from segtypes.common.header import CommonSegHeader


class Ps2SegHeader(CommonSegHeader):
    def parse_header(self, rom_bytes):
        header_lines = []
        header_lines.append(".section .data\n")
        header_lines.append(
            self.get_line("word", rom_bytes[0x00:0x04][::-1], "ELF magic")
        )
        header_lines.append(
            self.get_line("byte", rom_bytes[0x04:0x05], "Binary architecture")
        )
        header_lines.append(
            self.get_line("byte", rom_bytes[0x05:0x06], "Data encoding")
        )
        header_lines.append(
            self.get_line("byte", rom_bytes[0x06:0x07], "ELF version")
        )
        header_lines.append(
            self.get_line("byte", rom_bytes[0x07:0x08], "OS ABI")
        )
        header_lines.append(
            self.get_line("byte", rom_bytes[0x08:0x09], "ABI version")
        )
        header_lines.append(self.get_line("word", rom_bytes[0x09:0x10], "Zero-filled"))
        header_lines.append(
            self.get_line("hword", rom_bytes[0x10:0x12][::-1], "Object file type")
        )
        header_lines.append(
            self.get_line("hword", rom_bytes[0x12:0x14][::-1], "Machine")
        )
        header_lines.append(
            self.get_line("word", rom_bytes[0x14:0x18][::-1], "File version")
        )
        header_lines.append(
            self.get_line("word", rom_bytes[0x18:0x1C][::-1], "Entry point")
        )
        header_lines.append(
            self.get_line("word", rom_bytes[0x1C:0x20][::-1], "Program header table offset")
        )
        header_lines.append(
            self.get_line("word", rom_bytes[0x20:0x24][::-1], "Section header table offset")
        )
        header_lines.append(
            self.get_line("word", rom_bytes[0x24:0x28][::-1], "Processor-specific flags")
        )
        header_lines.append(
            self.get_line("hword", rom_bytes[0x28:0x2A][::-1], "ELF header size")
        )
        header_lines.append(
            self.get_line("hword", rom_bytes[0x2A:0x2C][::-1], "Program header entry size")
        )
        header_lines.append(
            self.get_line("hword", rom_bytes[0x2C:0x2E][::-1], "Program header entry count")
        )
        header_lines.append(
            self.get_line("hword", rom_bytes[0x2E:0x30][::-1], "Section header entry size")
        )
        header_lines.append(
            self.get_line("hword", rom_bytes[0x30:0x32][::-1], "Section header entry count")
        )
        header_lines.append(
            self.get_line("hword", rom_bytes[0x32:0x34][::-1], "String table section header index")
        )

        ph_off, sh_off = struct.unpack('<II', rom_bytes[0x1C:0x24])
        ph_esz, ph_ecnt, sh_esz, sh_ecnt = struct.unpack('<HHHH', rom_bytes[0x2A:0x32])

        if ph_off > 0x34:
            header_lines.append(self.get_line("word", rom_bytes[0x34:ph_off], "Zero-filled"))

        ph_end = ph_off + ph_esz * ph_ecnt

        for count, i in enumerate(range(ph_off, ph_end, ph_esz)):
            header_lines.append(self.get_line("word", rom_bytes[i:i+0x4][::-1], f"Program {count} type"))
            header_lines.append(self.get_line("word", rom_bytes[i+0x4:i+0x8][::-1], f"Program {count} file offset"))
            header_lines.append(self.get_line("word", rom_bytes[i+0x8:i+0xC][::-1], f"Program {count} virtual address"))
            header_lines.append(self.get_line("word", rom_bytes[i+0xC:i+0x10][::-1], f"Program {count} physical address"))
            header_lines.append(self.get_line("word", rom_bytes[i+0x10:i+0x14][::-1], f"Program {count} file size"))
            header_lines.append(self.get_line("word", rom_bytes[i+0x14:i+0x18][::-1], f"Program {count} memory size"))
            header_lines.append(self.get_line("word", rom_bytes[i+0x18:i+0x1C][::-1], f"Program {count} flags"))
            header_lines.append(self.get_line("word", rom_bytes[i+0x1C:i+0x20][::-1], f"Program {count} alignment"))

            if ph_esz > 0x20:
                header_lines.append(self.get_line("word", rom_bytes[i+0x20:i+ph_esz], "Zero-filled"))

        prog_start = struct.unpack('<I', rom_bytes[ph_off+0x4:ph_off+0x8])[0]

        for i in range(prog_start - ph_end + 1):
            header_lines.append(self.get_line("byte", b'\0', f"Zero-filled"))

        return header_lines