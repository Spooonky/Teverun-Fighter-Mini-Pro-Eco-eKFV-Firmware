import os
from intelhex import IntelHex

PROP_RECORD_PREFIX = ":07AAA555"


class HexLoader:
    def __init__(self, path: str):
        self.path = path
        self.ih = IntelHex()
        self.prop_record: str | None = None  # der :07AAA555-Record aus der Original-Datei
        self._load()

    def _load(self):
        # 1. IntelHex laden (parst Standard-Records, verwirft :07AAA555)
        self.ih.loadhex(self.path)
        # 2. Rohdatei nach proprietärem Record durchsuchen
        with open(self.path, "r", encoding="ascii", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.upper().startswith(PROP_RECORD_PREFIX):
                    self.prop_record = line.upper()
                    break

    def read_byte(self, addr: int) -> int:
        return self.ih[addr]

    def write_byte(self, addr: int, value: int):
        self.ih[addr] = value

    def to_bytes(self) -> bytes:
        """Gibt die gesamte Binary als bytes zurück (von min- bis max-Adresse)."""
        result = bytearray()
        for start, end in self.ih.segments():
            result.extend(self.ih.tobinstr(start=start, end=end - 1))
        return bytes(result)

    def save_bin(self, output_path: str):
        """Speichert die Binary als .bin-Datei."""
        with open(output_path, "wb") as f:
            f.write(self.to_bytes())

    def _orig_prop_version(self) -> tuple:
        """Versions-Bytes (v0,v1,v2 = z.B. 05 04 13 fuer 5.4.19) aus dem
        Original-:07AAA555-Record uebernehmen, damit der Marker zur Firmware passt.
        Fallback 5.4.14, falls kein Original-Record vorhanden."""
        if self.prop_record:
            try:
                raw = bytes.fromhex(self.prop_record[1:])
                data = raw[4:4 + raw[0]]          # 00 00 v0 v1 v2 crc_hi crc_lo
                return (data[2], data[3], data[4])
            except Exception:
                pass
        return (0x05, 0x04, 0x0E)

    def save(self, output_path: str, crc: int):
        """
        Speichert als Intel HEX mit korrekter Record-Reihenfolge:
          Daten-Records … :04000005… :00000001FF :07AAA555…
        intelhex schreibt :04000005 an den Anfang — wir verschieben es manuell ans Ende.
        Der Versions-Marker im Prop-Record wird aus der Original-Firmware uebernommen.
        """
        from teverun_patcher.core.checksum import build_proprietary_record
        self.ih.write_hex_file(output_path)

        with open(output_path, "r", encoding="ascii") as f:
            lines = [l.rstrip("\r\n") for l in f.readlines()]

        start_rec = None
        filtered = []
        for line in lines:
            if line.upper().startswith(":04000005"):
                start_rec = line
            else:
                filtered.append(line)

        # filtered endet mit :00000001FF — Start-Record davor einfügen
        if start_rec:
            eof_idx = next(
                (i for i, l in enumerate(filtered) if l.upper().startswith(":00000001")),
                len(filtered) - 1,
            )
            filtered.insert(eof_idx, start_rec)

        prop = build_proprietary_record(crc, self._orig_prop_version())
        filtered.append(prop)

        with open(output_path, "w", encoding="ascii") as f:
            f.write("\n".join(filtered) + "\n")
