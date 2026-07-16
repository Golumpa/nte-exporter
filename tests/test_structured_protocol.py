from __future__ import annotations

import csv
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from nte_history_exporter.decoder.arc import (
    build_arc_rows_from_pairs,
    make_arc_uid,
    parse_arc_response,
)
from nte_history_exporter.decoder.boundary import annotate_groups, make_uid
from nte_history_exporter.decoder.protocol import decode_response_records
from nte_history_exporter.decoder.structured_protocol import (
    FORK_BLOCK_KIND,
    FORK_MARKER,
    MONOPOLY_BLOCK_KIND,
    MONOPOLY_ENVELOPE_FOOTER,
    MONOPOLY_MARKER,
    PROTOCOL_CONSTANT,
    ProtocolEnvelope,
    StructuredProtocolAssembler,
    parse_structured_blocks,
    parse_structured_records,
)
from nte_history_exporter.decoder.run import build_rows_from_pairs
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


def enveloped_monopoly_payload(
    item_spec: str,
    *,
    page_index: int,
    query_high: bool,
    pool_token: int = 256,
    shift: int = 3,
) -> bytes:
    envelope = (
        PROTOCOL_CONSTANT.to_bytes(4, "little")
        + ((0x80000000 if query_high else 0)).to_bytes(4, "little")
        + page_index.to_bytes(4, "little")
        + MONOPOLY_BLOCK_KIND.to_bytes(4, "little")
        + pool_token.to_bytes(4, "little")
        + MONOPOLY_ENVELOPE_FOOTER.to_bytes(4, "little")
        + b"\0\0"
    )
    return bit_pack_after_eight_byte_header(envelope + monopoly_payload(item_spec), shift)


def enveloped_fork_payload(
    item_spec: str,
    *,
    page_index: int,
    query_high: bool,
    shift: int = 3,
) -> bytes:
    envelope = (
        PROTOCOL_CONSTANT.to_bytes(4, "little")
        + ((0x80000000 if query_high else 0)).to_bytes(4, "little")
        + page_index.to_bytes(4, "little")
        + FORK_BLOCK_KIND.to_bytes(4, "little")
        + b"\0"
    )
    return bit_pack_after_eight_byte_header(envelope + fork_payload(item_spec), shift)


