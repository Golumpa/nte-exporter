GAME_NAME = "Neverness to Everness"
GAME_UID_PART = "nte"
SYSTEM = "monopoly"
SYSTEM_NAME = "Monopoly"
ARC_SYSTEM = "gashapon"
ARC_SYSTEM_NAME = "Gashapon"
BANNER_ID = "Lottery_Permanent"
BANNER_NAME = "Standard Board"
LIMITED_CHARACTER_BANNER_ID = "Lottery_LimitedCharacter"
LIMITED_CHARACTER_BANNER_NAME = "Limited Character Board"
ARC_BANNER_ID = "Arc_MiracleBox"
ARC_BANNER_NAME = "Arc Miracle Box"
EXPORTER_NAME = "nte-history-exporter"
EXPORTER_VERSION = "0.1.1"

HISTORY_REQUEST_BANNER = 4220
HISTORY_REQUEST_LENGTH = 45
PERMANENT_SELECTOR = 4
LIMITED_CHARACTER_SELECTOR = 8
HISTORY_PAGE_CURSOR_MULTIPLIER = 4

POOL_META = {
    "permanent": {
        "id": BANNER_ID,
        "name": BANNER_NAME,
        "system": SYSTEM_NAME,
        "shared_pity": False,
    },
    "limited_character": {
        "id": LIMITED_CHARACTER_BANNER_ID,
        "name": LIMITED_CHARACTER_BANNER_NAME,
        "system": SYSTEM_NAME,
        "shared_pity": True,
    },
    "arc_miracle_box": {
        "id": ARC_BANNER_ID,
        "name": ARC_BANNER_NAME,
        "system": ARC_SYSTEM_NAME,
        "shared_pity": True,
    },
}

ARC_HISTORY_REQUEST_BANNER = 2060
ARC_HISTORY_REQUEST_LENGTH = 34
ARC_HISTORY_CURSOR_OFFSET = 29
ARC_HISTORY_PAGE_CURSOR_MULTIPLIER = 2
ARC_RESPONSE_FIRST_RECORD_OFFSET = 0x4C
ARC_TIMESTAMP_TICKS_PER_SECOND = 20_000_000

TIMESTAMP_TICKS_PER_SECOND = 40_000_000
DOTNET_UNIX_EPOCH_SECONDS = 62_135_596_800

PERMANENT_MARKER = bytes.fromhex("440000000c85c99141bdbdb17d3995dd49bdb19501")
LIMITED_CHARACTER_MARKER = bytes.fromhex("4c0000000c85c99141bdbdb17d0da185c9858dd195c901")
MARKER = PERMANENT_MARKER
MARKERS = [PERMANENT_MARKER, LIMITED_CHARACTER_MARKER]
VALID_DICE_FIELDS = {0, 4, 8, 12, 16, 20, 24}
KEY_PREFIXES = [
    bytes.fromhex("98bdc9ad"),
    bytes.fromhex("10a58d95"),
    bytes.fromhex("c4c0"),
]
