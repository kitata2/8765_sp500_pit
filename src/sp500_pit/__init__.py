"""Point-in-time S&P 500 membership.

    import sp500_pit
    m = sp500_pit.connect()               # in-process, or the service if SP500_PIT_URL is set
    m.members_asof("2020-03-02", fmt="yahoo")
"""
import os

from .client import RemoteMembership
from .data import load
from .membership import DatasetMismatch, DateOutOfRange, Membership, parse_date
from .symbols import to_eodhd, to_yahoo

__all__ = ["Membership", "RemoteMembership", "DateOutOfRange", "DatasetMismatch", "connect", "load",
           "parse_date", "to_yahoo", "to_eodhd"]


def connect(url=None, path=None, expected_sha256=None):
    """Remote client when `url` or SP500_PIT_URL is set, otherwise load the local CSV.

    `expected_sha256` pins the dataset version (see `meta()['sha256']`) and fails closed on a mismatch.
    """
    url = url or os.environ.get("SP500_PIT_URL")
    source = RemoteMembership(url) if url else load(path)
    if expected_sha256 and source.meta()["sha256"] != expected_sha256:
        raise DatasetMismatch(f"dataset sha256 {source.meta()['sha256']} != pinned {expected_sha256}")
    return source
