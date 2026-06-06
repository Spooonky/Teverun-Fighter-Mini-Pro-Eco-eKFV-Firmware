"""Wandelt einen rohen Chip-Dump (mit Bootloader) in eine flashbare Intel-HEX
im Teverun-OTA-Format um.

Vorgehen:
  1. Bootloader (0x08000000..0x08006FFF) abschneiden -> App ab 0x08007000.
  2. Trailing-0xFF-Padding der App entfernen (App endet am letzten Content-Byte,
     ein evtl. isolierter Sektor-Marker hinter einer grossen FF-Luecke wird NICHT
     mit aufgenommen -- er ist nicht Teil des OTA-Payloads).
  3. Intel-HEX bauen: Extended-Linear-Address 0x0800, Daten-Records,
     Start-Linear-Address-Record, EOF, dann proprietaerer :07AAA555-Record
     mit CRC16-Modbus ueber die App-Bytes.

Das Ergebnis hat exakt das Format das die offizielle Teverun-OTA-App und der
IVCU-Bootloader erwarten (identisch zu den bekannten D5-HEX-Dateien).
"""
from __future__ import annotations
import os

APP_BASE = 0x08007000
BOOTLOADER_SIZE = 0x7000
GAP_THRESHOLD = 0x400
DEFAULT_START_ADDR = 0x08007149


def _crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def _prop_record(crc: int) -> str:
    rb = bytes([0x07, 0xAA, 0xA5, 0x55, 0x00, 0x00, 0x05, 0x04, 0x0E,
                (crc >> 8) & 0xFF, crc & 0xFF])
    chk = sum(rb) % 256
    return f":{rb.hex().upper()}{chk:02X}"


def _ihex_record(rtype: int, addr16: int, data: bytes) -> str:
    rb = bytes([len(data), (addr16 >> 8) & 0xFF, addr16 & 0xFF, rtype]) + data
    chk = (-sum(rb)) & 0xFF
    return f":{rb.hex().upper()}{chk:02X}"


def extract_app(dump: bytes) -> bytes:
    """Schneidet Bootloader ab und trimmt Trailing-FF/Sektor-Marker.

    Gibt die reine App-Byte-Sequenz ab 0x08007000 zurueck (ohne Padding).
    """
    if len(dump) <= BOOTLOADER_SIZE:
        raise ValueError(f"Dump zu klein ({len(dump)} B) - enthaelt keinen App-Bereich")
    app = dump[BOOTLOADER_SIZE:]

    end = 0
    i = 0
    n = len(app)
    while i < n:
        if app[i] != 0xFF:
            end = i + 1
            i += 1
            continue
        j = i
        while j < n and app[j] == 0xFF:
            j += 1
        if (j - i) >= GAP_THRESHOLD:
            break
        i = j
    return app[:end]


def build_hex(dump: bytes, output_path: str,
              start_addr: int = DEFAULT_START_ADDR,
              bin_path: str | None = None) -> dict:
    """Baut die flashbare HEX aus einem rohen Dump. Gibt Info-Dict zurueck.

    Wenn bin_path gesetzt ist, wird zusaetzlich die reine App-Byte-Sequenz
    (Bootloader gestrippt, identisch zum HEX-Inhalt) als .bin geschrieben.
    """
    app = extract_app(dump)
    crc = _crc16_modbus(app)

    lines: list[str] = []
    cur_upper = None

    for off in range(0, len(app), 16):
        full = APP_BASE + off
        upper = (full >> 16) & 0xFFFF
        if upper != cur_upper:
            lines.append(_ihex_record(0x04, 0x0000,
                                      bytes([(upper >> 8) & 0xFF, upper & 0xFF])))
            cur_upper = upper
        chunk = app[off:off + 16]
        lines.append(_ihex_record(0x00, full & 0xFFFF, chunk))

    sa = start_addr.to_bytes(4, "big")
    lines.append(_ihex_record(0x05, 0x0000, sa))
    lines.append(":00000001FF")
    lines.append(_prop_record(crc))

    with open(output_path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")

    if bin_path:
        with open(bin_path, "wb") as f:
            f.write(app)

    return {
        "app_size": len(app),
        "app_start": APP_BASE,
        "app_end": APP_BASE + len(app),
        "crc": crc,
        "start_addr": start_addr,
        "output": output_path,
        "bin_output": bin_path,
    }


def convert_file(dump_path: str, output_path: str,
                 start_addr: int = DEFAULT_START_ADDR,
                 bin_path: str | None = None) -> dict:
    with open(dump_path, "rb") as f:
        dump = f.read()
    return build_hex(dump, output_path, start_addr, bin_path=bin_path)
