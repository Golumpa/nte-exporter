import re
import struct

ACHIEVEMENT_RECORD_MARKER = b"AchievementRecord\0"
ACHIEVEMENT_ID = re.compile(rb"([A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+)\0")
RECORD_COUNT_OFFSET = 22
RECORDS_OFFSET = 38
COMPLETION_TICKS_OFFSET = 8
MAX_ACHIEVEMENTS = 1_000


def extract_achievement_ids(stream: bytes) -> list[str]:
    for block in _game_data_blocks(stream):
        decoded = _decompress_lz4_block(block)
        marker = decoded.find(ACHIEVEMENT_RECORD_MARKER)
        if marker < 0:
            continue
        achievement_ids = _completed_achievement_ids(decoded, marker)
        if achievement_ids:
            return achievement_ids
    return []


def reassemble_tcp_segments(segments: list[tuple[int, bytes]]) -> bytes:
    if not segments:
        return b""
    output = bytearray()
    start = min(sequence for sequence, _payload in segments)
    for sequence, payload in sorted(set(segments)):
        offset = sequence - start
        if offset > len(output):
            return b""
        output.extend(payload[max(0, len(output) - offset) :])
    return bytes(output)


def _completed_achievement_ids(decoded: bytes, marker: int) -> list[str]:
    # The component header stores its record count before a fixed schema descriptor.
    if marker + RECORDS_OFFSET > len(decoded):
        return []
    count = struct.unpack_from("<I", decoded, marker + RECORD_COUNT_OFFSET)[0]
    if count > MAX_ACHIEVEMENTS:
        return []
    matches = list(ACHIEVEMENT_ID.finditer(decoded, marker + RECORDS_OFFSET))
    if len(matches) < count:
        return []
    completed = []
    for match in matches[:count]:
        # Each name is followed by progress, then a zero timestamp until completion.
        ticks_offset = match.end() + COMPLETION_TICKS_OFFSET
        if ticks_offset + 8 > len(decoded):
            return []
        if struct.unpack_from("<Q", decoded, ticks_offset)[0]:
            completed.append(match.group(1).decode("ascii"))
    return completed


def _game_data_blocks(stream: bytes):
    position = 0
    while position + 4 <= len(stream):
        frame_size = struct.unpack_from("<I", stream, position)[0]
        frame_end = position + 4 + frame_size
        if not frame_size or frame_end > len(stream):
            return
        frame = stream[position + 4 : frame_end]
        if len(frame) < 4:
            return
        header_size = struct.unpack_from("<I", frame)[0]
        size_offset = 12 + header_size
        data_offset = size_offset + 4
        if data_offset <= len(frame):
            data_size = struct.unpack_from("<I", frame, size_offset)[0]
            if data_size and data_offset + data_size <= len(frame):
                yield frame[data_offset : data_offset + data_size]
        position = frame_end


def _decompress_lz4_block(data: bytes) -> bytes:
    output = bytearray()
    position = 0
    while position < len(data):
        if len(data) - position <= 3 and not any(data[position:]):
            break
        token = data[position]
        position += 1
        literal_length, position = _lz4_length(data, position, token >> 4)
        literal_end = position + literal_length
        if literal_end > len(data):
            return b""
        output.extend(data[position:literal_end])
        position = literal_end
        if position == len(data) or (
            len(data) - position <= 3 and not any(data[position:])
        ):
            break
        if position + 2 > len(data):
            return b""
        offset = struct.unpack_from("<H", data, position)[0]
        position += 2
        if not offset or offset > len(output):
            return b""
        match_length, position = _lz4_length(data, position, token & 15)
        for _ in range(match_length + 4):
            output.append(output[-offset])
    return bytes(output)


def _lz4_length(data: bytes, position: int, length: int) -> tuple[int, int]:
    if length != 15:
        return length, position
    while position < len(data):
        value = data[position]
        position += 1
        length += value
        if value != 255:
            return length, position
    return length, position
