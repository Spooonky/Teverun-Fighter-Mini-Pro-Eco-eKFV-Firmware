"""BLE-Name-Variant Patch (Non-Lockup mit Initial-Delay).

Beim Boot wartet der Patch zuerst ~420ms (Initial-Delay damit das BLE-Modul nach
Power-On seine +READY-Phase abschließt), sendet dann `AT+LENAME=<NEUER_NAME>\\r\\n`
gefolgt von `AT+LENAME?\\r\\n` als Verify, und ruft danach den normalen Main-Loop
auf (`bl 0x0801C278`).

Beim Power-On (kalter Boot, BLE-Modul auch im AT-Mode) wird der Name akzeptiert
und persistiert im Modul-Flash. Beim Warm-Boot nach OTA-Flash ist das BLE-Modul
noch im transparent-mode mit der OTA-App connected → AT+LENAME wird durchgereicht
statt verarbeitet. User muss dann 1× Power-Cycle.

Layout (ab 0x0801D988):
  Prelude (24): push, flag check, regs setup, initial poll
  Cmds (14 × N): ldr r0, movs r1, bl UART_SEND, poll
  Final (6): final poll
  Main-Loop-Call (4): bl ORIG_TARGET — IVCU normal weiterboot
  Pop (2): pop {r4-r7, pc}
  Poll-Loop (22): subr — pollt USART1 STS/DAT, sammelt RX-Bytes
  Pool: flag_addr, usart_base, rx_buf, 3× poll_counts, str_addrs[N]
  Strings: ATs
"""
import re

from teverun_patcher.core.hex_loader import HexLoader

# Hook und Patch-Adressen für D5 4.14.11
HOOK_ADDR   = 0x0800B87E
PATCH_ADDR  = 0x0801D988   # 116-Byte-Gap nach Original-App-Ende (0x0801D913)
ORIG_TARGET = 0x0801C278   # main-loop work, unused in lockup variant
UART_SEND   = 0x080199B6   # USART1 sender (r0=buf, r1=len)
APP_END     = 0x0801D913   # Original-App-Ende (letztes Byte der Original-FW)

# RAM-Adressen
FLAG_ADDR   = 0x20003500   # 1-Byte Flag "Patch lief schon"
RX_BUF      = 0x20002800   # 60-Byte RX-Sammler vom Modul
USART1_BASE = 0x40013800   # STS @ +0, DAT @ +4

# Poll-Counts
INITIAL_POLL = 0x00800000   # ~420ms — Modul-Boot abwarten
CMD_POLL     = 0x00200000   # ~105ms — zwischen Cmds
FINAL_POLL   = 0x00400000   # ~210ms — vor lockup


# ZWINGEND FÜR CLI.PY: Das originale Dictionary erweitern
VARIANTS = {
    "TDE":    ("TDE",    "eKFV (Deutschland - Strikt 20 km/h)"),
    "TDEINT": ("TDEINT", "TDEINT (Deutschland International)"),
    # T2 ENTFERNT: das Patchen der T2-BLE-Adresse macht den OTA-Flash dauerhaft
    # unmoeglich (Semi-Brick der IVCU). Niemals wieder aufnehmen.
    "T1":     ("T1",     "Standard International (Basis)"),
    "T1IL":   ("T1IL",   "Israel-Spezifisch"),
    "TAT":    ("TAT",    "Oesterreich / Alpenraum-Profil")
}

