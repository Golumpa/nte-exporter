from tests.support import *  # noqa: F401,F403
from nte_history_exporter.decoder.arc import annotate_arc_groups


class ArcDecodingTests(unittest.TestCase):
    def test_page_split_timestamp_variants_form_one_ten_pull(self):
        rows = [
            {
                "page": 1 if index < 5 else 2,
                "timestamp_raw_hex": "aa" if index < 5 else "bb",
                "timestamp_decoded": "2026-07-11 07:21:22",
            }
            for index in range(10)
        ]

        annotate_arc_groups(rows)

        self.assertEqual([row["timestamp_group_ordinal"] for row in rows], list(range(10)))
        self.assertEqual({row["timestamp_raw_hex"] for row in rows}, {"aa"})
        self.assertEqual(rows[5]["timestamp_reconciled_from_raw_hex"], "bb")

    def test_arc_key_timestamp_and_uid_match_fixture(self):
        fixture = load_network_fixture()
        row = fixture_session().build_rows("arc_miracle_box")[0]
        self.assertEqual(decode_arc_key(bytes.fromhex(row["reward_key_hex"])), "fork_nonos")
        _ticks, _unix, decoded = decode_arc_timestamp(bytes.fromhex(row["timestamp_raw_hex"]))
        self.assertEqual(decoded, "2030-01-02 00:00:00")
        self.assertEqual(row["uid"], fixture["expected"]["arc_first_uid"])

    def test_arc_response_parser_matches_fixture_first_page(self):
        decoded = parse_arc_response(fixture_payload("arc-page-1-response"))
        self.assertEqual(len(decoded), 5)
        self.assertEqual([row["reward_id"] for row in decoded], ["fork_nonos"] * 5)
        self.assertEqual(decoded[0]["reward_type"], "arc")
        self.assertEqual(decode_arc_key(bytes.fromhex(decoded[0]["reward_key_hex"])), "fork_nonos")

    def test_arc_response_parser_rejects_invalid_timestamp_noise(self):
        response = bytearray(0x4C)
        response += (10).to_bytes(4, "little")
        response += bytes.fromhex("ccdee4d6be")
        response += (8).to_bytes(4, "little")
        response += b"garb"
        response += (0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")

        self.assertEqual(parse_arc_response(bytes(response)), [])

    def test_arc_partial_timestamp_group_is_exported_without_warning(self):
        decoded = fixture_session().build_rows("arc_miracle_box")
        exported = [row for row in decoded if row["export_record"] is True]

        # The oldest group is a 10-pull split by stopping at page 5 (5 of 10 rows).
        # Its captured prefix is ordinal-stable, so every row is exported with a
        # stable UID and no warning.
        self.assertEqual(len(decoded), 25)
        self.assertEqual(len(exported), 25)
        self.assertTrue(all(row["uid"] for row in decoded))
        self.assertTrue(all(row["uid_status"] == "stable" for row in decoded))

    def test_arc_incomplete_prefix_keeps_stable_uids(self):
        pairs = fixture_session().pairs_for_kind("arc_miracle_box")
        full_pairs = pairs[:2]
        trunc_pairs = pairs[:1]
        ts = parse_arc_response(fixture_payload("arc-page-1-response"))[0]["timestamp_raw_hex"]
        full = [r for r in build_arc_rows_from_pairs(full_pairs) if r["timestamp_raw_hex"] == ts]
        trunc = [r for r in build_arc_rows_from_pairs(trunc_pairs) if r["timestamp_raw_hex"] == ts]
        self.assertTrue(trunc)
        self.assertEqual([r["uid"] for r in trunc], [r["uid"] for r in full[: len(trunc)]])

    def test_arc_row_builder_accepts_live_pairs_with_kind(self):
        response = fixture_payload("arc-page-1-response")
        decoded = build_arc_rows_from_pairs([(1, 2, 1, 1.0, 2, 1.1, response, "arc_miracle_box")])
        self.assertEqual(len(decoded), 5)
        self.assertEqual(decoded[0]["reward_id"], "fork_nonos")

    def test_arc_export_is_shared_pity(self):
        rows = fixture_session().build_rows("arc_miracle_box")
        export = build_export_json(rows, [])
        self.assertEqual(export["banner"]["id"], "Arc_MiracleBox")
        self.assertIs(export["banner"]["shared_pity"], True)

    def test_group_detection_counts_only_dice_records_but_uid_ordinals_keep_all_rows(self):
        rows = [
            {
                "page": 1,
                "timestamp_raw_hex": "aa",
                "timestamp_decoded": "2026-01-01 00:00:00",
                "result_type": "dice",
                "dice": 1,
                "reward_key_hex": "k1",
                "quantity": 1,
            },
            {
                "page": 1,
                "timestamp_raw_hex": "aa",
                "timestamp_decoded": "2026-01-01 00:00:00",
                "result_type": "points_gift",
                "dice": 0,
                "reward_key_hex": "k2",
                "quantity": 1,
            },
            {
                "page": 1,
                "timestamp_raw_hex": "aa",
                "timestamp_decoded": "2026-01-01 00:00:00",
                "result_type": "chase_reward",
                "dice": -4,
                "reward_key_hex": "k3",
                "quantity": 30,
            },
            {
                "page": 1,
                "timestamp_raw_hex": "aa",
                "timestamp_decoded": "2026-01-01 00:00:00",
                "result_type": "dice",
                "dice": 2,
                "reward_key_hex": "k4",
                "quantity": 1,
            },
            {
                "page": 1,
                "timestamp_raw_hex": "bb",
                "timestamp_decoded": "2026-01-01 00:01:00",
                "result_type": "dice",
                "dice": 3,
                "reward_key_hex": "k5",
                "quantity": 1,
            },
        ]

        annotated = annotate_groups(rows)

        # Ordinals cover every row in the group, but the dice-only count drives
        # timestamp_group_size_seen (2 dice in the 4-record group).
        self.assertEqual([row["timestamp_group_ordinal"] for row in annotated[:4]], [0, 1, 2, 3])
        self.assertEqual({row["timestamp_group_size_seen"] for row in annotated[:4]}, {2})
        self.assertEqual({row["timestamp_group_record_size_seen"] for row in annotated[:4]}, {4})
        self.assertTrue(all(row["export_record"] for row in annotated))
