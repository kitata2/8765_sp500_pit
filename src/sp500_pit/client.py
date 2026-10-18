"""HTTP client exposing the same query methods as `Membership`."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Dict, List, Optional, Tuple

from .membership import DateOutOfRange, parse_date

DEFAULT_URL = "http://127.0.0.1:8765"


class RemoteMembership:
    def __init__(self, base_url: str = DEFAULT_URL, timeout: float = 30.0):
        if urllib.parse.urlparse(base_url).scheme not in ("http", "https"):
            raise ValueError("base_url must be http(s)")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, **params):
        query = urllib.parse.urlencode({k: str(v) for k, v in params.items() if v is not None})
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}?{query}", timeout=self.timeout) as resp:  # noqa: S310
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = json.load(exc).get("error", exc.reason)
            raise (DateOutOfRange if "precedes first snapshot" in detail else ValueError)(detail) from None

    def meta(self) -> dict:
        return self._get("/meta")

    def members_asof(self, asof, fmt: str = "raw") -> List[str]:
        return self._get("/members", date=parse_date(asof), fmt=fmt)["tickers"]

    def union(self, start, end, fmt: str = "raw") -> List[str]:
        return self._get("/union", start=parse_date(start), end=parse_date(end), fmt=fmt)["tickers"]

    def change_points(self, start=None, end=None, fmt: str = "raw") -> List[Tuple[date, List[str]]]:
        rows = self._get("/change_points", start=start and parse_date(start), end=end and parse_date(end), fmt=fmt)
        return [(date.fromisoformat(r["date"]), r["tickers"]) for r in rows]

    def changes(self, start=None, end=None) -> List[Dict]:
        rows = self._get("/changes", start=start and parse_date(start), end=end and parse_date(end))
        return [{**r, "date": date.fromisoformat(r["date"])} for r in rows]

    def intervals(self, ticker: str) -> List[Tuple[date, Optional[date]]]:
        return [(date.fromisoformat(a), b and date.fromisoformat(b)) for a, b in self._get("/intervals", ticker=ticker)]

    def check_range(self, start, end) -> List[str]:
        return self._get("/check_range", start=parse_date(start), end=parse_date(end))["warnings"]

    def audit(self) -> dict:
        return self._get("/audit")

    def frame(self, fmt: str = "yahoo"):
        import pandas as pd

        return pd.DataFrame([dict(date=pd.Timestamp(d), tickers=t) for d, t in self.change_points(fmt=fmt)])
