"""Loopback-only JSON service over the membership table (stdlib, no dependencies)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .data import find_csv
from .membership import DateOutOfRange, Membership
from .symbols import FORMATS


class _Store:
    """Reloads the CSV when its mtime changes so a `git pull` is picked up without a restart."""

    def __init__(self, path: Optional[Path]):
        self._path = Path(path) if path else find_csv()
        if self._path is None:
            raise FileNotFoundError("No membership CSV found; run `sp500-pit fetch`")
        self._lock = threading.Lock()
        self._mtime = 0.0
        self._membership: Optional[Membership] = None

    def get(self) -> Membership:
        with self._lock:
            mtime = self._path.stat().st_mtime
            if self._membership is None or mtime != self._mtime:
                self._membership = Membership.from_csv(self._path)
                self._mtime = mtime
            return self._membership


def _iso(value):
    return value.isoformat() if value is not None else None


def _route(m: Membership, path: str, q: dict):
    fmt = q.get("fmt", "raw")
    if fmt not in FORMATS:
        raise ValueError(f"fmt must be one of {sorted(FORMATS)}")
    if path == "/health":
        return {"status": "ok"}
    if path == "/meta":
        return m.meta()
    if path == "/members":
        return {"date": q["date"], "tickers": m.members_asof(q["date"], fmt)}
    if path == "/union":
        return {"tickers": m.union(q["start"], q["end"], fmt)}
    if path == "/change_points":
        return [{"date": d.isoformat(), "tickers": t}
                for d, t in m.change_points(q.get("start"), q.get("end"), fmt)]
    if path == "/changes":
        return [{**c, "date": c["date"].isoformat()} for c in m.changes(q.get("start"), q.get("end"))]
    if path == "/intervals":
        return [[_iso(a), _iso(b)] for a, b in m.intervals(q["ticker"])]
    if path == "/check_range":
        return {"warnings": m.check_range(q["start"], q["end"])}
    if path == "/audit":
        return m.audit()
    return None


def make_server(host: str = "127.0.0.1", port: int = 8765, path=None) -> ThreadingHTTPServer:
    store = _Store(path)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                result = _route(store.get(), url.path, query)
            except (KeyError, ValueError, DateOutOfRange) as exc:
                msg = f"missing parameter {exc}" if isinstance(exc, KeyError) else str(exc)
                return self._send(400, {"error": msg})
            if result is None:
                return self._send(404, {"error": "unknown route"})
            self._send(200, result)

        def log_message(self, *args) -> None:  # silence per-request stderr noise
            pass

    return ThreadingHTTPServer((host, port), Handler)
