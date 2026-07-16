from tests.support import *  # noqa: F401,F403


class MappingAndUpdateTests(unittest.TestCase):
    def test_pool_mapping_json_files_have_uniform_shape(self):
        required_top_level = {"pool_key", "game", "system", "banner", "request", "response"}
        for pool_key, mapping in load_pool_mappings().items():
            with self.subTest(pool_key=pool_key):
                self.assertEqual(set(required_top_level) - set(mapping), set())
                self.assertEqual(mapping["pool_key"], pool_key)
                self.assertIn("id", mapping["system"])
                self.assertIn("name", mapping["system"])
                self.assertIn("id", mapping["banner"])
                self.assertIn("name", mapping["banner"])
                self.assertIn("shared_pity", mapping["banner"])
                self.assertIn("family", mapping["request"])
                self.assertIn("length", mapping["request"])
                self.assertIn("constant", mapping["request"])
                self.assertIn("cursor_step", mapping["request"])

    def test_pool_mapping_json_matches_runtime_pool_meta(self):
        for pool_key, mapping in load_pool_mappings().items():
            with self.subTest(pool_key=pool_key):
                self.assertEqual(pool_meta_from_mapping(mapping), POOL_META[pool_key])

    def test_update_version_comparison_handles_release_tags(self):
        self.assertTrue(is_newer_version("v0.1.7", "0.1.6"))
        self.assertTrue(is_newer_version("0.2.0", "0.1.6"))
        self.assertTrue(is_newer_version("v0.1.10", "0.1.9"))
        self.assertFalse(is_newer_version("v0.1.6", "0.1.6"))
        self.assertFalse(is_newer_version("v0.1.5", "0.1.6"))
        self.assertFalse(is_newer_version("latest", "0.1.6"))

    def test_update_check_reports_newer_github_release(self):
        latest = {
            "tag_name": "v0.1.7",
            "html_url": "https://github.com/Golumpa/nte-exporter/releases/tag/v0.1.7",
        }
        with patch("nte_history_exporter.update_check.fetch_latest_release", return_value=latest):
            update = check_for_update("0.1.6", timeout=0.1)

        self.assertEqual(
            update,
            UpdateInfo(
                current_version="0.1.6",
                latest_version="v0.1.7",
                release_url="https://github.com/Golumpa/nte-exporter/releases/tag/v0.1.7",
            ),
        )

    def test_update_check_ignores_prerelease(self):
        latest = {
            "tag_name": "v0.1.8-dev-branch.123",
            "html_url": "https://github.com/Golumpa/nte-exporter/releases/tag/v0.1.8-dev-branch.123",
            "prerelease": True,
        }
        with patch("nte_history_exporter.update_check.fetch_latest_release", return_value=latest):
            self.assertIsNone(check_for_update("0.1.7", timeout=0.1))

    def test_update_check_is_quiet_when_unavailable_or_current(self):
        with patch("nte_history_exporter.update_check.fetch_latest_release", side_effect=OSError("offline")):
            self.assertIsNone(check_for_update("0.1.6", timeout=0.1))

        with patch("nte_history_exporter.update_check.fetch_latest_release", return_value={"tag_name": "v0.1.6"}):
            self.assertIsNone(check_for_update("0.1.6", timeout=0.1))

    def test_reward_mapping_files_have_expected_shape(self):
        self.assertTrue(ARC_META)
        for arc_id, meta in ARC_META.items():
            with self.subTest(arc_id=arc_id):
                self.assertTrue(arc_id.startswith("fork_"))
                self.assertIn("name", meta)
                self.assertIn(meta.get("rank"), ("S", "A", "B"))

        self.assertTrue(CHARACTERS)
        for character_id, info in CHARACTERS.items():
            with self.subTest(character_id=character_id):
                self.assertTrue(character_id.isdigit())
                self.assertIn("name", info)
                self.assertIn(info.get("rank"), ("S", "A"))

        self.assertTrue(ITEMS)
        for item_id, info in ITEMS.items():
            with self.subTest(item_id=item_id):
                self.assertIn(info.get("type"), ("item", "cosmetic"))
                self.assertIn("name", info)

    def test_rewards_by_id_merges_all_mapping_files(self):
        for reward_id in (*ARC_META, *CHARACTERS, *ITEMS):
            with self.subTest(reward_id=reward_id):
                reward = REWARDS_BY_ID[reward_id]
                self.assertEqual(reward["id"], reward_id)
                self.assertIn(reward["type"], ("arc", "character", "item", "cosmetic"))

    def test_decode_reward_key_round_trips_observed_keys(self):
        observed = {
            "98bdc9ad7dd9a5b99501": "fork_vine",
            "98bdc9ad7d41c9bdad85c9e5bdb901": "fork_Prokaryon",
            "98bdc9ad7ddda1d585add585b99d01": "fork_whuakuang",
            "98bdc9ad7dddd5a1d585add585b99d01": "fork_wuhuakuang",
            "10a58d9539bdc9b585b101": "DiceNormal",
            "10a58d957dd1a58dad95d17dc1c400": "Dice_ticket_01",
            "10a58d957dd1a58dad95d17dc1c800": "Dice_ticket_02",
            "10a58d95b1a5b5a5d19501": "Dicelimite",
            "1885cda1a5bdb97d1db1a591957dc5c0c4c000": "Fashion_Glide_1010",
            "1885cda1a5bdb97dd995a1a58db1957dc5c0c4c07c59c1c0e000": "Fashion_vehicle_1010_V008",
            "c4c0cccc00": "1033",
            "c4c0dcc000": "1070",
            "c4c0dcc0": "1070",
            "c4c0c8c4": "1021",
        }
        for key_hex, expected_id in observed.items():
            with self.subTest(key_hex=key_hex):
                self.assertEqual(decode_reward_key(bytes.fromhex(key_hex)), expected_id)

    def test_infer_reward_type_for_unmapped_ids(self):
        self.assertEqual(infer_reward_type("fork_newarc"), "arc")
        self.assertEqual(infer_reward_type("1099"), "character")
        self.assertEqual(infer_reward_type("Fashion_hat_2000"), "cosmetic")
        self.assertEqual(infer_reward_type("Dice_ticket_03"), "item")
        self.assertEqual(infer_reward_type(""), "")

