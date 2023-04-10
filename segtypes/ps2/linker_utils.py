import spimdisasm

from util import options

from segtypes.common.codesubsegment import CommonSegCodeSubsegment

def get_asm_linker_entries(segment: CommonSegCodeSubsegment) -> "List[LinkerEntry]":
    from segtypes.linker_entry import LinkerEntry

    linker_entries = []

    asm_out_dir = options.opts.nonmatchings_path / segment.dir
    asm_out_dir.mkdir(parents=True, exist_ok=True)

    # Include individual .s files in the linker script
    symbols_entries = spimdisasm.mips.FunctionRodataEntry.getAllEntriesFromSections(
        segment.spim_section, None
    )
    
    for entry in symbols_entries:
        if entry.function is not None:
            func_sym = segment.get_symbol(
                entry.function.vram,
                in_segment=True,
                type="func",
                local_only=True,
            )
            assert func_sym is not None

            asm_path = asm_out_dir / segment.name / (func_sym.name + ".s")
            linker_entries.append(LinkerEntry(segment, [asm_path], asm_path, segment.get_linker_section()))

    return linker_entries