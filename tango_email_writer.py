import os
import json
import pandas as pd
from datetime import datetime
import logging

# -----------------------------
# Configure logging
# -----------------------------
logging.basicConfig(
    filename="excel_update.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# -----------------------------
# Paths
# -----------------------------
AWB_FILE = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\awb_all_output.txt"
INVOICE_FILE = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\invoice_all_output.txt"
MATCHED_FILE = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\matched_results.txt"
EXCEL_FILE = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\AWB_Invoice_Tracker.xlsx"
TEMP_EXCEL = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\AWB_Invoice_Tracker_temp.xlsx"

# -----------------------------
# Columns
# -----------------------------
SYSTEM_COLUMNS = [
    "HAWB No","FLT_NO","Date","PKG","GW","source",
    "MBS No","MBS Date","Invoice No","INVOICEVAL","Currency",
    "Ex works Price","Packing Charges","Charges to Airport","FOB VALUE","Freight Charges"
]

MANUAL_COLUMNS = [
    "CHA","CCO_NO","COST_CNTR","CCO_DT","TYPE","FOC","DSR_JobNo",
    "DSR_ClearanceDate","Receipt Date","remarks","Dup_BOE_Sub_Date","Dup_BOW_Sub_Remarks"
]

ALL_COLUMNS = SYSTEM_COLUMNS + MANUAL_COLUMNS

# -----------------------------
# Utility Functions
# -----------------------------
def parse_delimited_json(file_path):
    items = []
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        parts = content.split("\n--------------------------------------------------------------------------------\n")
        for p in parts:
            p = p.strip()
            if not p:
                continue
            try:
                items.append(json.loads(p))
            except Exception as e:
                logging.warning(f"Failed to parse JSON: {e}")
    return items


def parse_date(date_str):
    if not date_str or date_str in [None, "null"]:
        return ""
    for fmt in ("%d.%m.%Y","%d-%m-%Y","%d %b %Y","%d %B %Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%d-%m-%Y")
        except:
            continue
    return date_str


def safe_get(d, keys, default=""):
    for key in keys:
        if isinstance(d, dict) and key in d:
            d = d[key]
        else:
            return default
    return d


def try_numeric(val):
    if val in [None, ""]:
        return ""
    try:
        return float(val)
    except:
        return val


# -----------------------------
# Parse Source Files
# -----------------------------
awb_jsons = parse_delimited_json(AWB_FILE)
invoice_jsons = parse_delimited_json(INVOICE_FILE)

print(f"Total AWBs loaded: {len(awb_jsons)}")
print(f"Total Invoices loaded: {len(invoice_jsons)}")

# Lookup by filename (CRITICAL FIX)
awb_file_dict = {
    os.path.basename(a.get("_source_file", "")).strip().lower(): a
    for a in awb_jsons
    if a.get("_source_file")
}

# Lookup by invoice number
invoice_dict = {
    safe_get(i, ["invoice","invoice_number"]): i
    for i in invoice_jsons
    if safe_get(i, ["invoice","invoice_number"])
}

print(f"AWB filename index size: {len(awb_file_dict)}")
print(f"Invoice index size: {len(invoice_dict)}")


# -----------------------------
# Parse matched_results.txt
# -----------------------------
matched_rows = []
matched_hawb_set = set()
matched_invoice_set = set()

current_awb_filename = None
current_has_match = False
current_invoices = []

with open(MATCHED_FILE, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()

        # Start of new AWB block
        if line.startswith("AWB FILE:"):

            # Process previous block
            if current_awb_filename and current_has_match:
                awb_json = awb_file_dict.get(current_awb_filename)

                if awb_json:
                    hawb_no = safe_get(awb_json, ["awb","hawb"])
                    matched_hawb_set.add(hawb_no)

                    for inv_no in current_invoices:
                        invoice_json = invoice_dict.get(inv_no)
                        matched_invoice_set.add(inv_no)

                        row = {col:"" for col in ALL_COLUMNS}

                        # AWB DATA
                        row["HAWB No"] = hawb_no
                        row["FLT_NO"] = safe_get(awb_json, ["awb","flight_date_2"])
                        
                        # Prefer invoice values if available (CORRECTED LOGIC)
                        if invoice_json:
                            row["PKG"] = try_numeric(safe_get(invoice_json, ["invoice","no_pieces"]))
                            row["GW"] = try_numeric(safe_get(invoice_json, ["invoice","gross_weight"]))
                        else:
                            row["PKG"] = try_numeric(safe_get(awb_json, ["awb","no_pieces"]))
                            row["GW"] = try_numeric(safe_get(awb_json, ["awb","gross_weight"]))

                        row["source"] = safe_get(awb_json, ["awb","classification","category"])

                        # INVOICE DATA
                        if invoice_json:
                            row["MBS No"] = safe_get(invoice_json, ["invoice","delivery_note"])
                            row["MBS Date"] = parse_date(safe_get(invoice_json, ["invoice","invoice_date"]))
                            row["Invoice No"] = inv_no
                            row["INVOICEVAL"] = try_numeric(safe_get(invoice_json, ["invoice","total_price"]))
                            row["Currency"] = safe_get(invoice_json, ["invoice","currency"])
                            row["Ex works Price"] = try_numeric(safe_get(invoice_json, ["invoice","ex_factory"]))
                            row["Packing Charges"] = try_numeric(safe_get(invoice_json, ["invoice","packing"]))
                            row["Charges to Airport"] = try_numeric(safe_get(invoice_json, ["invoice","loading_charges"]))
                            row["FOB VALUE"] = try_numeric(
                                safe_get(invoice_json, ["invoice","other_fields","value_fob"])
                            )
                            row["Freight Charges"] = try_numeric(
                                safe_get(invoice_json, ["invoice","air_or_sea_freight_charges"])
                            )

                        matched_rows.append(row)

            # Reset block
            raw_filename = line.replace("AWB FILE:", "").strip()
            current_awb_filename = os.path.basename(raw_filename).strip().lower()
            current_has_match = False
            current_invoices = []

            print(f"\nProcessing: {current_awb_filename}")

        elif "MATCHED INVOICE" in line:
            current_has_match = True

        elif line.startswith("Invoice No:"):
            invoice_no = line.replace("Invoice No:", "").strip()
            current_invoices.append(invoice_no)
            print(f"   Matched invoice: {invoice_no}")

# Process last block
if current_awb_filename and current_has_match:
    awb_json = awb_file_dict.get(current_awb_filename)

    if awb_json:
        hawb_no = safe_get(awb_json, ["awb","hawb"])
        matched_hawb_set.add(hawb_no)

        for inv_no in current_invoices:
            invoice_json = invoice_dict.get(inv_no)
            matched_invoice_set.add(inv_no)

            row = {col:"" for col in ALL_COLUMNS}

            row["HAWB No"] = hawb_no
            row["FLT_NO"] = safe_get(awb_json, ["awb","flight_date_2"])
            row["Date"] = parse_date(safe_get(awb_json, ["awb","executed_on_date"]))
            row["PKG"] = try_numeric(safe_get(awb_json, ["awb","no_pieces"]))
            row["GW"] = try_numeric(safe_get(awb_json, ["awb","gross_weight"]))
            row["source"] = safe_get(awb_json, ["awb","classification","category"])

            if invoice_json:
                row["MBS No"] = safe_get(invoice_json, ["invoice","delivery_note"])
                row["MBS Date"] = parse_date(safe_get(invoice_json, ["invoice","invoice_date"]))
                row["Invoice No"] = inv_no
                row["INVOICEVAL"] = try_numeric(safe_get(invoice_json, ["invoice","total_price"]))
                row["Currency"] = safe_get(invoice_json, ["invoice","currency"])

            matched_rows.append(row)

print("\nMatch Summary")
print(f"Matched rows created: {len(matched_rows)}")
print(f"Unique matched AWBs: {len(matched_hawb_set)}")
print(f"Unique matched invoices: {len(matched_invoice_set)}")


# -----------------------------
# Missing AWBs
# -----------------------------
missing_awb_rows = []

for a in awb_jsons:
    hawb = safe_get(a, ["awb","hawb"])
    if hawb and hawb not in matched_hawb_set:
        row = {col:"" for col in ALL_COLUMNS}
        row["HAWB No"] = hawb
        row["PKG"] = try_numeric(safe_get(a, ["awb","no_pieces"]))
        row["GW"] = try_numeric(safe_get(a, ["awb","gross_weight"]))
        row["source"] = safe_get(a, ["awb","classification","category"])
        missing_awb_rows.append(row)


# -----------------------------
# Missing Invoices
# -----------------------------
missing_invoice_rows = []

for inv_no, inv in invoice_dict.items():
    if inv_no not in matched_invoice_set:
        row = {col:"" for col in ALL_COLUMNS}
        row["Invoice No"] = inv_no
        row["MBS No"] = safe_get(inv, ["invoice","delivery_note"])
        row["MBS Date"] = parse_date(safe_get(inv, ["invoice","invoice_date"]))
        row["INVOICEVAL"] = try_numeric(safe_get(inv, ["invoice","total_price"]))
        row["Currency"] = safe_get(inv, ["invoice","currency"])
        missing_invoice_rows.append(row)


df_matched = pd.DataFrame(matched_rows, columns=ALL_COLUMNS)
df_missing_awb = pd.DataFrame(missing_awb_rows, columns=ALL_COLUMNS)
df_missing_invoice = pd.DataFrame(missing_invoice_rows, columns=ALL_COLUMNS)


# -----------------------------
# Merge with existing Excel
# -----------------------------
def merge_and_save_excel():
    if os.path.exists(EXCEL_FILE):
        try:
            xls = pd.ExcelFile(EXCEL_FILE)
            merged_sheets = {}

            for sheet_name, df_new in zip(
                ["matched","missing_awb","missing_invoice"],
                [df_matched, df_missing_awb, df_missing_invoice]
            ):
                if sheet_name in xls.sheet_names:
                    old_df = pd.read_excel(xls, sheet_name=sheet_name, dtype=str)

                    for col in MANUAL_COLUMNS:
                        if col in old_df.columns:
                            old_map = old_df.set_index("HAWB No")[col].to_dict()
                            df_new[col] = df_new["HAWB No"].map(old_map).fillna("")
                        else:
                            df_new[col] = ""

                merged_sheets[sheet_name] = df_new

            with pd.ExcelWriter(TEMP_EXCEL, engine="openpyxl") as writer:
                for sheet_name, df in merged_sheets.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False)

            os.replace(TEMP_EXCEL, EXCEL_FILE)
            logging.info("Excel updated successfully.")

        except PermissionError:
            logging.warning("Excel file is open. Could not update.")
            print("⚠ Excel file is open. Close it and rerun.")
    else:
        with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl") as writer:
            df_matched.to_excel(writer, sheet_name="matched", index=False)
            df_missing_awb.to_excel(writer, sheet_name="missing_awb", index=False)
            df_missing_invoice.to_excel(writer, sheet_name="missing_invoice", index=False)

        logging.info("Excel created successfully.")


# -----------------------------
# Execute Save
# -----------------------------
merge_and_save_excel()

print("\nFINAL COUNTS")
print(f"Matched rows: {len(df_matched)}")
print(f"Missing AWB rows: {len(df_missing_awb)}")
print(f"Missing Invoice rows: {len(df_missing_invoice)}")
