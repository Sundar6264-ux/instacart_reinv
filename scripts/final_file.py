#!/usr/bin/env python3
import os
import re, math
from pathlib import Path
from datetime import datetime
import pandas as pd

# ========= Paths / Naming =========
INPUT_FILE   = "mapped_items.xlsx"
OUTPUT_XLSX  = "processed_new_inventory_final.xlsx"   # optional xlsx (still produced)
OVERRIDE_DATE = None  # e.g., "20250828" to force a specific date; otherwise use today

# ========= SFTP creds via env =========
INSTACART_SFTP_PASSWORD = os.getenv("INSTACART_SFTP_PASSWORD")
INSTACART_SFTP_USR = os.getenv("INSTACART_SFTP_USR")
INSTACART_SFTP_HOST = os.getenv("INSTACART_SFTP_HOST")

# ========= Regex helpers =========
_INT_OR_WHOLE_FLOAT = re.compile(r'^\d+(?:\.0+)?$')  # "182" or "182.0" allowed

def normalize_numeric_token(s):
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    if s.isdigit():
        return s
    if _INT_OR_WHOLE_FLOAT.fullmatch(s):
        return s.split('.', 1)[0]
    return None

def first_valid_numeric_from_list(s):
    if s is None:
        return None
    for token in re.split(r'[;,]', str(s)):
        norm = normalize_numeric_token(token)
        if norm is not None:
            return norm
    return None

# ========= Size / unit extraction =========
def extract_size_and_unit(name):
    if not isinstance(name, str):
        return name, 1, "each"
    words = name.strip().split()
    if not words:
        return name, 1, "each"
    allowed = {"g","lb","gr","kg","pk","pack","each","oz","mg","ml","l"}
    if words[-1].lower() == "each" and len(words) >= 2:
        t = words[-2]
        m = re.match(r'^(\d+(?:\.\d+)?)([A-Za-z]+)$', t)
        if m:
            try: num = float(m.group(1))
            except ValueError: num = 1
            unit = m.group(2).lower()
            if unit in allowed:
                return " ".join(words[:-2]), num, unit
    t = words[-1]
    m = re.match(r'^(\d+(?:\.\d+)?)([A-Za-z]+)$', t)
    if m:
        try: num = float(m.group(1))
        except ValueError: num = 1
        unit = m.group(2).lower()
        if unit in allowed:
            return " ".join(words[:-1]), num, unit
    return name, 1, "each"

# ========= Lookup-code selection =========
def get_lookup_code(row, product_code_col: str, sku_col: str) -> str:
    pc_raw = row[product_code_col] if pd.notna(row[product_code_col]) else ""
    sku_raw = row[sku_col]         if pd.notna(row[sku_col])         else ""
    pc_str, sku_str = str(pc_raw).strip(), str(sku_raw).strip()
    pc = first_valid_numeric_from_list(pc_str) or normalize_numeric_token(pc_str) or ""
    sk = first_valid_numeric_from_list(sku_str) or normalize_numeric_token(sku_str) or ""
    try: pc_int = int(pc) if pc else None
    except: pc_int = None
    try: sk_int = int(sk) if sk else None
    except: sk_int = None
    if pc_int is not None and sk_int is not None:
        return pc if pc_int >= sk_int else sk
    if pc_int is not None: return pc
    if sk_int is not None: return sk
    return ""

# ========= Retail rounding helper =========
def retail_round(x: float) -> float:
    if pd.isna(x):
        return x
    base = math.floor(x)
    cents = [0.29, 0.49, 0.79, 0.99]
    fractional = x - base
    for c in cents:
        if fractional <= c + 1e-9:
            return round(base + c, 2)
    return round(base + 1 + 0.29, 2)

