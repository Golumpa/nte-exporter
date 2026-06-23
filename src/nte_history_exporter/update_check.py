from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any

LATEST_RELEASE_API_URL = "https://api.github.com/repos/Golumpa/nte-exporter/releases/latest"
RELEASES_URL = "https://github.com/Golumpa/nte-exporter/releases"


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str


def check_for_update(current_version: str, *, timeout: float = 1.5) -> UpdateInfo | None:
    """Return update details when GitHub has a newer release.

    Update checks are intentionally best-effort. Network errors, invalid
    responses, or unusual tag names should not stop the exporter from running.
    """

    try:
        latest = fetch_latest_release(timeout=timeout)
    except Exception:
        return None

    latest_version = str(latest.get("tag_name", "")).strip()
    release_url = str(latest.get("html_url", "")).strip() or RELEASES_URL
    if not latest_version or not is_newer_version(latest_version, current_version):
        return None
    return UpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        release_url=release_url,
    )


def fetch_latest_release(*, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        LATEST_RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "nte-history-exporter",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_parts = _version_parts(candidate)
    current_parts = _version_parts(current)
    if candidate_parts is None or current_parts is None:
        return False
    width = max(len(candidate_parts), len(current_parts))
    normalized_candidate = candidate_parts + (0,) * (width - len(candidate_parts))
    normalized_current = current_parts + (0,) * (width - len(current_parts))
    return normalized_candidate > normalized_current


def _version_parts(version: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", version.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))
