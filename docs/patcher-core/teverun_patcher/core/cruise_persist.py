"""CruiseMode-Persistenz fuer IVCU R5.4.19 (getestet, power-cycle-fest).

5.4.19 empfaengt CruiseMode im Display-Sync-Paket (0x2000134D+5), kopiert ihn aber
nicht nach 0x2000029B. Dieser Patch ergaenzt die fehlende Bruecke (Cave 0x0801DD00 +
2 Hooks), mit Sync-Guard gegen den Boot-Moment. Adressen konfliktfrei zu
settings_persist; vorassembliert (tools/build_cruise_bridge_wp.py). Nur R5.4.19.
"""

BASE_ADDR = 0x08007000

CAVE_ADDR = 0x0801DD00
CAVE_HEX = "0fb442f20140c2f20000017889b941f24d32c2f20002527902f0020240f29b23c2f200031b7803f002039a4211d10121017041f24d30c2f20000427902f0020240f29b21c2f200010b7823f0020313430b700fbc41f24d30c2f20000c078f1f740bc232040f2dc21c2f200010870002042f20141c2f2000108707047"

HOOKS = [
    (0x0800F5DE, "0ef08fbb"),        # sync-Verarbeitung -> sync_cave
    (0x0800EDDA, "0ef0c2ff00bf"),    # Default-Init -> boot_cave + nop
]

EXPECT = [
    (0x0800F5DE, "4d48c078"),
    (0x0800EDDA, "2320f0490870"),
]


def is_compatible(loader) -> bool:
    try:
        for addr, exp in EXPECT:
            for i, want in enumerate(bytes.fromhex(exp)):
                if loader.read_byte(addr + i) != want:
                    return False
        return True
    except Exception:
        return False


def apply(loader) -> dict:
    if not is_compatible(loader):
        raise ValueError("CruiseMode-Speicherung nur fuer R5.4.19 (Original-Bytes passen nicht).")

    cave = bytes.fromhex(CAVE_HEX)
    app_end = loader.ih.maxaddr()
    for a in range(app_end + 1, CAVE_ADDR):
        loader.write_byte(a, 0xFF)
    for i, b in enumerate(cave):
        loader.write_byte(CAVE_ADDR + i, b)
    for addr, hx in HOOKS:
        for i, b in enumerate(bytes.fromhex(hx)):
            loader.write_byte(addr + i, b)

    return {"cave_addr": CAVE_ADDR, "cave_len": len(cave), "hooks": len(HOOKS)}
