"""Root pytest conftest.

Adds every immediate subdirectory of ``tests/`` to ``sys.path`` so a test
module in one phase's test directory (e.g. ``tests/baseline/``) can import
another phase's shared helpers module (e.g. ``from backtest_helpers import
...``) without duplicating fixture-building code, regardless of pytest's
test collection order. Each phase still owns its own ``*_helpers.py`` file
(``tests/data/helpers.py``, ``tests/backtest/backtest_helpers.py``,
``tests/trade_journal/journal_helpers.py``, ``tests/storage/storage_helpers.py``)
-- this only makes those importable from sibling test directories.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
for _entry in sorted(_TESTS_DIR.iterdir()):
    if _entry.is_dir() and not _entry.name.startswith((".", "__")):
        path_str = str(_entry)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
