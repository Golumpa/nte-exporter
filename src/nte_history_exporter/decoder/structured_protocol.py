from __future__ import annotations

import struct
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Literal


RecordType = Literal["monopoly", "fork"]

MONOPOLY_MARKER = b"FMonopolyLotteryRecordData"
FORK_MARKER = b"FForkLotteryRecordData"
MAX_ROWS_PER_BLOCK = 100
MAX_STRING_LENGTH = 256
DOTNET_EPOCH_TICKS = 621_355_968_000_000_000
DOTNET_TICKS_PER_SECOND = 10_000_000
MIN_UNIX_SECONDS = 1_500_000_000
MAX_UNIX_SECONDS = 4_102_444_800
PROTOCOL_CONSTANT = 0x03000000
MONOPOLY_BLOCK_KIND = 527
FORK_BLOCK_KIND = 5906
MONOPOLY_ENVELOPE_FOOTER = 1_774_080


class StructuredProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class StructuredRecord:
    record_type: RecordType
    item_id: str
    count: int
    ticks: int
    timestamp_unix: float
    timestamp_decoded: str
    pool_id: str | None
    roll_points_raw: int | None
    secondary_item_id: str | None
    secondary_count: int | None
    record_start: int
    record_end: int
    record_hex: str
    protocol_view: str
    source_index: int | None = None
    generation_index: int | None = None


@dataclass(frozen=True)
class ProtocolEnvelope:
    record_type: RecordType
    stream_key: str
    page_index: int
    query_high: bool
    segment_index: int


@dataclass(frozen=True)
class StructuredBlock:
    record_type: RecordType
    marker_offset: int
    declared_size: int
    rows: tuple[StructuredRecord, ...]
    envelope: ProtocolEnvelope | None


@dataclass
class _Generation:
    index: int
    segments: dict[int, StructuredBlock] = field(default_factory=dict)


@dataclass
class _Stream:
    generations: list[_Generation] = field(default_factory=list)


class StructuredProtocolAssembler:
    """Assemble retransmitted and overlapping structured snapshot segments."""

    def __init__(self) -> None:
        self._stream_order: list[str] = []
        self._streams: dict[str, _Stream] = {}
        self._legacy_rows: list[StructuredRecord] = []
        self.warnings: list[dict[str, str | int]] = []

    def add_blocks(self, blocks: list[StructuredBlock]) -> None:
        for block in blocks:
            self.add_block(block)

    def add_block(self, block: StructuredBlock) -> bool:
        envelope = block.envelope
        if envelope is None:
            if not self._legacy_rows:
                self._stream_order.append("__legacy__")
            self._legacy_rows.extend(block.rows)
            return True

        stream = self._streams.get(envelope.stream_key)
        if stream is None:
            stream = _Stream()
            self._streams[envelope.stream_key] = stream
            self._stream_order.append(envelope.stream_key)
        if not stream.generations:
            stream.generations.append(_Generation(0))
        generation = stream.generations[-1]
        existing = generation.segments.get(envelope.segment_index)
        if existing is not None:
            if _block_signature(existing) == _block_signature(block):
                return False
            generation = _Generation(len(stream.generations))
            stream.generations.append(generation)
        generation.segments[envelope.segment_index] = block
        return True

    def rows(self, record_type: RecordType | None = None) -> list[StructuredRecord]:
        rows: list[StructuredRecord] = []
        for stream_key in self._stream_order:
            if stream_key == "__legacy__":
                rows.extend(
                    row
                    for row in self._legacy_rows
                    if record_type is None or row.record_type == record_type
                )
                continue
            assembled = self._assemble_stream(stream_key, self._streams[stream_key])
            rows.extend(row for row in assembled if record_type is None or row.record_type == record_type)
        return rows

    def _assemble_stream(self, stream_key: str, stream: _Stream) -> list[StructuredRecord]:
        result: list[StructuredRecord] = []
        result_max_segment: int | None = None
        for generation in stream.generations:
            if not generation.segments:
                continue
            generation_rows = _generation_rows(generation)
            segment_indexes = sorted(generation.segments)
            generation_min = segment_indexes[0]
            generation_max = segment_indexes[-1]
            if not result:
                result = generation_rows
                result_max_segment = generation_max
                continue
            if generation_min == 0:
                if result_max_segment is None or generation_max >= result_max_segment:
                    result = generation_rows
                    result_max_segment = generation_max
                    continue
                merged = _partial_snapshot_merge(generation_rows, result)
                if merged is not None:
                    result = merged
                else:
                    self._warn(stream_key, generation, "partial snapshot cannot be merged safely")
                continue
            if result_max_segment is not None and generation_min > result_max_segment:
                result.extend(generation_rows)
                result_max_segment = generation_max
                continue
            self._warn(stream_key, generation, "non-zero snapshot reset cannot be merged safely")
        return result

    def _warn(self, stream_key: str, generation: _Generation, message: str) -> None:
        warning = {
            "code": "AMBIGUOUS_STRUCTURED_SNAPSHOT",
            "stream_key": stream_key,
            "generation_index": generation.index,
            "message": message,
        }
        if warning not in self.warnings:
            self.warnings.append(warning)


