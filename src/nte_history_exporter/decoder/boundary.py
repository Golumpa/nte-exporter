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


def select_continuous_run_from_page_1(pairs: list[tuple]) -> tuple[list[tuple], list[dict[str, Any]]]:
    """Pick the run of pages starting at page 1 and continuing without gaps.

    History always loads page 1 first and is scrolled downward, so the page-1
    run holds the newest, contiguous history. Anchoring here (instead of the
    longest run anywhere) keeps the newest pages even when a later packet is
    lost, and guarantees the newest timestamp group's ordinal 0 is captured so
    every exported UID is stable. Pages after the first gap are ignored with a
    warning. If page 1 itself was not captured we fall back to the longest run
    and warn that the result may be unstable.
    """
    warnings: list[dict[str, Any]] = []
    if not pairs:
        return [], warnings

    pairs_by_page = {pair[0]: pair for pair in pairs}
    seen_pages = sorted(pairs_by_page)
    if 1 in pairs_by_page:
        selected_pages: list[int] = []
        page = 1
        while page in pairs_by_page:
            selected_pages.append(page)
            page += 1
        if len(selected_pages) < len(seen_pages):
            ignored = [p for p in seen_pages if p not in selected_pages]
            warnings.append(
                {
                    "code": "PAGE_GAP_DETECTED",
                    "ignored_pages": ignored,
                    "reason": (
                        f"Page gap detected after page {selected_pages[-1]}; "
                        f"ignored later pages {ignored}. Re-scan or scroll more slowly."
                    ),
                }
            )
        return [pairs_by_page[p] for p in selected_pages], warnings

    warnings.append(
        {
            "code": "DID_NOT_START_AT_PAGE_1",
            "reason": "Page 1 was not captured; results may be unstable. Re-scan from the top.",
        }
    )
    return longest_monotonic_page_run(pairs), warnings


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


def annotate_groups(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Assign timestamp-group ordinals and stable UIDs to every decoded row.

    Pages are anchored at page 1 (see select_continuous_run_from_page_1), so the
    newest group's ordinal 0 is always captured and every UID is stable. The only
    nuance is the oldest group: if the capture did not reach the true end of
    history (final page full) and the dice-only count is not a complete multiple
    of 10, it may be an unfinished 10-pull continuing onto an uncaptured page. Its
    captured prefix is still ordinal-stable, so it is exported with an
    informational warning rather than withheld.
    """
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
        at_oldest_boundary = group_index == len(groups) - 1
        dice_record_count = sum(1 for row in group if is_dice_record(row))
        dice_complete = dice_record_count > 0 and dice_record_count % 10 == 0
        incomplete = at_oldest_boundary and not final_page_is_partial and not dice_complete
        skip_reason = (
            "oldest timestamp group may continue onto the next uncaptured page; "
            "exported rows are stable, scroll further to capture the rest"
            if incomplete
            else ""
        )

        if incomplete:
            warnings.append(
                {
                    "code": "INCOMPLETE_TIMESTAMP_GROUP_EXPORTED",
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
            row["timestamp_group_boundary"] = "oldest" if at_oldest_boundary else ("newest" if group_index == 0 else "")
            row["uid_status"] = "incomplete_stable" if incomplete else "stable"
            row["uid"] = make_uid(row, ordinal)
            row["export_record"] = True
            row["skip_reason"] = skip_reason
    return rows, warnings
