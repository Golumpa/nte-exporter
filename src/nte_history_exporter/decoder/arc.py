from __future__ import annotations

import hashlib
import struct
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from nte_history_exporter.constants import (
    ARC_BANNER_ID,
    ARC_HISTORY_CURSOR_OFFSET,
    ARC_HISTORY_PAGE_CURSOR_MULTIPLIER,
    ARC_HISTORY_REQUEST_BANNER,
    ARC_HISTORY_REQUEST_LENGTH,
    ARC_RESPONSE_FIRST_RECORD_OFFSET,
    ARC_SYSTEM,
    ARC_TIMESTAMP_TICKS_PER_SECOND,
    DOTNET_UNIX_EPOCH_SECONDS,
    GAME_UID_PART,
    POOL_META,
)
from nte_history_exporter.decoder.boundary import longest_monotonic_page_run
from nte_history_exporter.decoder.run import fmt_packet_time
from nte_history_exporter.mappings import ARC_META


def is_arc_history_request(content: bytes) -> bool:
    return len(content) == ARC_HISTORY_REQUEST_LENGTH and struct.unpack_from("<I", content, 24)[0] == ARC_HISTORY_REQUEST_BANNER


def arc_request_page(content: bytes) -> int:
    return struct.unpack_from("<I", content, ARC_HISTORY_CURSOR_OFFSET)[0] // ARC_HISTORY_PAGE_CURSOR_MULTIPLIER


