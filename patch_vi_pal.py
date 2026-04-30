"""
patch_vi_pal.py - Patches GC-EU / GC-EU-MQ ROMs to use correct PAL video timing

Background:
    The GameCube editions of Ocarina of Time configure the N64
    Video Interface using NTSC timing regardless of the console's TV
    type. This was identified by binary analysis of the ROM: a VI mode struct
    is written at startup that specifies 525-line 60 Hz output.

    The PAL N64 releases use Full PAL (FPAL) timing instead:
      - 625 lines per frame (50 Hz)
      - A larger vertical active window covering half-lines 47-617
      - A vertical scale factor of 0.833 that stretches the 240-line
        framebuffer to fill the PAL display region

Method:
    The VI mode struct was located in ROM by binary analysis and signature
    matching. The struct is 80 bytes and holds the hardware register values
    written to the VI at startup. By replacing the NTSC values with the
    correct FPAL values, the ROM produces a proper PAL signal.

    Struct layout (offsets relative to struct base):
        +0x00  u8   type       - Mode identifier
        +0x01  [3 bytes padding]
        +0x04  u32  ctrl       - VI control register (unchanged)
        +0x08  u32  width      - Frame width in pixels (unchanged, 320)
        +0x0C  u32  burst      - Sync burst timing
        +0x10  u32  vSync      - Lines per frame
        +0x14  u32  hSync      - Horizontal sync timing
        +0x18  u32  leap       - Leap correction
        +0x1C  u32  hStart     - Horizontal active window
        +0x20  u32  xScale     - Horizontal scale (unchanged)
        +0x24  u32  vCurrent   - Current vertical line (unchanged, 0)
        +0x28  u32  fldRegs[0].origin  (unchanged)
        +0x2C  u32  fldRegs[0].yScale  - Vertical scale factor
        +0x30  u32  fldRegs[0].vStart  - Vertical active window
        +0x34  u32  fldRegs[0].vBurst  - Vertical burst timing
        +0x38  u32  fldRegs[0].vIntr   (unchanged)
        +0x3C  u32  fldRegs[1].origin  (unchanged)
        +0x40  u32  fldRegs[1].yScale  - Vertical scale factor
        +0x44  u32  fldRegs[1].vStart  - Vertical active window
        +0x48  u32  fldRegs[1].vBurst  - Vertical burst timing
        +0x4C  u32  fldRegs[1].vIntr   (unchanged)

    Register values were identified by comparing the binary data in the
    GC-EU ROM against the known PAL N64 releases.

    The ROM header contains an IPL3 checksum (bytes 0x10-0x17) computed
    over ROM bytes 0x1000-0x100FFF. Since the patched struct lies within
    this range, the checksum must be recalculated after patching. GC-EU
    and GC-EU-MQ use CIC-6105 with seed 0xDF26F436.

Usage:
    python3 patch_vi_pal.py input.z64 output.z64

    Works with: GC-EU  (baserom-decompressed.z64)
                GC-EU-MQ (baserom-decompressed.z64)
    Requires: decompressed ROM, no external dependencies.
"""

import struct
import sys

# Signature: first 16 bytes of the VI mode struct as it appears in the ROM.
#   02          = type byte (NTSC mode identifier)
#   00 00 00    = padding (alignment to 4 bytes)
#   00 00 31 1e = ctrl register (type-16 | gamma dither | gamma | divot | antialias | pixel adv)
#   00 00 01 40 = width = 320 (0x140)
#   03 e5 22 39 = burst: NTSC values (57, 34, 5, 62)
SIGNATURE = bytes.fromhex("020000000000311e0000014003e52239")

# Patches to apply, relative to the struct base address.
# Format: (struct_offset, old_value_hex, new_value_hex, description)
PATCHES = [
    # type: software identifier indicating which VI mode this struct represents.
    # Does not affect hardware directly but is updated for correctness.
    # NTSC = 0x02, FPAL = 0x2C
    (0x00, "02",       "2c",       "type: NTSC (0x02) -> FPAL (0x2C)"),

    # burst: packed register encoding four sync pulse timing values.
    # NTSC: (57, 34, 5, 62) = 0x03E52239
    # FPAL: (58, 30, 4, 69) = 0x04541E3A
    (0x0C, "03e52239", "04541e3a", "burst: (57,34,5,62) -> (58,30,4,69)"),

    # vSync: total number of half-lines per frame.
    # NTSC: 525 lines = 0x020D  (60 Hz)
    # FPAL: 625 lines = 0x0271  (50 Hz)
    (0x10, "0000020d", "00000271", "vSync: 525 lines (60 Hz) -> 625 lines (50 Hz)"),

    # hSync: horizontal sync duration and leap value.
    # NTSC: (3093,  0) = 0x00000C15
    # FPAL: (3177, 23) = 0x00170C69
    (0x14, "00000c15", "00170c69", "hSync: (3093,0) -> (3177,23)"),

    # leap: fine correction applied to hSync to compensate for sub-pixel drift.
    # NTSC: (3093, 3093) = 0x0C150C15
    # FPAL: (3183, 3181) = 0x0C6F0C6D
    (0x18, "0c150c15", "0c6f0c6d", "leap: (3093,3093) -> (3183,3181)"),

    # hStart: horizontal window defining the active picture area (start, end).
    # NTSC: (108, 748) = 0x006C02EC
    # FPAL: (128, 768) = 0x00800300
    (0x1C, "006c02ec", "00800300", "hStart: (108,748) -> (128,768)"),

    # fldRegs[0].yScale: vertical scale factor for field 0.
    # The framebuffer is 240 lines. PAL has a taller active region, so the
    # output must be stretched vertically to fill it. The scale factor is
    # stored as a fixed-point value: floor(factor * 1024).
    # NTSC: 1.0   = 0x00000400  (no stretch)
    # FPAL: 0.833 = 0x00000354  (matches PAL N64 releases)
    (0x2C, "00000400", "00000354", "fldRegs[0].yScale: 1.0 -> 0.833"),

    # fldRegs[0].vStart: vertical window defining the active picture area.
    # Encoded as (start_half_line << 16) | end_half_line.
    # NTSC: (37,  511) = 0x002501FF
    # FPAL: (47,  617) = 0x002F0269  (Full PAL -- wider window than standard PAL)
    (0x30, "002501ff", "002f0269", "fldRegs[0].vStart: (37,511) -> (47,617)"),

    # fldRegs[0].vBurst: vertical color burst timing for field 0.
    # NTSC: (4,   2, 14, 0) = 0x000E0204
    # FPAL: (107, 2,  9, 0) = 0x0009026B
    (0x34, "000e0204", "0009026b", "fldRegs[0].vBurst: (4,2,14,0) -> (107,2,9,0)"),

    # fldRegs[1].yScale: same as fldRegs[0] (deinterlaced mode -- both fields identical).
    (0x40, "00000400", "00000354", "fldRegs[1].yScale: 1.0 -> 0.833"),

    # fldRegs[1].vStart: same as fldRegs[0].
    (0x44, "002501ff", "002f0269", "fldRegs[1].vStart: (37,511) -> (47,617)"),

    # fldRegs[1].vBurst: same as fldRegs[0].
    (0x48, "000e0204", "0009026b", "fldRegs[1].vBurst: (4,2,14,0) -> (107,2,9,0)"),
]


