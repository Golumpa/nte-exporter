from __future__ import annotations

from typing import Any

from nte_history_exporter.mappings import load_mapping_file

POOL_MAPPING_FILES = {
    "permanent": "permanent_board.json",
    "limited_character": "limited_character_board.json",
    "arc_miracle_box": "arc_miracle_box.json",
}


def load_pool_mapping(pool_key: str) -> dict[str, Any]:
    return load_mapping_file(POOL_MAPPING_FILES[pool_key])


def load_pool_mappings() -> dict[str, dict[str, Any]]:
    return {pool_key: load_pool_mapping(pool_key) for pool_key in POOL_MAPPING_FILES}


def pool_meta_from_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": mapping["banner"]["id"],
        "name": mapping["banner"]["name"],
        "system": mapping["system"]["name"],
        "shared_pity": mapping["banner"]["shared_pity"],
    }
