"""WheelDiameter-Persistenz fuer R5.4.19 (IVCU).

5.4.19 hat die komplette WheelDiameter-Kette an 0x2000029D (Speed-Formel WDx287, TX-Echo,
Settings-Pack -> Mirror 0x20001A28+3, EEPROM-Boot-Load), ABER es fehlten zwei Dinge, die
R3 4.10 hat: (a) der Display-Unpack frame[8]->0x2000029D im Sync-Block, und (b) der Save-
Trigger. Beides (live verifiziert) per Cave nachgeruestet:

  Hook @0x0800F8EE (Konvergenzpunkt im Sync-Block -> flag-unabhaengig) -> Cave:
    r2 = frame[8] (neuer WD, x10) ; r3 = alter WD ; 0x2000029D = r2   (= der Unpack)
    wenn geaendert: Mirror+3 = r2 ; 0x0801700C(idx=1)  (Block 0x20001A28 in Flash speichern)
    r0 = frame[9] (Original) ; zurueck @0x0800F8F2

Cave liegt am App-Ende (wie BLE), der 8-Byte-End-Marker wird mitgefuehrt. Konflikt-frei mit
allen Byte-Features (Speed/ZeroStart/Cruise/Blinker) und mit BLE, sofern NACH BLE angewendet.
Keystone-frei (Pyodide): Fix-Bytes + berechnete Branches.
"""
from teverun_patcher.core.hex_loader import HexLoader

HOOK = 0x0800F8EE
HOOK_OLD = bytes.fromhex("8c48407a")   # ldr r0,[pc,#0x230] ; ldrb r0,[r0,#9]
RET   = 0x0800F8F2
SAVE  = 0x0801700C                      # Save-Dispatcher (r0=Block-Index; 1 = Block 0x20001A28)
FLASH_BASE = 0x08007000

# Cave-Fixbytes (keystone-verifiziert), Branches werden adressabhaengig eingesetzt:
_PREFIX = bytes.fromhex("09490a7a09490b780a709a4208d00849ca702de90c500120")  # +0x00..+0x17
_MID    = bytes.fromhex("bde80c500149487a")                                   # +0x1C..+0x23 (pop.w; ldr; ldrb)
_LITERALS = bytes.fromhex("4d130020"  # 0x2000134D (Frame-Basis)
                          "9d020020"  # 0x2000029D (WD-Var)
                          "281a0020")  # 0x20001A28 (EEPROM-Mirror)


def is_compatible(loader: HexLoader) -> bool:
    try:
        return bytes(loader.read_byte(HOOK + i) for i in range(4)) == HOOK_OLD
    except Exception:
        return False


def _enc_branch(pc: int, target: int, link: bool) -> bytes:
    """Thumb-2 B.W (link=False) / BL (link=True), 4 Bytes."""
    imm = target - (pc + 4)
    s = (imm >> 24) & 1
    i1 = (imm >> 23) & 1
    i2 = (imm >> 22) & 1
    imm10 = (imm >> 12) & 0x3FF
    imm11 = (imm >> 1) & 0x7FF
    j1 = 1 - (i1 ^ s)
    j2 = 1 - (i2 ^ s)
    hw1 = 0xF000 | (s << 10) | imm10
    hw2 = (0xD000 if link else 0x9000) | (j1 << 13) | (j2 << 11) | imm11
    return hw1.to_bytes(2, "little") + hw2.to_bytes(2, "little")


def _build_cave(cave: int) -> bytes:
    assert cave % 4 == 0
    b = _PREFIX                                   # +0x00
    b += _enc_branch(cave + 0x18, SAVE, True)     # +0x18 bl 0x0801700C
    b += _MID                                     # +0x1C
    b += _enc_branch(cave + 0x24, RET, False)     # +0x24 b.w 0x0800F8F2
    b += _LITERALS                                # +0x28
    assert len(b) == 0x34, len(b)
    return b


def apply(loader: HexLoader) -> dict:
    cur = bytes(loader.read_byte(HOOK + i) for i in range(4))
    if cur != HOOK_OLD:
        raise RuntimeError(
            "WheelDiameter-Persistenz nur fuer R5.4.19 verfuegbar (Hook @0x%08X = %s)." % (HOOK, cur.hex()))

    # End-Marker (letzte 8 Bytes) sichern und ans neue Ende mitfuehren (wie BLE).
    pre_max = loader.ih.maxaddr()
    footer = bytes(loader.read_byte(pre_max - 7 + i) for i in range(8))

    app_end = pre_max + 1
    cave = (app_end + 3) & ~3
    for a in range(app_end, cave):                # evtl. Alignment-Luecke fuellen
        loader.write_byte(a, 0xFF)
    for i, by in enumerate(_build_cave(cave)):
        loader.write_byte(cave + i, by)

    for i, by in enumerate(_enc_branch(HOOK, cave, False)):
        loader.write_byte(HOOK + i, by)

    tail = loader.ih.maxaddr() + 1
    pad = (4 - (tail + 8 - FLASH_BASE) % 4) % 4
    for i in range(pad):
        loader.write_byte(tail + i, 0xFF)
    footer_addr = tail + pad
    for i, by in enumerate(footer):
        loader.write_byte(footer_addr + i, by)

    return {"cave_addr": cave, "cave_size": 0x34, "hook_addr": HOOK, "footer_addr": footer_addr}