# Modell-Zuordnungstabelle basierend auf den App-Extraktionstexten
MODEL_REGISTRY = {
    # Schema A (T2 Global) -> Benötigt 2-Stelligen Code
    "A": {
        "FM": "FIGHTER MINI",
        "FP": "FIGHTER MINI PRO",
        "FE": "FIGHTER ELEVEN",
        "FU": "FIGHTER ELEVEN+",
        "SU": "SUPREME ULTRA",
        "SR": "SUPREME 7260",
        "T4": "TETRA 4 MOTOR",
        "T2": "TETRA 2 MOTOR"
    },
    # Schema B (Standard-Kennungen) -> 3-Stellige Codes
    "B": {
        "GTE": "TEVERUN GT", "GTP": "TEVERUN GT",
        "T40": "TETRA 4 MOTOR",
        "T20": "TETRA 2 MOTOR",
        "FTE": "FIGHTER TEN",
        "FEE": "FIGHTER ELEVEN", "FEP": "FIGHTER ELEVEN",
        "SPP": "SUPREME PLUS",
        "SPU": "SUPREME ULTRA",
        "SPR": "SUPREME 7260R",
        "BME": "BLADE MINI", "BMP": "BLADE MINI", "BMU": "BLADE MINI",
        "FME": "FIGHTER MINI", "FMO": "FIGHTER MINI", "FMP": "FIGHTER MINI", "FMA": "FIGHTER MINI EKFV",
        "BQE": "BLADE Q", "BQP": "BLADE Q",
        "FQ":  "FIGHTER Q",
        "SE":  "TEVERUN SPACE"
    }
}

# Ziel-Kürzel, die das native deutsche FIN-Layout behalten (Modell-Code an
# Original-Position, FIN wie auf dem Aufkleber). Alle anderen Kürzel werden auf
# das internationale App-Generic-Layout umgebaut (Modell-Code an App-Parser-Index).
DE_LAYOUT_PREFIXES = {"TDE", "TDEINT", "TAT"}

# Länge des BLE-Namensfelds (mit Spaces gepaddet) — verifiziert lauffähig.
NAME_FIELD_LEN = 19

# Sentinel-Variante: kompletter Name wird verbatim geschrieben (Voll-Custom).
RAW_VARIANT = "__RAW__"

# Deutsche FIN-Struktur: TDE1FMA25E0458
#   country = führender Buchstaben-Lauf (TDE / TDEINT / TAT ...)
#   gen     = 1 Ziffer (Generation / Versionierung des Scooters)
#   model   = 3 Zeichen (Basis 2 Zeichen + Varianten-Zeichen, z.B. FM + A)
#   year    = 2 Ziffern (Modelljahr, 25 -> 2025)
#   gps     = 1 Buchstabe (E = GPS verbaut, A = kein GPS)
#   counter = restliche Ziffern (fortlaufender Zähler)
FIN_RE = re.compile(r"^([A-Z]+)(\d)([A-Z]{2}[A-Z0-9])(\d{2})([A-Z])(\d+)$")


def _resolve_model_name(model: str) -> str:
    """Modellname aus dem 3-stelligen Modell-Code ableiten.

    Reihenfolge: exakter 3-Zeichen-Treffer (Schema B, z.B. SPP/SPU/BME) →
    Basis-2-Zeichen (Schema A, z.B. FM → Fighter Mini) → Unbekannt.
    """
    model = (model or "").upper()
    if model in MODEL_REGISTRY["B"]:
        return MODEL_REGISTRY["B"][model]
    base2 = model[:2]
    if base2 in MODEL_REGISTRY["A"]:
        return MODEL_REGISTRY["A"][base2]
    for pattern, name in MODEL_REGISTRY["B"].items():
        if model.startswith(pattern):
            return name
    return "Unbekanntes Modell"


def _scan_model_code(fin: str) -> str:
    """Best-effort Modell-Code-Suche, wenn die FIN nicht dem DE-Schema folgt."""
    area = fin[:12]
    for pattern in MODEL_REGISTRY["B"]:
        if pattern in area:
            return (pattern + "X")[:3]
    for pattern in MODEL_REGISTRY["A"]:
        if pattern in area or (fin.startswith("T2") and pattern == fin[7:9]):
            return (pattern + "X")[:3]
    return "FMA"  # Default: Fighter Mini eKFV


