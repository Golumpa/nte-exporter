from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from nte_history_exporter.decoder.arc import (
    arc_request_page,
    build_arc_rows_from_pairs,
    is_arc_history_request,
    parse_arc_response,
    select_continuous_arc_run,
)
from nte_history_exporter.decoder.boundary import select_continuous_run_from_page_1
from nte_history_exporter.decoder.protocol import (
    history_request_kind,
    is_history_request,
    request_page,
    response_contains_history_marker,
)
from nte_history_exporter.decoder.run import build_rows_from_pairs


@dataclass
class UdpPacket:
    timestamp: float
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    payload: bytes


@dataclass
class PendingRequest:
    page: int
    offset: int
    kind: str
    request_msg: int
    request_time: float
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int


class LiveHistorySession:
    def __init__(self, local_ip: str) -> None:
        self.local_ip = local_ip
        self.pending: deque[PendingRequest] = deque()
        self.pairs: list[tuple] = []
        self.packet_count = 0
        self.last_match_time: float | None = None
        self.last_page_seen: int | None = None

    def process_packet(self, packet: UdpPacket) -> bool:
        self.packet_count += 1

        if packet.src_ip == self.local_ip and is_history_request(packet.payload):
            offset = int.from_bytes(packet.payload[31:35], "little")
            req = PendingRequest(
                page=request_page(packet.payload),
                offset=offset,
                kind=history_request_kind(packet.payload),
                request_msg=self.packet_count,
                request_time=packet.timestamp,
                src_ip=packet.src_ip,
                dst_ip=packet.dst_ip,
                src_port=packet.src_port,
                dst_port=packet.dst_port,
            )
            self.pending.append(req)
            self.last_page_seen = req.page
            return False

        if packet.src_ip == self.local_ip and is_arc_history_request(packet.payload):
            page = arc_request_page(packet.payload)
            req = PendingRequest(
                page=page,
                offset=page * 2,
                kind="arc_miracle_box",
                request_msg=self.packet_count,
                request_time=packet.timestamp,
                src_ip=packet.src_ip,
                dst_ip=packet.dst_ip,
                src_port=packet.src_port,
                dst_port=packet.dst_port,
            )
            self.pending.append(req)
            self.last_page_seen = req.page
            return False

        if packet.dst_ip != self.local_ip or len(packet.payload) < 100:
            return False

        is_monopoly_response = response_contains_history_marker(packet.payload)
        is_arc_response = bool(parse_arc_response(packet.payload))
        if not is_monopoly_response and not is_arc_response:
            return False

        for req in self.pending:
            if req.kind == "arc_miracle_box" and not is_arc_response:
                continue
            if req.kind != "arc_miracle_box" and not is_monopoly_response:
                continue
            if (
                packet.src_ip == req.dst_ip
                and packet.dst_ip == req.src_ip
                and packet.src_port == req.dst_port
                and packet.dst_port == req.src_port
            ):
                self.pending.remove(req)
                self.pairs.append(
                    (
                        req.page,
                        req.offset,
                        req.request_msg,
                        req.request_time,
                        self.packet_count,
                        packet.timestamp,
                        packet.payload,
                        req.kind,
                    )
                )
                self.last_match_time = packet.timestamp
                self.last_page_seen = req.page
                return True

        return False

    def kinds_seen(self) -> list[str]:
        seen = []
        for pair in self.pairs:
            kind = pair[7] if len(pair) > 7 else "permanent"
            if kind not in seen:
                seen.append(kind)
        return seen

    def pairs_for_kind(self, kind: str) -> list[tuple]:
        return [pair for pair in self.pairs if (pair[7] if len(pair) > 7 else "permanent") == kind]

    def build_rows(self, kind: str | None = None) -> list[dict[str, Any]]:
        if kind == "arc_miracle_box":
            best_run, _warnings = select_continuous_arc_run(self.pairs_for_kind(kind))
            return build_arc_rows_from_pairs(best_run)
        return build_rows_from_pairs(self.best_run(kind))

    def best_run(self, kind: str | None = None) -> list[tuple]:
        pairs = self.pairs_for_kind(kind) if kind else self.pairs
        best_run, _warnings = select_continuous_run_from_page_1(pairs)
        return best_run
