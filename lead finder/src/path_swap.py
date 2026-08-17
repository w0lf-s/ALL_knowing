from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator

from src.config import LEAD_SCRAPER_DIR, ROOT


@contextmanager
def linkedin_src_path() -> Iterator[None]:
    lead_src = str(ROOT)
    li_root = str(LEAD_SCRAPER_DIR)
    removed: list[tuple[int, str]] = []
    for i, entry in list(enumerate(sys.path)):
        if entry == lead_src or entry.rstrip("\\/") == str(ROOT).rstrip("\\/"):
            removed.append((i, entry))
    for i, _ in reversed(removed):
        sys.path.pop(i)
    if li_root in sys.path:
        sys.path.remove(li_root)
    sys.path.insert(0, li_root)

    cached = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "src" or k.startswith("src.")}
    try:
        yield
    finally:
        for k in list(sys.modules):
            if k == "src" or k.startswith("src."):
                sys.modules.pop(k, None)
        sys.modules.update(cached)
        if li_root in sys.path:
            sys.path.remove(li_root)
        for i, entry in removed:
            sys.path.insert(min(i, len(sys.path)), entry)
