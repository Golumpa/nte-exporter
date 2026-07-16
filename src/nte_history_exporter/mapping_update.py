from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


NTE_ASSETS_REPOSITORY = "https://github.com/Waifus-Grace/NTE_Assets"
DEFAULT_SOURCE_REF = "main"
ASSET_TABLES = {
    "characters": "DataTable/Character/DT_Character.json",
    "arcs": "DataTable/Fork/DT_ForkItemData.json",
    "inventory": "DataTable/Inventory/DT_ItemConfig.json",
    "capital_inventory": "DataTable/Inventory/DT_CapitalItemConfig.json",
    "appearances": "DataTable/Character/Appearance/DT_AppearanceData.json",
    "illustrations": "DataTable/Gacha/GachaIllustrate.json",
    "mystery_box_pools": "DataTable/GashaponLottery/DT_GashaponLotteryGlobal.json",
    "vehicle_inventory": "DataTable/Vehicle/DT_VehicleItemData.json",
    "localization": "Localization/en/game.json",
}
REWARD_MAPPING_FILES = ("arcs.json", "characters.json", "items.json")
RANK_BY_QUALITY = {
    "EItemQuality::ITEM_QUALITY_ORANGE": "S",
    "EItemQuality::ITEM_QUALITY_PURPLE": "A",
    "EItemQuality::ITEM_QUALITY_BLUE": "B",
}


class MappingUpdateError(ValueError):
    pass


@dataclass(frozen=True)
class AssetSource:
    tables: dict[str, dict[str, Any]]
    source: str
    source_ref: str | None
    sha256: str
    file_sha256: dict[str, str]


@dataclass(frozen=True)
class MappingUpdateResult:
    mappings: dict[str, dict[str, dict[str, Any]]]
    report: dict[str, Any]

    @property
    def change_count(self) -> int:
        changes = self.report["changes"]
        return changes["additions"] + changes["updates"] + changes["deletions"]


def load_assets(*, assets_root: Path | None = None, source_ref: str = DEFAULT_SOURCE_REF) -> AssetSource:
    tables: dict[str, dict[str, Any]] = {}
    file_hashes: dict[str, str] = {}
    combined = hashlib.sha256()

    for label, relative_path in ASSET_TABLES.items():
        if assets_root is not None:
            path = assets_root / Path(relative_path)
            try:
                raw = path.read_bytes()
            except OSError as exc:
                raise MappingUpdateError(f"cannot read NTE_Assets table {path}: {exc}") from exc
        else:
            url = f"https://raw.githubusercontent.com/Waifus-Grace/NTE_Assets/{source_ref}/{relative_path}"
            request = urllib.request.Request(url, headers={"User-Agent": "nte-history-exporter-mapping-update"})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    raw = response.read()
            except OSError as exc:
                raise MappingUpdateError(f"cannot download NTE_Assets table {relative_path}: {exc}") from exc

        try:
            document = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MappingUpdateError(f"invalid NTE_Assets JSON in {relative_path}: {exc}") from exc
        tables[label] = (
            _extract_localization(document, relative_path)
            if label == "localization"
            else _extract_rows(document, relative_path)
        )
        digest = hashlib.sha256(raw).hexdigest()
        file_hashes[relative_path] = digest
        combined.update(relative_path.encode("utf-8"))
        combined.update(b"\0")
        combined.update(raw)

    source = str(assets_root.resolve()) if assets_root is not None else NTE_ASSETS_REPOSITORY
    return AssetSource(
        tables=tables,
        source=source,
        source_ref=None if assets_root is not None else source_ref,
        sha256=combined.hexdigest(),
        file_sha256=file_hashes,
    )


