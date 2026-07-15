from tests.support import *  # noqa: F401,F403

from datetime import datetime, timezone

from nte_history_exporter.constants import MYSTERY_BOX_MARKER
from nte_history_exporter.decoder.mystery_box import (
    build_mystery_box_rows_from_pairs,
    is_mystery_box_history_request,
    mystery_box_request_page,
    parse_mystery_box_response,
)


def mystery_box_request(page: int) -> bytes:
    request = bytearray(54)
    request[26:30] = (2060).to_bytes(4, "little")
    request[31:35] = (page * 2).to_bytes(4, "little")
    request[35:39] = (2110).to_bytes(4, "little")
    request[40:44] = (2).to_bytes(4, "little")
    request[44:48] = (2060).to_bytes(4, "little")
    request[49:53] = (10).to_bytes(4, "little")
    request[53] = 6
    return bytes(request)


def mystery_box_response(records: list[tuple[str, int, datetime]]) -> bytes:
    body = bytearray()
    for reward_id, quantity, timestamp in records:
        encoded_id = reward_id.encode("utf-8") + b"\0"
        ticks = int(timestamp.timestamp() * 10_000_000) + 621_355_968_000_000_000
        body += len(encoded_id).to_bytes(4, "little")
        body += encoded_id
        body += quantity.to_bytes(4, "little")
        body += b"\x01"
        body += ticks.to_bytes(8, "little")
    return (
        bytes(50)
        + MYSTERY_BOX_MARKER
        + b"\0"
        + bytes(4)
        + len(body).to_bytes(4, "little")
        + len(records).to_bytes(4, "little")
        + body
        + b"\x03"
    )


class MysteryBoxDecodingTests(unittest.TestCase):
    def test_recognizes_request_and_page_cursor(self):
        request = mystery_box_request(6)
        self.assertTrue(is_mystery_box_history_request(request))
        self.assertEqual(mystery_box_request_page(request), 6)

    def test_decodes_exact_quantity_and_timestamp(self):
        timestamp = datetime(2026, 7, 8, 19, 9, 33, tzinfo=timezone.utc)
        rows = parse_mystery_box_response(
            mystery_box_response(
                [
                    ("vehicle039", 1, timestamp),
                    ("SpecialGift_ticket", 3, timestamp),
                    ("gold", 100_000, timestamp),
                ]
            )
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["reward_id"], "vehicle039")
        self.assertEqual(rows[0]["reward_name"], "Draco")
        self.assertEqual(rows[0]["timestamp_decoded"], "2026-07-08 19:09:33")
        self.assertEqual(rows[1]["quantity"], 3)
        self.assertEqual(rows[1]["result_type"], "single_pull")
        self.assertEqual(rows[2]["reward_name"], "Beetle Coin")
        self.assertEqual(rows[2]["reward_rank"], "B")

    def test_live_session_accepts_partial_final_page(self):
        session = LiveHistorySession("192.168.0.10")
        request = mystery_box_request(3)
        timestamp = datetime(2026, 7, 8, 19, 9, 33, tzinfo=timezone.utc)
        response = mystery_box_response(
            [("Fons", 100_000, timestamp), ("gold", 100_000, timestamp)]
        )
        self.assertFalse(
            session.process_packet(
                UdpPacket(1.0, "192.168.0.10", "203.0.113.5", 50000, 40000, request)
            )
        )
        self.assertTrue(
            session.process_packet(
                UdpPacket(1.1, "203.0.113.5", "192.168.0.10", 40000, 50000, response)
            )
        )
        self.assertEqual(session.kinds_seen(), ["mystery_box"])
        self.assertEqual(session.pairs[0][0], 3)
        self.assertEqual(session.pairs[0][8:10], (0, 2))

    def test_rows_and_export_use_non_shared_mystery_box_banner(self):
        timestamp = datetime(2026, 7, 8, 19, 9, 33, tzinfo=timezone.utc)
        response = mystery_box_response([("Fons", 100_000, timestamp)])
        rows = build_mystery_box_rows_from_pairs(
            [(1, 2, 1, 1.0, 2, 1.1, response, "mystery_box", 0, 1)]
        )
        export = build_export_json(rows, [])
        self.assertEqual(export["banner"]["id"], "Gashapon_MysteryBox")
        self.assertEqual(export["banner"]["name"], "Mystery Box")
        self.assertIs(export["banner"]["shared_pity"], False)
        self.assertEqual(export["records"][0]["result_type"], "single_pull")
        self.assertEqual(export["records"][0]["quantity"], 100_000)
        self.assertNotIn("roll_result", export["records"][0])
        self.assertEqual(rows[0]["timestamp_group_size_seen"], 1)
        self.assertEqual(rows[0]["uid_status"], "stable")

    def test_export_path_uses_mystery_box_prefix(self):
        _csv_path, json_path = export_paths("mystery_box", "218216016349")
        self.assertRegex(
            json_path.name,
            r"^218216016349_MysteryBox_\d{8}_\d{6}(?:_\d+)?\.json$",
        )
