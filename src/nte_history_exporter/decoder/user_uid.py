from __future__ import annotations

import struct
from collections import Counter


MIN_USER_UID = 100_000_000_000
MAX_USER_UID = 999_999_999_999
USER_UID_RECORD_OFFSETS = (
    (b"TagOthers", (16,)),
    (b"PrivateSpawnInfoRecord", (40,)),
    (b"SimpleQuestRecord", (20, 52)),
    (b"FurnitureLayoutDataRec", (56, 64)),
    (b"StoreBrandItemSalesVolumeRecord", (16,)),
    (b"StorePropertyRecord", (20,)),
)


def _plausible_user_uid(value: int) -> bool:
    return MIN_USER_UID <= value <= MAX_USER_UID


def extract_user_uid_candidates(payload: bytes) -> list[str]:
    results = []
    for marker, distances in USER_UID_RECORD_OFFSETS:
        search_from = 0
        while True:
            marker_pos = payload.find(marker, search_from)
            if marker_pos == -1:
                break
            for distance in distances:
                offset = marker_pos - distance
                if offset < 0:
                    continue
                value = struct.unpack_from("<Q", payload, offset)[0]
                if _plausible_user_uid(value):
                    results.append(str(value))
            search_from = marker_pos + len(marker)
    return results


def extract_user_uid(payload: bytes) -> str | None:
    candidates = extract_user_uid_candidates(payload)
    if not candidates:
        return None
    return Counter(candidates).most_common(1)[0][0]
