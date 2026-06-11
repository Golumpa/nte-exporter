from __future__ import annotations

import hashlib
from typing import Any

from nte_history_exporter.constants import BANNER_ID, GAME_UID_PART, SYSTEM


def make_uid(record: dict[str, Any], ordinal: int) -> str:
    source = "|".join(
        [
            GAME_UID_PART,
            SYSTEM,
            str(record.get("pool_group_id", BANNER_ID)),
            str(record.get("timestamp_raw_hex", "")),
            str(ordinal),
            str(record.get("dice", "")),
            str(record.get("reward_key_hex", "")),
            str(record.get("quantity", "")),
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]


def longest_monotonic_page_run(pairs: list[tuple]) -> list[tuple]:
    runs: list[list[tuple]] = []
    current: list[tuple] = []
    prev_page = None
    for pair in pairs:
        page = pair[0]
        if prev_page is None or page == prev_page + 1:
            current.append(pair)
        else:
            if current:
                runs.append(current)
            current = [pair]
        prev_page = page
    if current:
        runs.append(current)
    return max(runs, key=len) if runs else []


def page_gap_warnings(pairs: list[tuple], best_run: list[tuple]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if len(pairs) < 2:
        return warnings

    best_run_ids = {id(pair) for pair in best_run}
    ignored_pages = [pair[0] for pair in pairs if id(pair) not in best_run_ids]
    previous_page = pairs[0][0]
    for pair in pairs[1:]:
        page = pair[0]
        if page != previous_page + 1:
            warning = {
                "code": "PAGE_GAP_DETECTED",
                "previous_page": previous_page,
                "next_page": page,
                "ignored_pages": ignored_pages,
                "reason": (
                    f"Page gap detected: saw page {previous_page} then page {page}. "
                    "Pages outside the longest continuous run were ignored for stable dedupe. "
                    "Re-scan or scroll more slowly."
                ),
            }
            warnings.append(warning)
        previous_page = page
    return warnings


def is_dice_record(row: dict[str, Any]) -> bool:
    result_type = row.get("result_type")
    if result_type:
        return result_type == "dice"

    dice = row.get("dice")
    if dice in ("", None):
        return False
    try:
        return int(dice) > 0
    except (TypeError, ValueError):
        return False


def annotate_groups(
    rows: list[dict[str, Any]],
    *,
    starts_from_page_1: bool = True,
    stable_only: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not rows:
        return rows, []

    last_page = max(int(r["page"]) for r in rows if str(r.get("page", "")).isdigit())
    last_page_records = [r for r in rows if r.get("page") == last_page]
    final_page_is_partial = len(last_page_records) < 5

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    prev_ts = None
    for row in rows:
        ts = row.get("timestamp_raw_hex", "")
        if prev_ts is None or ts == prev_ts:
            current.append(row)
        else:
            groups.append(current)
            current = [row]
        prev_ts = ts
    if current:
        groups.append(current)

    warnings: list[dict[str, Any]] = []
    for group_index, group in enumerate(groups):
        at_newest_boundary = group_index == 0
        at_oldest_boundary = group_index == len(groups) - 1
        dice_records_in_group = [row for row in group if is_dice_record(row)]
        dice_record_count = len(dice_records_in_group)
        # A complete multiple of 10 dice rolls proves the pull set is finished.
        # Unseen continuation rows can only be non-dice tails that sort after the
        # seen rows, so exported ordinals (and UIDs) stay stable.
        dice_complete = dice_record_count > 0 and dice_record_count % 10 == 0
        group_status = "stable"
        skip_reason = ""

        if at_newest_boundary and not starts_from_page_1:
            group_status = "dropped_boundary_group"
            skip_reason = "newest timestamp group may be partial because scan did not start from page 1"
        elif at_oldest_boundary and not final_page_is_partial and not dice_complete:
            group_status = "dropped_boundary_group"
            skip_reason = "oldest timestamp group may continue onto the next uncaptured page"

        if group_status != "stable":
            warnings.append(
                {
                    "code": "PARTIAL_TIMESTAMP_GROUP_DROPPED",
                    "timestamp_raw": group[0].get("timestamp_raw_hex", ""),
                    "timestamp_decoded": group[0].get("timestamp_decoded", ""),
                    "records": len(group),
                    "dice_records": dice_record_count,
                    "reason": skip_reason,
                }
            )

        for ordinal, row in enumerate(group):
            row["timestamp_group_index"] = group_index
            row["timestamp_group_ordinal"] = ordinal
            row["timestamp_group_size_seen"] = dice_record_count
            row["timestamp_group_record_size_seen"] = len(group)
            row["timestamp_group_boundary"] = ",".join(
                name
                for name, yes in [("newest", at_newest_boundary), ("oldest", at_oldest_boundary)]
                if yes
            )
            if group_status == "stable":
                row["uid_status"] = "stable"
                row["uid"] = make_uid(row, ordinal)
                row["export_record"] = True
                row["skip_reason"] = ""
            else:
                row["uid_status"] = group_status
                row["uid"] = "" if stable_only else make_uid(row, ordinal)
                row["export_record"] = not stable_only
                row["skip_reason"] = skip_reason
    return rows, warnings
