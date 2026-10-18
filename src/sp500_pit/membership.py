"""Pure-Python point-in-time index membership. No third-party dependencies."""
from __future__ import annotations

import bisect
import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .symbols import clean, formatter


OK, WARN, ERROR = "OK", "WARN", "ERROR"
MAX_CHURN = 15  # added + removed symbols at one change point before it looks like a data problem


class DateOutOfRange(ValueError):
    """Requested date precedes the first snapshot."""


class DatasetMismatch(ValueError):
    """The loaded dataset is not the pinned version."""


def parse_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date") and callable(value.date):  # pandas.Timestamp
        return value.date()
    return date.fromisoformat(str(value)[:10])


class Membership:
    """Change-point table: a snapshot dated d is in force from d (inclusive) until the next snapshot."""

    def __init__(self, snapshots: List[Tuple[date, frozenset]], source: str = "", sha256: str = ""):
        if not snapshots:
            raise ValueError("No membership snapshots")
        ordered = sorted(snapshots, key=lambda s: s[0])
        collapsed: List[Tuple[date, frozenset]] = []
        for when, members in ordered:
            if collapsed and collapsed[-1][0] == when:
                collapsed[-1] = (when, members)
            elif not collapsed or collapsed[-1][1] != members:
                collapsed.append((when, members))
        self._snaps = collapsed
        self._dates = [d for d, _ in collapsed]
        self.source = source
        self.sha256 = sha256
        self._intervals: Optional[Dict[str, List[Tuple[date, Optional[date]]]]] = None
        self._content_hash: Optional[str] = None

    @classmethod
    def from_csv(cls, path) -> "Membership":
        path = Path(path)
        payload = path.read_bytes()
        rows = csv.DictReader(payload.decode("utf-8-sig").splitlines())
        if not rows.fieldnames or not {"date", "tickers"} <= set(rows.fieldnames):
            raise ValueError(f"{path.name}: expected columns date,tickers; got {rows.fieldnames}")
        snaps = []
        for row in rows:
            members = frozenset(t for t in (clean(x) for x in row["tickers"].split(",")) if t)
            snaps.append((date.fromisoformat(row["date"].strip()), members))
        return cls(snaps, source=path.name, sha256=hashlib.sha256(payload).hexdigest())

    @property
    def first_date(self) -> date:
        return self._dates[0]

    @property
    def last_date(self) -> date:
        return self._dates[-1]

    def _index(self, asof: date) -> int:
        idx = bisect.bisect_right(self._dates, asof) - 1
        if idx < 0:
            raise DateOutOfRange(f"{asof} precedes first snapshot {self.first_date}")
        return idx

    def members_asof(self, asof, fmt: str = "raw") -> List[str]:
        fn = formatter(fmt)
        return sorted({fn(t) for t in self._snaps[self._index(parse_date(asof))][1]})

    def union(self, start, end, fmt: str = "raw") -> List[str]:
        """Every symbol that was a member at any time in [start, end]."""
        s, e = parse_date(start), parse_date(end)
        if e < s:
            raise ValueError("end precedes start")
        fn = formatter(fmt)
        lo = self._index(s)
        hi = bisect.bisect_right(self._dates, e)
        return sorted({fn(t) for _, members in self._snaps[lo:hi] for t in members})

    def change_points(self, start=None, end=None, fmt: str = "raw") -> List[Tuple[date, List[str]]]:
        """Snapshots in force during [start, end], including the one in force at start."""
        fn = formatter(fmt)
        lo = self._index(parse_date(start)) if start is not None else 0
        hi = bisect.bisect_right(self._dates, parse_date(end)) if end is not None else len(self._snaps)
        return [(d, sorted({fn(t) for t in m})) for d, m in self._snaps[lo:hi]]

    def changes(self, start=None, end=None) -> List[dict]:
        """Added/removed symbols at each change point after the first (raw spelling)."""
        s = parse_date(start) if start is not None else None
        e = parse_date(end) if end is not None else None
        out = []
        for i in range(1, len(self._snaps)):
            when, members = self._snaps[i]
            if (s and when < s) or (e and when > e):
                continue
            prev = self._snaps[i - 1][1]
            out.append(dict(date=when, added=sorted(members - prev), removed=sorted(prev - members)))
        return out

    def intervals(self, ticker: str) -> List[Tuple[date, Optional[date]]]:
        """Membership spells as (first snapshot in, first snapshot out or None); end is exclusive."""
        spells = self._spells()
        key = clean(ticker)
        return list(spells.get(key) or spells.get(key.replace("-", ".")) or [])

    def _spells(self) -> Dict[str, List[Tuple[date, Optional[date]]]]:
        if self._intervals is None:
            raw: Dict[str, List[list]] = {}
            previous: frozenset = frozenset()
            for when, members in self._snaps:
                for t in members - previous:
                    raw.setdefault(t, []).append([when, None])
                for t in previous - members:
                    raw[t][-1][1] = when
                previous = members
            self._intervals = {t: [(a, b) for a, b in v] for t, v in raw.items()}
        return self._intervals

    def check_range(self, start, end, max_stale_days: int = 120) -> List[str]:
        """Human-readable caveats for using the table over [start, end]."""
        s, e = parse_date(start), parse_date(end)
        notes = []
        if s < self.first_date:
            notes.append(f"start {s} precedes first snapshot {self.first_date}")
        elif s.year < 2001:
            notes.append("pre-2001 history is unverified (first snapshot has fewer than 494 symbols)")
        if (e - self.last_date).days > max_stale_days:
            notes.append(f"end {e} is {(e - self.last_date).days} days after last snapshot {self.last_date}; "
                         "recent index changes may be missing")
        return notes

    def validate(self, min_members: int = 480, max_members: int = 520) -> List[Tuple[date, int]]:
        """Snapshots whose size is outside the plausible 500-ish range."""
        return [(d, len(m)) for d, m in self._snaps if not min_members <= len(m) <= max_members]

    def coverage(self, available: Iterable[str], dates: Optional[Iterable] = None, fmt: str = "raw") -> List[dict]:
        """Share of members on each date that have usable data; `available` uses spelling `fmt`."""
        have = set(available)
        if dates is None:
            dates = [date(y, 1, 1) for y in range(self.first_date.year, self.last_date.year + 1)]
        report = []
        for d in map(parse_date, dates):
            if d < self.first_date:
                continue
            members = self.members_asof(d, fmt)
            missing = [t for t in members if t not in have]
            report.append(dict(date=d, n_members=len(members), n_available=len(members) - len(missing),
                               pct=100 * (1 - len(missing) / len(members)) if members else 0.0, missing=missing))
        return report

    @property
    def content_hash(self) -> str:
        """Hash of the change points themselves, stable across CSV re-serialisation."""
        if self._content_hash is None:
            body = [[d.isoformat(), sorted(m)] for d, m in self._snaps]
            self._content_hash = hashlib.sha256(json.dumps(body, separators=(",", ":")).encode()).hexdigest()
        return self._content_hash

    def restatements(self, newer: "Membership") -> List[dict]:
        """Dates up to this table's last snapshot where `newer` rewrites history."""
        def at(m: "Membership", d: date) -> frozenset:
            return m._snaps[m._index(d)][1] if d >= m.first_date else frozenset()

        days = sorted({d for d in self._dates + newer._dates if d <= self.last_date})
        out = []
        for d in days:
            old, new = at(self, d), at(newer, d)
            if old != new:
                out.append(dict(date=d, added=sorted(new - old), removed=sorted(old - new)))
        return out

    def audit(self, today: Optional[date] = None, max_stale_days: int = 120) -> dict:
        """Structural checks only; they cannot prove the history is complete or correct."""
        today = today or date.today()
        checks: List[dict] = []

        def check(name: str, status: str, detail: str = "", **extra) -> None:
            checks.append(dict(check=name, status=status, detail=detail, **extra))

        sizes = self.validate()
        hard = [(d.isoformat(), n) for d, n in sizes if n < 400 or n > 600]
        check("member_count", ERROR if hard else (WARN if sizes else OK),
              "snapshots outside 480-520 members", count=len(sizes), offenders=[(d.isoformat(), n) for d, n in sizes][:20])
        churn = [(c["date"].isoformat(), len(c["added"]) + len(c["removed"])) for c in self.changes()
                 if len(c["added"]) + len(c["removed"]) > MAX_CHURN]
        check("bulk_churn", WARN if churn else OK, f"change points moving more than {MAX_CHURN} symbols",
              count=len(churn), offenders=churn[:20])
        spells = self._spells()
        reentry = sorted(t for t, s in spells.items() if len(s) > 1)
        check("ticker_reentry", WARN if reentry else OK,
              "tickers that left and re-entered; may be different companies", count=len(reentry), offenders=reentry[:20])
        closed = sum(1 for s in spells.values() if s[-1][1] is not None)
        long_history = (self.last_date - self.first_date).days > 365
        check("closed_intervals", ERROR if (closed == 0 and long_history) else OK,
              "a multi-year universe in which nothing ever exited is survivorship-biased", closed=closed)
        age = (today - self.last_date).days
        check("stale_tail", WARN if age > max_stale_days else OK,
              f"last snapshot {self.last_date} is {age} days old")
        statuses = {c["status"] for c in checks}
        report = dict(status=ERROR if ERROR in statuses else (WARN if WARN in statuses else OK),
                      sha256=self.sha256, content_hash=self.content_hash, checks=checks)
        report["audit_hash"] = hashlib.sha256(json.dumps(report, sort_keys=True, default=str).encode()).hexdigest()
        return report

    def meta(self) -> dict:
        return dict(source=self.source, sha256=self.sha256, content_hash=self.content_hash,
                    n_change_points=len(self._snaps),
                    first_date=self.first_date.isoformat(), last_date=self.last_date.isoformat(),
                    n_symbols=len({t for _, m in self._snaps for t in m}),
                    caveats="Tickers not permanent IDs; early history unverified; no price data")

    def frame(self, fmt: str = "yahoo"):
        """DataFrame with `date` and `tickers` (list) columns; requires pandas."""
        import pandas as pd

        return pd.DataFrame([dict(date=pd.Timestamp(d), tickers=t) for d, t in self.change_points(fmt=fmt)])
