from typing import Dict, List, Optional, Tuple, Set

from segtypes.common.code import CommonSegCode
from segtypes.segment import Segment

class Ps2SegCode(CommonSegCode):
    def handle_alls(self, segs: List[Segment], base_segs) -> bool:
        for i, elem in enumerate(segs):
            if elem.type.startswith("all_"):
                alls = []

                rep_type = f"{elem.type[4:]}"
                replace_class = Segment.get_class_for_type(rep_type)

                for base in base_segs.items():
                    if isinstance(elem.rom_start, int) and isinstance(
                        self.rom_start, int
                    ):
                        # Shoddy rom to ram
                        assert self.vram_start is not None, self.vram_start
                        vram_start = elem.rom_start - self.rom_start + self.vram_start
                    else:
                        vram_start = None

                    rom_start = elem.rom_start
                    rom_end = elem.rom_end

                    # Lookup the rom start and end if we don't know what they are
                    if rep_type == '.data' and rom_start is None and rom_end is None and vram_start is None:
                        for seg in segs:
                            if seg.name == base[0]:
                                rom_start = seg.rom_start
                                rom_end = seg.rom_end
                                vram_start = seg.vram_start
                                break

                    rep: Segment = replace_class(
                        rom_start=rom_start,
                        rom_end=rom_end,
                        type=rep_type,
                        name=base[0],
                        vram_start=vram_start,
                        args=[],
                        yaml={},
                    )
                    rep.extract = False
                    rep.given_subalign = self.given_subalign
                    rep.exclusive_ram_id = self.get_exclusive_ram_id()
                    rep.given_dir = self.given_dir
                    rep.given_symbol_name_format = self.symbol_name_format
                    rep.given_symbol_name_format_no_rom = self.symbol_name_format_no_rom
                    rep.sibling = base[1]
                    rep.parent = self
                    if rep.special_vram_segment:
                        self.special_vram_segment = True
                    alls.append(rep)

                # Insert alls into segs at i
                del segs[i]
                segs[i:i] = alls
                return True
        return False