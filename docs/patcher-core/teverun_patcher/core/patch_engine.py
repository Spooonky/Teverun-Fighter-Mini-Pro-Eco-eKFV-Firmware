from __future__ import annotations
from dataclasses import dataclass, field
from teverun_patcher.core.hex_loader import HexLoader
from teverun_patcher.core.checksum import crc16_modbus
from teverun_patcher.core import thumb2_modimm


MOTOR_CAP_PER_KMH = 64


@dataclass
class PatchResult:
    addr: int
    old: int
    new: int
    note: str


@dataclass
class PatchReport:
    applied: list[PatchResult] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def compute_motor_cap_bytes(speed_kmh: int, expected_orig_hw2: int = 0x6FC8) -> tuple[int, int] | None:
    """Berechnet die 2 HW2-Bytes (low, high) für eine motor-cap cmp.w-Instruktion.

    Stock: cap=0x640 (1600), entspricht ~25 km/h. Skalierung: cap = speed * 64.
    Returns: (byte_low, byte_high) im Speicher-Layout, oder None wenn Encoding scheitert.
    """
    cap_value = speed_kmh * MOTOR_CAP_PER_KMH
    enc = thumb2_modimm.encode_for_cmp_w(cap_value)
    if enc is None:
        return None
    i, imm3, imm8, hw2_high = enc
    return (imm8, hw2_high)


def apply(loader: HexLoader, profile: dict, params: dict) -> PatchReport:
    """
    Wendet Patches aus dem Profil an.

    params-Beispiel: {"speed": 30, "motor_cap": True}

    Transform-Logik:
    - direct:        Schreibt speed-Byte. Nur wenn speed_kmh > int(expected).
    - lookup:        Sucht params["speed"] in patch["map"]. Überspringt wenn nicht vorhanden.
    - fixed:         Schreibt immer patch["value"]. Aktiv wenn Gruppe-Param truthy.
    - motor_cap_lo:  Patcht das Low-Byte des cmp.w-HW2 (imm8). Wert dynamisch aus speed berechnet.
    - motor_cap_hi:  Patcht das High-Byte des cmp.w-HW2 (imm3+marker). Wert dynamisch aus speed.
    """
    report = PatchReport()
    speed = int(params.get("speed", 20))
    motor_cap = bool(params.get("motor_cap", False))

    for patch in profile.get("patches", []):
        addr = int(patch["addr"], 16)
        expected = int(patch["expected"], 16)
        group = patch["group"]
        transform = patch["transform"]
        note = patch.get("note", "")

        if group == "speed":
            active = speed > 20
        elif group == "motor_cap":
            active = motor_cap
        elif group == "kickstart":
            active = bool(params.get("kickstart", False))
        else:
            active = True

        if not active:
            report.skipped.append((addr, f"group '{group}' inactive"))
            continue

        try:
            actual = loader.read_byte(addr)
        except Exception as e:
            report.errors.append((addr, f"read error: {e}"))
            continue

        if actual != expected:
            report.errors.append((addr, f"expected 0x{expected:02X} but found 0x{actual:02X}"))
            continue

        if transform == "direct":
            if speed <= expected:
                report.skipped.append((addr, f"speed {speed} <= expected {expected:#x}"))
                continue
            new_val = speed & 0xFF

        elif transform == "lookup":
            map_ = patch.get("map", {})
            key = str(speed)
            if key not in map_:
                report.skipped.append((addr, f"no lookup value for speed={speed}"))
                continue
            lookup_val = int(map_[key], 16)
            if lookup_val == expected:
                report.skipped.append((addr, "lookup value equals original"))
                continue
            new_val = lookup_val

        elif transform == "fixed":
            new_val = int(patch["value"], 16)

        elif transform in ("motor_cap_lo", "motor_cap_hi"):
            cap_bytes = compute_motor_cap_bytes(speed)
            if cap_bytes is None:
                report.errors.append((addr, f"motor cap: speed {speed} nicht als Thumb-2 imm12 kodierbar"))
                continue
            byte_lo, byte_hi = cap_bytes
            new_val = byte_lo if transform == "motor_cap_lo" else byte_hi
            if new_val == expected:
                report.skipped.append((addr, f"motor cap byte unverändert (speed {speed})"))
                continue

        else:
            report.errors.append((addr, f"unknown transform '{transform}'"))
            continue

        loader.write_byte(addr, new_val)
        report.applied.append(PatchResult(addr=addr, old=actual, new=new_val, note=note))

    return report


def save(loader: HexLoader, output_path: str) -> int:
    """Speichert gepatchten HEX mit aktuellem CRC16-Modbus. Gibt CRC zurück.

    CRC wird über die Segmente-konkateniert berechnet (das was `to_bytes()` liefert).
    Das ist der Wert den die OTA-App im Prop-Record erwartet — wenn der nicht stimmt
    lehnt die App das Upload mit "Please Load the correct upgrade file" ab.
    """
    data = loader.to_bytes()
    crc = crc16_modbus(data)
    loader.save(output_path, crc)
    return crc