def parse_fin(fin: str) -> dict:
    """Zerlegt eine FIN/Seriennummer in ihre Felder.

    Greift die deutsche Struktur (FIN_RE), sonst Best-effort-Fallback.
    Rückgabe enthält immer: country, gen, model (3-stellig), year, gps,
    counter, model_name, code_a (2-stellig), code_b (3-stellig), scheme.
    """
    fin = (fin or "").strip().upper()
    m = FIN_RE.match(fin)
    if m:
        country, gen, model, year, gps, counter = m.groups()
        parsed = {
            "raw": fin, "scheme": "DE",
            "country": country, "gen": gen, "model": model,
            "year": year, "gps": gps, "counter": counter,
        }
    else:
        # Fallback: führender Buchstaben-Lauf = country, erste Ziffer = gen,
        # Modell-Code per Registry-Scan, restliche Ziffern als Zähler.
        mc = re.match(r"^([A-Z]+)", fin)
        country = mc.group(1) if mc else (fin[:3] or "TDE")
        rest = fin[len(country):]
        gen = rest[0] if rest[:1].isdigit() else "1"
        digits = "".join(c for c in fin if c.isdigit())
        parsed = {
            "raw": fin, "scheme": "FALLBACK",
            "country": country, "gen": gen,
            "model": _scan_model_code(fin),
            "year": digits[:2] if len(digits) >= 2 else "25",
            "gps": "E",
            "counter": digits[-4:] if len(digits) >= 4 else digits.ljust(4, "0"),
        }

    parsed["model_name"] = _resolve_model_name(parsed["model"])
    parsed["code_a"] = parsed["model"][:2]
    parsed["code_b"] = parsed["model"][:3]
    return parsed


def detect_scooter_model(vin: str) -> tuple[str, str, str]:
    """Backward-Compat-Wrapper: (model_name, code_a, code_b)."""
    p = parse_fin(vin)
    return p["model_name"], p["code_a"], p["code_b"]


def rebuild_ble_name(parsed: dict, target_prefix: str) -> str:
    """Baut den BLE-Namen aus den FIN-Feldern für das Ziel-Länderkürzel.

    - DE-Layout (TDE/TDEINT/TAT): country + gen + model + year + gps + counter
      (nur Land getauscht, alle Felder nativ erhalten).
    - International (T2/T1/T1IL): Modell-Code an App-Parser-Index platzieren
      (T2 → Index 7-8, 2-stellig; sonst → Index 6-8, 3-stellig). Die übrigen
      Felder (gen+year+gps+counter) füllen davor/danach auf.
    """
    target_prefix = (target_prefix or "").strip().upper()
    gen     = parsed.get("gen") or "1"
    model   = (parsed.get("model") or "FMA").upper()
    year    = parsed.get("year") or ""
    gps     = parsed.get("gps") or ""
    counter = parsed.get("counter") or ""

    if target_prefix in DE_LAYOUT_PREFIXES:
        visible = f"{target_prefix}{gen}{model}{year}{gps}{counter}"
    else:
        if target_prefix.startswith("T2"):
            model_code, model_start = model[:2], 7
        else:
            model_code, model_start = model[:3], 6
        payload = f"{gen}{year}{gps}{counter}"
        fill_len = max(0, model_start - len(target_prefix))
        fill = payload[:fill_len].ljust(fill_len, "0")
        rest = payload[fill_len:]
        visible = f"{target_prefix}{fill}{model_code}{rest}"

    return visible[:NAME_FIELD_LEN]


