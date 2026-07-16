from __future__ import annotations

import ipaddress
import struct


# Production entries from clientRes/OB-NTE-ServerList/serverlist_hhOS.json.
# Test and certification servers are intentionally excluded.
SERVER_REGIONS = {
    "23001": {"account_region": "AS", "name": "Asia"},
    "23002": {"account_region": "NA_SA", "name": "America"},
    "23003": {"account_region": "EU", "name": "Europe"},
    "23004": {"account_region": "SE", "name": "SEA"},
}


def account_region_for_server(server_id: str | None) -> str | None:
    if not server_id:
        return None
    server = SERVER_REGIONS.get(str(server_id).strip())
    return server["account_region"] if server else None


def extract_server_id(payload: bytes) -> str | None:
    """Extract DistrictId from the initial server-selection TCP response.

    This response is a length-prefixed FlatBuffers message. DistrictId is at
    byte 96 in the current schema. Validate the frame and its following server
    address before accepting the value so an arbitrary integer at that offset
    is not mistaken for a server ID.
    """
    if len(payload) < 168:
        return None

    frame_size = struct.unpack_from("<I", payload, 0)[0] + 4
    if frame_size > len(payload) or frame_size < 168:
        return None
    if struct.unpack_from("<I", payload, 4)[0] != 20:
        return None

    server_id = struct.unpack_from("<I", payload, 96)[0]
    if not 20_000 <= server_id <= 99_999:
        return None

    address_length = struct.unpack_from("<I", payload, 132)[0]
    address_end = 136 + address_length
    if not 1 <= address_length <= 255 or address_end > frame_size:
        return None
    try:
        address = payload[136:address_end].decode("ascii")
        ipaddress.ip_address(address)
    except (UnicodeDecodeError, ValueError):
        return None

    return str(server_id)
