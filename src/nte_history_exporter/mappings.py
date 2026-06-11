from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAPPINGS_DIR = PROJECT_ROOT / "mappings"


def load_mapping_file(filename: str) -> dict[str, Any]:
    return json.loads((MAPPINGS_DIR / filename).read_text(encoding="utf-8"))


ARC_META: dict[str, dict[str, Any]] = load_mapping_file("arcs.json")
CHARACTERS: dict[str, dict[str, Any]] = load_mapping_file("characters.json")
ITEMS: dict[str, dict[str, Any]] = load_mapping_file("items.json")

# Reward keys in Monopoly history packets are the reward id string itself
# (ASCII*4 with carry, see decoder.protocol.decode_reward_key), so all reward
# metadata is looked up by decoded id rather than by raw key bytes.
REWARDS_BY_ID: dict[str, dict[str, Any]] = {}
for _arc_id, _meta in ARC_META.items():
    REWARDS_BY_ID[_arc_id] = {"type": "arc", "id": _arc_id, "name": _meta["name"], "rank": _meta["rank"]}
for _character_id, _meta in CHARACTERS.items():
    REWARDS_BY_ID[_character_id] = {
        "type": "character",
        "id": _character_id,
        "name": _meta["name"],
        "rank": _meta["rank"],
    }
for _item_id, _meta in ITEMS.items():
    REWARDS_BY_ID[_item_id] = {"type": _meta["type"], "id": _item_id, "name": _meta["name"], "rank": _meta.get("rank")}
