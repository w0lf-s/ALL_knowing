from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx


def sanitize_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"http_{exc.response.status_code}"
    text = str(exc)
    text = re.sub(
        r"(?i)(token|apikey|api_key|key)=[^&\s'\"<>]+",
        r"\1=REDACTED",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180] if text else "request_failed"


def _retry_wait(resp, attempt: int) -> float:
    raw = resp.headers.get("Retry-After") if resp is not None else None
    wait = 2 ** attempt
    if raw:
        try:
            wait = float(raw)
        except Exception:
            wait = 2 ** attempt
    return min(max(wait, 0.1), 3.0)


class HttpClient:
    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retries: int = 3,
        timeout: float | None = None,
    ) -> Any:
        last_err: Exception | None = None
        req = {"params": params, "headers": headers}
        if timeout is not None:
            req["timeout"] = timeout
        for attempt in range(retries):
            try:
                resp = await self._client.get(url, **req)
                if resp.status_code in (429, 500, 502, 503, 504):
                    await asyncio.sleep(_retry_wait(resp, attempt))
                    last_err = httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_err = exc
                await asyncio.sleep(min(2 ** attempt, 3.0))
        raise last_err or RuntimeError("request failed")

    async def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retries: int = 3,
        timeout: float | None = None,
    ) -> str:
        last_err: Exception | None = None
        req = {"params": params, "headers": headers}
        if timeout is not None:
            req["timeout"] = timeout
        for attempt in range(retries):
            try:
                resp = await self._client.get(url, **req)
                if resp.status_code in (429, 500, 502, 503, 504):
                    await asyncio.sleep(_retry_wait(resp, attempt))
                    last_err = httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    continue
                resp.raise_for_status()
                return resp.text
            except Exception as exc:
                last_err = exc
                await asyncio.sleep(min(2 ** attempt, 3.0))
        raise last_err or RuntimeError("request failed")


class TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: float | None = None) -> None:
        self.rate = rate_per_sec
        self.capacity = capacity if capacity is not None else max(rate_per_sec, 1.0)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.updated
                self.updated = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(wait)
