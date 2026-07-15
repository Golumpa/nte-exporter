from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nte_history_exporter.constants import POOL_META
from nte_history_exporter.decoder.protocol import decode_response_records, structured_monopoly_rows
from nte_history_exporter.decoder.structured_protocol import (
    StructuredProtocolAssembler,
    parse_structured_blocks,
)


def fmt_packet_time(ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def _build_primary_rows_from_pairs(pairs: list[tuple]) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    for pair in pairs:
        page, offset, req_i, req_ts, resp_i, resp_ts, response_content = pair[:7]
        kind = pair[7] if len(pair) > 7 else "permanent"
        pool = POOL_META.get(kind, POOL_META["permanent"])
        records = decode_response_records(response_content)
        if len(pair) > 9:
            slice_start, slice_count = pair[8:10]
            records = records[slice_start : slice_start + slice_count]
        if not records:
            rows_out.append(
                {
                    "page": page,
                    "offset": offset,
                    "row": "",
                    "pool_group_id": pool["id"],
                    "pool_group_name": pool["name"],
                    "request_msg": req_i,
                    "request_time_utc": fmt_packet_time(req_ts),
                    "response_msg": resp_i,
                    "response_time_utc": fmt_packet_time(resp_ts),
                    "response_len": len(response_content),
                    "record_count": 0,
                    "record_hex": response_content.hex(),
                }
            )
            continue
        for row_index, record in enumerate(records, start=1):
            rows_out.append(
                {
                    "page": page,
                    "offset": offset,
                    "pool_group_id": pool["id"],
                    "pool_group_name": pool["name"],
                    "request_msg": req_i,
                    "request_time_utc": fmt_packet_time(req_ts),
                    "response_msg": resp_i,
                    "response_time_utc": fmt_packet_time(resp_ts),
                    "response_len": len(response_content),
                    "record_count": len(records),
                    **record,
                    "row": row_index,
                }
            )
    return rows_out


def build_rows_from_pairs(pairs: list[tuple]) -> list[dict[str, Any]]:
    primary_rows = _build_primary_rows_from_pairs(pairs)
    decoded_rows = [row for row in primary_rows if row.get("record_count", 0)]
    if decoded_rows and any(row.get("decoder_mode") != "structured_fallback" for row in decoded_rows):
        return primary_rows

    assembler = StructuredProtocolAssembler()
    for source_index, pair in enumerate(pairs):
        assembler.add_blocks(
            parse_structured_blocks(pair[6], "monopoly", source_index=source_index)
        )
    assembled = assembler.rows("monopoly")
    if not assembled:
        return primary_rows

    rows_out: list[dict[str, Any]] = []
    converted = structured_monopoly_rows(assembled)
    for row_index, (record, structured) in enumerate(zip(converted, assembled), start=1):
        source_index = structured.source_index or 0
        pair = pairs[source_index]
        page, offset, req_i, req_ts, resp_i, resp_ts, response_content = pair[:7]
        kind = pair[7] if len(pair) > 7 else "permanent"
        pool = POOL_META.get(kind, POOL_META["permanent"])
        rows_out.append(
            {
                "page": page,
                "offset": offset,
                "pool_group_id": pool["id"],
                "pool_group_name": pool["name"],
                "request_msg": req_i,
                "request_time_utc": fmt_packet_time(req_ts),
                "response_msg": resp_i,
                "response_time_utc": fmt_packet_time(resp_ts),
                "response_len": len(response_content),
                "record_count": len(assembled),
                **record,
                "row": row_index,
                "structured_assembly": "snapshot_segments",
                "structured_assembly_warning_count": len(assembler.warnings),
            }
        )
    return rows_out