def n64_crc_6105(rom: bytes) -> tuple:
    """
    Computes the N64 IPL3 checksum for CIC-6105.

    Processes ROM bytes 0x1000-0x100FFF using six 32-bit accumulators
    initialized to seed 0xDF26F436. CIC-6105 differs from CIC-6102 in the
    t1 accumulator: it XORs against a 256-byte table located within the
    IPL3 code itself at ROM offset 0x0750.
    """
    MASK = 0xFFFFFFFF
    SEED = 0xDF26F436

    def rol(v, b):
        b &= 31
        return ((v << b) | (v >> (32 - b))) & MASK if b else v & MASK

    t1 = t2 = t3 = t4 = t5 = t6 = SEED

    for pos in range(0x1000, 0x101000, 4):
        d = struct.unpack_from(">I", rom, pos)[0]
        r = rol(d, d & 0x1F)

        if (t6 + d) > MASK:
            t4 = (t4 + 1) & MASK
        t6 = (t6 + d) & MASK
        t3 = (t3 ^ d) & MASK
        t5 = (t5 + r) & MASK

        if t2 > d:
            t2 = (t2 ^ r) & MASK
        else:
            t2 = (t2 ^ (t6 ^ d)) & MASK

        # CIC-6105: XOR t1 against the 256-byte IPL3 table at 0x0750
        t1 = (t1 + (struct.unpack_from(">I", rom, 0x0750 + (pos & 0xFF))[0] ^ d)) & MASK

    crc1 = (t6 ^ t4 ^ t3) & MASK
    crc2 = (t5 ^ t2 ^ t1) & MASK
    return crc1, crc2


def patch_rom(input_path, output_path):
    with open(input_path, "rb") as f:
        rom = bytearray(f.read())

    # Locate the VI mode struct by signature rather than a hardcoded offset
    # so that the script works for both GC-EU and GC-EU-MQ.
    matches = []
    pos = 0
    while True:
        idx = rom.find(SIGNATURE, pos)
        if idx == -1:
            break
        matches.append(idx)
        pos = idx + 1

    if len(matches) == 0:
        print("ERROR: VI mode struct signature not found.")
        print("       Verify that the ROM is decompressed and is GC-EU or GC-EU-MQ.")
        sys.exit(1)

    if len(matches) > 1:
        print(f"WARNING: Signature found {len(matches)} times: {[hex(m) for m in matches]}")
        print("         Using first match.")

    struct_offset = matches[0]
    print(f"Found VI mode struct at ROM offset 0x{struct_offset:08X}")
    print()

    for rel_offset, old_hex, new_hex, description in PATCHES:
        abs_offset = struct_offset + rel_offset
        old_bytes = bytes.fromhex(old_hex)
        new_bytes = bytes.fromhex(new_hex)

        actual = bytes(rom[abs_offset : abs_offset + len(old_bytes)])
        if actual != old_bytes:
            print(f"ERROR at +0x{rel_offset:02X} ({description})")
            print(f"  Expected: {old_hex}")
            print(f"  Found:    {actual.hex()}")
            sys.exit(1)

        rom[abs_offset : abs_offset + len(new_bytes)] = new_bytes
        print(f"  +0x{rel_offset:02X}  {description}")
        print(f"         {old_hex} -> {new_hex}")

    # Recalculate the IPL3 checksum.
    # The patched struct at 0x6E60 lies within the checksummed region
    # (0x1000-0x100FFF), so the header must be updated.
    print()
    print("Recalculating IPL3 checksum (CIC-6105, seed=0xDF26F436)...")
    crc1, crc2 = n64_crc_6105(bytes(rom))
    struct.pack_into(">I", rom, 0x10, crc1)
    struct.pack_into(">I", rom, 0x14, crc2)
    print(f"  New checksum: {crc1:08X} {crc2:08X}")

    with open(output_path, "wb") as f:
        f.write(rom)
    print(f"Patched ROM saved to: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input.z64 output.z64")
        sys.exit(1)
    patch_rom(sys.argv[1], sys.argv[2])