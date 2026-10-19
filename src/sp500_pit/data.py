"""Locate, fetch and load the membership CSV."""
from __future__ import annotations

import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

from .membership import Membership

CSV_NAME = "S&P 500 Historical Components & Changes (Updated).csv"
ENV_DATA = "SP500_PIT_DATA"
REMOTE_URL = ("https://raw.githubusercontent.com/kitata2/8765_sp500_pit/master/"
              "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv")
_REPO_ROOT = Path(__file__).resolve().parents[2]


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "sp500_pit"


def find_csv() -> Optional[Path]:
    """SP500_PIT_DATA (file or folder), then the repo checkout, then the download cache."""
    env = os.environ.get(ENV_DATA)
    candidates = []
    if env:
        p = Path(env)
        candidates.append(p / CSV_NAME if p.is_dir() else p)
    candidates += [_REPO_ROOT / CSV_NAME, cache_dir() / CSV_NAME]
    return next((c for c in candidates if c.is_file()), None)


def fetch(dest: Optional[Path] = None, url: str = REMOTE_URL) -> Path:
    """Download the latest CSV atomically into the cache (or `dest`)."""
    if not url.startswith("https://"):
        raise ValueError("Only https URLs are allowed")
    dest = Path(dest) if dest else cache_dir() / CSV_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - scheme checked above
        payload = resp.read()
    if len(payload) < 1000 or not payload.startswith(b"date,tickers"):
        raise ValueError("Downloaded file is not a membership CSV")
    fd, tmp = tempfile.mkstemp(dir=dest.parent, suffix=".tmp")
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
    os.replace(tmp, dest)
    return dest


def load(path=None, auto_fetch: bool = True) -> Membership:
    csv_path = Path(path) if path else find_csv()
    if csv_path is None:
        if not auto_fetch:
            raise FileNotFoundError(f"No membership CSV found; set {ENV_DATA} or run `sp500-pit fetch`")
        csv_path = fetch()
    return Membership.from_csv(csv_path)
