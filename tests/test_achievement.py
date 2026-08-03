import struct
import unittest

from nte_history_exporter.decoder.achievement import (
    ACHIEVEMENT_RECORD_MARKER,
    extract_achievement_ids,
    reassemble_tcp_segments,
)


class AchievementPacketTests(unittest.TestCase):
    def test_extracts_only_completed_achievements(self):
        header = ACHIEVEMENT_RECORD_MARKER + b"\0" * 4 + struct.pack("<I", 2) + b"\0" * 12
        completed = b"\x0a\0\0\0Battle_30\0" + b"\0" * 8 + struct.pack("<Q", 1)
        incomplete = b"\x13\0\0\0Playstation_035\0" + b"\0" * 16
        decoded = header + completed + incomplete
        extension = len(decoded) - 15
        compressed = b"\xf0" + bytes([extension]) + decoded
        frame = struct.pack("<I", 0) + b"\0" * 8 + struct.pack("<I", len(compressed)) + compressed
        stream = struct.pack("<I", len(frame)) + frame

        self.assertEqual(extract_achievement_ids(stream), ["Battle_30"])
        self.assertEqual(extract_achievement_ids(b"\x01\0\0\0\0"), [])

    def test_reassembles_tcp_data(self):
        self.assertEqual(
            reassemble_tcp_segments([(104, b"bar"), (100, b"foobar"), (100, b"foobar")]),
            b"foobarr",
        )
