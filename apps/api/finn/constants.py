"""Shared constants across FINN API, storage, network, and pipeline modules.

Contains zero 3rd-party dependencies so it is safe to import anywhere in the serverless bundle.
"""

from __future__ import annotations

# Lenders / financial intermediaries where EBITDA is not meaningful (interest is their operating cost of funds)
LENDER_SYMBOLS: frozenset[str] = frozenset({"HDFCBANK", "BAJFINANCE", "CREDITACC", "CAMS"})
