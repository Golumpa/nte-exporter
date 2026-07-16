from __future__ import annotations

import hashlib
import struct
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterator

from nte_history_exporter.constants import (
    ARC_SYSTEM,
    DOTNET_UNIX_EPOCH_SECONDS,
    GAME_UID_PART,
    MYSTERY_BOX_BANNER_ID,
    MYSTERY_BOX_HISTORY_CURSOR_OFFSET,
    MYSTERY_BOX_HISTORY_PAGE_CURSOR_MULTIPLIER,
    MYSTERY_BOX_HISTORY_REQUEST_CONSTANT,
    MYSTERY_BOX_HISTORY_REQUEST_CONSTANT_OFFSET,
    MYSTERY_BOX_HISTORY_REQUEST_KIND,
    MYSTERY_BOX_HISTORY_REQUEST_KIND_OFFSET,
    MYSTERY_BOX_HISTORY_REQUEST_LENGTH,
    MYSTERY_BOX_MARKER,
    POOL_META,
)
from nte_history_exporter.decoder.boundary import select_continuous_run_from_page_1
from nte_history_exporter.decoder.protocol import infer_reward_type
from nte_history_exporter.decoder.run import fmt_packet_time
from nte_history_exporter.mappings import REWARDS_BY_ID

DOTNET_TICKS_PER_SECOND = 10_000_000
MAX_RECORDS_PER_BLOCK = 100
MAX_REWARD_ID_LENGTH = 256
REWARDS_BY_CASEFOLDED_ID = {
    reward_id.casefold(): reward for reward_id, reward in REWARDS_BY_ID.items()
}


def is_mystery_box_history_request(content: bytes) -> bool:
    if len(content) < MYSTERY_BOX_HISTORY_REQUEST_LENGTH:
        return False
    return (
        struct.unpack_from("<I", content, MYSTERY_BOX_HISTORY_REQUEST_CONSTANT_OFFSET)[0]
        == MYSTERY_BOX_HISTORY_REQUEST_CONSTANT
        and struct.unpack_from("<I", content, MYSTERY_BOX_HISTORY_REQUEST_KIND_OFFSET)[0]
        == MYSTERY_BOX_HISTORY_REQUEST_KIND
    )


def mystery_box_request_page(content: bytes) -> int:
    cursor = struct.unpack_from("<I", content, MYSTERY_BOX_HISTORY_CURSOR_OFFSET)[0]
    return cursor // MYSTERY_BOX_HISTORY_PAGE_CURSOR_MULTIPLIER


def _protocol_views(payload: bytes) -> Iterator[bytes]:
    yield payload
    # History payloads can begin at a non-byte-aligned transport position.
    for bit_shift in range(1, 8):
        shifted = bytearray()
        for index in range(max(0, len(payload) - 8)):
            bit_pos = (8 + index) * 8 + bit_shift
            byte_pos, shift = divmod(bit_pos, 8)
            if byte_pos >= len(payload):
                break
            value = payload[byte_pos] >> shift
            if shift and byte_pos + 1 < len(payload):
                value |= payload[byte_pos + 1] << (8 - shift)
            shifted.append(value & 0xFF)
        yield bytes(shifted)


