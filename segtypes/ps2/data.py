from segtypes.ps2 import linker_utils
from segtypes.common.data import CommonSegData
from segtypes.common.codesubsegment import CommonSegCodeSubsegment

class Ps2SegData(CommonSegData):
    def scan(self, rom_bytes: bytes):
        super().scan(rom_bytes)

        if (
            self.rom_start is not None
            and self.rom_end is not None
            and self.rom_start != self.rom_end
            and self.should_linker_use_asm()
        ):
            self.scan_code(rom_bytes)

    # Modify linker script generation to use individual .s.o files
    def get_linker_entries(self) -> "List[LinkerEntry]":
        from segtypes.linker_entry import LinkerEntry

        if self.should_linker_use_asm():
            return linker_utils.get_asm_linker_entries(self)

        return super().get_linker_entries()
    
    def should_linker_use_asm(self):
        path = self.out_path()
        return path and path.suffix == '.c' and not path.exists()