def assembled_block(item_id: str, segment_index: int, source_index: int = 0):
    block = parse_structured_blocks(
        monopoly_payload(item_id), "monopoly", source_index=source_index
    )[0]
    envelope = ProtocolEnvelope(
        record_type="monopoly",
        stream_key="monopoly:256",
        page_index=segment_index // 2,
        query_high=segment_index % 2 == 0,
        segment_index=segment_index,
    )
    return replace(block, envelope=envelope)


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

    def test_protocol_envelope_exposes_stream_and_segment_identity(self):
        payload = enveloped_monopoly_payload("1003", page_index=2, query_high=False)

        block = parse_structured_blocks(payload, "monopoly")[0]

        self.assertIsNotNone(block.envelope)
        self.assertEqual(block.envelope.stream_key, "monopoly:256")
        self.assertEqual(block.envelope.page_index, 2)
        self.assertFalse(block.envelope.query_high)
        self.assertEqual(block.envelope.segment_index, 3)

    def test_assembler_orders_segments_and_ignores_retransmissions(self):
        assembler = StructuredProtocolAssembler()
        segment_one = assembled_block("1010", 1)
        assembler.add_blocks([segment_one, assembled_block("1003", 0), segment_one])

        rows = assembler.rows("monopoly")

        self.assertEqual([row.item_id for row in rows], ["1003", "1010"])
        self.assertEqual([row.generation_index for row in rows], [0, 0])
        self.assertEqual(assembler.warnings, [])

    def test_assembler_never_deduplicates_blocks_without_envelopes(self):
        assembler = StructuredProtocolAssembler()
        block = parse_structured_blocks(monopoly_payload("1003"), "monopoly")[0]

        assembler.add_blocks([block, block])

        self.assertEqual([row.item_id for row in assembler.rows("monopoly")], ["1003", "1003"])

    def test_new_complete_generation_replaces_old_snapshot(self):
        assembler = StructuredProtocolAssembler()
        assembler.add_blocks([assembled_block("1003", 0), assembled_block("1010", 1)])
        assembler.add_blocks([assembled_block("1020", 0), assembled_block("1021", 1)])

        rows = assembler.rows("monopoly")

        self.assertEqual([row.item_id for row in rows], ["1020", "1021"])
        self.assertEqual([row.generation_index for row in rows], [1, 1])

    def test_partial_generation_merges_only_on_unique_overlap(self):
        assembler = StructuredProtocolAssembler()
        assembler.add_blocks(
            [
                assembled_block("1003", 0),
                assembled_block("1010", 1),
                assembled_block("1020", 2),
            ]
        )
        assembler.add_blocks([assembled_block("1099", 0), assembled_block("1010", 1)])

        rows = assembler.rows("monopoly")

        self.assertEqual([row.item_id for row in rows], ["1099", "1010", "1020"])
        self.assertEqual(assembler.warnings, [])

    def test_ambiguous_partial_generation_keeps_proven_snapshot(self):
        assembler = StructuredProtocolAssembler()
        assembler.add_blocks(
            [
                assembled_block("1003", 0),
                assembled_block("1010", 1),
                assembled_block("1003", 2),
                assembled_block("1010", 3),
            ]
        )
        assembler.add_blocks([assembled_block("1099", 0), assembled_block("1010", 1)])

        rows = assembler.rows("monopoly")

        self.assertEqual([row.item_id for row in rows], ["1003", "1010", "1003", "1010"])
        self.assertEqual(assembler.warnings[0]["code"], "AMBIGUOUS_STRUCTURED_SNAPSHOT")

    def test_pair_assembly_is_used_only_for_all_structured_fallback(self):
        segment_one = enveloped_monopoly_payload("1010", page_index=1, query_high=False)
        segment_zero = enveloped_monopoly_payload("1003", page_index=0, query_high=True)
        pairs = [
            (2, 8, 1, 1.0, 2, 1.1, segment_one, "permanent"),
            (1, 4, 3, 1.2, 4, 1.3, segment_zero, "permanent"),
        ]

        with patch("nte_history_exporter.decoder.protocol._decode_aligned_response_records", return_value=[]):
            rows = build_rows_from_pairs(pairs)
        annotated = annotate_groups(rows)

        self.assertEqual([row["reward_id"] for row in annotated], ["1003", "1010"])
        self.assertTrue(all(row["structured_assembly"] == "snapshot_segments" for row in annotated))
        self.assertEqual(annotated[0]["uid"], make_uid(annotated[0], 0))

    def test_pair_assembly_cannot_reorder_successful_heuristic_rows(self):
        segment_one = enveloped_monopoly_payload("1010", page_index=1, query_high=False)
        segment_zero = enveloped_monopoly_payload("1003", page_index=0, query_high=True)
        pairs = [
            (2, 8, 1, 1.0, 2, 1.1, segment_one, "permanent"),
            (1, 4, 3, 1.2, 4, 1.3, segment_zero, "permanent"),
        ]

        rows = build_rows_from_pairs(pairs)

        self.assertEqual([row["reward_id"] for row in rows], ["1010", "1003"])
        self.assertTrue(all(row["decoder_mode"] == "heuristic_enriched" for row in rows))
        self.assertTrue(all("structured_assembly" not in row for row in rows))

    def test_arc_fallback_uses_the_same_segment_assembly_and_uid_order(self):
        segment_one = enveloped_fork_payload("fork_vine", page_index=1, query_high=False)
        segment_zero = enveloped_fork_payload("fork_dustbin", page_index=0, query_high=True)
        pairs = [
            (2, 4, 1, 1.0, 2, 1.1, segment_one, "arc_miracle_box"),
            (1, 2, 3, 1.2, 4, 1.3, segment_zero, "arc_miracle_box"),
        ]

        rows = build_arc_rows_from_pairs(pairs)

        self.assertEqual([row["reward_id"] for row in rows], ["fork_dustbin", "fork_vine"])
        self.assertTrue(all(row["structured_assembly"] == "snapshot_segments" for row in rows))
        self.assertEqual(
            rows[0]["uid"],
            make_arc_uid(rows[0]["timestamp_raw_hex"], rows[0]["timestamp_group_ordinal"]),
        )

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
