from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAPPINGS_DIR = PROJECT_ROOT / "mappings"

POOL_MAPPING_FILES = {
    "permanent": "permanent_board.json",
    "limited_character": "limited_character_board.json",
    "arc_miracle_box": "arc_miracle_box.json",
}


def load_pool_mapping(pool_key: str) -> dict[str, Any]:
    filename = POOL_MAPPING_FILES[pool_key]
    return json.loads((MAPPINGS_DIR / filename).read_text(encoding="utf-8"))


def load_pool_mappings() -> dict[str, dict[str, Any]]:
    return {pool_key: load_pool_mapping(pool_key) for pool_key in POOL_MAPPING_FILES}


def pool_meta_from_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": mapping["banner"]["id"],
        "name": mapping["banner"]["name"],
        "system": mapping["system"]["name"],
        "shared_pity": mapping["banner"]["shared_pity"],
    }
