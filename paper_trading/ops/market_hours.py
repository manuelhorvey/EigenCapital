"""Weekend market-hours check for EigenCapital paper trading engine.

Forex markets are effectively closed from Friday 5pm ET to Sunday 5pm ET.
"""

from datetime import datetime

import pytz

ET = pytz.timezone("US/Eastern")


def is_market_closed() -> bool:
    """Return True if no major market is open (weekend / forex closed window)."""
    now = datetime.now(tz=ET)
    return _is_closed_time(now)


def is_weekend() -> bool:
    """Return True during the weekend forex close (Fri 5pm ET – Sun 5pm ET).

    Distinct from is_market_closed() because weekend-eligible assets
    (e.g. BTCUSD) should still be tradeable during this window.
    """
    now = datetime.now(tz=ET)
    return _is_closed_time(now)


def _is_closed_time(dt: datetime) -> bool:
    # Saturday (5)
    if dt.weekday() == 5:
        return True
    # Sunday (6) — closed before 5pm ET, open after (forex week opens)
    if dt.weekday() == 6:
        return dt.hour < 17
    # Friday after 5pm ET (forex close)
    return dt.weekday() == 4 and dt.hour >= 17
