"""Point-in-time S&P 500 membership.

    import sp500_pit
    m = sp500_pit.connect()               # in-process, or the service if SP500_PIT_URL is set
    m.members_asof("2020-03-02", fmt="yahoo")
"""
import os

from .client import RemoteMembership
from .data import load
from .membership import DateOutOfRange, Membership, parse_date
from .symbols import to_eodhd, to_yahoo

__all__ = ["Membership", "RemoteMembership", "DateOutOfRange", "connect", "load", "parse_date",
           "to_yahoo", "to_eodhd"]


def connect(url=None, path=None):
    """Remote client when `url` or SP500_PIT_URL is set, otherwise load the local CSV."""
    url = url or os.environ.get("SP500_PIT_URL")
    return RemoteMembership(url) if url else load(path)