def _decode_timestamp(raw: bytes) -> tuple[int, float, str]:
    ticks = struct.unpack("<Q", raw)[0]
    unix_seconds = ticks / DOTNET_TICKS_PER_SECOND - DOTNET_UNIX_EPOCH_SECONDS
    decoded = datetime.fromtimestamp(unix_seconds, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return ticks, unix_seconds, decoded


def _parse_view(data: bytes) -> list[dict[str, Any]]:
    marker_pos = data.find(MYSTERY_BOX_MARKER)
    if marker_pos < 0:
        return []
    pos = marker_pos + len(MYSTERY_BOX_MARKER)
    if pos < len(data) and data[pos] == 0:
        pos += 1
    if pos + 12 > len(data):
        return []
    _reserved, _declared_size, row_count = struct.unpack_from("<III", data, pos)
    pos += 12
    if row_count > MAX_RECORDS_PER_BLOCK:
        return []

    rows: list[dict[str, Any]] = []
    try:
        for _ in range(row_count):
            record_start = pos
            reward_length = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            if not 1 <= reward_length <= MAX_REWARD_ID_LENGTH or pos + reward_length + 13 > len(data):
                return []
            reward_raw = data[pos : pos + reward_length]
            pos += reward_length
            if not reward_raw.endswith(b"\0"):
                return []
            reward_id = reward_raw[:-1].decode("utf-8")
            quantity = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            record_flag = data[pos]
            pos += 1
            timestamp_raw = data[pos : pos + 8]
            pos += 8
            ticks, unix_seconds, timestamp_decoded = _decode_timestamp(timestamp_raw)
            reward = REWARDS_BY_ID.get(reward_id) or REWARDS_BY_CASEFOLDED_ID.get(
                reward_id.casefold(), {}
            )
            rows.append(
                {
                    "record_start": record_start,
                    "record_end": pos,
                    "record_len": pos - record_start,
                    "reward_type": reward.get("type") or infer_reward_type(reward_id),
                    "reward_id": reward_id,
                    "reward_name": reward.get("name", ""),
                    "reward_rank": reward.get("rank"),
                    "quantity": quantity,
                    "source_type": "mystery_box",
                    "result_type": "single_pull",
                    "timestamp_raw_hex": timestamp_raw.hex(),
                    "timestamp_ticks": ticks,
                    "timestamp_unix": unix_seconds,
                    "timestamp_decoded": timestamp_decoded,
                    "record_flag": record_flag,
                    "record_hex": data[record_start:pos].hex(),
                    "decoder_mode": "structured",
                }
            )
    except (OSError, OverflowError, UnicodeDecodeError, ValueError, struct.error):
        return []
    return rows


def parse_mystery_box_response(payload: bytes) -> list[dict[str, Any]]:
    for view in _protocol_views(payload):
        rows = _parse_view(view)
        if rows:
            return rows
    return []


def make_mystery_box_uid(timestamp_raw: str, ordinal: int) -> str:
    source = "|".join(
        [GAME_UID_PART, ARC_SYSTEM, MYSTERY_BOX_BANNER_ID, timestamp_raw, str(ordinal)]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]


def annotate_mystery_box_rows(rows: list[dict[str, Any]]) -> None:
    groups: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[row["timestamp_raw_hex"]].append(index)
    for group_index, (timestamp_raw, indexes) in enumerate(groups.items()):
        for ordinal, index in enumerate(indexes):
            row = rows[index]
            row["timestamp_group_index"] = group_index
            row["timestamp_group_ordinal"] = ordinal
            row["timestamp_group_size_seen"] = len(indexes)
            row["timestamp_group_record_size_seen"] = len(indexes)
            row["timestamp_group_boundary"] = (
                "oldest" if group_index == len(groups) - 1 else ("newest" if group_index == 0 else "")
            )
            row["uid"] = make_mystery_box_uid(timestamp_raw, ordinal)
            row["uid_status"] = "stable"
            row["export_record"] = True
            row["skip_reason"] = ""


def build_mystery_box_rows_from_pairs(pairs: list[tuple]) -> list[dict[str, Any]]:
    pool = POOL_META["mystery_box"]
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        page, offset, req_i, req_ts, resp_i, resp_ts, response = pair[:7]
        records = parse_mystery_box_response(response)
        if len(pair) > 9:
            slice_start, slice_count = pair[8:10]
            records = records[slice_start : slice_start + slice_count]
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
    annotate_mystery_box_rows(rows)
    return rows


def select_continuous_mystery_box_run(
    pairs: list[tuple],
) -> tuple[list[tuple], list[dict[str, Any]]]:
    return select_continuous_run_from_page_1(pairs)