def parse_structured_records(payload: bytes, record_type: RecordType) -> list[StructuredRecord]:
    """Parse typed history blocks from raw or bit-shifted protocol payloads.

    Invalid candidates are ignored deliberately: callers use this parser only
    as enrichment/fallback and retain the established decoder as their primary
    path.
    """
    assembler = StructuredProtocolAssembler()
    assembler.add_blocks(parse_structured_blocks(payload, record_type))
    return assembler.rows(record_type)


def parse_structured_blocks(
    payload: bytes,
    record_type: RecordType,
    *,
    source_index: int | None = None,
) -> list[StructuredBlock]:
    marker = MONOPOLY_MARKER if record_type == "monopoly" else FORK_MARKER
    for view_name, data in _iter_protocol_views(payload):
        if marker not in data:
            continue
        blocks: list[StructuredBlock] = []
        search_from = 0
        while True:
            marker_pos = data.find(marker, search_from)
            if marker_pos < 0:
                break
            try:
                parsed = _parse_block(
                    data, marker_pos, record_type, marker, view_name, source_index
                )
            except (StructuredProtocolError, UnicodeDecodeError):
                parsed = None
            if parsed is not None:
                blocks.append(parsed)
            search_from = marker_pos + len(marker)
        if blocks:
            return blocks
    return []


def _parse_block(
    data: bytes,
    marker_pos: int,
    record_type: RecordType,
    marker: bytes,
    view_name: str,
    source_index: int | None,
) -> StructuredBlock:
    envelope = _parse_protocol_envelope(record_type, data, marker_pos, view_name)
    pos = marker_pos + len(marker)
    if _byte_at(data, pos) == 0:
        pos += 1
    _reserved = _u32_at(data, pos)
    declared_size = _u32_at(data, pos + 4)
    row_count = _u32_at(data, pos + 8)
    pos += 12
    if row_count > MAX_ROWS_PER_BLOCK:
        raise StructuredProtocolError(f"row count is too large: {row_count}")
    if declared_size > len(data) - pos:
        raise StructuredProtocolError("declared block size exceeds payload")

    reader = _Reader(data, pos)
    records = []
    for _row_index in range(row_count):
        row_start = reader.pos
        if record_type == "monopoly":
            record = _parse_monopoly_row(reader, row_start, view_name, source_index)
        else:
            record = _parse_fork_row(reader, row_start, view_name, source_index)
        records.append(record)
    return StructuredBlock(
        record_type=record_type,
        marker_offset=marker_pos,
        declared_size=declared_size,
        rows=tuple(records),
        envelope=envelope,
    )


def _parse_monopoly_row(
    reader: "_Reader", row_start: int, view_name: str, source_index: int | None
) -> StructuredRecord:
    roll_points_raw = reader.u32()
    item_spec = reader.string()
    _reserved = reader.u32()
    secondary_count = reader.u32()
    secondary_item_id = reader.string()
    result_or_pool = reader.string()

    pool_pos = reader.pos
    possible_pool = reader.try_string()
    if possible_pool and possible_pool.startswith("CardPool_"):
        pool_id = possible_pool
    else:
        reader.pos = pool_pos
        pool_id = result_or_pool if result_or_pool.startswith("CardPool_") else None

    ticks = reader.u64()
    return _make_record(
        reader,
        "monopoly",
        item_spec,
        ticks,
        pool_id,
        roll_points_raw,
        secondary_item_id or None,
        secondary_count,
        row_start,
        view_name,
        source_index,
    )


