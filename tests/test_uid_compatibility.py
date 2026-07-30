from tests.support import *  # noqa: F401,F403


class UidCompatibilityTests(unittest.TestCase):
    def test_monopoly_page_split_timestamp_variants_complete_ten_pull(self):
        rows = [self._synthetic_row(1, "aa", "dice") for _ in range(5)]
        rows += [self._synthetic_row(2, "bb", "dice") for _ in range(5)]
        for row in rows:
            row["timestamp_decoded"] = "2026-07-11 07:21:22"

        annotated = annotate_groups(rows)

        self.assertEqual([row["timestamp_group_ordinal"] for row in annotated], list(range(10)))
        self.assertEqual({row["timestamp_raw_hex"] for row in annotated}, {"aa"})

    def test_monopoly_singles_with_same_second_remain_separate(self):
        rows = [self._synthetic_row(1, "aa", "dice"), self._synthetic_row(2, "bb", "dice")]
        for row in rows:
            row["timestamp_decoded"] = "2026-07-11 07:21:22"

        annotated = annotate_groups(rows)

        self.assertEqual([row["timestamp_group_ordinal"] for row in annotated], [0, 0])
        self.assertEqual([row["timestamp_raw_hex"] for row in annotated], ["aa", "bb"])

    def test_uid_source_matches_committed_network_fixture(self):
        fixture = load_network_fixture()
        rows = annotate_groups(fixture_session().build_rows("permanent"))
        self.assertEqual(rows[0]["uid"], fixture["expected"]["permanent_first_uid"])

    def test_uid_uses_pool_timestamp_and_ordinal_only(self):
        row = {
            "pool_group_id": "Lottery_LimitedCharacter",
            "timestamp_raw_hex": "40e93247c3097b23",
            "dice": 5,
            "reward_key_hex": "10a58d957dd1a58dad95d17dc1c800",
            "quantity": 50,
        }
        changed_content = {
            **row,
            "dice": 1,
            "reward_key_hex": "98bdc9ad7dd9a5b99501",
            "quantity": 1,
        }
        changed_pool = {**row, "pool_group_id": "Lottery_Permanent"}

        self.assertEqual(make_uid(row, 0), "74a9ef4aacde549dfe8e8e7cc6ddd65b")
        self.assertEqual(make_uid(changed_content, 0), make_uid(row, 0))
        self.assertNotEqual(make_uid(changed_pool, 0), make_uid(row, 0))
        self.assertNotEqual(make_uid(row, 1), make_uid(row, 0))

    def test_pages_1_to_5_exports_every_row(self):
        annotated = annotate_groups(fixture_session().build_rows("permanent"))

        exported = [row for row in annotated if row["export_record"] is True]

        # Every decoded row is exported; boundary groups are never dropped.
        self.assertEqual(len(annotated), 25)
        self.assertEqual(len(exported), 25)

    @staticmethod
    def _synthetic_row(page, timestamp_hex, result_type):
        return {
            "page": page,
            "timestamp_raw_hex": timestamp_hex,
            "timestamp_decoded": f"ts-{timestamp_hex}",
            "result_type": result_type,
            "dice": 4 if result_type == "dice" else 0,
            "reward_key_hex": "10a58d9539bdc9b585b101",
            "quantity": 1,
        }

    def test_oldest_group_with_partial_dice_count_exports_without_warning(self):
        rows = [self._synthetic_row(1, "aa", "dice") for _ in range(5)]
        rows += [self._synthetic_row(2, "bb", "dice") for _ in range(5)]
        rows += [self._synthetic_row(3, "bb", "dice") for _ in range(4)]
        rows += [self._synthetic_row(3, "bb", "points_gift")]

        annotated = annotate_groups(rows)
        exported = [row for row in annotated if row["export_record"] is True]

        # Oldest group is a partially captured 10-pull on a full final page. Its
        # captured prefix is ordinal-stable, so it is exported with stable UIDs.
        self.assertEqual(len(exported), 15)
        oldest = [row for row in annotated if row["timestamp_raw_hex"] == "bb"]
        self.assertTrue(all(row["uid"] for row in oldest))
        self.assertTrue(all(row["uid_status"] == "stable" for row in oldest))
        self.assertEqual([row["timestamp_group_ordinal"] for row in oldest], list(range(10)))

    def test_incomplete_oldest_prefix_keeps_stable_uids(self):
        full = [self._synthetic_row(1, "aa", "dice") for _ in range(5)]
        full += [self._synthetic_row(2, "bb", "dice") for _ in range(3)]
        full += [self._synthetic_row(3, "bb", "dice") for _ in range(2)]
        truncated = [r for r in full if r["page"] in (1, 2)]

        full_rows = annotate_groups([dict(r) for r in full])
        trunc_rows = annotate_groups([dict(r) for r in truncated])

        full_uids = [r["uid"] for r in full_rows if r["timestamp_raw_hex"] == "bb"][:3]
        trunc_uids = [r["uid"] for r in trunc_rows if r["timestamp_raw_hex"] == "bb"]
        # Capturing only the first 3 of a 5-record oldest group yields the same
        # UIDs those rows have in the full capture.
        self.assertEqual(len(trunc_uids), 3)
        self.assertEqual(trunc_uids, full_uids)

    def test_oldest_group_with_ten_dice_exports_on_full_final_page(self):
        rows = [self._synthetic_row(1, "aa", "dice") for _ in range(5)]
        rows += [self._synthetic_row(2, "bb", "dice") for _ in range(5)]
        rows += [self._synthetic_row(3, "bb", "dice") for _ in range(5)]

        annotated = annotate_groups(rows)
        exported = [row for row in annotated if row["export_record"] is True]

        self.assertEqual(len(exported), 15)

    def test_run_selection_anchors_to_page_1_and_keeps_newest(self):
        # Page 2's response was lost: captured pages 1, 3, 4, 5.
        pairs = [(p, p * 2, 0, 0, 0, 0, b"", "permanent") for p in (1, 3, 4, 5)]
        run, warnings = select_continuous_run_from_page_1(pairs)

        # The page-1 run (just page 1, the newest history) is kept; later pages are
        # ignored with a gap warning, never silently discarding page 1.
        self.assertEqual([p[0] for p in run], [1])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["code"], "PAGE_GAP_DETECTED")
        self.assertEqual(warnings[0]["ignored_pages"], [3, 4, 5])

    def test_run_selection_warns_when_page_1_missing(self):
        pairs = [(p, p * 2, 0, 0, 0, 0, b"", "permanent") for p in (3, 4, 5)]
        run, warnings = select_continuous_run_from_page_1(pairs)

        self.assertEqual([p[0] for p in run], [3, 4, 5])
        self.assertEqual(warnings[0]["code"], "DID_NOT_START_AT_PAGE_1")

    def test_committed_network_scan_exports_all_rows(self):
        fixture = load_network_fixture()
        annotated = annotate_groups(fixture_session().build_rows("permanent"))
        exported = [row for row in annotated if row["export_record"] is True]

        self.assertEqual(len(annotated), fixture["expected"]["permanent_records"])
        self.assertEqual(len(exported), fixture["expected"]["permanent_records"])

    def test_monopoly_uid_compatibility_vectors_are_frozen(self):
        vectors = [
            ("Lottery_Permanent", "0000000000000000", 0, "5da57468adb23fcfde530fd849a25767"),
            ("Lottery_Permanent", "00a243eb689b7a23", 0, "8f9fb9bc92a867f6f41e5839e94c7991"),
            ("Lottery_Permanent", "00a243eb689b7a23", 1, "6a0bea71d091b9b7063780fcc86238d5"),
            ("Lottery_LimitedCharacter", "00a243eb689b7a23", 0, "b8f5d3c27315c70ceafbe8eb2bab0fc2"),
            ("Lottery_LimitedCharacter", "ffffffffffffffff", 9, "66916e1f077fdf7664f0f0edc4c64eb8"),
        ]

        for pool_group_id, timestamp_raw_hex, ordinal, expected_uid in vectors:
            with self.subTest(
                pool_group_id=pool_group_id,
                timestamp=timestamp_raw_hex,
                ordinal=ordinal,
            ):
                row = {
                    "pool_group_id": pool_group_id,
                    "timestamp_raw_hex": timestamp_raw_hex,
                }
                self.assertEqual(make_uid(row, ordinal), expected_uid)

    def test_arc_uid_compatibility_vectors_are_frozen(self):
        vectors = [
            ("0000000000000000", 0, "faa0b07cefd71758d4a8d64bc2a2f78e"),
            ("00a243eb689b7a23", 0, "7a7ef75281fcced043f691d269477cfa"),
            ("00a243eb689b7a23", 1, "f798c076ea1d137a08fe62df859e8a7f"),
            ("ffffffffffffffff", 9, "d114cc6c313a15f55ca12910801d78ea"),
        ]

        for timestamp_raw_hex, ordinal, expected_uid in vectors:
            with self.subTest(timestamp=timestamp_raw_hex, ordinal=ordinal):
                self.assertEqual(make_arc_uid(timestamp_raw_hex, ordinal), expected_uid)
