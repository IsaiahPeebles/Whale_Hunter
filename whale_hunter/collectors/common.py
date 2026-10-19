from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import httpx

log = logging.getLogger("whale_hunter")
_client = httpx.Client(timeout=20, headers={"User-Agent": "whale-hunter/0.1"})


def get_json(url, params=None, retries=4):
    for attempt in range(retries):
        wait = 1.5 * (attempt + 1)
        try:
            r = _client.get(url, params=params)
            if r.status_code == 429:  # rate limited: back off harder, honor Retry-After
                wait = float(r.headers.get("Retry-After") or 2 ** (attempt + 1))
            if r.status_code == 429 or r.status_code >= 500:
                raise httpx.HTTPStatusError(str(r.status_code), request=r.request, response=r)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            if attempt == retries - 1:
                raise
            log.debug("retrying %s in %.1fs: %s", url, wait, e)
            time.sleep(min(wait, 30))


def parse_iso(s):
    """ISO-8601 -> epoch seconds. Handles 'Z' and odd fractional digits (py3.9 fromisoformat can't)."""
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if "." in s:
        head, rest = s.split(".", 1)
        frac = re.match(r"\d*", rest).group()
        tz = rest[len(frac):] or "+00:00"
        s = f"{head}.{frac[:6].ljust(6, '0')}{tz}"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
