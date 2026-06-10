"""Settings-Persistenz-Patch fuer IVCU R5.4.19 (ALI-Port).

Ruestet EEPROM-Persistenz fuer Zusatz-Settings nach (C6/C7/C8 per-Gang, AutoCruise,
Kickstart), die 5.4.19 zwar empfaengt aber nicht speichert. Architektur: Code-Cave
(Thumb-2) @ 0x0801DB00 + 3 Hooks (per-Gang-Config-Empfang, AutoCruise-Command, Boot-Load).

Die Cave-/Hook-Bytes sind VORASSEMBLIERT (Keystone, siehe tools/gen_persist_cave.py),
damit dieses Modul OHNE Assembler laeuft — wichtig fuer den Pyodide-WebPatcher.

NUR fuer R5.4.19 (Adressen versionsspezifisch). Erst Bench-/Fahrtest, dann verlassen.
"""

BASE_ADDR = 0x08007000

CAVE_ADDR = 0x0801DB00
CAVE_HEX = (
    "00b582b06b4640f2c621c2f200010878187040f2c721c2f200010878587040f2c821c2f2"
    "00010878987040f29931c2f200010878d87040f29d21c2f20001087818716846052146f6"
    "df72c0f6010290476b465871000a9871b02007216a4646f6c173c0f60103984702b000bd"
    "fff7c8ff38bc5df814fb00b54cf25133c0f600039847fff7bdff00bd00b5002040f2c621"
    "c2f20001087040f2c721c2f20001087040f2c821c2f200010870ff2040f29031c2f20001"
    "087082b0b0206946072248f69573c0f6010398476846052146f6df72c0f6010290476b46"
    "59799a791202114388421ed16b46187840f2c621c2f200010870587840f2c721c2f20001"
    "0870987840f2c821c2f200010870d87840f29931c2f200010870187940f29d21c2f20001"
    "087002b000bd"
)

# (Adresse, neue Bytes hex) — die 3 Hooks
HOOKS = [
    (0x0800D15C, "10f006fd00bf"),                          # per-Gang-Config -> bl hook1 + nop
    (0x0800C52C, "11f023fb"),                              # AutoCruise-Command -> bl ac_trampoline
    (0x0800EDF2, "0ef0c9fe00bf00bf00bf00bf00bf00bf00bf00bf"),  # Boot-Default-Init -> bl cave_boot + nops
]

# (Adresse, erwartete Original-Bytes hex) — Sicherheits-Check vor dem Patchen
EXPECT = [
    (0x0800D15C, "38bc5df814fb"),   # pop{r3,r4,r5}; ldr pc,[sp],#0x14
    (0x0800C52C, "fff710ff"),       # bl 0x0800C350
    (0x0800EDF2, "0020"),           # movs r0,#0 (Default-Init-Start)
]


def is_compatible(loader) -> bool:
    """True, wenn die Firmware die erwarteten Original-Bytes an allen Hook-Punkten hat (= R5.4.19)."""
    try:
        for addr, exp in EXPECT:
            b = bytes.fromhex(exp)
            for i, want in enumerate(b):
                if loader.read_byte(addr + i) != want:
                    return False
        return True
    except Exception:
        return False


def apply(loader) -> dict:
    """Schreibt Cave + Hooks in den geladenen HexLoader (in-place).

    Rueckgabe: {'cave_addr', 'cave_len', 'hooks'} oder wirft ValueError bei Inkompatibilitaet.
    """
    if not is_compatible(loader):
        raise ValueError("Settings-Persistenz nur fuer R5.4.19 (Original-Bytes passen nicht).")

    cave = bytes.fromhex(CAVE_HEX)

    # Luecke zwischen App-Ende und Cave mit 0xFF fuellen (zusammenhaengendes Image)
    app_end = loader.ih.maxaddr()
    for a in range(app_end + 1, CAVE_ADDR):
        loader.write_byte(a, 0xFF)

    # Cave schreiben
    for i, b in enumerate(cave):
        loader.write_byte(CAVE_ADDR + i, b)

    # Hooks schreiben
    for addr, hx in HOOKS:
        for i, b in enumerate(bytes.fromhex(hx)):
            loader.write_byte(addr + i, b)

    return {"cave_addr": CAVE_ADDR, "cave_len": len(cave), "hooks": len(HOOKS)}
