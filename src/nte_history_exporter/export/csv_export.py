from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

FIELDNAMES = [
    "uid",
    "uid_status",
    "export_record",
    "skip_reason",
    "page",
    "offset",
    "row",
    "pool_group_id",
    "pool_group_name",
    "timestamp_group_index",
    "timestamp_group_ordinal",
    "timestamp_group_size_seen",
    "timestamp_group_record_size_seen",
    "timestamp_group_boundary",
    "roll_result",
    "result_type",
    "result_source_raw",
    "dice",
    "dice_raw_u32",
    "reward_type",
    "reward_id",
    "reward_name",
    "reward_rank",
    "quantity",
    "timestamp_decoded",
    "timestamp_raw_hex",
    "timestamp_ticks",
    "timestamp_unix",
    "reward_key_hex",
    "source_type",
    "type_key_hex",
    "request_msg",
    "request_time_utc",
    "response_msg",
    "response_time_utc",
    "response_len",
    "record_count",
    "record_start",
    "record_end",
    "record_len",
    "dice_offset_in_record",
    "record_hex",
]


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
