"""Browser-Driver für den Pyodide-Web-Patcher.

Dünne Hülle um denselben Patch-Kern wie die CLI (``teverun_patcher.core.*``).
Die JavaScript-Glue (``web-patcher.js``) schreibt die gewählte Firmware in das
virtuelle Pyodide-Dateisystem und ruft hier eine Funktion auf; zurück kommen
HEX-Text + BIN-Bytes, die der Browser als Download anbietet.

Keine externen Abhängigkeiten außer ``intelhex`` (via micropip installiert).
"""
import json
import os

from teverun_patcher.core.hex_loader import HexLoader
from teverun_patcher.core import patch_engine, ble_name_patch, bin_to_hex
from teverun_patcher.core.fingerprint import identify

IN_HEX = "/work/in.hex"
DUMP   = "/work/dump.bin"
OUT_HEX = "/work/out.hex"
OUT_BIN = "/work/out.bin"


def _read_text(path: str) -> str:
    with open(path, "r", encoding="ascii") as f:
        return f.read()


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def patch_d5(speed, ble_variant=None, ble_serial=None, blinker_fix=False,
             zerostart=False, cruise=False) -> dict:
    """Patcht die Firmware (zuvor von JS nach IN_HEX geschrieben).

    Das Profil wird per Fingerprint AUTOMATISCH erkannt (5.4.14, 5.4.19, ...).
    Der Versions-Marker im Prop-Record wird aus der Original-Firmware uebernommen.

    speed:        int > 20 aktiviert die Speed/Zug-Freigabe (Clamp-Entfernung).
    ble_variant:  None oder Laender-Kennung (nur fuer ble_capable-Profile).
    ble_serial:   Original-FIN (fuer BLE-Namensumbau), nur bei ble_variant noetig.
    blinker_fix:  True aktiviert den Blinker-Fix (nur R5.4.19).
    zerostart:    True aktiviert ZeroStart-Freigabe (nur R5.4.19).
    cruise:       True aktiviert Cruise/Tempomat (nur R5.4.19; zieht ZeroStart-Freigabe mit).

    R5.4.19: ZeroStart/Cruise/Speed teilen sich denselben Builder-Bytebereich -> die
    Kombination wird zentral in core.r5_4_19_features aufgeloest. Andere Profile (5.4.14)
    nutzen weiterhin den klassischen Gruppen-Patch (nur Speed).
    """
    loader = HexLoader(IN_HEX)
    profile = identify(loader)
    if profile is None:
        raise RuntimeError("Firmware nicht erkannt — kein passendes Profil.")

    speed = int(speed)
    is_r519 = profile.get("id") == "r5_4_19"

    if (zerostart or cruise or blinker_fix) and not is_r519:
        raise RuntimeError("ZeroStart / Cruise / Blinker-Fix sind nur fuer die R5.4.19-Firmware verfuegbar.")

    if is_r519:
        from teverun_patcher.core import r5_4_19_features
        applied = r5_4_19_features.apply_features(
            loader,
            speed_remove=speed > 20,
            zerostart=bool(zerostart),
            cruise=bool(cruise),
            blinker=bool(blinker_fix),
        )
        n_applied = len(applied)
    else:
        params = {"speed": speed, "motor_cap": False, "kickstart": False}
        report = patch_engine.apply(loader, profile, params)
        if not report.ok:
            errs = "; ".join(f"0x{a:08X}: {m}" for a, m in report.errors)
            raise RuntimeError("Patch fehlgeschlagen: " + errs)
        n_applied = len(report.applied)

    target_name = None
    if ble_variant:
        if not profile.get("ble_capable", False):
            raise RuntimeError("BLE-Namensaenderung fuer diese Firmware nicht unterstuetzt (nur 5.4.14).")
        info = ble_name_patch.apply(loader, ble_variant, ble_serial, cfg=profile.get("ble"))
        target_name = info["target_name"]

    crc = patch_engine.save(loader, OUT_HEX)
    loader.save_bin(OUT_BIN)

    return {
        "hex": _read_text(OUT_HEX),
        "bin": _read_bytes(OUT_BIN),
        "crc": crc,
        "applied": n_applied,
        "skipped": 0,
        "target_name": target_name,
        "profile": profile.get("name", "?"),
        "blinker_fix": bool(blinker_fix) and is_r519,
        "zerostart": bool(zerostart) and is_r519,
        "cruise": bool(cruise) and is_r519,
    }


def patch_auto() -> dict:
    """Profil-freier Auto-Unlock (von JS nach IN_HEX geschrieben).

    Findet die Speed-Clamps per Muster (Frame-Builder + cmp/Bcc/mov -> FRAME[+0xA])
    und entfernt sie — funktioniert auch fuer unbekannte/neue Versionen. Der
    Versions-Marker wird aus der Original-Firmware uebernommen. Fail-safe: ohne
    klares Muster wird nichts gepatcht (RuntimeError)."""
    from teverun_patcher.core import auto_unlock
    loader = HexLoader(IN_HEX)
    res = auto_unlock.find_and_unlock(loader)
    if not res.ok:
        raise RuntimeError("Auto-Unlock: kein Speed-Clamp-Muster gefunden (nichts gepatcht).")
    crc = patch_engine.save(loader, OUT_HEX)
    loader.save_bin(OUT_BIN)
    return {
        "hex": _read_text(OUT_HEX),
        "bin": _read_bytes(OUT_BIN),
        "crc": crc,
        "applied": len(res.patched),
        "builders": len(res.builders),
        "clamps": [("0x%08X" % a) for a, _sz, _r, _v in res.patched],
        "target_name": None,
    }


def passthrough() -> dict:
    """ALI-Roh-Dump (von JS nach DUMP geschrieben) -> flashbare HEX+BIN."""
    info = bin_to_hex.convert_file(DUMP, OUT_HEX, bin_path=OUT_BIN)
    return {
        "hex": _read_text(OUT_HEX),
        "bin": _read_bytes(OUT_BIN),
        "crc": info["crc"],
        "applied": 0,
        "skipped": 0,
        "app_size": info["app_size"],
        "target_name": None,
    }


def ble_preview(ble_variant, ble_serial) -> str:
    """Vorschau des erzeugten BLE-Namens — ohne Patch (für Live-Anzeige)."""
    return ble_name_patch.compute_target_name(ble_variant, ble_serial)
