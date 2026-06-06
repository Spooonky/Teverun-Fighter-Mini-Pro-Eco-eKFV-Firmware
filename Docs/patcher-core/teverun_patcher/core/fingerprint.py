import json
import os
from teverun_patcher.core.hex_loader import HexLoader

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "..", "profiles")


def load_profiles() -> list[dict]:
    """Lädt alle .json-Profildateien (außer schema.json)."""
    profiles = []
    for fname in os.listdir(PROFILES_DIR):
        if fname.endswith(".json") and fname != "schema.json":
            with open(os.path.join(PROFILES_DIR, fname), encoding="utf-8") as f:
                profiles.append(json.load(f))
    return profiles


def identify(loader: HexLoader) -> dict | None:
    """
    Prüft alle Profile gegen den geladenen HEX.
    Gibt das erste passende Profil zurück oder None.
    Ein Profil passt wenn ALLE fingerprint-Bytes übereinstimmen.
    """
    for profile in load_profiles():
        if _matches(loader, profile):
            return profile
    return None


def _matches(loader: HexLoader, profile: dict) -> bool:
    for fp in profile.get("fingerprint", []):
        addr = int(fp["addr"], 16)
        expected = int(fp["value"], 16)
        try:
            actual = loader.read_byte(addr)
        except Exception:
            return False
        if actual != expected:
            return False
    return True
