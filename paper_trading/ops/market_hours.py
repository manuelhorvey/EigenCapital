"""Weekend market-hours check for Quorrin paper trading engine.

Forex markets are effectively closed from Friday 5pm ET to Sunday 5pm ET.
"""

from datetime import datetime

import pytz

ET = pytz.timezone("US/Eastern")


def is_market_closed() -> bool:
    """Return True if no major market is open (weekend / forex closed window)."""
    now = datetime.now(tz=ET)
    # Saturday (5)
    if now.weekday() == 5:
        return True
    # Sunday (6) — closed before 5pm ET, open after (forex week opens)
    if now.weekday() == 6:
        return now.hour < 17
    # Friday after 5pm ET (forex close)
    return now.weekday() == 4 and now.hour >= 17
