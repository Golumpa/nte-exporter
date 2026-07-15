from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from nte_history_exporter.decoder.arc import parse_arc_response
from nte_history_exporter.decoder.protocol import decode_response_records
from nte_history_exporter.decoder.structured_protocol import (
    FORK_MARKER,
    MONOPOLY_MARKER,
    parse_structured_records,
)
from nte_history_exporter.export.csv_export import write_csv
from nte_history_exporter.export.json_export import build_export_json
from tests.support import fixture_payload


STRUCTURED_TICKS = 639_131_653_353_040_000


def fstring(value: str) -> bytes:
    raw = value.encode("utf-8") + b"\0"
    return len(raw).to_bytes(4, "little") + raw


def monopoly_payload(
    item_spec: str,
    *,
    ticks: int = STRUCTURED_TICKS,
    roll_points: int = 2,
    secondary_item_id: str = "",
    secondary_count: int = 0,
    pool_id: str = "CardPool_Character",
) -> bytes:
    row = (
        roll_points.to_bytes(4, "little")
        + fstring(item_spec)
        + (0).to_bytes(4, "little")
        + secondary_count.to_bytes(4, "little")
        + fstring(secondary_item_id)
        + fstring(item_spec.split(",", 1)[0])
        + fstring(pool_id)
        + ticks.to_bytes(8, "little")
    )
    return (
        MONOPOLY_MARKER
        + b"\0"
        + (0).to_bytes(4, "little")
        + len(row).to_bytes(4, "little")
        + (1).to_bytes(4, "little")
        + row
    )


def fork_payload(item_spec: str, *, ticks: int = STRUCTURED_TICKS) -> bytes:
    row = fstring(item_spec) + fstring("ForkLottery_AnHunQu") + ticks.to_bytes(8, "little")
    return (
        FORK_MARKER
        + b"\0"
        + (0).to_bytes(4, "little")
        + len(row).to_bytes(4, "little")
        + (1).to_bytes(4, "little")
        + row
    )


def bit_pack_after_eight_byte_header(payload: bytes, shift: int) -> bytes:
    packed = int.from_bytes(payload, "little") << shift
    return bytes(8) + packed.to_bytes(len(payload) + 1, "little")


class StructuredProtocolTests(unittest.TestCase):
    def test_structured_monopoly_parser_enriches_the_existing_decoder(self):
        payload = monopoly_payload(
            "Fashion_vehicle_1010_V008,3",
            secondary_item_id="Dice_ticket_02",
            secondary_count=5,
        )

        rows = decode_response_records(payload)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decoder_mode"], "heuristic_enriched")
        self.assertEqual(rows[0]["reward_id"], "Fashion_vehicle_1010_V008")
        self.assertEqual(rows[0]["reward_name"], "Tiger Incoming! - Livery")
        self.assertEqual(rows[0]["quantity"], 3)
        self.assertEqual(rows[0]["dice"], 2)
        self.assertEqual(rows[0]["secondary_reward_id"], "Dice_ticket_02")
        self.assertEqual(rows[0]["secondary_quantity"], 5)
        self.assertEqual(rows[0]["structured_pool_id"], "CardPool_Character")

    def test_structured_monopoly_parser_falls_back_when_heuristic_returns_no_rows(self):
        payload = monopoly_payload("Dice_ticket_02,50", roll_points=0)

        with patch("nte_history_exporter.decoder.protocol._decode_aligned_response_records", return_value=[]):
            rows = decode_response_records(payload)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decoder_mode"], "structured_fallback")
        self.assertEqual(rows[0]["reward_id"], "Dice_ticket_02")
        self.assertEqual(rows[0]["quantity"], 50)
        self.assertEqual(rows[0]["result_type"], "points_gift")

    def test_structured_fork_parser_is_a_complete_fallback(self):
        rows = parse_arc_response(fork_payload("fork_dustbin,2"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decoder_mode"], "structured_fallback")
        self.assertEqual(rows[0]["reward_id"], "fork_dustbin")
        self.assertEqual(rows[0]["reward_name"], "Dangerous Game")
        self.assertEqual(rows[0]["structured_pool_id"], "ForkLottery_AnHunQu")

    def test_structured_parser_realigns_bit_packed_payload(self):
        payload = bit_pack_after_eight_byte_header(monopoly_payload("1003,1"), 3)

        rows = parse_structured_records(payload, "monopoly")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].item_id, "1003")
        self.assertEqual(rows[0].protocol_view, "shift8:3")

    def test_matching_structured_data_enriches_without_replacing_heuristic_identity(self):
        heuristic_payload = fixture_payload("limited-points-gift-1")
        original = decode_response_records(heuristic_payload)[0]
        structured_ticks = original["timestamp_ticks"] // 4
        combined = heuristic_payload + monopoly_payload(
            "1020,7",
            ticks=structured_ticks,
            roll_points=0,
            pool_id="CardPool_Character",
        )

        enriched = decode_response_records(combined)[0]

        self.assertEqual(enriched["decoder_mode"], "heuristic_enriched")
        self.assertEqual(enriched["quantity"], 7)
        self.assertEqual(enriched["reward_id"], original["reward_id"])
        self.assertEqual(enriched["timestamp_raw_hex"], original["timestamp_raw_hex"])
        self.assertEqual(enriched["timestamp_ticks"], original["timestamp_ticks"])

    def test_conflicting_structured_data_cannot_override_heuristic_record(self):
        heuristic_payload = fixture_payload("limited-points-gift-1")
        original = decode_response_records(heuristic_payload)[0]
        combined = heuristic_payload + monopoly_payload(
            "1003,99",
            ticks=original["timestamp_ticks"] // 4,
            roll_points=6,
        )

        decoded = decode_response_records(combined)[0]

        self.assertNotIn("decoder_mode", decoded)
        self.assertEqual(decoded["reward_id"], original["reward_id"])
        self.assertEqual(decoded["quantity"], original["quantity"])
        self.assertEqual(decoded["dice"], original["dice"])

    def test_malformed_structured_block_fails_closed(self):
        malformed = (
            MONOPOLY_MARKER
            + b"\0"
            + (0).to_bytes(4, "little")
            + (9999).to_bytes(4, "little")
            + (1).to_bytes(4, "little")
        )

        self.assertEqual(decode_response_records(malformed), [])

    def test_structured_diagnostics_are_debug_only(self):
        row = decode_response_records(monopoly_payload("1003,1"))[0]
        row.update(
            {
                "uid": "stable-test-uid",
                "export_record": True,
                "pool_group_id": "Lottery_Permanent",
                "timestamp_group_ordinal": 0,
            }
        )

        export_record = build_export_json([row], [])["records"][0]
        self.assertNotIn("decoder_mode", export_record)
        self.assertNotIn("structured_pool_id", export_record)
        self.assertNotIn("secondary_reward_id", export_record)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "debug.csv"
            write_csv(path, [row])
            with path.open(newline="", encoding="utf-8") as handle:
                debug_record = next(csv.DictReader(handle))
        self.assertEqual(debug_record["decoder_mode"], "heuristic_enriched")
        self.assertEqual(debug_record["structured_pool_id"], "CardPool_Character")


if __name__ == "__main__":
    unittest.main()