def _parse_fork_row(
    reader: "_Reader", row_start: int, view_name: str, source_index: int | None
) -> StructuredRecord:
    item_spec = reader.string()
    pool_id = reader.string()
    ticks = reader.u64()
    return _make_record(
        reader,
        "fork",
        item_spec,
        ticks,
        pool_id or None,
        None,
        None,
        None,
        row_start,
        view_name,
        source_index,
    )


def _make_record(
    reader: "_Reader",
    record_type: RecordType,
    item_spec: str,
    ticks: int,
    pool_id: str | None,
    roll_points_raw: int | None,
    secondary_item_id: str | None,
    secondary_count: int | None,
    row_start: int,
    view_name: str,
    source_index: int | None,
) -> StructuredRecord:
    item_id, count = _parse_item_spec(item_spec)
    if not item_id:
        raise StructuredProtocolError("structured item ID is empty")
    timestamp_unix = (ticks - DOTNET_EPOCH_TICKS) / DOTNET_TICKS_PER_SECOND
    if not MIN_UNIX_SECONDS <= timestamp_unix <= MAX_UNIX_SECONDS:
        raise StructuredProtocolError("structured timestamp is out of range")
    timestamp_decoded = datetime.fromtimestamp(timestamp_unix, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return StructuredRecord(
        record_type=record_type,
        item_id=item_id,
        count=count,
        ticks=ticks,
        timestamp_unix=timestamp_unix,
        timestamp_decoded=timestamp_decoded,
        pool_id=pool_id,
        roll_points_raw=roll_points_raw,
        secondary_item_id=secondary_item_id,
        secondary_count=secondary_count,
        record_start=row_start,
        record_end=reader.pos,
        record_hex=reader.data[row_start : reader.pos].hex(),
        protocol_view=view_name,
        source_index=source_index,
    )


def _parse_item_spec(value: str) -> tuple[str, int]:
    item_id, separator, raw_count = value.rpartition(",")
    if separator:
        try:
            count = int(raw_count)
        except ValueError:
            count = 0
        if item_id and count > 0:
            return item_id, count
    return value, 1


def _parse_protocol_envelope(
    record_type: RecordType,
    data: bytes,
    marker_pos: int,
    view_name: str,
) -> ProtocolEnvelope | None:
    if marker_pos == 0 or not view_name.startswith("shift8:"):
        return None
    if record_type == "monopoly":
        if marker_pos < 26:
            raise StructuredProtocolError("monopoly envelope is truncated")
        protocol_constant = _relative_u32(data, marker_pos, -26)
        query_raw = _relative_u32(data, marker_pos, -22)
        page_raw = _relative_u32(data, marker_pos, -18)
        block_kind = _relative_u32(data, marker_pos, -14)
        pool_token = _relative_u32(data, marker_pos, -10)
        footer = _relative_u32(data, marker_pos, -6)
        if (
            protocol_constant != PROTOCOL_CONSTANT
            or block_kind != MONOPOLY_BLOCK_KIND
            or footer != MONOPOLY_ENVELOPE_FOOTER
        ):
            raise StructuredProtocolError("invalid monopoly envelope constants")
        stream_key = f"monopoly:{pool_token}"
    else:
        if marker_pos < 17:
            raise StructuredProtocolError("fork envelope is truncated")
        protocol_constant = _relative_u32(data, marker_pos, -17)
        query_raw = _relative_u32(data, marker_pos, -13)
        page_raw = _relative_u32(data, marker_pos, -9)
        block_kind = _relative_u32(data, marker_pos, -5)
        if protocol_constant != PROTOCOL_CONSTANT or block_kind != FORK_BLOCK_KIND:
            raise StructuredProtocolError("invalid fork envelope constants")
        stream_key = "fork"
    page_index = page_raw & 0x7FFFFFFF
    query_high = bool(query_raw & 0x80000000)
    return ProtocolEnvelope(
        record_type=record_type,
        stream_key=stream_key,
        page_index=page_index,
        query_high=query_high,
        segment_index=_segment_index(page_index, query_high),
    )


def _segment_index(page_index: int, query_high: bool) -> int:
    if query_high:
        return page_index * 2
    if page_index > 0:
        return page_index * 2 - 1
    raise StructuredProtocolError("low query cannot describe page zero")


def _row_signature(row: StructuredRecord) -> tuple:
    return (
        row.record_type,
        row.ticks,
        row.pool_id,
        row.item_id,
        row.count,
        row.roll_points_raw,
        row.secondary_item_id,
        row.secondary_count,
    )


def _block_signature(block: StructuredBlock) -> tuple:
    return block.record_type, tuple(_row_signature(row) for row in block.rows)


def _generation_rows(generation: _Generation) -> list[StructuredRecord]:
    rows = []
    for segment_index in sorted(generation.segments):
        block = generation.segments[segment_index]
        rows.extend(replace(row, generation_index=generation.index) for row in block.rows)
    return rows


def _partial_snapshot_merge(
    new_rows: list[StructuredRecord], old_rows: list[StructuredRecord]
) -> list[StructuredRecord] | None:
    if not new_rows:
        return list(old_rows)
    if not old_rows:
        return list(new_rows)
    new_signatures = [_row_signature(row) for row in new_rows]
    old_signatures = [_row_signature(row) for row in old_rows]
    max_overlap = min(len(new_signatures), len(old_signatures))
    matches: list[tuple[int, int]] = []
    for overlap in range(max_overlap, 0, -1):
        suffix = new_signatures[-overlap:]
        for position in range(len(old_signatures) - overlap + 1):
            if old_signatures[position : position + overlap] == suffix:
                matches.append((overlap, position))
        if matches:
            break
    if len(matches) != 1:
        return None
    overlap, position = matches[0]
    return [*new_rows, *old_rows[position + overlap :]]


class _Reader:
    def __init__(self, data: bytes, pos: int) -> None:
        self.data = data
        self.pos = pos

    def u32(self) -> int:
        value = _u32_at(self.data, self.pos)
        self.pos += 4
        return value

    def u64(self) -> int:
        value = _u64_at(self.data, self.pos)
        self.pos += 8
        return value

    def string(self) -> str:
        length_pos = self.pos
        length = self.u32()
        if length == 0 or length > MAX_STRING_LENGTH:
            raise StructuredProtocolError(f"invalid string length {length} at {length_pos}")
        end = self.pos + length
        raw = self.data[self.pos:end]
        if len(raw) != length:
            raise StructuredProtocolError("string exceeds payload")
        self.pos = end
        if raw.endswith(b"\0"):
            raw = raw[:-1]
        return raw.decode("utf-8")

    def try_string(self) -> str | None:
        start = self.pos
        try:
            return self.string()
        except (StructuredProtocolError, UnicodeDecodeError):
            self.pos = start
            return None


def _iter_protocol_views(payload: bytes):
    yield "raw", payload
    for bit_shift in range(1, 8):
        shifted = _decode_shifted_bytes(payload, byte_offset=8, bit_shift=bit_shift)
        yield f"shift8:{bit_shift}", shifted


def _decode_shifted_bytes(data: bytes, *, byte_offset: int, bit_shift: int) -> bytes:
    result = bytearray()
    count = max(0, len(data) - byte_offset)
    for index in range(count):
        bit_pos = (byte_offset + index) * 8 + bit_shift
        byte_pos, shift = divmod(bit_pos, 8)
        if byte_pos >= len(data):
            break
        value = data[byte_pos] >> shift
        if shift and byte_pos + 1 < len(data):
            value |= data[byte_pos + 1] << (8 - shift)
        result.append(value & 0xFF)
    return bytes(result)


def _byte_at(data: bytes, pos: int) -> int:
    try:
        return data[pos]
    except IndexError as exc:
        raise StructuredProtocolError("byte exceeds payload") from exc


def _u32_at(data: bytes, pos: int) -> int:
    try:
        return struct.unpack_from("<I", data, pos)[0]
    except struct.error as exc:
        raise StructuredProtocolError("u32 exceeds payload") from exc


def _relative_u32(data: bytes, marker_pos: int, relative_pos: int) -> int:
    pos = marker_pos + relative_pos
    if pos < 0:
        raise StructuredProtocolError("envelope position precedes payload")
    return _u32_at(data, pos)


def _u64_at(data: bytes, pos: int) -> int:
    try:
        return struct.unpack_from("<Q", data, pos)[0]
    except struct.error as exc:
        raise StructuredProtocolError("u64 exceeds payload") from exc
