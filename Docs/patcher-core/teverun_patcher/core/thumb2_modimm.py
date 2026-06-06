"""Thumb-2 Modified Immediate Encoder/Decoder.

Genutzt für `cmp.w Rn, #imm` und ähnliche Instruktionen mit imm12-Feld.
Spezifikation: ARMv7-M ARM, ThumbExpandImm Pseudocode.

Layout des Instruction-Encoded imm12:
    imm12<11>   = i  (HW1 bit 10)
    imm12<10:8> = imm3 (HW2 bits 14:12)
    imm12<7:0>  = imm8 (HW2 bits 7:0)

Decoding:
    if imm12<11:10> == 0b00:
        4 special simple replication patterns
    else:
        rot = imm12<11:7>           (5 bits, range 8..31)
        v   = 0x80 | imm12<6:0>     (implicit bit 7 = 1)
        result = ROR(v, rot)
"""
from __future__ import annotations


def _ror32(x: int, n: int) -> int:
    n &= 31
    return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF


def _rol32(x: int, n: int) -> int:
    n &= 31
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def encode(value: int) -> tuple[int, int, int] | None:
    """Encode 32-bit `value` as (i, imm3, imm8). None wenn nicht kodierbar."""
    value &= 0xFFFFFFFF

    if value < 256:
        return (0, 0, value)

    lo = value & 0xFF
    hi = (value >> 8) & 0xFF
    h2 = (value >> 16) & 0xFF
    h3 = (value >> 24) & 0xFF
    if hi == 0 and h3 == 0 and h2 == lo:
        return (0, 1, lo)
    if lo == 0 and h2 == 0 and hi == h3:
        return (0, 2, hi)
    if lo == hi == h2 == h3:
        return (0, 3, lo)

    for rot in range(8, 32):
        v = _rol32(value, rot)
        if v < 256 and (v & 0x80):
            imm87 = rot & 1
            imm8 = (imm87 << 7) | (v & 0x7F)
            i = (rot >> 4) & 1
            imm3 = (rot >> 1) & 7
            return (i, imm3, imm8)

    return None


def decode(i: int, imm3: int, imm8: int) -> int:
    """Decode (i, imm3, imm8) zurück zum 32-bit-Wert."""
    imm12 = ((i & 1) << 11) | ((imm3 & 7) << 8) | (imm8 & 0xFF)
    high2 = (imm12 >> 10) & 3

    if high2 == 0:
        sub = (imm12 >> 8) & 3
        b = imm12 & 0xFF
        if sub == 0:
            return b
        if sub == 1:
            return (b << 16) | b
        if sub == 2:
            return (b << 24) | (b << 8)
        if sub == 3:
            return (b << 24) | (b << 16) | (b << 8) | b

    rot = (imm12 >> 7) & 0x1F
    v = 0x80 | (imm12 & 0x7F)
    return _ror32(v, rot)


def patch_hw2_imm12(orig_hw2: int, new_value: int) -> int | None:
    """Berechnet das neue HW2-Wort für eine cmp.w/mov.w-Instruktion.

    Behält Bits 15 und 11:8 (1111-Marker) bei, ersetzt nur i kann nicht
    geändert werden weil i in HW1 ist — der Aufrufer muss HW1 separat
    patchen falls nötig.

    Returns: neues HW2 oder None wenn Encoding scheitert.
    """
    enc = encode(new_value)
    if enc is None:
        return None
    i, imm3, imm8 = enc
    new_hw2 = (orig_hw2 & 0x8F00) | ((imm3 & 7) << 12) | (imm8 & 0xFF)
    new_hw2 |= 0x0F00
    return new_hw2


def encode_for_cmp_w(value: int) -> tuple[int, int, int, int] | None:
    """Liefert (hw1_bit_i, imm3, imm8_byte, hw2_high_byte) für cmp.w-Patch.

    Praktisch: Returns dict-like info für Patch-Engine.
    """
    enc = encode(value)
    if enc is None:
        return None
    i, imm3, imm8 = enc
    hw2_high = 0x0F | ((imm3 & 7) << 4)
    return (i, imm3, imm8, hw2_high)
