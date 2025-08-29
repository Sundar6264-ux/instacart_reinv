import pandas as pd

def map_sales_to_inventory(
    inventory_file: str,
    sales_file: str,
    output_file: str,
):
    # Load both sheets
    df_inventory = pd.read_excel(inventory_file)
    df_sales = pd.read_excel(sales_file)

    # Get unique set of product names from sales file
    sales_names = set(df_sales["product_name"].dropna().astype(str).str.strip())

    # --- Apply filtering ---
    # Match by name
    mask_name = df_inventory["name"].astype(str).str.strip().isin(sales_names)

    # Must have SKU or code
    mask_sku_code = (
        df_inventory["sku"].notna() & (df_inventory["sku"].astype(str).str.strip() != "")
    ) | (
        df_inventory["code"].notna() & (df_inventory["code"].astype(str).str.strip() != "")
    )

    # Combine filters
    mask = mask_name & mask_sku_code
    df_mapped = df_inventory[mask].copy()

    # --- Convert price from cents to dollars ---
    if "price" in df_mapped.columns:
        df_mapped["price"] = pd.to_numeric(df_mapped["price"], errors="coerce") / 100.0

    # Write to new Excel with same header as inventory
    df_mapped.to_excel(output_file, index=False)

    print(f"Mapped {len(df_mapped)} items (with sku/code) from {len(df_inventory)} inventory rows.")
    print(f"Converted price from cents → dollars.")
    print(f"Output written to: {output_file}")

if __name__ == "__main__":
    map_sales_to_inventory(
        "clover_items.xlsx",
        "product_names_last_3_months.xlsx",
        "mapped_items.xlsx",
    )