def load_current_mappings(directory: Path) -> dict[str, dict[str, dict[str, Any]]]:
    mappings = {}
    for filename in REWARD_MAPPING_FILES:
        path = directory / filename
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MappingUpdateError(f"cannot read {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise MappingUpdateError(f"{path} must contain an object")
        mappings[filename] = value
    validate_mappings(mappings)
    return mappings


def build_mapping_update(
    current: dict[str, dict[str, dict[str, Any]]],
    assets: AssetSource,
) -> MappingUpdateResult:
    validate_mappings(current)
    translations = _build_translation_index(assets.tables["localization"])
    output = {
        "arcs.json": _build_primary_mapping(assets.tables["arcs"], "arc", translations),
        "characters.json": _build_primary_mapping(assets.tables["characters"], "character", translations),
        "items.json": _build_item_mapping(assets.tables, translations),
    }
    validate_mappings(output)

    additions: dict[str, list[str]] = {}
    updates: dict[str, list[str]] = {}
    deletions: dict[str, list[str]] = {}
    for filename in REWARD_MAPPING_FILES:
        old = current[filename]
        new = output[filename]
        additions[filename] = sorted(new.keys() - old.keys(), key=str.casefold)
        deletions[filename] = sorted(old.keys() - new.keys(), key=str.casefold)
        updates[filename] = sorted(
            (item_id for item_id in old.keys() & new.keys() if old[item_id] != new[item_id]),
            key=str.casefold,
        )

    report = {
        "schema_version": 2,
        "source": assets.source,
        "source_ref": assets.source_ref,
        "source_sha256": assets.sha256,
        "source_file_sha256": assets.file_sha256,
        "safety": {
            "authoritative_snapshot": True,
            "deletions_allowed": True,
            "pool_mappings_touched": False,
            "uid_inputs_touched": False,
        },
        "changes": {
            "additions": sum(map(len, additions.values())),
            "updates": sum(map(len, updates.values())),
            "deletions": sum(map(len, deletions.values())),
        },
        "additions_by_file": additions,
        "updates_by_file": updates,
        "deletions_by_file": deletions,
        "output_counts": {filename: len(entries) for filename, entries in output.items()},
    }
    return MappingUpdateResult(output, report)


def write_update(result: MappingUpdateResult, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename in REWARD_MAPPING_FILES:
        _atomic_write(directory / filename, _dump_mapping(result.mappings[filename]))
    report_text = json.dumps(result.report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write(directory / "mapping-update-report.json", report_text)


def apply_update(result: MappingUpdateResult, directory: Path) -> None:
    """Replace all reward maps as one transaction, rolling back on failure."""
    directory.mkdir(parents=True, exist_ok=True)
    originals: dict[Path, bytes | None] = {}
    written: list[Path] = []
    for filename in REWARD_MAPPING_FILES:
        path = directory / filename
        originals[path] = path.read_bytes() if path.exists() else None
    try:
        for filename in REWARD_MAPPING_FILES:
            path = directory / filename
            _atomic_write(path, _dump_mapping(result.mappings[filename]))
            written.append(path)
    except OSError:
        for path in reversed(written):
            original = originals[path]
            if original is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write_bytes(path, original)
        raise


def validate_mappings(mappings: dict[str, dict[str, dict[str, Any]]]) -> None:
    if set(mappings) != set(REWARD_MAPPING_FILES):
        raise MappingUpdateError(f"mapping set must be exactly {REWARD_MAPPING_FILES}")
    locations: dict[str, str] = {}
    folded: dict[str, str] = {}
    for filename in REWARD_MAPPING_FILES:
        entries = mappings[filename]
        if not isinstance(entries, dict):
            raise MappingUpdateError(f"{filename} must contain an object")
        for item_id, meta in entries.items():
            if not isinstance(item_id, str) or not item_id:
                raise MappingUpdateError(f"{filename} contains an invalid item ID")
            if item_id in locations:
                raise MappingUpdateError(f"item ID {item_id} appears in {locations[item_id]} and {filename}")
            locations[item_id] = filename
            case_key = item_id.casefold()
            if case_key in folded and folded[case_key] != item_id:
                raise MappingUpdateError(f"case-insensitive duplicate IDs: {folded[case_key]} and {item_id}")
            folded[case_key] = item_id
            if not isinstance(meta, dict):
                raise MappingUpdateError(f"{filename}:{item_id} must be an object")
            name = meta.get("name")
            if not isinstance(name, str) or not name.strip():
                raise MappingUpdateError(f"{filename}:{item_id}.name must be a non-empty string")
            rank = meta.get("rank")
            if filename == "arcs.json" and rank not in {"S", "A", "B"}:
                raise MappingUpdateError(f"{filename}:{item_id}.rank must be S, A, or B")
            if filename == "characters.json" and rank not in {"S", "A"}:
                raise MappingUpdateError(f"{filename}:{item_id}.rank must be S or A")
            if filename == "items.json":
                if meta.get("type") not in {"item", "cosmetic"}:
                    raise MappingUpdateError(f"{filename}:{item_id}.type must be item or cosmetic")
                if rank not in {"S", "A", "B"}:
                    raise MappingUpdateError(f"{filename}:{item_id}.rank must be S, A, or B")


def _extract_rows(document: Any, relative_path: str) -> dict[str, Any]:
    candidates = document if isinstance(document, list) else [document]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        rows = candidate.get("Rows")
        if isinstance(rows, dict):
            return rows
        if all(isinstance(key, str) for key in candidate) and candidate:
            return candidate
    raise MappingUpdateError(f"NTE_Assets table {relative_path} does not contain a Rows object")


def _extract_localization(document: Any, relative_path: str) -> dict[str, Any]:
    if not isinstance(document, dict) or not all(isinstance(value, dict) for value in document.values()):
        raise MappingUpdateError(f"NTE_Assets localization {relative_path} must contain namespace objects")
    return document


def _build_translation_index(localization: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {}
    for namespace, entries in localization.items():
        for key, value in entries.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise MappingUpdateError(f"invalid English localization entry {namespace}:{key}")
            result.setdefault(key, []).append((namespace, value))
    return result


def _build_primary_mapping(
    rows: dict[str, Any],
    kind: str,
    translations: dict[str, list[tuple[str, str]]],
) -> dict[str, dict[str, Any]]:
    result = {}
    for item_id in sorted(rows, key=lambda value: (value.casefold(), value)):
        meta = _normalise_row(item_id, rows[item_id], translations)
        if kind == "character" and meta["rank"] not in {"S", "A"}:
            raise MappingUpdateError(f"unexpected character quality for {item_id}")
        result[item_id] = {"name": meta["name"], "rank": meta["rank"]}
    return result


def _build_item_mapping(
    tables: dict[str, dict[str, Any]],
    translations: dict[str, list[tuple[str, str]]],
) -> dict[str, dict[str, Any]]:
    inventory = _casefold_index(tables["inventory"], "inventory")
    capital = _casefold_index(tables["capital_inventory"], "capital inventory")
    appearances = _casefold_index(tables["appearances"], "appearances")
    vehicle_inventory = _casefold_index(tables["vehicle_inventory"], "vehicle inventory")
    result: dict[str, dict[str, Any]] = {}
    candidate_ids = _reward_candidate_ids(tables)
    for candidate_id in candidate_ids:
        folded = candidate_id.casefold()
        if candidate_id.isdigit() or folded.startswith("fork_") or folded.startswith("characterawaken_"):
            continue
        sources = (inventory, capital, appearances, vehicle_inventory)
        match = next((source.get(folded) for source in sources if folded in source), None)
        if match is None:
            raise MappingUpdateError(f"reward {candidate_id} is missing from item tables")
        canonical_id, row = match
        if folded.startswith("fashion_glide_") and folded in appearances:
            canonical_id = appearances[folded][0]
        meta = _normalise_row(canonical_id, row, translations)
        result[canonical_id] = {
            "type": _item_mapping_type(canonical_id),
            "name": meta["name"],
            "rank": meta["rank"],
        }
    return dict(sorted(result.items(), key=lambda pair: (pair[0].casefold(), pair[0])))


def _reward_candidate_ids(tables: dict[str, dict[str, Any]]) -> list[str]:
    """Return rewards used by ordinary Gacha and every Mystery Box rotation."""
    candidates: dict[str, str] = {
        item_id.casefold(): item_id for item_id in tables["illustrations"]
    }
    for pool_id, pool in tables["mystery_box_pools"].items():
        if not isinstance(pool, dict):
            raise MappingUpdateError(f"Mystery Box pool {pool_id} must be an object")
        gifts = pool.get("GiftList")
        if not isinstance(gifts, list):
            raise MappingUpdateError(f"Mystery Box pool {pool_id} has no GiftList")
        for index, gift in enumerate(gifts):
            if not isinstance(gift, dict):
                raise MappingUpdateError(
                    f"Mystery Box pool {pool_id} gift {index} must be an object"
                )
            item_id = gift.get("ItemID")
            if not isinstance(item_id, str) or not item_id:
                raise MappingUpdateError(
                    f"Mystery Box pool {pool_id} gift {index} has no ItemID"
                )
            candidates.setdefault(item_id.casefold(), item_id)
    return sorted(candidates.values(), key=lambda value: (value.casefold(), value))


def _item_mapping_type(item_id: str) -> str:
    folded = item_id.casefold()
    cosmetic_prefixes = ("fashion_", "frame_", "bussinesscard_")
    return "cosmetic" if folded.startswith(cosmetic_prefixes) else "item"


def _casefold_index(rows: dict[str, Any], label: str) -> dict[str, tuple[str, Any]]:
    result: dict[str, tuple[str, Any]] = {}
    for item_id, row in rows.items():
        folded = item_id.casefold()
        if folded in result and result[folded][0] != item_id:
            raise MappingUpdateError(f"{label} has case-insensitive duplicate IDs: {result[folded][0]} and {item_id}")
        result[folded] = (item_id, row)
    return result


def _normalise_row(
    item_id: str,
    row: Any,
    translations: dict[str, list[tuple[str, str]]],
) -> dict[str, str]:
    if not isinstance(row, dict):
        raise MappingUpdateError(f"NTE_Assets row {item_id} must be an object")
    item_name = row.get("ItemName") or row.get("Name")
    if not isinstance(item_name, dict):
        raise MappingUpdateError(f"NTE_Assets row {item_id} has no ItemName")
    name = _translate_name(item_id, item_name, translations)
    quality = row.get("ItemQuality") or row.get("Quality")
    rank = RANK_BY_QUALITY.get(quality)
    if rank is None:
        raise MappingUpdateError(f"NTE_Assets row {item_id} has unsupported quality {quality!r}")
    return {"name": name.strip(), "rank": rank}


def _translate_name(
    item_id: str,
    string_reference: dict[str, Any],
    translations: dict[str, list[tuple[str, str]]],
) -> str:
    key = string_reference.get("Key")
    if not isinstance(key, str) or not key:
        raise MappingUpdateError(f"NTE_Assets row {item_id} has no localization key")
    table_id = string_reference.get("TableId")
    expected_namespace = None
    if isinstance(table_id, str) and table_id:
        expected_namespace = table_id.rsplit("/", 1)[-1].split(".", 1)[0]
    matches = translations.get(key, [])
    preferred = [value for namespace, value in matches if namespace == expected_namespace]
    if len(preferred) == 1:
        name = preferred[0]
    elif len(matches) == 1:
        name = matches[0][1]
    elif not matches:
        raise MappingUpdateError(f"English localization is missing {item_id} key {key}")
    else:
        namespaces = ", ".join(namespace for namespace, _value in matches)
        raise MappingUpdateError(f"English localization key {key} for {item_id} is ambiguous: {namespaces}")
    if not name.strip():
        raise MappingUpdateError(f"English localization key {key} for {item_id} is empty")
    return name


def _dump_mapping(mapping: dict[str, dict[str, Any]]) -> str:
    lines = ["{"]
    entries = list(mapping.items())
    for index, (item_id, meta) in enumerate(entries):
        comma = "," if index < len(entries) - 1 else ""
        key = json.dumps(item_id, ensure_ascii=False)
        value = json.dumps(meta, ensure_ascii=False, separators=(", ", ": "))
        lines.append(f"  {key}: {value}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
