from __future__ import annotations

from collections import Counter, deque
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
    decode_response_records,
    history_request_kind,
    is_history_request,
    request_page,
    response_contains_history_marker,
)
from nte_history_exporter.decoder.run import build_rows_from_pairs
from nte_history_exporter.decoder.mystery_box import (
    build_mystery_box_rows_from_pairs,
    is_mystery_box_history_request,
    mystery_box_request_page,
    parse_mystery_box_response,
    select_continuous_mystery_box_run,
)
from nte_history_exporter.decoder.structured_protocol import FORK_MARKER, MONOPOLY_MARKER
from nte_history_exporter.constants import MYSTERY_BOX_MARKER
from nte_history_exporter.decoder.user_uid import extract_user_uid_candidates
from nte_history_exporter.live_capture.diagnostics import CaptureDiagnostics


@dataclass
class UdpPacket:
    timestamp: float
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    payload: bytes
    protocol: str = "udp"


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
    response_candidates: int = 0
    response_candidate_lengths: tuple[int, ...] = ()


class LiveHistorySession:
    def __init__(self, local_ip: str) -> None:
        self.local_ip = local_ip
        self.pending: deque[PendingRequest] = deque()
        self.pairs: list[tuple] = []
        self.packet_count = 0
        self.last_match_time: float | None = None
        self.last_page_seen: int | None = None
        self.last_capture_was_replacement = False
        self.requested_pages: dict[str, set[int]] = {}
        self.unanswered_pages: dict[str, dict[int, str]] = {}
        self.user_uid: str | None = None
        self.user_uid_candidates: Counter[str] = Counter()
        self.diagnostics = CaptureDiagnostics()

    def _mark_unanswered(self, request: PendingRequest) -> None:
        if request.response_candidates:
            lengths = ", ".join(str(length) for length in request.response_candidate_lengths)
            reason = (
                f"{request.response_candidates} matching inbound UDP packet(s) captured "
                f"but not recognized as history response (lengths: {lengths})"
            )
        else:
            reason = "request captured; no matching response page was captured"
        self.unanswered_pages.setdefault(request.kind, {})[request.page] = reason

    def _queue_request(self, request: PendingRequest) -> None:
        # The game may pipeline several page requests before responses arrive,
        # and one response can contain multiple five-record pages. Keep that
        # queue intact; only replace an earlier duplicate request for the same
        # page, such as a recovery pass after reopening the history board.
        retained = deque()
        for pending in self.pending:
            same_stream = (
                pending.src_ip == request.src_ip
                and pending.dst_ip == request.dst_ip
                and pending.src_port == request.src_port
                and pending.dst_port == request.dst_port
                and pending.kind == request.kind
            )
            if same_stream and (request.page == 1 or pending.page == request.page):
                self._mark_unanswered(pending)
                self.diagnostics.add_event(
                    "REQUEST_REPLACED",
                    request.request_msg,
                    reason=True,
                    kind=pending.kind,
                    page=pending.page,
                    response_candidates=pending.response_candidates,
                )
            else:
                retained.append(pending)
        self.pending = retained
        self.requested_pages.setdefault(request.kind, set()).add(request.page)
        self.pending.append(request)

    def process_packet(self, packet: UdpPacket) -> bool:
        self.packet_count += 1
        self.diagnostics.observe_packet(packet.protocol)
        candidates = extract_user_uid_candidates(packet.payload)
        if candidates:
            self.user_uid_candidates.update(candidates)
            self.user_uid = self.user_uid_candidates.most_common(1)[0][0]
        if packet.protocol != "udp":
            return False

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
            self._queue_request(req)
            self.diagnostics.counters["history_requests_recognized"] += 1
            self.diagnostics.add_event(
                "HISTORY_REQUEST_RECOGNIZED",
                self.packet_count,
                kind=req.kind,
                page=req.page,
            )
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
            self._queue_request(req)
            self.diagnostics.counters["history_requests_recognized"] += 1
            self.diagnostics.add_event(
                "HISTORY_REQUEST_RECOGNIZED",
                self.packet_count,
                kind=req.kind,
                page=req.page,
            )
            self.last_page_seen = req.page
            return False

        if packet.src_ip == self.local_ip and is_mystery_box_history_request(packet.payload):
            page = mystery_box_request_page(packet.payload)
            req = PendingRequest(
                page=page,
                offset=page * 2,
                kind="mystery_box",
                request_msg=self.packet_count,
                request_time=packet.timestamp,
                src_ip=packet.src_ip,
                dst_ip=packet.dst_ip,
                src_port=packet.src_port,
                dst_port=packet.dst_port,
            )
            self._queue_request(req)
            self.diagnostics.counters["history_requests_recognized"] += 1
            self.diagnostics.add_event(
                "HISTORY_REQUEST_RECOGNIZED",
                self.packet_count,
                kind=req.kind,
                page=req.page,
            )
            self.last_page_seen = req.page
            return False

        if packet.dst_ip != self.local_ip:
            return False

        connection_candidates = [
            req
            for req in self.pending
            if (
                packet.src_ip == req.dst_ip
                and packet.dst_ip == req.src_ip
                and packet.src_port == req.dst_port
                and packet.dst_port == req.src_port
            )
        ]
        if not connection_candidates:
            return False

        if len(packet.payload) < 100:
            self._record_rejected_candidate(
                connection_candidates,
                packet.payload,
                "RESPONSE_TOO_SHORT",
            )
            return False

        monopoly_records = decode_response_records(packet.payload)
        arc_records = parse_arc_response(packet.payload) if not monopoly_records else []
        mystery_box_records = (
            parse_mystery_box_response(packet.payload)
            if not monopoly_records and not arc_records
            else []
        )
        if monopoly_records:
            candidates = [
                req
                for req in connection_candidates
                if req.kind not in {"arc_miracle_box", "mystery_box"}
            ]
            records = monopoly_records
        elif arc_records:
            candidates = [req for req in connection_candidates if req.kind == "arc_miracle_box"]
            records = arc_records
        elif mystery_box_records:
            candidates = [req for req in connection_candidates if req.kind == "mystery_box"]
            records = mystery_box_records
        else:
            candidates = connection_candidates
            records = []

        if records and not candidates:
            self._record_rejected_candidate(
                connection_candidates,
                packet.payload,
                "RESPONSE_KIND_MISMATCH",
            )
            return False

        if not records:
            reason = (
                "HISTORY_MARKER_PARSE_FAILED"
                if response_contains_history_marker(packet.payload)
                or MONOPOLY_MARKER in packet.payload
                or FORK_MARKER in packet.payload
                or MYSTERY_BOX_MARKER in packet.payload
                else "NO_HISTORY_MARKER"
            )
            self._record_rejected_candidate(candidates, packet.payload, reason)
            return False

        decoder_modes = sorted({record.get("decoder_mode", "heuristic") for record in records})
        self.diagnostics.counters["history_responses_decoded"] += 1
        self.diagnostics.add_event(
            "HISTORY_RESPONSE_DECODED",
            self.packet_count,
            kind=candidates[0].kind,
            payload_length=len(packet.payload),
            record_count=len(records),
            decoder_modes=decoder_modes,
        )

        page_count = max(1, (len(records) + 4) // 5)
        if len(records) < 5:
            selected = [candidates[-1]]
        else:
            selected = candidates[:page_count]

        for page_slice, req in enumerate(selected):
            self.pending.remove(req)
            self.unanswered_pages.setdefault(req.kind, {}).pop(req.page, None)
            slice_start = page_slice * 5
            slice_count = min(5, len(records) - slice_start)
            if slice_count <= 0:
                break
            self.last_capture_was_replacement = any(
                pair[0] == req.page and (pair[7] if len(pair) > 7 else "permanent") == req.kind
                for pair in self.pairs
            )
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
                    slice_start,
                    slice_count,
                )
            )
            self.last_match_time = packet.timestamp
            self.last_page_seen = req.page
            self.diagnostics.counters["pages_matched"] += 1
            self.diagnostics.add_event(
                "PAGE_RESPONSE_MATCHED",
                self.packet_count,
                kind=req.kind,
                page=req.page,
                record_count=slice_count,
            )

        return bool(selected)

    def _record_rejected_candidate(
        self,
        requests: list[PendingRequest],
        payload: bytes,
        reason: str,
    ) -> None:
        for req in requests:
            req.response_candidates += 1
            req.response_candidate_lengths = (
                *req.response_candidate_lengths[-4:],
                len(payload),
            )
        self.diagnostics.counters["response_candidates_rejected"] += 1
        self.diagnostics.add_event(
            reason,
            self.packet_count,
            reason=True,
            kind=requests[0].kind if requests else None,
            page=requests[0].page if requests else None,
            payload_length=len(payload),
            matching_requests=len(requests),
        )

    def diagnostic_report(self) -> dict[str, Any]:
        return self.diagnostics.report(self.pending)

    def kinds_seen(self) -> list[str]:
        seen = []
        for pair in self.pairs:
            kind = pair[7] if len(pair) > 7 else "permanent"
            if kind not in seen:
                seen.append(kind)
        return seen

    def pairs_for_kind(self, kind: str) -> list[tuple]:
        return [pair for pair in self.pairs if (pair[7] if len(pair) > 7 else "permanent") == kind]

    def missing_pages(self, kind: str) -> list[int]:
        pages = {pair[0] for pair in self.pairs_for_kind(kind)}
        if not pages:
            return []
        return [page for page in range(1, max(pages) + 1) if page not in pages]

    def missing_page_reason(self, kind: str, page: int) -> str:
        unanswered = self.unanswered_pages.get(kind, {})
        if page in unanswered:
            return unanswered[page]
        pending = next(
            (request for request in self.pending if request.kind == kind and request.page == page),
            None,
        )
        if pending and pending.response_candidates:
            lengths = ", ".join(str(length) for length in pending.response_candidate_lengths)
            return (
                f"{pending.response_candidates} matching inbound UDP packet(s) captured "
                f"but not recognized as history response (lengths: {lengths})"
            )
        if page in self.requested_pages.get(kind, set()):
            return "request captured; no matching response page was captured"
        return "request was not captured"

    def build_rows(self, kind: str | None = None) -> list[dict[str, Any]]:
        if kind == "arc_miracle_box":
            best_run, _warnings = select_continuous_arc_run(self.pairs_for_kind(kind))
            return build_arc_rows_from_pairs(best_run)
        if kind == "mystery_box":
            best_run, _warnings = select_continuous_mystery_box_run(self.pairs_for_kind(kind))
            return build_mystery_box_rows_from_pairs(best_run)
        return build_rows_from_pairs(self.best_run(kind))

    def best_run(self, kind: str | None = None) -> list[tuple]:
        pairs = self.pairs_for_kind(kind) if kind else self.pairs
        best_run, _warnings = select_continuous_run_from_page_1(pairs)
        return best_run