def prompt_user_configuration() -> tuple[str, str]:
    """Fallback-CLI, wird aber normalerweise durch die cli.py gesteuert."""
    print("\n=== Teverun BLE-Name Patcher Konfiguration ===")

    while True:
        vin_input = input("Bitte geben Sie die FIN / Seriennummer Ihres Scooters ein: ").strip()
        if len(vin_input) < 8:
            print("Fehler: Die FIN ist zu kurz.")
            continue
        break

    p = parse_fin(vin_input)
    print(f"\n-> Erkanntes Fahrzeugmodell: {p['model_name']}")
    print(f"   Modell-Code {p['model']}  |  Generation {p['gen']}  |  Bj. 20{p['year']}"
          f"  |  GPS: {'ja' if p['gps'] == 'E' else 'nein'}")

    available_options = list(VARIANTS.keys())
    for idx, prefix in enumerate(available_options, 1):
        print(f"  [{idx}] {prefix} -> {VARIANTS[prefix][1]}")

    while True:
        try:
            choice = int(input(f"\nWählen Sie die gewünschte Ziel-Kennung (1-{len(available_options)}): "))
            if 1 <= choice <= len(available_options):
                selected_prefix = available_options[choice - 1]
                break
        except ValueError:
            pass
        print("Ungültige Auswahl.")

    return selected_prefix, vin_input


def _build_name_field(variant: str, serial: str) -> bytes:
    """Generiert das exakte NAME_FIELD_LEN-Byte lange Namensfeld.

    Sonderfall RAW_VARIANT: ``serial`` wird komplett verbatim geschrieben
    (nur auf NAME_FIELD_LEN getrimmt) — keine Zerlegung, kein Rebuild.
    """
    if variant == RAW_VARIANT:
        visible = (serial or "")[:NAME_FIELD_LEN]
    else:
        prefix = VARIANTS.get(variant.strip().upper(), (variant, ""))[0]
        parsed = parse_fin(serial)
        visible = rebuild_ble_name(parsed, prefix)

    # Sicherheits-Guard: ein BLE-Name mit 'T2'-Praefix (die T2-Adresse) macht den
    # OTA-Flash der IVCU dauerhaft unmoeglich (Semi-Brick). Hart blockieren.
    if visible.upper().startswith("T2"):
        raise ValueError(
            "BLE-Praefix 'T2' ist deaktiviert: das Patchen der T2-Adresse macht "
            "den OTA-Flash der IVCU dauerhaft unmoeglich (Semi-Brick)."
        )

    padding = NAME_FIELD_LEN - len(visible)
    name_field = visible.encode("ascii", "replace") + b" " * padding

    assert len(name_field) == NAME_FIELD_LEN
    return name_field


def compute_target_name(variant: str, serial: str) -> str:
    """Der exakte BLE-Name, der ins Modul geschrieben wird (ohne Padding).

    Identisch zu dem, was apply() als ``target_name`` zurückgibt — Single Source
    of Truth für Vorschau (Wizard) und tatsächlichen Patch.
    """
    return _build_name_field(variant, serial).rstrip(b" ").decode("ascii")


def _encode_bl(instr_addr: int, target: int) -> bytes:
    offset = target - (instr_addr + 4)
    off = offset & 0x01FFFFFF
    s = (off >> 24) & 1
    i1 = (off >> 23) & 1
    i2 = (off >> 22) & 1
    i10 = (off >> 12) & 0x3FF
    i11 = (off >> 1) & 0x7FF
    j1 = (i1 ^ 1) ^ s
    j2 = (i2 ^ 1) ^ s
    hw1 = 0xF000 | (s << 10) | i10
    hw2 = 0xD000 | (j1 << 13) | (j2 << 11) | i11
    return hw1.to_bytes(2, "little") + hw2.to_bytes(2, "little")


