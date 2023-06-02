import spimdisasm
import subprocess

from util import options

from segtypes.common.codesubsegment import CommonSegCodeSubsegment

demangle_cache = {}

def demangle(sym):
    if sym in demangle_cache:
        return demangle_cache[sym]
    else:
        # TODO: This is super slow. Is there a better way?
        demangled = subprocess.check_output(['tools/ee/gcc/bin/ee-c__filt.exe', sym]).decode().strip()
        demangle_cache[sym] = demangled
        return demangled

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

            asm_path = asm_out_dir / segment.name / (create_asm_file_name(func_sym) + ".s")
            linker_entries.append(LinkerEntry(segment, [asm_path], asm_path, segment.get_linker_section()))

    return linker_entries

name_cache = {}
prev_names = set()

def make_unique_name(func_sym, demangled):
    # Check if the name is already in the cache. If so, use it
    if func_sym.vram_start in name_cache:
        return name_cache[func_sym.vram_start]
    
    # Append a unique suffix to the demangled name
    suffix = 2
    new_name = demangled
    while new_name.lower() in prev_names:
        new_name = f'{demangled}_{suffix}'
        suffix += 1
    prev_names.add(new_name.lower())

    # Cache the new name
    name_cache[func_sym.vram_start] = new_name
    return new_name

def create_asm_file_name(func_sym):
    demangled = demangle(func_sym.name).split('(')[0].replace(':', '_').replace('<', '_').replace('>', '_').replace(' ', '_').replace('=', 'equals')
    demangled = make_unique_name(func_sym, demangled)
    return demangled