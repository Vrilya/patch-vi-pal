# patch_vi_pal

patch_vi_pal is a Python script that patches decompressed GameCube-edition Ocarina of Time ROMs (GC-EU and GC-EU-MQ) to use correct PAL video timing, making them behave identically to the PAL N64 releases on PAL hardware.

The script was written as part of a reverse engineering study of the N64 Video Interface configuration embedded in OoT ROMs, and how the GC editions differ from the original PAL cartridges.

## Background

The N64 Video Interface (VI) is configured at startup by writing a set of hardware registers from a data structure stored in ROM. By reverse engineering the GC-EU ROM, I located this structure and identified that it contains NTSC timing values, 525 lines at 60 Hz, even though the game is intended for PAL hardware.

The PAL N64 releases instead use Full PAL (FPAL) timing: 625 lines at 50 Hz, with a larger vertical active window and a vertical scale factor of 0.833 that stretches the 240-line framebuffer to fill the PAL display region. By replacing the NTSC values in the GC-EU ROM with the correct FPAL values, the ROM produces a proper PAL signal.

The structure is found by scanning the ROM for a known byte signature rather than a hardcoded offset, so the script works with both GC-EU and GC-EU-MQ.

The following registers are patched:

| Struct offset | Register   | NTSC value   | PAL value    | Description                      |
|---------------|------------|--------------|--------------|----------------------------------|
| +0x00         | type       | `0x02`       | `0x2C`       | VI mode identifier               |
| +0x0C         | burst      | `0x03E52239` | `0x04541E3A` | Sync burst timing                |
| +0x10         | vSync      | `0x0000020D` | `0x00000271` | Lines per frame (525 → 625)      |
| +0x14         | hSync      | `0x00000C15` | `0x00170C69` | Horizontal sync timing           |
| +0x18         | leap       | `0x0C150C15` | `0x0C6F0C6D` | Leap correction                  |
| +0x1C         | hStart     | `0x006C02EC` | `0x00800300` | Horizontal active window         |
| +0x2C         | yScale[0]  | `0x00000400` | `0x00000354` | Vertical scale (field 0)         |
| +0x30         | vStart[0]  | `0x002501FF` | `0x002F0269` | Vertical active window (field 0) |
| +0x34         | vBurst[0]  | `0x000E0204` | `0x0009026B` | Vertical burst timing (field 0)  |
| +0x40         | yScale[1]  | `0x00000400` | `0x00000354` | Vertical scale (field 1)         |
| +0x44         | vStart[1]  | `0x002501FF` | `0x002F0269` | Vertical active window (field 1) |
| +0x48         | vBurst[1]  | `0x000E0204` | `0x0009026B` | Vertical burst timing (field 1)  |

The `yScale` value `0x0354` corresponds to a factor of 0.833, which is `floor(0.833 * 1024)`. This matches the vertical scale used by the PAL N64 releases.

After patching, the IPL3 checksum (ROM bytes `0x10`–`0x17`) is recalculated. The checksum covers ROM bytes `0x1000`–`0x100FFF`, and since the patched structure lies within this range the header must be updated for the ROM to be accepted. The CIC-6105 algorithm is used with seed `0xDF26F436`, implemented directly in the script with no external dependencies.

## Usage

    python3 patch_vi_pal.py <input.z64> <output.z64>

The input must be a decompressed ROM. Both GC-EU and GC-EU-MQ are supported.

Example:

    python3 patch_vi_pal.py baserom-decompressed.z64 baserom-decompressed-pal.z64

## Requirements

Python 3. No external packages required.
