"""Validated local settings shared by the desktop app and CLI."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT / "settings.json"
EXAMPLE_SETTINGS_PATH = ROOT / "settings.example.json"
DATABASE = ROOT / "data" / "messages.sqlite3"
IMPORTS = ROOT / "data" / "imports"


def validate(config):
    if not isinstance(config, dict):
        raise ValueError("Settings must be a JSON object")
    rules = config.get("categories")
    if not isinstance(rules, dict) or not rules:
        raise ValueError("Add at least one category with keywords")
    for name, words in rules.items():
        if not isinstance(name, str) or not name.strip() or name in ("Uncategorized", "Needs review"):
            raise ValueError("Use nonempty category names other than Uncategorized and Needs review")
        if not isinstance(words, list) or any(not isinstance(w, str) or not w.strip() for w in words):
            raise ValueError(f"{name}: keywords must be a list of nonempty strings")
    senders = config.get("sender_names", [])
    if not isinstance(senders, list) or any(not isinstance(name, str) or not name.strip() for name in senders):
        raise ValueError("sender_names must be a list of nonempty display names")
    mappings = config.get("chat_categories", {})
    if not isinstance(mappings, dict):
        raise ValueError("chat_categories must map chat names to category names")
    for chat, category in mappings.items():
        if not isinstance(chat, str) or not chat.strip() or not isinstance(category, str) or category not in rules:
            raise ValueError("Every chat assignment needs a nonempty chat name and an existing category")
    if config.get("date_order", "MDY") not in ("MDY", "DMY"):
        raise ValueError("date_order must be MDY or DMY for dates like 10/23/2026; year-first dates work with either")
    interval = config.get("poll_seconds", 3)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval < 1:
        raise ValueError("poll_seconds must be a finite number of at least 1")
    return config


def settings():
    path = SETTINGS_PATH if SETTINGS_PATH.exists() else EXAMPLE_SETTINGS_PATH
    return validate(json.loads(path.read_text(encoding="utf-8-sig")))


def save_settings(config):
    validate(config)
    temporary = SETTINGS_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(SETTINGS_PATH)
