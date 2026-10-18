"""Ticker spelling per vendor. The dataset itself uses the raw (dotted) form, e.g. BRK.B."""
from __future__ import annotations

from typing import Callable, Dict


def clean(ticker: object) -> str:
    text = str(ticker).strip().upper()
    return "" if text == "NAN" else text


def to_yahoo(ticker: str) -> str:
    return clean(ticker).replace(".", "-")


def to_eodhd(ticker: str) -> str:
    code = to_yahoo(ticker)
    return f"{code}.US" if code else ""


FORMATS: Dict[str, Callable[[str], str]] = {"raw": clean, "yahoo": to_yahoo, "eodhd": to_eodhd}


def formatter(fmt: str) -> Callable[[str], str]:
    try:
        return FORMATS[fmt]
    except KeyError:
        raise ValueError(f"fmt must be one of {sorted(FORMATS)}") from None
