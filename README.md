# patch_gc_bootlogo

patch_gc_bootlogo is a Python script that patches decompressed GameCube-edition Ocarina of Time ROMs to restore the Nintendo boot logo sequence that is disabled in the GC releases.

The script supports GC-EU, GC-EU-MQ, GC-US, and GC-US-MQ. It restores the startup logo fade-in, visible hold, texture scroll, fade-out, and transition to the title screen by replacing the disabled GC logo update routine with a trampoline into a small injected code cave.

The script was written as part of a reverse engineering study of the GameCube OoT ROMs, the title-screen boot flow, and the startup logo state machine that still exists in the ROM but is skipped by the GC editions.

## Background

The GameCube releases still contain the title boot mode that displays the Nintendo logo, but the per-frame logo update routine has been reduced to a tiny stub that exits immediately:

    this->exit = true;

At the machine-code level this routine is only 16 bytes:

| Instruction | Meaning |
|-------------|---------|
| `240E0001` | Load `1` into `t6` |
| `A08E01E1` | Store `1` to `this->exit` |
| `03E00008` | Return to caller |
| `00000000` | Delay-slot `nop` |

Because `this->exit` is set on the first frame, the game immediately leaves the logo state and continues toward the title screen. The rendering code and logo state still exist; the GC ROM simply never allows the logo state to run for more than one frame.

By comparing runtime behavior and inspecting the title overlay in memory, I identified the state fields used by the boot logo routine: the black-screen cover alpha, fade speed, visible-duration timer, texture-scroll counters, and exit flag. Reintroducing the original style of per-frame logic restores the sequence without needing to move or resize any ROM segments.

## Patch method

The disabled GC routine is too small to hold the full replacement routine directly. The script therefore uses a trampoline and a code cave:

1. The 16-byte GC stub is replaced with a MIPS `j` instruction that jumps to unused zero-filled padding inside the always-loaded `code` segment.
2. The code cave receives a 156-byte replacement routine that updates the logo state each frame.
3. The replacement routine ends with `jr ra`, returning to the original caller just like the original function would.

The MIPS `j` instruction does not modify `ra`, which is important here: the caller already reached the routine through `jal`, so `ra` still points back to the correct return address.

The injected routine is position-independent. It uses only register-relative state access through the object pointer in `a0`, plus local branches. No absolute data pointers, relocation entries, DMA-table edits, or segment expansion are required.

## Supported ROM profiles

The script identifies ROM versions by scanning for build-data signatures. A profile supplies the title routine offset, the code-segment mapping, and the selected code cave.

| Profile | Build date/time | `code` ROM start | `code` RAM start | Stub ROM offset | Cave ROM offset | Cave RAM address | `j` instruction |
|---------|-----------------|------------------|------------------|-----------------|-----------------|------------------|-----------------|
| `gc-eu` | `03-02-21 20:12:23` | `0x00A88000` | `0x80010F00` | `0x00B8A250` | `0x00B59FEC` | `0x800E2EEC` | `0x08038BBB` |
| `gc-eu-mq` | `03-02-21 20:37:19` | `0x00A88000` | `0x80010F00` | `0x00B8A230` | `0x00B59FCC` | `0x800E2ECC` | `0x08038BB3` |
| `gc-us` | `02-12-19 13:28:09` | `0x00A86000` | `0x80010EE0` | `0x00B8AA60` | `0x00B5A68C` | `0x800E556C` | `0x0803955B` |
| `gc-us-mq` | `02-12-19 14:05:42` | `0x00A86000` | `0x80010EE0` | `0x00B8AA40` | `0x00B5A66C` | `0x800E554C` | `0x08039553` |

The GC-US and GC-US-MQ profiles use a different `code` RAM base from the GC-EU profiles. This matters because the trampoline jumps to a RAM address, not a ROM offset.

## Replacement routine

The injected routine is a 39-instruction MIPS routine that restores the missing per-frame state transitions. It does not call any new functions and does not reference any absolute addresses; all state access is done through `a0 + offset`, where `a0` is the active boot-logo state object.

At a high level, the routine performs these state transitions:

| Condition | Action | Result |
|-----------|--------|--------|
| `+0x1D6` is nonzero | Add `+0x1D8` into `+0x1D6` | Fade step continues |
| `+0x1D6` reaches zero or below | Clamp `+0x1D6` to `0`, write `3` to `+0x1D8` | Fade-in is finished; fade direction changes |
| `+0x1D6` reaches `255` or above | Clamp `+0x1D6` to `255`, write `1` to `+0x1E1` | Fade-out is finished; logo mode exits |
| `+0x1D6` is zero and `+0x1DA` is nonzero | Decrement `+0x1D4` and `+0x1DA` | Logo remains fully visible for the hold period |
| `+0x1D4` reaches zero during hold | Write `400` back to `+0x1D4` | Secondary timer is reset |
| Every frame | Write `(+0x1DC & 0x7F)` to `+0x1DE`, then increment `+0x1DC` | Texture-scroll state advances |

The relevant state fields are:

| Struct offset | Local label | Type | Description |
|---------------|-------------|------|-------------|
| `+0x1D4` | `hold_subtimer` | `s16` | Secondary timer used while the logo is fully visible |
| `+0x1D6` | `cover_alpha` | `s16` | Black cover alpha; `255` is black, `0` is visible |
| `+0x1D8` | `alpha_step` | `s16` | Fade step; negative during fade-in, positive during fade-out |
| `+0x1DA` | `hold_timer` | `s16` | Number of frames the logo remains fully visible |
| `+0x1DC` | `scroll_counter` | `s16` | Texture-scroll counter |
| `+0x1DE` | `scroll_value` | `s16` | Texture-scroll value, updated as `scroll_counter & 0x7F` |
| `+0x1E1` | `exit_flag` | `u8` | Set to `1` when the logo sequence is finished |

The draw routine is not patched. The existing rendering path reads these state fields normally, so restoring the update routine is enough to bring back the visible logo sequence.

## MIPS jump encoding

The trampoline is a standard MIPS `j` instruction:

    opcode      = 2
    instr_index = (target_ram & 0x0FFFFFFF) >> 2
    instruction = (opcode << 26) | instr_index

For example, the GC-US profile jumps to `0x800E556C`:

    instr_index = (0x800E556C & 0x0FFFFFFF) >> 2
                = 0x0003955B

    instruction = (2 << 26) | 0x0003955B
                = 0x0803955B

The delay slot after the jump is filled with `nop`.

## Safety checks

Before writing anything, the script verifies that:

| Check | Purpose |
|-------|---------|
| Build-data signature is present | Selects the correct ROM profile |
| The 16-byte GC stub matches | Prevents patching the wrong code or an already-patched ROM |
| The code cave is zero-filled | Avoids overwriting real code or another experiment |


## Usage

    python3 patch_gc_eu_bootlogo_trampoline2.py <input.z64> <output.z64>

The input must be a decompressed ROM. GC-EU, GC-EU-MQ, GC-US, and GC-US-MQ are detected automatically through build-data signatures.

Example:

    python3 patch_gc_eu_bootlogo_trampoline2.py baserom-decompressed.z64 baserom-bootlogo.z64

A profile can also be selected manually:

    python3 patch_gc_eu_bootlogo_trampoline2.py baserom-decompressed.z64 baserom-bootlogo.z64 --profile gc-us-mq

Supported profile names:

    gc-eu
    gc-eu-mq
    gc-us
    gc-us-mq

## Requirements

Python 3. No external packages required.
