"""R5.4.19 Feature-Kombinationen: Speed / ZeroStart / Cruise / Blinker.

Die drei Fahr-Features teilen sich denselben Controller-Frame-Builder-Bytebereich
(0x08010052/54/58 in 4 Buildern), daher haengt das Byte-Ergebnis von der KOMBINATION
ab -- kein flaches Gruppen-Stapeln moeglich. Alles live am Roller verifiziert
(DAP-Link, 2026-06-12):

  - Der Motor-Controller honoriert Cruise NUR bei Frame+0xF Bit5=0 (= ZeroStart-Freigabe).
  - Bit5=0 braucht eine konsistente Speed-Behandlung (Clamp weg ODER halbiert), sonst Limp.
  - Cruise selbst braucht Flag=0 (Sync-Block 0x0800F8B0 laeuft sauber), sonst bricht die
    Motor-Auswahl. -> Cruise-Combos = Flag=0 (wie build_zerostart_full);
    Nicht-Cruise-Combos = Flag locked + Direct-Force (Bit5-bic, Clamp-NOP/Half).

Speed-Modi:
  - speed_remove=True  -> Clamp 'movs r7,#0x16' NOPen  -> voller Speed (Display GearLimitSpeed)
  - sonst (Z/C aktiv)  -> Clamp -> 'lsrs r7,#1' (Half)  -> ~22 km/h, GearLimitSpeed 1-100% = 0-22

Mapping auf die verifizierten Einzel-Builds:
  speed_remove                 -> Clamp-NOP            (Speed-Gruppe)
  zerostart (capped)           -> bic + Half           (build_zs_half,  CRC 0x2206)
  zerostart + speed_remove     -> bic + Clamp-NOP      (build_zs_v2)
  cruise + speed_remove        -> Flag=0               (build_zerostart_full, CRC 0x9C25)
  cruise (capped)              -> Flag=0 + cbz-nop + bic + Half  (build_cruise_capped, CRC 0x9B1B)
"""

# Pro Builder: (cbz, bit5_orr, clamp_region, movs)
_BUILDERS = [
    (0x08010052, 0x08010054, 0x08010058, 0x0801005C),
    (0x08010202, 0x08010204, 0x08010208, 0x0801020C),
    (0x080103AA, 0x080103AC, 0x080103B0, 0x080103B4),
    (0x080105CA, 0x080105CC, 0x080105D0, 0x080105D4),
]
# Flag 0x2000030C dauerhaft 0 (TDE-Gate ueberspringen + Bit2-Zweig schreibt 0)
_FLAG = [
    (0x0800F99C, b"\x72\x48", b"\x0e\xe0"),
    (0x0800F9C8, b"\x01\x20", b"\x00\x20"),
]
_CBZ_OLD, _CBZ_NOP = b"\x28\xb1", b"\x00\xbf"            # cbz r0,#.. -> nop
_BIT5_OLD, _BIT5_NEW = b"\x46", b"\x26"                  # orr r6,#0x20 -> bic r6,#0x20 (low byte)
_CLAMP_OLD = bytes.fromhex("162f03dd1627")              # cmp r7,#0x16; ble; movs r7,#0x16
_CLAMP_HALF = bytes.fromhex("7f0800bf00bf")             # lsrs r7,#1; nop; nop
_MOVS_OLD, _MOVS_NOP = b"\x16\x27", b"\x00\xbf"         # movs r7,#0x16 -> nop
_BLINKER = (0x08019610, bytes.fromhex("fff790ff"), bytes.fromhex("00bf00bf"))


def _wr(loader, addr, old, new, applied):
    cur = bytes(loader.read_byte(addr + i) for i in range(len(old)))
    if cur != old:
        raise RuntimeError(
            "R5.4.19 @0x%08X: erwartet %s, gefunden %s (falsche Quelle/schon gepatcht?)"
            % (addr, old.hex(), cur.hex()))
    for i, b in enumerate(new):
        loader.write_byte(addr + i, b)
    applied.append(addr)


def apply_features(loader, speed_remove=False, zerostart=False, cruise=False, blinker=False):
    """Wendet die gewaehlte Feature-Kombination an. Gibt die Liste gepatchter Adressen zurueck.

    Hinweis: Cruise zieht zwingend die ZeroStart-FREIGABE (Bit5=0) mit -- das *Verhalten*
    bleibt aber per Display steuerbar. Cruise ohne diese Freigabe ist hardwareseitig
    (Motor-Controller) nicht moeglich.
    """
    applied = []

    if cruise:
        for addr, old, new in _FLAG:                    # Flag=0 -> Sync sauber, Motor intakt
            _wr(loader, addr, old, new, applied)
        if not speed_remove:                            # Capped: Builder muss bic+half ausfuehren
            for cbz, bit5, clamp, _movs in _BUILDERS:
                _wr(loader, cbz, _CBZ_OLD, _CBZ_NOP, applied)
                _wr(loader, bit5, _BIT5_OLD, _BIT5_NEW, applied)
                _wr(loader, clamp, _CLAMP_OLD, _CLAMP_HALF, applied)
        # speed_remove + cruise: Flag=0 ueberspringt den Clamp -> voller Speed, Bit5=0 natuerlich
    else:
        if zerostart:
            for cbz, bit5, clamp, movs in _BUILDERS:
                _wr(loader, bit5, _BIT5_OLD, _BIT5_NEW, applied)
                if speed_remove:
                    _wr(loader, movs, _MOVS_OLD, _MOVS_NOP, applied)
                else:
                    _wr(loader, clamp, _CLAMP_OLD, _CLAMP_HALF, applied)
        elif speed_remove:
            for _cbz, _bit5, _clamp, movs in _BUILDERS:
                _wr(loader, movs, _MOVS_OLD, _MOVS_NOP, applied)

    if blinker:
        addr, old, new = _BLINKER
        _wr(loader, addr, old, new, applied)

    return applied
