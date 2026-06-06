import struct


def crc16_modbus(data: bytes) -> int:
    """CRC16-Modbus: poly=0x8005, init=0xFFFF, refin/refout=True"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_proprietary_record(crc: int, version: tuple = (0x05, 0x04, 0x0E)) -> str:
    """
    Baut den proprietären :07AAA555-Record.
    Format: :07AAA555 00 00 <v0><v1><v2> [CRC_HI][CRC_LO] [PROP_CHK]
    `version` = die 3 Versions-Bytes (Default 5.4.14). Wird vom HexLoader aus dem
    Original-Prop-Record uebernommen, damit der Marker zur Firmware-Version passt
    (z.B. 5.4.10 -> 05 04 0A, 5.4.19 -> 05 04 13). Sonst lehnt die OTA-App ggf. ab.
    Pruefsumme: sum(alle Record-Bytes ausser letztem Byte) % 256.
    """
    v0, v1, v2 = version
    rb = bytes([0x07, 0xAA, 0xA5, 0x55, 0x00, 0x00, v0, v1, v2,
                (crc >> 8) & 0xFF, crc & 0xFF])
    chk = sum(rb) % 256
    return f":{rb.hex().upper()}{chk:02X}"
