from re import split
from capstone import *
from capstone.mips import *

from collections import OrderedDict
from segtypes.segment import N64Segment, parse_segment_name
import os
from pathlib import Path, PurePath
from ranges import Range, RangeDict
import re


STRIP_C_COMMENTS_RE = re.compile(
    r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
    re.DOTALL | re.MULTILINE
)


def strip_c_comments(text):
    def replacer(match):
        s = match.group(0)
        if s.startswith("/"):
            return " "
        else:
            return s
    return re.sub(STRIP_C_COMMENTS_RE, replacer, text)


C_FUNC_RE = re.compile(
    r"^(static\s+)?[^\s]+\s+([^\s(]+)\(([^;)]*)\)[^;]+?{",
    re.MULTILINE
)


def get_funcs_defined_in_c(c_file):
    with open(c_file, "r") as f:
        text = strip_c_comments(f.read())

    return set(m.group(2) for m in C_FUNC_RE.finditer(text))


def parse_segment_files(segment, segment_class, seg_start, seg_end, seg_name, seg_vram):
    prefix = seg_name if seg_name.endswith("/") else f"{seg_name}_"

    ret = []
    if "files" in segment:
        for i, split_file in enumerate(segment["files"]):
            if type(split_file) is dict:
                start = split_file["start"]
                end = split_file["end"]
                name = None if "name" not in split_file else split_file["name"]
                subtype = split_file["type"]
            else:
                start = split_file[0]
                end = seg_end if i == len(
                    segment["files"]) - 1 else segment["files"][i + 1][0]
                name = None if len(split_file) < 3 else split_file[2]
                subtype = split_file[1]

            if not name:
                name = N64SegCode.get_default_name(start) if seg_name == N64SegCode.get_default_name(
                    seg_start) else f"{prefix}{start:X}"

            if segment.get("vram_lock", False):
                vram = seg_vram
            else:
                vram = seg_vram + (start - seg_start)

            fl = {"start": start, "end": end, "name": name,
                  "vram": vram, "subtype": subtype}

            ret.append(fl)
    else:
        fl = {"start": seg_start, "end": seg_end,
              "name": seg_name, "vram": seg_vram, "subtype": "asm"}
        ret.append(fl)
    return ret


