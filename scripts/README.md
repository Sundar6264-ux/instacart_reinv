
# Instacart CSV Uploader — Clover → Pipeline

Automated, reproducible pipeline to:
- Retrieve **all inventory** from **Clover** via API
- Pull the **last 3 months** of orders and extract item names
- **Map** sales item names → Clover inventory SKUs
- Apply a **13% markup** to prices
- Generate **Excel** and **CSV** outputs
- **SFTP-upload** the final CSV to Instacart at the designated path
- Expose **downloadable artifacts** from the CI run (when used with GitHub Actions)

> Once uploaded, the file becomes visible on **dashboard.instacart.com** (subject to Instacart’s processing window).


## Repository Structure

```
.
├─ getAllInvItems.py           # Fetches Clover inventory and writes clover_items.xlsx
├─ getOrdersForL3Mos.py        # Fetches last 3 months of orders and writes product_names_last_3_months.xlsx
├─ mapItems.py                 # Maps sales names to inventory SKUs, writes mapped_items.xlsx
├─ final_file.py               # Applies 13% markup, builds final CSV/XLSX, and uploads via SFTP
└─ README.md                   # This file
```


## Requirements

- Python **3.9+** (tested on 3.10/3.11)
- A Clover account with API token and merchant id
- Instacart SFTP credentials
- Network egress to Clover API and Instacart SFTP

Python packages:
```
pandas
requests
python-dateutil
openpyxl
paramiko
```

Install quickly:
```bash
python -m venv .venv
source .venv/bin/activate   # on Windows: .venv\Scripts\activate
pip install -U pip
pip install pandas requests python-dateutil openpyxl paramiko
```


## Configuration

The scripts use environment variables for credentials and destinations.

### Clover
- CLOVER_API_TOKEN — Clover API token
- CLOVER_MERCHANT_ID — Clover merchant id

### Instacart SFTP
- INSTACART_SFTP_HOST — Instacart SFTP host
- INSTACART_SFTP_USR — Instacart SFTP username
- INSTACART_SFTP_PASSWORD — Instacart SFTP password

> **Tip:** Use a `.env` file with a tool like `direnv` or export vars in your CI secrets.

Example (bash):
```bash
export CLOVER_API_TOKEN="***"
export CLOVER_MERCHANT_ID="***"
export INSTACART_SFTP_HOST="sftp.instacart.com"
export INSTACART_SFTP_USR="myuser"
export INSTACART_SFTP_PASSWORD="mypassword"
```


## Outputs

Intermediate and final files (written to the repo root by default):

- clover_items.xlsx — complete inventory from Clover
- product_names_last_3_months.xlsx — unique product names parsed from last-3-months orders
- mapped_items.xlsx — sales names mapped to inventory SKUs
- processed_new_inventory_final.xlsx — final spreadsheet (for review/audit)
- final_inventory.csv — **final CSV uploaded to Instacart** (exact filename determined in `final_file.py`)

> The exact output CSV filename is derived in `final_file.py` and typically includes the current date.


## End-to-End Run (local)

Run the four stages in order:

```bash
# 1) Get Clover inventory
python getAllInvItems.py

# 2) Get last 3 months of orders (names only)
python getOrdersForL3Mos.py

# 3) Map sales names to inventory SKUs
python mapItems.py

# 4) Build final CSV/XLSX and upload via SFTP
python final_file.py
```

If everything is configured correctly, you will see logs indicating the SFTP upload to Instacart succeeded.


## How it Works (High-Level)

1. **Inventory Fetch (`getAllInvItems.py`)**  
   Calls Clover v3 APIs (paginated) with retry logic and compiles a normalized inventory workbook: `clover_items.xlsx`.

2. **Order Names (`getOrdersForL3Mos.py`)**  
   Computes a rolling 3‑month window, fetches orders from Clover, extracts item names, and writes `product_names_last_3_months.xlsx`.

3. **Mapping (`mapItems.py`)**  
   Joins item names from step #2 to inventory from step #1, producing `mapped_items.xlsx` with SKU/price metadata aligned.

4. **Finalize + Markup + SFTP (`final_file.py`)**  
   - Normalizes and **applies a 13% markup** to per‑unit price  
   - Generates an auditable Excel (`processed_new_inventory_final.xlsx`) and the **final CSV**  
   - Uses **Paramiko** to open an SFTP session to Instacart and upload the CSV to the **designated path**


## GitHub Actions (CI) Example

Create `.github/workflows/pipeline.yml`:

```yaml
name: Clover → Instacart CSV

on:
  workflow_dispatch:
  schedule:
    - cron: "0 12 * * 1-6"   # Mon–Sat 12:00 UTC (adjust as needed)

jobs:
  run-pipeline:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install deps
        run: |
          python -m venv .venv
          source .venv/bin/activate
          pip install -U pip
          pip install pandas requests python-dateutil openpyxl paramiko

      - name: Run pipeline
        env:
          CLOVER_API_TOKEN: ${{{{ secrets.CLOVER_API_TOKEN }}}}
          CLOVER_MERCHANT_ID: ${{{{ secrets.CLOVER_MERCHANT_ID }}}}
          INSTACART_SFTP_HOST: ${{{{ secrets.INSTACART_SFTP_HOST }}}}
          INSTACART_SFTP_USR: ${{{{ secrets.INSTACART_SFTP_USR }}}}
          INSTACART_SFTP_PASSWORD: ${{{{ secrets.INSTACART_SFTP_PASSWORD }}}}
        run: |
          source .venv/bin/activate
          python getAllInvItems.py
          python getOrdersForL3Mos.py
          python mapItems.py
          python final_file.py

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: outputs
          path: |
            clover_items.xlsx
            product_names_last_3_months.xlsx
            mapped_items.xlsx
            processed_new_inventory_final.xlsx
            *.csv
          if-no-files-found: warn
```

This workflow:
- Runs on a manual trigger or a schedule
- Installs dependencies
- Executes the four pipeline stages
- Publishes all generated files as **build artifacts** you can download from the run


## Troubleshooting

- **401/403 from Clover**  
  Ensure `CLOVER_API_TOKEN` and `CLOVER_MERCHANT_ID` are set correctly and the token has the required scopes.

- **Large Clover datasets**  
  Scripts use pagination and basic retry/backoff. If you hit API limits, increase delays or schedule during off-peak hours.

- **SFTP upload fails**  
  Verify host/user/password and firewall rules. Confirm the **destination path** required by Instacart. Paramiko errors will include the failing stage.

- **CSV schema mismatch on Instacart**  
  Confirm the final CSV column order and formatting expected by Instacart. Adjust field mapping in `final_file.py` if your Instacart spec differs.

- **Different markup**  
  The 13% markup is hard-coded in `final_file.py`. Change the constant there if you need an alternate rate.


## Security Notes

- Never commit credentials. Store them as **GitHub Actions secrets** or local environment variables.
- Rotate API tokens and SFTP passwords regularly.
- Review logs before sharing a run to ensure no secrets are printed.


## License

Proprietary — 2025. All rights reserved.  
(Replace with your preferred license.)
