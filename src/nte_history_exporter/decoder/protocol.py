from __future__ import annotations

import struct
from datetime import datetime, timezone
from typing import Any

from nte_history_exporter.constants import (
    DOTNET_UNIX_EPOCH_SECONDS,
    HISTORY_REQUEST_BANNER,
    HISTORY_REQUEST_LENGTH,
    HISTORY_PAGE_CURSOR_MULTIPLIER,
    LIMITED_CHARACTER_SELECTOR,
    MARKERS,
    PERMANENT_SELECTOR,
    TIMESTAMP_TICKS_PER_SECOND,
    VALID_DICE_FIELDS,
)
from nte_history_exporter.mappings import KNOWN_REWARDS


def decode_history_timestamp(raw8: bytes) -> tuple[int, float, str]:
    if len(raw8) != 8:
        raise ValueError("history timestamps must be exactly 8 bytes")
    ticks = struct.unpack("<Q", raw8)[0]
    unix_seconds = ticks / TIMESTAMP_TICKS_PER_SECOND - DOTNET_UNIX_EPOCH_SECONDS
    decoded = datetime.fromtimestamp(unix_seconds, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return ticks, unix_seconds, decoded


def history_request_kind(content: bytes) -> str:
    if len(content) != HISTORY_REQUEST_LENGTH or struct.unpack_from("<I", content, 35)[0] != HISTORY_REQUEST_BANNER:
        return ""
    selector = struct.unpack_from("<I", content, 40)[0]
    if selector == PERMANENT_SELECTOR:
        return "permanent"
    if selector == LIMITED_CHARACTER_SELECTOR:
        return "limited_character"
    return ""


def is_history_request(content: bytes) -> bool:
    return bool(history_request_kind(content))


def request_page(content: bytes) -> int:
    return struct.unpack_from("<I", content, 31)[0] // HISTORY_PAGE_CURSOR_MULTIPLIER


def response_contains_history_marker(content: bytes) -> bool:
    return any(marker in content for marker in MARKERS)


def extract_key(chunk_without_marker: bytes) -> str:
    fashion_prefix = bytes.fromhex("1885cda1a5bdb97d")
    fashion_pos = chunk_without_marker.rfind(fashion_prefix)
    if fashion_pos != -1:
        return chunk_without_marker[fashion_pos:].hex()

    char_prefix = bytes.fromhex("c4c0")
    char_pos = chunk_without_marker.find(char_prefix)
    if char_pos != -1 and char_pos + 5 <= len(chunk_without_marker):
        return chunk_without_marker[char_pos : char_pos + 5].hex()

    best = None
    for prefix in [bytes.fromhex("98bdc9ad"), bytes.fromhex("10a58d95")]:
        pos = chunk_without_marker.rfind(prefix)
        if pos != -1 and (best is None or pos > best):
            best = pos
    return "" if best is None else chunk_without_marker[best:].hex()


def extract_dice(chunk_without_marker: bytes) -> tuple[int | None, int | None, int | None]:
    for off in range(0, min(16, max(0, len(chunk_without_marker) - 3))):
        val = struct.unpack_from("<I", chunk_without_marker, off)[0]
        if val in VALID_DICE_FIELDS:
            return (0 if val == 0 else val // 4), val, off
    return None, None, None


def classify_result_type(
    chunk_without_marker: bytes,
    dice: int | None,
    dice_offset: int | None,
) -> tuple[str, int | None]:
    if dice is None or dice_offset is None:
        return "unknown", None
    if dice == 0:
        return "points_gift", 0

    source_off = dice_offset + 4
    if source_off + 4 <= len(chunk_without_marker):
        source_val = struct.unpack_from("<i", chunk_without_marker, source_off)[0]
        if source_val == 0:
            return "points_gift", source_val
        if source_val == -4:
            return "chase_reward", source_val
        return "dice", source_val
    return "dice", None


def guess_quantity(chunk_hex: str, key_hex: str, result_type: str | None = None) -> int | None:
    if key_hex == "10a58d957dd1a58dad95d17dc1c400":
        if result_type == "chase_reward":
            return 30
        return 4
    if key_hex == "10a58d9539bdc9b585b101":
        return 1
    if key_hex == "10a58d957dd1a58dad95d17dc1c800":
        if "c8b0d4c0" in chunk_hex:
            return 50
        if "c8b0ccc0" in chunk_hex:
            return 30
        return None
    if key_hex:
        return 1
    return None


def decode_response_records(response_content: bytes) -> list[dict[str, Any]]:
    marker = b""
    marker_offsets: list[int] = []
    for candidate_marker in MARKERS:
        offsets = [i for i in range(len(response_content)) if response_content.startswith(candidate_marker, i)]
        if offsets:
            marker = candidate_marker
            marker_offsets = offsets
            break
    if not marker_offsets:
        return []

    rows: list[dict[str, Any]] = []
    prev = 0x50
    for row_index, marker_offset in enumerate(marker_offsets, start=1):
        chunk = response_content[prev:marker_offset]
        full_record = response_content[prev : marker_offset + len(marker) + 8]
        dice, dice_raw, dice_offset = extract_dice(chunk)
        result_type, result_source_raw = classify_result_type(chunk, dice, dice_offset)
        if result_type == "points_gift":
            dice = 0
            dice_raw = 0
        elif result_type == "chase_reward":
            dice = -4
            dice_raw = -4
        key_hex = extract_key(chunk)
        reward = KNOWN_REWARDS.get(key_hex, {})
        timestamp_raw = response_content[marker_offset + len(marker) : marker_offset + len(marker) + 8]
        timestamp_ticks, timestamp_unix, timestamp_decoded = decode_history_timestamp(timestamp_raw)
        chunk_hex = chunk.hex()
        rows.append(
            {
                "row": row_index,
                "record_start": prev,
                "record_end": marker_offset + len(marker) + 8,
                "record_len": len(full_record),
                "dice": dice,
                "roll_result": (
                    "Points Gift"
                    if result_type == "points_gift"
                    else ("Chase Reward" if result_type == "chase_reward" else (f"Dice {dice}" if dice else ""))
                ),
                "result_type": result_type,
                "result_source_raw": result_source_raw,
                "dice_raw_u32": dice_raw,
                "dice_offset_in_record": dice_offset,
                "reward_key_hex": key_hex,
                "reward_type": reward.get("type", ""),
                "reward_id": reward.get("id", ""),
                "reward_name": reward.get("name", ""),
                "reward_rank": reward.get("rank"),
                "quantity": guess_quantity(chunk_hex, key_hex, result_type),
                "timestamp_raw_hex": timestamp_raw.hex(),
                "timestamp_ticks": timestamp_ticks,
                "timestamp_unix": f"{timestamp_unix:.6f}",
                "timestamp_decoded": timestamp_decoded,
                "record_hex": full_record.hex(),
            }
        )
        prev = marker_offset + len(marker) + 8
    return rows
