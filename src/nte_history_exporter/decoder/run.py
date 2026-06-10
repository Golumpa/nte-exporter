from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nte_history_exporter.constants import POOL_META
from nte_history_exporter.decoder.protocol import decode_response_records


def fmt_packet_time(ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def build_rows_from_pairs(pairs: list[tuple]) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    for pair in pairs:
        page, offset, req_i, req_ts, resp_i, resp_ts, response_content = pair[:7]
        kind = pair[7] if len(pair) > 7 else "permanent"
        pool = POOL_META.get(kind, POOL_META["permanent"])
        records = decode_response_records(response_content)
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
        for record in records:
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
                }
            )
    return rows_out
