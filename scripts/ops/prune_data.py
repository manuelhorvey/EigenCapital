#!/usr/bin/env python3
"""Prune data files older than configured retention periods.

This is now maintained at paper_trading/ops/prune_data.py.
This thin wrapper preserves backward compatibility for CLI users.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/prune_data.py
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/prune_data.py --apply
"""

from paper_trading.ops.prune_data import main
from pathlib import Path

if __name__ == "__main__":
    main()
