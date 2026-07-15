from __future__ import annotations

import struct
from dataclasses import dataclass
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


def parse_structured_records(payload: bytes, record_type: RecordType) -> list[StructuredRecord]:
    """Parse typed history blocks from raw or bit-shifted protocol payloads.

    Invalid candidates are ignored deliberately: callers use this parser only
    as enrichment/fallback and retain the established decoder as their primary
    path.
    """
    marker = MONOPOLY_MARKER if record_type == "monopoly" else FORK_MARKER
    for view_name, data in _iter_protocol_views(payload):
        if marker not in data:
            continue
        records: list[StructuredRecord] = []
        search_from = 0
        while True:
            marker_pos = data.find(marker, search_from)
            if marker_pos < 0:
                break
            try:
                parsed = _parse_block(data, marker_pos, record_type, marker, view_name)
            except (StructuredProtocolError, UnicodeDecodeError):
                parsed = []
            records.extend(parsed)
            search_from = marker_pos + len(marker)
        if records:
            return records
    return []


def _parse_block(
    data: bytes,
    marker_pos: int,
    record_type: RecordType,
    marker: bytes,
    view_name: str,
) -> list[StructuredRecord]:
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
            record = _parse_monopoly_row(reader, row_start, view_name)
        else:
            record = _parse_fork_row(reader, row_start, view_name)
        records.append(record)
    return records


def _parse_monopoly_row(reader: "_Reader", row_start: int, view_name: str) -> StructuredRecord:
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
    )


def _parse_fork_row(reader: "_Reader", row_start: int, view_name: str) -> StructuredRecord:
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


def _u64_at(data: bytes, pos: int) -> int:
    try:
        return struct.unpack_from("<Q", data, pos)[0]
    except struct.error as exc:
        raise StructuredProtocolError("u64 exceeds payload") from exc
