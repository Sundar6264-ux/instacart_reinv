#!/usr/bin/env python3
import os
import time
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional, Tuple

import requests
from dateutil.relativedelta import relativedelta  # pip install python-dateutil
from openpyxl import Workbook

# ----------------- Config -----------------
CLOVER_API_TOKEN = os.getenv("CLOVER_API_TOKEN")
CLOVER_MERCHANT_ID = os.getenv("CLOVER_MERCHANT_ID")
BASE_URL = f"https://api.clover.com/v3/merchants/{CLOVER_MERCHANT_ID}"

if not CLOVER_API_TOKEN or not CLOVER_MERCHANT_ID:
    print("❌ Missing Clover API credentials in environment variables", file=sys.stderr)
    sys.exit(1)

REQUEST_TIMEOUT_SEC = 30
MAX_RETRIES = 5
RETRY_BASE_DELAY = 1.0
BATCH_SIZE = 1000  # Clover max per page

# ----------------- HTTP helpers -----------------
HEADERS = {
    "Authorization": f"Bearer {CLOVER_API_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

def request_with_retries(method: str, url: str, *, params=None):
    attempt = 0
    while True:
        try:
            resp = requests.request(method, url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT_SEC)
        except requests.RequestException:
            attempt += 1
            if attempt > MAX_RETRIES:
                raise
            time.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            continue

        if resp.status_code in (429, 500, 502, 503, 504):
            attempt += 1
            if attempt > MAX_RETRIES:
                resp.raise_for_status()
            retry_after = resp.headers.get("Retry-After")
            delay = float(retry_after) if (retry_after and retry_after.isdigit()) else (RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            time.sleep(delay)
            continue

        resp.raise_for_status()
        return resp

# ----------------- Time window -----------------
def last_3_month_range_ms(now: Optional[datetime] = None) -> Tuple[int, int]:
    now = now or datetime.now(timezone.utc)
    start = (now - relativedelta(months=3)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000), int(now.timestamp() * 1000)

# ----------------- Generators -----------------
def iter_orders_in_range(start_ms: int, end_ms: int, batch_size: int = BATCH_SIZE) -> Iterable[Dict]:
    """
    Yields orders created in [start_ms, end_ms).
    """
    offset = 0
    url = f"{BASE_URL}/orders"

    while True:
        params = [
            ("offset", offset),
            ("limit", min(batch_size, 1000)),
            ("expand", "lineItems,lineItems.item"),
            ("filter", f"createdTime>={start_ms}"),
            ("filter", f"createdTime<{end_ms}"),
        ]
        resp = request_with_retries("GET", url, params=params)
        data = resp.json()
        orders = data.get("elements", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        if not orders:
            break

        for o in orders:
            ct = o.get("createdTime", 0)
            if start_ms <= ct < end_ms:
                yield o

        if len(orders) < batch_size:
            break
        offset += batch_size

def iter_product_names(start_ms: int, end_ms: int, unique_only: bool = True) -> Iterable[str]:
    """
    Yields product names from all orders in range.
    If unique_only=True, names are de-duplicated on the fly.
    """
    seen = set() if unique_only else None

    for order in iter_orders_in_range(start_ms, end_ms):
        li_container = order.get("lineItems") or {}
        line_items = li_container.get("elements", []) if isinstance(li_container, dict) else []
        if not line_items:
            continue

        for li in line_items:
            linked_item = li.get("item") or {}
            name = linked_item.get("name") or li.get("name")
            if not name:
                continue
            if seen is not None:
                if name in seen:
                    continue
                seen.add(name)
            yield str(name)

# ----------------- Excel export (streaming) -----------------
def export_product_names_last_3_months(filepath: str, unique_only: bool = True) -> None:
    start_ms, end_ms = last_3_month_range_ms()
    print(f"Window: {datetime.fromtimestamp(start_ms/1000, tz=timezone.utc)} → {datetime.fromtimestamp(end_ms/1000, tz=timezone.utc)}")

    wb = Workbook()
    ws = wb.active
    ws.title = "Products (Last 3 Months)"
    ws.append(["product_name"])

    count = 0
    for name in iter_product_names(start_ms, end_ms, unique_only=unique_only):
        ws.append([name])
        count += 1

    wb.save(filepath)
    print(f"Wrote {count} rows to {filepath}")

# ----------------- Main -----------------
if __name__ == "__main__":
    if not CLOVER_API_TOKEN or not MERCHANT_ID:
        raise SystemExit("Set CLOVER_API_TOKEN and CLOVER_MERCHANT_ID (env vars) or edit this file).")
    export_product_names_last_3_months("product_names_last_3_months.xlsx", unique_only=True)
