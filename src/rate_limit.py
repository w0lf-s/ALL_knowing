from __future__ import annotations

import asyncio
import json
from datetime import date

from src.http import TokenBucket
from src.paths import CACHE, ensure_dirs


class RateLimits:
    def __init__(self) -> None:
        self.finnhub = TokenBucket(50 / 60)
        self.sec = TokenBucket(8.0)
        self.groq = TokenBucket(0.5)
        self._av_lock = asyncio.Lock()

    async def alpha_vantage_slot(self, soft_cap: int = 20) -> bool:
        ensure_dirs()
        path = CACHE / "av_day.json"
        async with self._av_lock:
            today = date.today().isoformat()
            data = {"date": today, "count": 0}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    data = {"date": today, "count": 0}
            if data.get("date") != today:
                data = {"date": today, "count": 0}
            if int(data.get("count", 0)) >= soft_cap:
                return False
            data["count"] = int(data.get("count", 0)) + 1
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
            return True
