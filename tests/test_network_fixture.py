from tests.support import *  # noqa: F401,F403


class SyntheticNetworkFixtureTests(unittest.TestCase):
    def test_fixture_contains_only_synthetic_network_identity(self):
        fixture = load_network_fixture()

        self.assertTrue(fixture["privacy"]["synthetic"])
        self.assertFalse(fixture["privacy"]["contains_user_uid"])
        self.assertFalse(fixture["privacy"]["contains_raw_account_session"])
        self.assertEqual(fixture["local_ip"], "192.0.2.10")

        allowed_ips = {"192.0.2.10", "198.51.100.20"}
        for packet, decoded in zip(fixture["packets"], fixture_packets()):
            with self.subTest(label=packet["label"]):
                self.assertIn(packet["src_ip"], allowed_ips)
                self.assertIn(packet["dst_ip"], allowed_ips)
                self.assertEqual(packet["protocol"], "udp")
                self.assertIsNone(extract_user_uid(decoded.payload))

    def test_fixture_replays_permanent_and_arc_history(self):
        fixture = load_network_fixture()
        session = fixture_session()

        permanent = annotate_groups(session.build_rows("permanent"))
        arc = session.build_rows("arc_miracle_box")

        self.assertIsNone(session.user_uid)
        self.assertEqual(len(permanent), fixture["expected"]["permanent_records"])
        self.assertEqual(len(arc), fixture["expected"]["arc_records"])
        self.assertEqual(permanent[0]["uid"], fixture["expected"]["permanent_first_uid"])
        self.assertEqual(arc[0]["uid"], fixture["expected"]["arc_first_uid"])
        self.assertEqual(sorted({row["page"] for row in permanent}), [1, 2, 3, 4, 5])
        self.assertEqual(sorted({row["page"] for row in arc}), [1, 2, 3, 4, 5])
        self.assertEqual({row["timestamp_decoded"] for row in permanent}, {"2030-01-01 00:00:00"})
        self.assertEqual({row["timestamp_decoded"] for row in arc}, {"2030-01-02 00:00:00"})

        # Repeating one manufactured record prevents the replay transcript from
        # preserving a real account's pull sequence while still exercising page
        # ordering, timestamp ordinals, UID stability, and export behavior.
        self.assertEqual(len({row["record_hex"] for row in permanent}), 1)
        self.assertEqual(len({row["record_hex"] for row in arc}), 1)

    def test_fixture_protocol_samples_cover_edge_cases(self):
        points = decode_response_records(fixture_payload("limited-points-gift-1"))
        chase = decode_response_records(fixture_payload("limited-chase-reward"))
        batched = decode_response_records(fixture_payload("limited-batched-pages"))
        aligned = decode_response_records(fixture_payload("limited-bitpacked-source"))
        bitpacked = decode_response_records(fixture_payload("limited-bitpacked-response"))

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["result_type"], "points_gift")
        self.assertEqual(points[0]["reward_id"], "1020")
        self.assertEqual(len(chase), 1)
        self.assertEqual(chase[0]["result_type"], "chase_reward")
        self.assertEqual(chase[0]["reward_id"], "Dice_ticket_01")
        self.assertEqual(chase[0]["quantity"], 30)
        self.assertEqual(len(batched), 10)
        self.assertEqual(len(aligned), 10)
        self.assertEqual(
            [row["record_hex"] for row in bitpacked],
            [row["record_hex"] for row in aligned],
        )

    def test_fixture_exports_sanitized_json_with_stable_uids(self):
        session = fixture_session()
        rows = annotate_groups(session.build_rows("permanent"))
        export = build_export_json(rows, [])

        self.assertNotIn("user_uid", export)
        self.assertEqual(export["format_version"], 1)
        self.assertEqual(export["records"][0]["uid"], load_network_fixture()["expected"]["permanent_first_uid"])
        self.assertNotIn("record_hex", export["records"][0])
        self.assertNotIn("timestamp_raw_hex", export["records"][0])
