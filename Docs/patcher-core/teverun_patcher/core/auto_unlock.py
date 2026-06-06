"""Deterministischer Auto-Unlock (ohne AI, ohne Profil).

Findet die Controller-Frame-Builder ueber die Header-Signatur
``movs r0,#0x4A ; ldr r1,[pc,#imm] ; strb r0,[r1]`` und in jedem Builder den
Speed/Output-Clamp:

    cmp(.w) rM,#X  /  <bedingter Branch>  /  mov(s)/mov.w rM,#X

wobei ``rM`` exakt das Register ist, das in FRAME[+0x0A] (das Output/Zug-Byte des
Controller-Frames) geschrieben wird. Das ``mov(s)/mov.w rM,#X`` wird zu NOP
gesetzt -> der natuerliche Wert fliesst durch = entsperrt (wie manuell bei
5.4.10/5.4.14/5.4.19 verifiziert).

Robust gegen: Register-Wechsel (r7/r8/...), 2- oder 4-Byte-Clamp, beliebigen
Clamp-Wert (nicht auf 0x16 fest), Code-Verschiebungen zwischen Versionen.

Fail-safe: wird das Muster nicht eindeutig gefunden (kein FRAME[+0xA]-Write oder
kein cmp+mov-Clamp auf demselben Register), wird der Builder NICHT gepatcht,
sondern gemeldet. Keine Abhaengigkeit ausser dem HexLoader -> Pyodide-tauglich.
"""
from __future__ import annotations
from dataclasses import dataclass, field

FRAME_OUT_OFFSET = 0x0A      # Output/Zug-Byte im Controller-Frame
HEADER_VALUE = 0x4A          # Frame-Header[0]
NOP16 = bytes([0x00, 0xBF])           # NOP
NOPW = bytes([0xAF, 0xF3, 0x00, 0x80])  # NOP.W


@dataclass
class AutoResult:
    builders: list = field(default_factory=list)          # Header-Adressen
    patched: list = field(default_factory=list)           # (addr, size, reg, value)
    skipped: list = field(default_factory=list)            # (addr|None, grund)

    @property
    def ok(self) -> bool:
        return len(self.patched) > 0


def _u16(d, o):
    return d[o] | (d[o + 1] << 8)


# --- Instruktions-Matcher (geben (size, reg, value) bzw. (size, rt, rn) oder None) ---
def _movs(d, o):                       # movs rM,#imm8  (16-bit)
    hw = _u16(d, o)
    if (hw & 0xF800) == 0x2000:
        return 2, (hw >> 8) & 7, hw & 0xFF
    return None

def _movw(d, o):                       # mov.w rM,#imm8 (imm3=0, S=0)
    if d[o] == 0x4F and d[o + 1] == 0xF0:
        hw2 = _u16(d, o + 2)
        if (hw2 & 0x8000) == 0 and ((hw2 >> 12) & 7) == 0:
            return 4, (hw2 >> 8) & 0xF, hw2 & 0xFF
    return None

def _cmp(d, o):                        # cmp rM,#imm8 (16-bit)
    hw = _u16(d, o)
    if (hw & 0xF800) == 0x2800:
        return 2, (hw >> 8) & 7, hw & 0xFF
    return None

def _cmpw(d, o):                       # cmp.w rM,#imm8 (rd=PC, imm3=0)
    if (d[o] & 0xF0) == 0xB0 and d[o + 1] == 0xF1:
        hw2 = _u16(d, o + 2)
        if ((hw2 >> 8) & 0xF) == 0xF and ((hw2 >> 12) & 7) == 0:
            return 4, d[o] & 0xF, hw2 & 0xFF
    return None

def _strb(d, o, off):                  # strb rt,[rn,#off] (16-bit)
    hw = _u16(d, o)
    if (hw & 0xF800) == 0x7000 and ((hw >> 6) & 0x1F) == off:
        return 2, hw & 7, (hw >> 3) & 7
    return None

def _strbw(d, o, off):                 # strb.w rt,[rn,#imm12]
    if (d[o] & 0xF0) == 0x80 and d[o + 1] == 0xF8:
        hw2 = _u16(d, o + 2)
        if (hw2 & 0xFFF) == off:
            return 4, (hw2 >> 12) & 0xF, d[o] & 0xF
    return None


def _bcc(d, o):
    """16-bit bedingter Branch (Bcc, cond 0..0xD)?"""
    hw = _u16(d, o)
    return (hw & 0xF000) == 0xD000 and ((hw >> 8) & 0xF) <= 0xD


def find_and_unlock(loader, dry_run: bool = False) -> AutoResult:
    base = loader.ih.minaddr()
    data = bytearray(loader.to_bytes())
    n = len(data)
    res = AutoResult()

    # Frame-Builder-Header (movs r0,#0x4A; ldr r1,[pc]; strb r0,[r1]) — Kontext/Report
    headers = []
    for o in range(0, n - 5, 2):
        if (data[o] == HEADER_VALUE and data[o + 1] == 0x20 and
                data[o + 3] == 0x49 and data[o + 4] == 0x08 and data[o + 5] == 0x70):
            headers.append(base + o)
    res.builders = headers

    def header_near(addr):
        return any(addr - 0x80 <= h <= addr + 0x180 for h in headers)

    seen = set()
    o = 0
    while o < n - 4:
        # Selbst-Clamp: cmp rN,#X / Bcc / mov(s)/mov.w rN,#X  (an o steht das mov)
        mv = _movs(data, o) or _movw(data, o)
        if mv and o - 4 >= 0 and _bcc(data, o - 2):
            sz, reg, val = mv
            cm = None
            c = _cmp(data, o - 4)
            if c and c[1] == reg and c[2] == val:
                cm = o - 4
            if cm is None and o - 6 >= 0:
                c = _cmpw(data, o - 6)
                if c and c[1] == reg and c[2] == val:
                    cm = o - 6
            if cm is not None:
                # Verifizieren: rN wird in FRAME[+0xA] geschrieben (innerhalb +0x160)
                out_ok = False
                k = o + sz
                kend = min(o + 0x160, n - 3)
                while k < kend:
                    m = _strb(data, k, FRAME_OUT_OFFSET) or _strbw(data, k, FRAME_OUT_OFFSET)
                    if m and m[1] == reg:
                        out_ok = True
                        break
                    k += 2
                caddr = base + o
                if out_ok and header_near(caddr) and caddr not in seen:
                    seen.add(caddr)
                    if not dry_run:
                        nop = NOP16 if sz == 2 else NOPW
                        for i, b in enumerate(nop):
                            loader.write_byte(caddr + i, b)
                    res.patched.append((caddr, sz, reg, val))
                    o += sz
                    continue
        o += 2

    if not res.patched:
        res.skipped.append((None, "kein Speed-Clamp-Muster (cmp/Bcc/mov -> FRAME[+0xA]) gefunden"))
    return res
