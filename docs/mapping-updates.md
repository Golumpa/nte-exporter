# Reward mapping updates

`tools/update_mappings.py` rebuilds `arcs.json`, `characters.json`, and
`items.json` directly from the current
[`Waifus-Grace/NTE_Assets`](https://github.com/Waifus-Grace/NTE_Assets)
tables.

English display names come from `Localization/en/game.json`. The data tables
provide localization namespace/key references and quality metadata; their
embedded `LocalizedString` values are deliberately ignored.

The generated files are an authoritative snapshot, not an additive merge.
When NTE_Assets removes an ID, changes its casing, or updates its metadata, the
staged mapping reflects that change. This is intentional for a live-service
game whose asset tables evolve over time.

## Review workflow

### GitHub Actions

Run **Update reward mappings** from the repository's Actions tab. The optional
`source_ref` input accepts an NTE_Assets branch, tag, or commit and defaults to
`main`.

The workflow rebuilds the mappings, runs the complete test suite, uploads the
JSON review report, and opens a pull request from
`dev/automated-mapping-update`. Running it again updates the same open pull
request. If the authoritative snapshot has not changed, it reports zero changes
and does not create a commit or pull request.

The repository setting **Allow GitHub Actions to create and approve pull
requests** must be enabled for automatic pull-request creation. The workflow
uses only the repository-scoped `GITHUB_TOKEN` and grants it `contents: write`
and `pull-requests: write` permissions.

### Local

Stage the latest candidate files without touching the committed mappings:

```powershell
python tools/update_mappings.py
```

The required JSON tables are downloaded from the `main` branch by default.
Pin a tag, branch, or commit for reproducible review:

```powershell
python tools/update_mappings.py --source-ref e9752e5963103529f0d683fd0aed4752b7dfad78
```

To use an existing local checkout without network access:

```powershell
python tools/update_mappings.py --assets-root path\to\NTE_Assets
```

The default output is `build/mapping-update/` and contains the three candidate
mapping files plus `mapping-update-report.json`. The report lists additions,
updates, and deletions by file and records SHA-256 hashes for every source
table.

After reviewing the report and diff, apply the validated snapshot explicitly:

```powershell
python tools/update_mappings.py --apply
python -m pytest -q
```

For CI, `--check` exits with status 1 whenever the generated snapshot differs
from the committed reward mappings. It still writes the staged artifacts.

## Source rules

- Every Arc in `DT_ForkItemData` is emitted to `arcs.json`.
- Every character in `DT_Character` is emitted to `characters.json`.
- Other pull rewards are selected by `GachaIllustrate` and resolved to the
  inventory tables for quality and localization keys. Appearance-table IDs
  provide canonical casing for glider rewards.
- Mystery Box rewards are selected from every row in
  `DT_GashaponLotteryGlobal`. No event IDs are hard-coded, so future rotations
  are included automatically. Rewards resolve through the inventory, capital,
  appearance, and vehicle-item tables using case-insensitive IDs.
- Fashion, avatar-frame, and business-card Mystery Box rewards are categorized
  as cosmetics; other Mystery Box rewards, including vehicle keys and
  currencies, are categorized as items.
- Names are resolved strictly through `Localization/en/game.json`. A missing or
  ambiguous key fails the update instead of falling back to a DT value.
- Character-awakening illustration entries are not independent pull rewards
  and are excluded.
- Orange, purple, and blue item qualities map to `S`, `A`, and `B`.

## UID compatibility boundary

This updater reads and writes only the three reward mapping files. It never
reads or writes the permanent, limited, beginner, or Arc pool mapping files.
Banner IDs, timestamps, record ordering, format version, and all UID inputs are
therefore unchanged by mapping synchronization.

Reward IDs and display metadata may change or disappear when the authoritative
NTE_Assets snapshot changes. Existing exported history files remain unchanged;
new exports describe rewards using the current asset snapshot. UID stability is
independent of reward display mappings.
