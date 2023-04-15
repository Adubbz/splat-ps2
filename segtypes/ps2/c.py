from pathlib import Path
from typing import Optional, Set, List, Tuple

import spimdisasm

from util import options
from util.symbols import Symbol

from segtypes.ps2 import linker_utils
from segtypes.common.c import CommonSegC

SUBSTITUTIONS = {
    # Constant 0
    '$zero': '$0',

    # Result registers
    '$v0': '$2',
    '$v1': '$3',

    # Argument registers
    '$a0': '$4',
    '$a1': '$5',
    '$a2': '$6',
    '$a3': '$7',

    # Temporary registers
    '$t0': '$8',
    '$t1': '$9',
    '$t2': '$10',
    '$t3': '$11',
    '$t4': '$12',
    '$t5': '$13',
    '$t6': '$14',
    '$t7': '$15',

    # Saved registers
    '$s0': '$16',
    '$s1': '$17',
    '$s2': '$18',
    '$s3': '$19',
    '$s4': '$20',
    '$s5': '$21',
    '$s6': '$22',
    '$s7': '$23',

    # Temporary registers
    '$t8': '$24',
    '$t9': '$25',

    # Return address
    '$ra': '$31',

    # Accumulator registers
    '$ACC': 'ACC',

    # Q register
    '$Q': 'Q',

    # trunc.w.s should actually be cvt.w.s
    # See: https://github.com/Decompollaborate/rabbitizer/blob/40257d064931d415e5efec16844bb4083c145bc1/include/instructions/instr_id/r5900/r5900_cop1_fpu_s.inc#L106-L110
    'trunc.w.s': 'cvt.w.s',
}

class Ps2SegC(CommonSegC):
    # Modify generated .s files to use the expected register names
    def create_c_asm_file(
        self,
        func_rodata_entry: spimdisasm.mips.FunctionRodataEntry,
        out_dir: Path,
        func_sym: Symbol,
    ):
        outpath = out_dir / self.name / (func_sym.name + ".s")

        # Skip extraction if the file exists and the symbol is marked as extract=false
        if outpath.exists() and not func_sym.extract:
            return

        super().create_c_asm_file(func_rodata_entry, out_dir, func_sym)

        # Perform substitutions on register names
        with open(outpath, 'r') as f:
            lines = f.readlines()

        with open(outpath, 'w') as f:
            for line in lines:
                for old, new in SUBSTITUTIONS.items():
                    line = line.replace(old, new)
                f.write(line)

    # Modify linker script generation to use individual .s.o files
    def get_linker_entries(self) -> "List[LinkerEntry]":
        from segtypes.linker_entry import LinkerEntry

        path = self.out_path()

        if path:
            if path.exists():
                # Include the C file in the linker script
                return [LinkerEntry(self, [path], path, self.get_linker_section())]
            else:
                return linker_utils.get_asm_linker_entries(self)
        else:
            return []