# ========= Main transform =========
def process_mapped_items(input_file: str) -> pd.DataFrame:
    p = Path(input_file)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    df = pd.read_excel(input_file, dtype={"code": "string", "sku": "string"})
    required = ["name","code","sku","price","priceType"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"Missing required columns: {missing}")
    name_col, code_col, sku_col, price_col, price_type_col = "name","code","sku","price","priceType"
    df_f = df[~df[name_col].astype(str).str.contains(r'case|dozen', case=False, na=False)].copy()
    code_blank = df_f[code_col].isna() | (df_f[code_col].astype(str).str.strip() == "")
    sku_blank  = df_f[sku_col].isna()  | (df_f[sku_col].astype(str).str.strip() == "")
    df_f = df_f[~(code_blank & sku_blank)].copy()
    def _valid_row(r):
        code_is_blank = pd.isna(r[code_col]) or str(r[code_col]).strip() == ""
        return not (code_is_blank and normalize_numeric_token(r[sku_col]) is None)
    df_f = df_f[df_f.apply(_valid_row, axis=1)].copy()
    out = pd.DataFrame()
    base_price = pd.to_numeric(df_f[price_col], errors="coerce") * 1.13
    out["cost_price_per_unit"] = base_price.apply(retail_round)
    def map_cost_unit(x):
        s = str(x).strip().lower()
        if s in ("fixed","fix","fixed price","fixed_price","fixedprice"): return "each"
        if s in ("per unit","per_unit","perunit"): return "lb"
        return ""
    out["cost_unit"] = df_f[price_type_col].apply(map_cost_unit)
    out["lookup_code"] = df_f.apply(lambda r: get_lookup_code(r, code_col, sku_col), axis=1)
    def _process_name(n):
        cleaned,size,uom = extract_size_and_unit(n)
        return pd.Series([cleaned,size,uom])
    out[["name","size","size_uom"]] = df_f[name_col].apply(_process_name)
    out["unit_count"] = df_f["unit_count"] if "unit_count" in df_f.columns else None
    mask_pk = out["size_uom"].isin(["pk","pack"])
    to_fill = out.loc[mask_pk, "unit_count"].isna()
    out.loc[mask_pk & to_fill, "unit_count"] = out.loc[mask_pk & to_fill,"size"].round().astype("Int64")
    out.loc[mask_pk, "size"] = 1
    out["alcoholic"] = False
    out = out[out["lookup_code"].astype(str).str.strip() != ""].copy()
    work = out.copy()
    work["_price_for_rank"] = pd.to_numeric(work["cost_price_per_unit"], errors="coerce").fillna(float("-inf"))
    work["_rank"] = work.groupby("lookup_code")["_price_for_rank"].rank(method="first", ascending=False)
    out = work[work["_rank"] == 1].drop(columns=["_price_for_rank","_rank"]).reset_index(drop=True)
    return out

def save_outputs(df_out: pd.DataFrame, xlsx_path: str, csv_date_override: str | None = None) -> str:
    with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
        df_out.to_excel(writer, index=False, sheet_name="Sheet1")
        workbook, worksheet = writer.book, writer.sheets["Sheet1"]
        text_fmt = workbook.add_format({'num_format': '@'})
        for idx, col in enumerate(df_out.columns):
            if col == "lookup_code":
                worksheet.set_column(idx, idx, 20, text_fmt)
                break
    yyyymmdd = csv_date_override or datetime.now().strftime("%Y%m%d")
    csv_name = f"{yyyymmdd}_store_reinventory.csv"
    df_csv = df_out.copy()
    df_csv["lookup_code"] = df_csv["lookup_code"].astype(str).apply(lambda s: f'="{s}"')
    df_csv.to_csv(csv_name, index=False, encoding="utf-8-sig")
    print(f"✅ Wrote XLSX → {xlsx_path}")
    print(f"✅ Wrote CSV  → {csv_name}")
    return csv_name  # <-- needed by caller

def upload_via_sftp(local_file: str):
    # fail fast if env not set
    if not INSTACART_SFTP_HOST or not INSTACART_SFTP_USR or not INSTACART_SFTP_PASSWORD:
        raise RuntimeError("Missing one or more SFTP env vars: INSTACART_SFTP_HOST, INSTACART_SFTP_USR, INSTACART_SFTP_PASSWORD")

    import paramiko
    host = INSTACART_SFTP_HOST
    username = INSTACART_SFTP_USR
    password = INSTACART_SFTP_PASSWORD
    port = 22
    remote_dir = "/inventory-files/175949-spice_town-1"  # update if Instacart gave a different path

    transport = paramiko.Transport((host, port))
    transport.connect(username=username, password=password)
    sftp = paramiko.SFTPClient.from_transport(transport)

    remote_path = f"{remote_dir}/{Path(local_file).name}"
    sftp.put(local_file, remote_path)
    print(f"✅ Uploaded {local_file} → {remote_path}")

    sftp.close()
    transport.close()

if __name__ == "__main__":
    final_df = process_mapped_items(INPUT_FILE)
    csv_file = save_outputs(final_df, OUTPUT_XLSX, csv_date_override=OVERRIDE_DATE)
    upload_via_sftp(csv_file)