class N64SegCode(N64Segment):
    def __init__(self, segment, next_segment, options):
        super().__init__(segment, next_segment, options)
        self.files = parse_segment_files(
            segment, self.__class__, self.rom_start, self.rom_end, self.name, self.vram_addr)
        self.is_overlay = segment.get("overlay", False)
        self.labels_to_add = {}
        self.glabels_to_add = set()
        self.undefined_syms_to_add = set()
        self.glabels_added = set()
        self.all_functions = set()
        self.c_functions = {}
        self.c_variables = {}
        self.c_labels_to_add = set()
        self.ld_section_name = "." + segment.get("ld_name", f"text_{self.rom_start:X}")
        self.symbol_ranges = RangeDict()
        self.data_syms = {}
        self.rodata_syms = {}
        self.unk_syms = {}

    @staticmethod
    def get_default_name(addr):
        return f"code_{addr:X}"

    def get_func_name(self, addr):
        if addr in self.c_functions:
            return self.c_functions[addr]
        else:
            return "func_{:X}".format(addr)

    def get_unique_func_name(self, func_addr, rom_addr):
        func_name = self.get_func_name(func_addr)

        if func_name in self.all_functions or (self.is_overlay and (func_addr >= self.vram_addr) and (func_addr <= self.vram_addr + self.rom_end - self.rom_start)):
            return func_name + "_{:X}".format(rom_addr)
        return func_name

    def add_glabel(self, ram_addr, rom_addr):
        func = self.get_unique_func_name(ram_addr, rom_addr)
        self.glabels_to_add.discard(func)
        self.glabels_added.add(func)
        return "glabel " + func

    def get_header(self):
        ret = []

        ret.append(".include \"macro.inc\"")
        ret.append("")
        ret.append("# assembler directives")
        ret.append(".set noat      # allow manual use of $at")
        ret.append(".set noreorder # don't insert nops after branches")
        ret.append(
            ".set gp=64     # allow use of 64-bit general purpose registers")
        ret.append("")
        ret.append(".section .text, \"ax\"")
        ret.append("")

        return ret

    def get_gcc_inc_header(self):
        ret = []
        ret.append(".set noat      # allow manual use of $at")
        ret.append(".set noreorder # don't insert nops after branches")
        ret.append("")

        return ret

    @staticmethod
    def is_nops(insns):
        for insn in insns:
            if insn.mnemonic != "nop":
                return False
        return True

    @staticmethod
    def is_branch_insn(mnemonic):
        return (mnemonic.startswith("b") and not mnemonic.startswith("binsl") and not mnemonic == "break") or mnemonic == "j"

    def process_insns(self, insns, rom_addr):
        ret = OrderedDict()

        func = []
        end_func = False
        labels = []

        # Collect labels
        for insn in insns:
            if self.is_branch_insn(insn.mnemonic):
                op_str_split = insn.op_str.split(" ")
                branch_target = op_str_split[-1]
                branch_addr = int(branch_target, 0)
                labels.append((insn.address, branch_addr))

        # Main loop
        for i, insn in enumerate(insns):
            mnemonic = insn.mnemonic
            op_str = insn.op_str
            func_addr = insn.address if len(func) == 0 else func[0][0].address

            if mnemonic == "move":
                # Let's get the actual instruction out
                opcode = insn.bytes[3] & 0b00111111
                op_str += ", $zero"

                if opcode == 37:
                    mnemonic = "or"
                elif opcode == 45:
                    mnemonic = "daddu"
                elif opcode == 33:
                    mnemonic = "addu"
                else:
                    print("INVALID INSTRUCTION " + insn)
            elif mnemonic == "jal":
                jal_addr = int(op_str, 0)
                jump_func = self.get_func_name(jal_addr)
                if (
                    jump_func.startswith("func_")
                    and self.is_overlay
                    and jal_addr >= self.vram_addr
                    and jal_addr <= (self.vram_addr + self.rom_end - self.rom_start)
                ):
                    func_loc = self.rom_start + jal_addr - self.vram_addr
                    jump_func += "_{:X}".format(func_loc)

                if jump_func not in self.c_functions.values():
                    self.glabels_to_add.add(jump_func)
                op_str = jump_func
            elif self.is_branch_insn(insn.mnemonic):
                op_str_split = op_str.split(" ")
                branch_target = op_str_split[-1]
                branch_target_int = int(branch_target, 0)
                label = ""

                if branch_target_int in self.special_labels:
                    label = self.special_labels[branch_target_int]
                else:
                    if func_addr not in self.labels_to_add:
                        self.labels_to_add[func_addr] = set()
                    self.labels_to_add[func_addr].add(branch_target_int)
                    label = ".L" + branch_target[2:].upper()

                op_str = " ".join(op_str_split[:-1] + [label])
            elif mnemonic == "mtc0" or mnemonic == "mfc0":
                rd = (insn.bytes[2] & 0xF8) >> 3
                op_str = op_str.split(" ")[0] + " $" + str(rd)

            func.append((insn, mnemonic, op_str, rom_addr))
            rom_addr += 4

            if mnemonic == "jr":
                keep_going = False
                for label in labels:
                    if (label[0] > insn.address and label[1] <= insn.address) or (label[0] <= insn.address and label[1] > insn.address):
                        keep_going = True
                        break
                if not keep_going:
                    end_func = True
                    continue

            if i < len(insns) - 1 and self.get_func_name(insns[i + 1].address) in self.c_labels_to_add:
                end_func = True

            if end_func:
                if self.is_nops(insns[i:]) or i < len(insns) - 1 and insns[i + 1].mnemonic != "nop":
                    end_func = False
                    ret[func_addr] = func
                    func = []

        # Add the last function (or append nops to the previous one)
        if not self.is_nops([i[0] for i in func]):
            ret[func_addr] = func
        else:
            next(reversed(ret.values())).extend(func)

        return ret

    def get_file_for_addr(self, addr):
        for fl in self.files:
            if addr >= fl["vram"] and addr < fl["vram"] + fl["end"] - fl["start"]:
                return fl
        return None

    def store_syms(self, addr, name):
        sect = self.get_file_for_addr(addr)

        if sect:
            sect_name = sect["name"]
            sect_type = sect["subtype"]

            if sect_type in [".data", "data"]:
                if sect_name not in self.data_syms:
                    self.data_syms[sect_name] = {}
                self.data_syms[sect_name][addr] = name
            elif sect_type in [".rodata", "rodata"]:
                if sect_name not in self.rodata_syms:
                    self.rodata_syms[sect_name] = {}
                self.rodata_syms[sect_name][addr] = name
            elif sect_type == "bin":
                if sect_name not in self.unk_syms:
                    self.unk_syms[sect_name] = {}
                self.unk_syms[sect_name][addr] = name
            return sect_type
        else:
            return None

    # Determine symbols
    def determine_symbols(self, funcs):
        ret = {}

        for func_addr in funcs:
            func = funcs[func_addr]

            for i in range(len(func)):
                insn = func[i][0]

                if insn.mnemonic == "lui":
                    op_split = insn.op_str.split(", ")
                    reg = op_split[0]

                    if not op_split[1].startswith("0x"):
                        continue

                    lui_val = int(op_split[1], 0)
                    if lui_val >= 0x8000:
                        for j in range(i + 1, min(i + 6, len(func))):
                            s_insn = func[j][0]

                            s_op_split = s_insn.op_str.split(", ")

                            if s_insn.mnemonic in ["addiu", "ori"]:
                                s_reg = s_op_split[-2]
                            else:
                                s_reg = s_op_split[-1][s_op_split[-1].rfind("(") + 1: -1]

                            if reg == s_reg:
                                if s_insn.mnemonic not in ["addiu", "lw", "sw", "lh", "sh", "lhu", "lb", "sb", "lbu", "lwc1", "swc1", "ldc1", "sdc1"]:
                                    break

                                # Match!
                                reg_ext = ""

                                junk_search = re.search(
                                    r"[\(]", s_op_split[-1])
                                if junk_search is not None:
                                    if junk_search.start() == 0:
                                        break
                                    s_str = s_op_split[-1][:junk_search.start()]
                                    reg_ext = s_op_split[-1][junk_search.start():]
                                else:
                                    s_str = s_op_split[-1]

                                s_val = int(s_str, 0)

                                symbol_addr = (lui_val * 0x10000) + s_val

                                offset = 0
                                if symbol_addr in self.c_functions:
                                    sym_name = self.c_functions[symbol_addr]
                                    self.store_syms(symbol_addr, sym_name)
                                elif symbol_addr in self.c_variables:
                                    sym_name = self.c_variables[symbol_addr]
                                    self.store_syms(symbol_addr, sym_name)
                                elif symbol_addr in self.symbol_ranges:
                                    sym_name = self.symbol_ranges.get(symbol_addr)
                                    offset = symbol_addr - self.symbol_ranges.getrange(symbol_addr).start
                                else:
                                    sym_name = "D_{:X}".format(symbol_addr)
                                    sect_type = self.store_syms(symbol_addr, sym_name)
                                    if not self.options.get("create_detected_syms", False):
                                        break
                                    if not (sect_type and sect_type in [".data", ".rodata", ".bss"]):
                                        self.undefined_syms_to_add.add(sym_name)

                                if offset != 0:
                                    sym_name += f"+0x{offset:X}"
                                func[i] += ("%hi({})".format(sym_name),)
                                func[j] += ("%lo({}){}".format(sym_name, reg_ext),)
                                break
            ret[func_addr] = func
        return ret

    def add_labels(self, funcs):
        ret = {}

        for func in funcs:
            func_text = []

            # Add function glabel
            rom_addr = funcs[func][0][3]
            func_text.append(self.add_glabel(func, rom_addr))

            indent_next = False

            for insn in funcs[func]:
                # Add a label if we need one
                if func in self.labels_to_add and insn[0].address in self.labels_to_add[func]:
                    self.labels_to_add[func].remove(insn[0].address)
                    func_text.append(".L{:X}:".format(insn[0].address))

                rom_addr_padding = self.options.get("rom_address_padding", None)
                if rom_addr_padding:
                    rom_str = "{0:0{1}X}".format(insn[3], rom_addr_padding)
                else:
                    rom_str = "{:X}".format(insn[3])

                asm_comment = "/* {} {:X} {} */".format(
                    rom_str, insn[0].address, insn[0].bytes.hex().upper())

                if len(insn) > 4:
                    op_str = ", ".join(insn[2].split(", ")[:-1] + [insn[4]])
                else:
                    op_str = insn[2]

                insn_text = insn[1]
                if indent_next:
                    indent_next = False
                    insn_text = " " + insn_text

                mnemonic_ljust = 11
                if "mnemonic_ljust" in self.options:
                    mnemonic_ljust = self.options["mnemonic_ljust"]

                asm_insn_text = "  {}{}".format(
                    insn_text.ljust(mnemonic_ljust), op_str)
                func_text.append(asm_comment + asm_insn_text)

                if insn[0].mnemonic != "branch" and insn[0].mnemonic.startswith("b") or insn[0].mnemonic.startswith("j"):
                    indent_next = True

            ret[func] = (func_text, rom_addr)

            if self.options.get("find_file_boundaries") or self.options.get("find-file-boundaries"):
                if self.options.get("find-file-boundaries"):
                    self.warn("warning: find-file-boundaries with dashes is deprecated. Please rename this to use"
                              "underscores instead of dashes (find_file_boundaries).")
                if func != next(reversed(list(funcs.keys()))) and self.is_nops([i[0] for i in funcs[func][-2:]]):
                    new_file_addr = funcs[func][-1][3] + 4
                    if (new_file_addr % 16) == 0:
                        print("function at vram {:X} ends with nops so a new file probably starts at rom address 0x{:X}".format(
                            func, new_file_addr))

        return ret

    def get_pycparser_args(self):
        option = self.options.get("cpp_args")
        return ["-Iinclude", "-D_LANGUAGE_C", "-ffreestanding", "-DF3DEX_GBI_2", "-DSPLAT"] if option is None else option

    def should_run(self):
        subtypes = set(f["subtype"] for f in self.files)

        return (
            super().should_run()
            or ("c" in self.options["modes"] and "c" in subtypes)
            or ("asm" in self.options["modes"] and "asm" in subtypes)
            or ("hasm" in self.options["modes"] and "hasm" in subtypes)
            or ("bin" in self.options["modes"] and "bin" in subtypes)
            or ("data" in self.options["modes"] and "data" in subtypes)
            or ("rodata" in self.options["modes"] and "rodata" in subtypes)
        )

    def is_valid_ascii(self, bytes):
        if len(bytes) < 8:
            return False

        num_empty_bytes = 0
        for b in bytes:
            if b == 0:
                num_empty_bytes += 1

        empty_ratio = num_empty_bytes / len(bytes)
        if empty_ratio > 0.2:
            return False

        return True

    def gen_data_file(self, split_file, rom_bytes):
        ret = ".include \"macro.inc\"\n\n"
        ret += f'.section .{split_file["subtype"]}'

        if split_file["subtype"] == "data" and split_file["name"] in self.data_syms:
            sym_info = self.data_syms[split_file["name"]]
        elif split_file["subtype"] == "rodata" and split_file["name"] in self.rodata_syms:
            sym_info = self.rodata_syms[split_file["name"]]
        else:
            self.log("No data found for " + split_file["name"] + "; not generating file")
            return None

        sorted_syms = sorted(sym_info.keys())
        # check beginning
        if sorted_syms[0] != split_file["vram"]:
            sorted_syms.insert(0, split_file["vram"])

        # add end
        sorted_syms.append(split_file["vram"] + split_file["end"] - split_file["start"])

        for i in range(len(sorted_syms) - 1):
            start = sorted_syms[i]
            end = sorted_syms[i + 1]
            sym_rom_start = start - split_file["vram"] + split_file["start"]
            sym_rom_end = end - split_file["vram"] + split_file["start"]

            if start in sym_info:
                sym_name = sym_info[start]
            else:
                sym_name = f"D_{start:X}"

            sym_str = "\n\nglabel " + sym_name + "\n"
            sym_bytes = rom_bytes[sym_rom_start : sym_rom_end]

            # .ascii
            if self.is_valid_ascii(sym_bytes):
                try:
                    ascii_str = sym_bytes.decode("EUC-JP")
                    ascii_str = ascii_str.replace("\x00", "\\0")
                    sym_str += f'.ascii "{ascii_str}"'
                    ret += sym_str
                    continue
                except:
                    pass

            # Fallback to raw data
            if len(sym_bytes) % 4 == 0:
                stype = ".word "
                slen = 4
            elif len(sym_bytes) % 2 == 0:
                stype = ".short "
                slen = 2
            else:
                stype = ".byte "
                slen = 1

            sym_str += stype
            i = 0
            while i < len(sym_bytes):
                adv_amt = min(slen, len(sym_bytes) - i)

                word = int.from_bytes(sym_bytes[i : i + adv_amt], "big")

                if word in self.c_variables:
                    byte_str = self.c_variables[word]
                elif word in self.c_functions:
                    byte_str = self.c_functions[word]
                else:
                    byte_str = '0x{0:0{1}X}'.format(word,2 * slen)

                sym_str += byte_str + ", "
                i += adv_amt
            ret += sym_str[:-2] # omit final ", "

        return ret

    def get_c_preamble(self):
        ret = []

        if self.options.get("generated_c_preamble", None):
            ret.append(self.options["generated_c_preamble"])
        else:
            ret.append("#include \"common.h\"")

        ret.append("")
        return ret

    def split(self, rom_bytes, base_path):
        md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 + CS_MODE_BIG_ENDIAN)
        md.detail = True
        md.skipdata = True

        for split_file in self.files:
            if split_file["subtype"] in ["asm", "hasm", "c"]:
                if self.type not in self.options["modes"] and "all" not in self.options["modes"]:
                    continue

                if split_file["start"] == split_file["end"]:
                    continue

                out_dir = self.create_split_dir(base_path, "asm")

                rom_addr = split_file["start"]

                insns = []
                for insn in md.disasm(rom_bytes[split_file["start"]: split_file["end"]], split_file["vram"]):
                    insns.append(insn)

                funcs = self.process_insns(insns, rom_addr)
                funcs = self.determine_symbols(funcs)
                funcs_text = self.add_labels(funcs)

                if split_file["subtype"] == "c":
                    c_path = os.path.join(
                        base_path, "src", split_file["name"] + "." + self.get_ext(split_file["subtype"]))

                    if os.path.exists(c_path):
                        defined_funcs = get_funcs_defined_in_c(c_path)
                    else:
                        defined_funcs = set()

                    out_dir = self.create_split_dir(
                        base_path, os.path.join("asm", "nonmatchings"))

                    for func in funcs_text:
                        func_name = self.get_unique_func_name(
                            func, funcs_text[func][1])

                        if func_name not in defined_funcs:
                            # TODO make more graceful
                            if "compiler" in self.options and self.options["compiler"] == "GCC":
                                out_lines = self.get_gcc_inc_header()
                            else:
                                out_lines = []
                            out_lines.extend(funcs_text[func][0])
                            out_lines.append("")

                            outpath = Path(os.path.join(
                                out_dir, split_file["name"], func_name + ".s"))
                            outpath.parent.mkdir(parents=True, exist_ok=True)

                            with open(outpath, "w", newline="\n") as f:
                                f.write("\n".join(out_lines))
                            self.log(f"Disassembled {func_name} to {outpath}")

                    # Creation of c files
                    if not os.path.exists(c_path):  # and some option is enabled
                        c_lines = self.get_c_preamble()

                        for func in funcs_text:
                            func_name = self.get_unique_func_name(
                                func, funcs_text[func][1])
                            if self.options["compiler"] == "GCC":
                                c_lines.append("INCLUDE_ASM(s32, \"{}\", {});".format(
                                    split_file["name"], func_name))
                            else:
                                outpath = Path(os.path.join(out_dir, split_file["name"], func_name + ".s"))
                                rel_outpath = os.path.relpath(outpath, base_path)
                                c_lines.append(
                                    f"#pragma GLOBAL_ASM(\"{rel_outpath}\")")
                            c_lines.append("")

                        Path(c_path).parent.mkdir(parents=True, exist_ok=True)
                        with open(c_path, "w") as f:
                            f.write("\n".join(c_lines))
                        print(f"Wrote {split_file['name']} to {c_path}")

                else:
                    out_lines = self.get_header()
                    for func in funcs_text:
                        out_lines.extend(funcs_text[func][0])
                        out_lines.append("")

                    outpath = Path(os.path.join(
                        out_dir, split_file["name"] + ".s"))
                    outpath.parent.mkdir(parents=True, exist_ok=True)

                    with open(outpath, "w", newline="\n") as f:
                        f.write("\n".join(out_lines))

                self.all_functions |= self.glabels_added

            elif split_file["subtype"] == "data":
                out_dir = self.create_split_dir(base_path, os.path.join("asm", "data"))

                outpath = Path(os.path.join(out_dir, split_file["name"] + ".data.s"))
                outpath.parent.mkdir(parents=True, exist_ok=True)

                file_text = self.gen_data_file(split_file, rom_bytes)
                if file_text:
                    with open(outpath, "w", newline="\n") as f:
                        f.write(file_text)

            elif split_file["subtype"] == "rodata":
                out_dir = self.create_split_dir(base_path, os.path.join("asm", "data"))

                outpath = Path(os.path.join(out_dir, split_file["name"] + ".rodata.s"))
                outpath.parent.mkdir(parents=True, exist_ok=True)

                file_text = self.gen_data_file(split_file, rom_bytes)
                if file_text:
                    with open(outpath, "w", newline="\n") as f:
                        f.write(file_text)

            elif split_file["subtype"] == "bin" and ("bin" in self.options["modes"] or "all" in self.options["modes"]):
                out_dir = self.create_split_dir(base_path, "bin")

                bin_path = os.path.join(
                    out_dir, split_file["name"] + "." + self.get_ext(split_file["subtype"]))
                Path(bin_path).parent.mkdir(parents=True, exist_ok=True)
                with open(bin_path, "wb") as f:
                    f.write(rom_bytes[split_file["start"]: split_file["end"]])

        if self.options.get("symbol_debug_info", None):
            for split_file in self.files:
                name = split_file["name"]
                print(f"Symbol info for {name}:")

                if name in self.data_syms:
                    print("data:")
                    sym_info = self.data_syms[name]
                    sorted_syms = sorted(sym_info.keys())
                    for sym in sorted_syms:
                        print(f"0x{sym:X}: {sym_info[sym]}")
                    print("\n")
                if name in self.rodata_syms:
                    print("rodata:")
                    sym_info = self.rodata_syms[name]
                    sorted_syms = sorted(sym_info.keys())
                    for sym in sorted_syms:
                        print(f"0x{sym:X}: {sym_info[sym]}")
                    print("\n")
                if name in self.unk_syms:
                    print("unk:")
                    sym_info = self.unk_syms[name]
                    sorted_syms = sorted(sym_info.keys())
                    for sym in sorted_syms:
                        print(f"0x{sym:X}: {sym_info[sym]}")


    @staticmethod
    def get_subdir(subtype):
        if subtype in ["c", ".data", ".rodata", ".bss"]:
            return "src"
        elif subtype in ["asm", "hasm", "header"]:
            return "asm"
        return subtype

    @staticmethod
    def get_ext(subtype):
        if subtype in ["c", ".data", ".rodata", ".bss"]:
            return "c"
        elif subtype in ["asm", "hasm", "header"]:
            return "s"
        elif subtype == "bin":
            return "bin"
        return subtype

    @staticmethod
    def get_ld_obj_type(subtype, section_name):
        if subtype in "c":
            return ".text"
        elif subtype in ["bin", ".data", "data"]:
            return ".data"
        elif subtype in [".rodata", "rodata"]:
            return ".rodata"
        elif subtype == ".bss":
            return ".bss"
        return section_name

    def get_ld_files(self):
        def transform(split_file):
            subdir = self.get_subdir(split_file["subtype"])
            obj_type = self.get_ld_obj_type(split_file["subtype"], ".text")
            ext = self.get_ext(split_file['subtype'])
            start = split_file["start"]

            return subdir, f"{split_file['name']}.{ext}", obj_type, start

        return [transform(file) for file in self.files]

    def get_ld_section_name(self):
        path = PurePath(self.name)
        name = path.name if path.name != "" else path.parent

        return f"code_{name}"
