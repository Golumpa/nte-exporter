from __future__ import annotations

from typing import Any

from nte_history_exporter import __version__
from nte_history_exporter.constants import (
    ARC_BANNER_ID,
    BANNER_ID,
    EXPORTER_NAME,
    GAME_NAME,
    POOL_META,
)


def build_export_json(
    rows: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    *,
    source: str = "packet_capture",
    capture_source: str | None = None,
    user_uid: str | None = None,
    flow_index: int | None = None,
    candidate_request_response_pairs: int | None = None,
    pages_seen: list[int] | None = None,
) -> dict[str, Any]:
    exported = [r for r in rows if r.get("export_record") is True]
    representative = exported[0] if exported else (rows[0] if rows else {})
    pool_group_id = representative.get("pool_group_id", BANNER_ID)
    pool = next((meta for meta in POOL_META.values() if meta["id"] == pool_group_id), POOL_META["permanent"])
    scan: dict[str, Any] = {
        "mode": "stable_only",
        "boundary_policy": "export_ordinal_stable_groups",
        "decoded_records": len(rows),
        "exported_records": len(exported),
        "skipped_records": len(rows) - len(exported),
        "warnings": warnings,
    }
    if flow_index is not None:
        scan["udp_flow_index"] = flow_index
    if candidate_request_response_pairs is not None:
        scan["candidate_request_response_pairs"] = candidate_request_response_pairs
    if pages_seen is not None:
        scan["pages_seen"] = pages_seen

    normalized_user_uid = user_uid.strip() if user_uid else ""
    export: dict[str, Any] = {
        "format": "nte-history-export",
        "format_version": 1,
        "game": GAME_NAME,
        "source": source,
    }
    if capture_source:
        export["capture_source"] = capture_source
    export["exporter"] = {"name": EXPORTER_NAME, "version": __version__}
    export.update(
        {
            "banner": {
                "id": pool["id"],
                "name": pool["name"],
                "system": pool["system"],
                "shared_pity": pool["shared_pity"],
            },
            "scan": scan,
        }
    )
    if normalized_user_uid:
        export["user_uid"] = normalized_user_uid
    export["records"] = [_record_for_export(r) for r in exported]
    return export


def _record_for_export(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("pool_group_id") == ARC_BANNER_ID:
        return {
            "uid": row.get("uid"),
            "pool_group_id": row.get("pool_group_id"),
            "timestamp": row.get("timestamp_decoded"),
            "timestamp_group_ordinal": row.get("timestamp_group_ordinal"),
            "reward_type": row.get("reward_type"),
            "reward_id": row.get("reward_id"),
            "reward_name": row.get("reward_name"),
            "reward_rank": row.get("reward_rank"),
            "source_type": row.get("source_type"),
        }

    return {
        "uid": row.get("uid"),
        "pool_group_id": row.get("pool_group_id", BANNER_ID),
        "timestamp": row.get("timestamp_decoded"),
        "timestamp_group_ordinal": row.get("timestamp_group_ordinal"),
        "roll_result": row.get("dice"),
        "result_type": row.get("result_type") or ("points_gift" if row.get("dice") == 0 else "dice"),
        "reward_type": row.get("reward_type"),
        "reward_id": row.get("reward_id"),
        "reward_name": row.get("reward_name"),
        "reward_rank": row.get("reward_rank"),
        "quantity": row.get("quantity"),
    }