def _ldr_pc(rt: int, instr_addr: int, target: int) -> bytes:
    pc = (instr_addr + 4) & ~3
    offset = target - pc
    assert 0 <= offset <= 1020 and offset % 4 == 0, f"ldr range bad: 0x{offset:x}"
    return (0x4800 | (rt << 8) | (offset // 4)).to_bytes(2, "little")


def _ble_cfg(cfg: dict = None) -> dict:
    """Versionsabhaengige BLE-Adressen. Default = 5.4.14 (Modul-Konstanten);
    ein Profil kann sie via 'ble'-Block ueberschreiben (Hex-Strings oder int)."""
    d = {"hook_addr": HOOK_ADDR, "orig_target": ORIG_TARGET, "uart_send": UART_SEND,
         "patch_addr": PATCH_ADDR, "app_end": APP_END,
         "flag_addr": FLAG_ADDR, "rx_buf": RX_BUF}
    if cfg:
        for k in d:
            v = cfg.get(k)
            if v is not None:
                d[k] = int(v, 16) if isinstance(v, str) else int(v)
    return d


def _build_patch_bytes(variant: str, serial: str, cfg: dict = None) -> tuple[bytes, list[bytes]]:
    C = _ble_cfg(cfg)
    PATCH_ADDR = C["patch_addr"]; ORIG_TARGET = C["orig_target"]
    UART_SEND = C["uart_send"]; FLAG_ADDR = C["flag_addr"]; RX_BUF = C["rx_buf"]
    name_field = _build_name_field(variant, serial)
    cmd_set    = b"AT+LENAME=" + name_field + b"\r\n"   
    cmd_verify = b"AT+LENAME?\r\n"                       
    COMMANDS = [cmd_set, cmd_verify]

    prelude_size = 24
    cmd_size = 14
    final_size = 6
    mainloop_size = 6   
    poll_loop_size = 22

    code_base = prelude_size + cmd_size * len(COMMANDS) + final_size + mainloop_size + poll_loop_size
    pool_pad = (4 - (code_base % 4)) % 4
    code_size = code_base + pool_pad

    pool_start = PATCH_ADDR + code_size
    pool_size = 4 * (6 + len(COMMANDS))
    str_section = pool_start + pool_size

    str_addrs = []
    cur = str_section
    for cmd in COMMANDS:
        str_addrs.append(cur)
        cur += len(cmd)

    flag_lit  = pool_start + 0
    usart_lit = pool_start + 4
    rxbuf_lit = pool_start + 8
    init_lit  = pool_start + 12
    cmd_lit   = pool_start + 16
    final_lit = pool_start + 20
    str_lits  = pool_start + 24

    mainloop_addr = PATCH_ADDR + prelude_size + cmd_size * len(COMMANDS) + final_size
    poll_loop_addr = mainloop_addr + mainloop_size

    code = bytearray()
    a = PATCH_ADDR

    # ---- Prelude ----
    code += b"\xF0\xB5"; a += 2
    code += _ldr_pc(4, a, flag_lit); a += 2
    code += b"\x20\x78"; a += 2
    cbnz_off = mainloop_addr - (a + 4)
    cbnz_imm = cbnz_off >> 1
    code += (0xB900 | (((cbnz_imm >> 5) & 1) << 9) | ((cbnz_imm & 0x1F) << 3) | 0).to_bytes(2, "little"); a += 2
    code += b"\x01\x20"; a += 2
    code += b"\x20\x70"; a += 2
    code += _ldr_pc(2, a, usart_lit); a += 2
    code += _ldr_pc(5, a, rxbuf_lit); a += 2
    code += b"\x00\x26"; a += 2
    code += _ldr_pc(7, a, init_lit); a += 2
    code += _encode_bl(a, poll_loop_addr); a += 4

    assert a == PATCH_ADDR + prelude_size

    # ---- Cmds ----
    for i, cmd in enumerate(COMMANDS):
        code += _ldr_pc(0, a, str_lits + 4*i); a += 2
        code += bytes([len(cmd), 0x21]); a += 2
        code += _encode_bl(a, UART_SEND); a += 4
        code += _ldr_pc(7, a, cmd_lit); a += 2
        code += _encode_bl(a, poll_loop_addr); a += 4

    # ---- Final delay ----
    code += _ldr_pc(7, a, final_lit); a += 2
    code += _encode_bl(a, poll_loop_addr); a += 4

    # ---- Main-Loop-Call ----
    assert a == mainloop_addr
    code += _encode_bl(a, ORIG_TARGET); a += 4
    code += b"\xF0\xBD"; a += 2

    # ---- Poll-Loop subroutine ----
    assert a == poll_loop_addr
    poll_start = a
    code += b"\x13\x88"; a += 2
    code += b"\x9B\x06"; a += 2
    skip_label = poll_start + 16
    bpl_off = skip_label - (a + 4)
    code += (0xD500 | ((bpl_off // 2) & 0xFF)).to_bytes(2, "little"); a += 2
    code += b"\x13\x79"; a += 2
    code += b"\xF0\x2E"; a += 2
    bhs_off = skip_label - (a + 4)
    code += (0xD200 | ((bhs_off // 2) & 0xFF)).to_bytes(2, "little"); a += 2
    code += b"\xAB\x55"; a += 2
    code += b"\x01\x36"; a += 2
    code += b"\x01\x3F"; a += 2
    bne_off = poll_start - (a + 4)
    code += (0xD100 | ((bne_off // 2) & 0xFF)).to_bytes(2, "little"); a += 2
    code += b"\x70\x47"; a += 2

    code += b"\x00" * pool_pad
    a += pool_pad

    pool = bytearray()
    pool += FLAG_ADDR.to_bytes(4, "little")
    pool += USART1_BASE.to_bytes(4, "little")
    pool += RX_BUF.to_bytes(4, "little")
    pool += INITIAL_POLL.to_bytes(4, "little")
    pool += CMD_POLL.to_bytes(4, "little")
    pool += FINAL_POLL.to_bytes(4, "little")
    for sa in str_addrs:
        pool += sa.to_bytes(4, "little")

    strings = b"".join(COMMANDS)
    full = bytes(code) + bytes(pool) + strings
    return full, COMMANDS


def apply(loader: HexLoader, variant: str = None, serial: str = None, cfg: dict = None) -> dict:
    C = _ble_cfg(cfg)
    APP_END = C["app_end"]; PATCH_ADDR = C["patch_addr"]; HOOK_ADDR = C["hook_addr"]
    if variant is None or serial is None:
        variant, serial = prompt_user_configuration()

    if serial == "INTERACTIVE_PROMPT" or not serial:
        variant, serial = prompt_user_configuration()

    name_field = _build_name_field(variant, serial)
    target_name = name_field.rstrip(b" ").decode("ascii")

    patch_bytes, _ = _build_patch_bytes(variant, serial, cfg)

    pre_max = loader.ih.maxaddr()
    footer_bytes = bytes(loader.read_byte(pre_max - 7 + i) for i in range(8))

    gap_start = APP_END + 1            
    gap_end   = PATCH_ADDR             
    for addr in range(gap_start, gap_end):
        loader.write_byte(addr, 0xFF)

    for i, b in enumerate(patch_bytes):
        loader.write_byte(PATCH_ADDR + i, b)

    hook_bytes = _encode_bl(HOOK_ADDR, PATCH_ADDR)
    for i, b in enumerate(hook_bytes):
        loader.write_byte(HOOK_ADDR + i, b)

    tail_addr = loader.ih.maxaddr() + 1
    align_pad = (4 - (tail_addr + 8 - 0x08007000) % 4) % 4
    for i in range(align_pad):
        loader.write_byte(tail_addr + i, 0xFF)
    footer_addr = tail_addr + align_pad
    for i, b in enumerate(footer_bytes):
        loader.write_byte(footer_addr + i, b)

    print(f"\nPatch erfolgreich angewendet! Ziel-Name im BLE-Modul: '{target_name}'")

    return {
        "variant": variant,
        "serial": serial,
        "target_name": target_name,
        "patch_addr": PATCH_ADDR,
        "patch_size": len(patch_bytes),
        "hook_addr": HOOK_ADDR,
        "gap_start": gap_start,
        "gap_end": gap_end,
        "gap_size": gap_end - gap_start,
        "align_padding": align_pad,
        "footer_bytes": footer_bytes.hex(),
        "footer_addr": footer_addr,
        "lockup": False,
    }
