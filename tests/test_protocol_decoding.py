from tests.support import *  # noqa: F401,F403


class ProtocolDecodingTests(unittest.TestCase):
    def test_limited_selector_and_marker_decode(self):
        request = bytearray(45)
        request[31:35] = (4).to_bytes(4, "little")
        request[35:39] = (4220).to_bytes(4, "little")
        request[40:44] = (8).to_bytes(4, "little")
        self.assertEqual(history_request_kind(bytes(request)), "limited_character")

    def test_monopoly_request_allows_coalesced_trailing_payload(self):
        request = bytearray(45)
        request[31:35] = (25 * 4).to_bytes(4, "little")
        request[35:39] = (4220).to_bytes(4, "little")
        request[40:44] = (4).to_bytes(4, "little")
        coalesced = bytes(request) + bytes.fromhex(
            "007c669610062038461bc40100000872a34b93821a0219aa933b0a6b2ba34a6b"
        )

        self.assertEqual(history_request_kind(coalesced), "permanent")

    def test_arc_request_allows_coalesced_trailing_payload(self):
        request = bytearray(34)
        request[24:28] = (2060).to_bytes(4, "little")
        request[29:33] = (7 * 2).to_bytes(4, "little")

        self.assertTrue(is_arc_history_request(bytes(request) + bytes(32)))
        self.assertEqual(arc_request_page(bytes(request) + bytes(32)), 7)

        response = bytearray(220)
        response[0x50:0x54] = (4).to_bytes(4, "little")
        response[0x54:0x58] = (20).to_bytes(4, "little")
        response[0x58:0x5d] = bytes.fromhex("c4c0c4c000")
        marker_offset = 0x5d
        response[marker_offset:marker_offset + len(LIMITED_CHARACTER_MARKER)] = LIMITED_CHARACTER_MARKER
        timestamp_raw = (2556647947780680000).to_bytes(8, "little")
        response[marker_offset + len(LIMITED_CHARACTER_MARKER):marker_offset + len(LIMITED_CHARACTER_MARKER) + 8] = timestamp_raw

        rows = decode_response_records(bytes(response))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reward_id"], "1010")
        self.assertEqual(rows[0]["reward_name"], "Nanally")

    def test_fixture_prefixed_points_gift_overrides_visible_dice(self):
        decoded = decode_response_records(fixture_payload("limited-points-gift-1"))[0]
        self.assertEqual(decoded["result_type"], "points_gift")
        self.assertEqual(decoded["result_source_raw"], 0)
        self.assertEqual(decoded["dice"], 0)
        self.assertEqual(decoded["dice_raw_u32"], 0)
        self.assertEqual(decoded["reward_id"], "1020")

    def test_fixture_prefixed_chase_reward_overrides_visible_dice_and_quantity(self):
        decoded = decode_response_records(fixture_payload("limited-chase-reward"))[0]

        self.assertEqual(decoded["result_type"], "chase_reward")
        self.assertEqual(decoded["result_source_raw"], -4)
        self.assertEqual(decoded["dice"], -4)
        self.assertEqual(decoded["dice_raw_u32"], -4)
        self.assertEqual(decoded["reward_id"], "Dice_ticket_01")
        self.assertEqual(decoded["quantity"], 30)

    def test_warp_piece_chase_subrecord_without_prefix_marker_is_chase_reward(self):
        decoded = decode_single_record(
            "c1c4b0ccc00000000000040000003c00000010a58d957dd1a58dad95d17dc1c400"
            "4c0000000c85c99141bdbdb17d0da185c9858dd195c90140eb2c2dd7227b23"
        )

        self.assertEqual(decoded["result_type"], "chase_reward")
        self.assertEqual(decoded["result_source_raw"], -4)
        self.assertEqual(decoded["dice"], -4)
        self.assertEqual(decoded["dice_raw_u32"], -4)
        self.assertEqual(decoded["reward_id"], "Dice_ticket_01")
        self.assertEqual(decoded["reward_name"], "Warp Piece")
        self.assertEqual(decoded["quantity"], 30)

    def test_page_first_prefix_uses_real_dice_field(self):
        cases = [
            (
                "003006000014000000040000002800000098bdc9ad7dd9a5b995010000000008000000"
                "3c00000010a58d957dd1a58dad95d17dc1c4002800000098bdc9ad7dd9a5b995014c"
                "0000000c85c99141bdbdb17d0da185c9858dd195c901c0dd53bd2b137b23",
                1,
                "fork_vine",
            ),
            (
                "00c8060000140000001000000014000000c4c0d4d400000000000400000014000000"
                "c4c0d4d400440000000c85c99141bdbdb17d3995dd49bdb1950100d929e115087b23",
                4,
                "1055",
            ),
        ]
        for record_hex, expected_dice, reward_id in cases:
            with self.subTest(reward_id=reward_id):
                decoded = decode_single_record(record_hex)

                self.assertEqual(decoded["dice"], expected_dice)
                self.assertEqual(decoded["dice_raw_u32"], expected_dice * 4)
                self.assertEqual(decoded["dice_offset_in_record"], 9)
                self.assertEqual(decoded["result_type"], "dice")
                self.assertEqual(decoded["reward_id"], reward_id)

    def test_batched_monopoly_response_normalizes_embedded_page_header(self):
        decoded = decode_response_records(fixture_payload("limited-batched-pages"))

        self.assertEqual(len(decoded), 10)
        self.assertEqual(decoded[5]["dice"], 4)
        self.assertEqual(decoded[5]["result_type"], "dice")

    def test_monopoly_response_parser_realigns_bit_packed_payload(self):
        reference_rows = decode_response_records(fixture_payload("limited-bitpacked-source"))
        decoded = decode_response_records(fixture_payload("limited-bitpacked-response"))

        self.assertEqual(len(decoded), 10)
        self.assertEqual(
            [row["record_hex"] for row in decoded],
            [row["record_hex"] for row in reference_rows],
        )

    def test_page_gap_warning_reports_ignored_pages(self):
        pairs = [(p, p * 2, 0, 0, 0, 0, b"", "permanent") for p in (1, 2, 3, 5)]
        run, warnings = select_continuous_run_from_page_1(pairs)
        self.assertEqual([p[0] for p in run], [1, 2, 3])
        self.assertEqual(warnings[0]["code"], "PAGE_GAP_DETECTED")
        self.assertEqual(warnings[0]["ignored_pages"], [5])