def decode_arc_key(raw: bytes) -> str | None:
    if raw.endswith(b"\x00"):
        raw = raw[:-1]
    prefix = bytes.fromhex("ccdee4d6be")
    if not raw.startswith(prefix):
        return None
    out = "fork_"
    for byte in raw[len(prefix) :]:
        if 0xC2 <= byte <= 0xF4 and (byte - 0xC2) % 2 == 0:
            out += chr(ord("a") + (byte - 0xC2) // 2)
        elif 0x82 <= byte <= 0xB4 and (byte - 0x82) % 2 == 0:
            out += chr(ord("A") + (byte - 0x82) // 2)
        else:
            out += f"_{byte:02x}"
    return out


def decode_arc_timestamp(raw8: bytes) -> tuple[int, float, str]:
    ticks = struct.unpack("<Q", raw8)[0]
    unix_seconds = ticks / ARC_TIMESTAMP_TICKS_PER_SECOND - DOTNET_UNIX_EPOCH_SECONDS
    decoded = datetime.fromtimestamp(unix_seconds, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return ticks, unix_seconds, decoded


def parse_arc_response(response: bytes) -> list[dict[str, Any]]:
    pos = ARC_RESPONSE_FIRST_RECORD_OFFSET
    records: list[dict[str, Any]] = []
    while pos + 4 <= len(response):
        start = pos
        name_len2 = struct.unpack_from("<I", response, pos)[0]
        pos += 4
        if name_len2 <= 0 or name_len2 > 200 or name_len2 % 2:
            break
        name_len = name_len2 // 2
        if pos + name_len + 4 > len(response):
            break
        name_raw = response[pos : pos + name_len]
        pos += name_len

        type_len2 = struct.unpack_from("<I", response, pos)[0]
        pos += 4
        if type_len2 <= 0 or type_len2 > 200 or type_len2 % 2:
            break
        type_len = type_len2 // 2
        if pos + type_len + 8 > len(response):
            break
        type_raw = response[pos : pos + type_len]
        pos += type_len

        timestamp_raw = response[pos : pos + 8]
        pos += 8
        arc_id = decode_arc_key(name_raw) or name_raw.hex()
        meta = ARC_META.get(arc_id, {})
        ticks, unix_seconds, timestamp_decoded = decode_arc_timestamp(timestamp_raw)
        records.append(
            {
                "record_start": start,
                "record_end": pos,
                "record_len": pos - start,
                "reward_key_hex": name_raw.hex(),
                "reward_type": "arc",
                "reward_id": arc_id,
                "reward_name": meta.get("name", "UNKNOWN"),
                "reward_rank": meta.get("rank", ""),
                "type_key_hex": type_raw.hex(),
                "source_type": "miracle_box",
                "timestamp_raw_hex": timestamp_raw.hex(),
                "timestamp_ticks": ticks,
                "timestamp_unix": unix_seconds,
                "timestamp_decoded": timestamp_decoded,
                "record_hex": response[start:pos].hex(),
            }
        )
    return records


def build_arc_rows_from_pairs(pairs: list[tuple]) -> list[dict[str, Any]]:
    pool = POOL_META["arc_miracle_box"]
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        page, offset, req_i, req_ts, resp_i, resp_ts, response = pair[:7]
        records = parse_arc_response(response)
        for row_index, record in enumerate(records, start=1):
            rows.append(
                {
                    **record,
                    "page": page,
                    "offset": offset,
                    "row": row_index,
                    "pool_group_id": pool["id"],
                    "pool_group_name": pool["name"],
                    "request_msg": req_i,
                    "request_time_utc": fmt_packet_time(req_ts),
                    "response_msg": resp_i,
                    "response_time_utc": fmt_packet_time(resp_ts),
                    "response_len": len(response),
                    "record_count": len(records),
                }
            )
    annotate_arc_groups(rows)
    return rows


def make_arc_uid(timestamp_raw: str, ordinal: int, arc_key_hex: str) -> str:
    source = "|".join([GAME_UID_PART, ARC_SYSTEM, ARC_BANNER_ID, timestamp_raw, str(ordinal), arc_key_hex])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]


def annotate_arc_groups(rows: list[dict[str, Any]]) -> None:
    groups: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[row["timestamp_raw_hex"]].append(index)

    for group_index, (timestamp_raw, indexes) in enumerate(groups.items()):
        complete = len(indexes) % 10 == 0
        for ordinal, index in enumerate(indexes):
            row = rows[index]
            row["timestamp_group_index"] = group_index
            row["timestamp_group_ordinal"] = ordinal
            row["timestamp_group_size_seen"] = len(indexes)
            row["uid"] = make_arc_uid(timestamp_raw, ordinal, row["reward_key_hex"])
            row["uid_status"] = "stable" if complete else "skipped_incomplete_timestamp_group"
            row["export_record"] = complete
            row["skip_reason"] = "" if complete else "arc timestamp group is not a complete 10-pull in this capture"


def arc_stability_warnings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings = []
    seen = set()
    for row in rows:
        if row.get("export_record") is True:
            continue
        timestamp_raw = row["timestamp_raw_hex"]
        if timestamp_raw in seen:
            continue
        seen.add(timestamp_raw)
        group = [r for r in rows if r["timestamp_raw_hex"] == timestamp_raw]
        warnings.append(
            {
                "code": "INCOMPLETE_ARC_10_PULL_DROPPED",
                "timestamp_raw": timestamp_raw,
                "timestamp_decoded": row["timestamp_decoded"],
                "records": len(group),
                "reason": "arc timestamp group is not a complete 10-pull in this capture",
            }
        )
    return warnings


def select_continuous_arc_run(pairs: list[tuple]) -> tuple[list[tuple], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    if not pairs:
        return [], warnings
    pairs_by_page = {pair[0]: pair for pair in pairs}
    seen_pages = sorted(pairs_by_page)
    if 1 in pairs_by_page:
        selected_pages = []
        page = 1
        while page in pairs_by_page:
            selected_pages.append(page)
            page += 1
        if len(selected_pages) < len(seen_pages):
            ignored = [page for page in seen_pages if page not in selected_pages]
            warnings.append(
                {
                    "code": "PAGE_GAP_DETECTED",
                    "ignored_pages": ignored,
                    "reason": f"Using continuous pages 1-{selected_pages[-1]}; ignored later pages {ignored}.",
                }
            )
        return [pairs_by_page[page] for page in selected_pages], warnings

    warnings.append({"code": "DID_NOT_START_AT_PAGE_1", "reason": "Arc history scan did not start at page 1."})
    return longest_monotonic_page_run(pairs), warnings
