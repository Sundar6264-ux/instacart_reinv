#!/usr/bin/env python3
import os
import sys
import time
from typing import Dict, Iterable, Optional
import requests
from openpyxl import Workbook
from config import API_TOKEN, BASE_URL,MERCHANT_ID

# ========= Configuration =========
CLOVER_API_TOKEN = API_TOKEN
CLOVER_MERCHANT_ID = MERCHANT_ID

# Tune these if needed
DEFAULT_BATCH_SIZE = 1000  # Clover max
REQUEST_TIMEOUT_SEC = 30
MAX_RETRIES = 5            # for 429/5xx
RETRY_BASE_DELAY = 1.0     # seconds (exponential backoff)
EXPAND = None              # e.g., "categories,tags,itemStock" (not required for selected fields)
FILTER = None              # e.g., "deleted=false"

# ========= Utilities =========
def _require_env(var_name: str) -> str:
    val = os.getenv(var_name)
    if not val:
        print(f"ERROR: Environment variable {var_name} is not set.", file=sys.stderr)
        sys.exit(1)
    return val

def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {CLOVER_API_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def _request_with_retries(method: str, url: str, *, params: Optional[Dict] = None) -> requests.Response:
    """Robust request with basic retry/backoff for 429/5xx."""
    attempt = 0
    while True:
        try:
            resp = requests.request(method, url, headers=_headers(), params=params, timeout=REQUEST_TIMEOUT_SEC)
        except requests.RequestException as e:
            attempt += 1
            if attempt > MAX_RETRIES:
                raise
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            time.sleep(delay)
            continue

        if resp.status_code in (429, 500, 502, 503, 504):
            attempt += 1
            if attempt > MAX_RETRIES:
                resp.raise_for_status()
            # honor Retry-After if present
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            else:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            time.sleep(delay)
            continue

        # Raise for other non-2xx
        resp.raise_for_status()
        return resp

# ========= Clover API ===============
def get_items(*, offset: int, limit: int, expand: Optional[str] = EXPAND, filters: Optional[str] = FILTER):
    """
    Call Clover Inventory Items API.
    Docs: GET /v3/merchants/{mId}/items?offset=&limit=&expand=&filter=
    """
    if not BASE_URL:
        print("ERROR: BASE_URL not configured (missing CLOVER_MERCHANT_ID).", file=sys.stderr)
        sys.exit(1)

    url = f"{BASE_URL}/items"
    params = {
        "offset": offset,
        "limit": min(limit, 1000),  # API cap
    }
    if expand:
        params["expand"] = expand
    if filters:
        params["filter"] = filters

    resp = _request_with_retries("GET", url, params=params)
    data = resp.json()

    # Clover often returns:
    # { "elements": [ ... ], "href": "...", "limit": 1000, "offset": 0, "count": 12345 }
    items = data.get("elements")
    if items is None:
        # In case API returns a raw list (unlikely) or a different wrapper
        items = data if isinstance(data, list) else []
    return items

def iter_all_items(batch_size: int = DEFAULT_BATCH_SIZE) -> Iterable[Dict]:
    """Generator that yields all items across pages."""
    offset = 0
    while True:
        chunk = get_items(offset=offset, limit=batch_size, expand=EXPAND, filters=FILTER)
        if not chunk:
            break
        # Stream out each item without holding the entire dataset in memory
        yield from chunk
        if len(chunk) < batch_size:
            break
        offset += batch_size

# ========= Flattening / Export =========
def flatten_item_min(item: Dict) -> Dict:
    """
    Extract only the required fields from a Clover item.
    NOTE: Clover often uses 'itemCode' for the code; some payloads also have 'code'.
    'price' is typically in cents; 'cost' may require appropriate plan/permissions to be populated.
    """
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "code": item.get("code") or item.get("itemCode"),
        "sku": item.get("sku"),
        "price": item.get("price"),
        "priceType": item.get("priceType"),
        "cost": item.get("cost"),
    }

def export_items_to_excel_min(filepath: str, batch_size: int = DEFAULT_BATCH_SIZE):
    wb = Workbook()
    ws = wb.active
    ws.title = "Items"

    headers = ["id", "name", "code", "sku", "price", "priceType", "cost"]
    ws.append(headers)

    count = 0
    for item in iter_all_items(batch_size=batch_size):
        row = flatten_item_min(item)
        ws.append([row.get(h) for h in headers])
        count += 1

    wb.save(filepath)
    print(f"Wrote {count} items to {filepath}")

# ========= Main =========
if __name__ == "__main__":
    # Validate env before running
    # Optionally set EXPAND/FILTER here if you want to refine results (not required for these columns)
    # EXPAND = None
    # FILTER = "deleted=false"

    out_path = "clover_items.xlsx"
    export_items_to_excel_min(out_path, batch_size=DEFAULT_BATCH_SIZE)
