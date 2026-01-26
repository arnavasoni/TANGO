# 26-01-2026
import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import json

# ---------------- CONFIG ----------------
# MATCHED_RESULTS_FILE = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\matched_results.txt"
# INVOICE_ALL_OUTPUT_FILE = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\invoice_all_output.txt"
# AWB_ALL_OUTPUT_FILE = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\awb_all_output.txt"
MATCHED_RESULTS_FILE = r"C:\Users\SONIARN\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\matched_results.txt"
INVOICE_ALL_OUTPUT_FILE = r"C:\Users\SONIARN\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\invoice_all_output.txt"
AWB_ALL_OUTPUT_FILE = r"C:\Users\SONIARN\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\awb_all_output.txt"

SEPARATOR_LINE = "-" * 80

# AWB behavior toggle
KEEP_AWB = "LAST"   # "FIRST" or "LAST"
# ----------------------------------------


class MatchedResultsHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory:
            return

        src_path = os.path.abspath(event.src_path)

        if src_path == os.path.abspath(MATCHED_RESULTS_FILE):
            self.clean_matched_file(MATCHED_RESULTS_FILE)

        elif src_path == os.path.abspath(INVOICE_ALL_OUTPUT_FILE):
            self.clean_invoice_output(INVOICE_ALL_OUTPUT_FILE)

        elif src_path == os.path.abspath(AWB_ALL_OUTPUT_FILE):
            self.clean_awb_output(AWB_ALL_OUTPUT_FILE)

    # ------------------------------------------------------------------
    # PART 1 : MATCHED RESULTS (FIRST WINS)
    # ------------------------------------------------------------------
    def clean_matched_file(self, file_path):
        if not os.path.exists(file_path):
            return

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        cleaned_lines = []
        seen_invoices_per_awb = set()

        current_invoice_no = None
        invoice_block = []
        inside_invoice_block = False

        def flush_invoice_block():
            nonlocal invoice_block, current_invoice_no
            if current_invoice_no not in seen_invoices_per_awb:
                cleaned_lines.extend(invoice_block)
                seen_invoices_per_awb.add(current_invoice_no)
            else:
                print(f"[MATCHED_RESULTS] Removed duplicate invoice {current_invoice_no}")
            invoice_block = []
            current_invoice_no = None

        for line in lines:
            if line.startswith("AWB FILE:"):
                if inside_invoice_block:
                    flush_invoice_block()
                    inside_invoice_block = False

                cleaned_lines.append(line)
                seen_invoices_per_awb.clear()
                continue

            if line.strip() == "MATCHED INVOICE:":
                if inside_invoice_block:
                    flush_invoice_block()
                inside_invoice_block = True
                invoice_block = [line]
                continue

            if inside_invoice_block:
                invoice_block.append(line)
                if "Invoice No:" in line:
                    current_invoice_no = line.split("Invoice No:")[-1].strip()
                continue

            cleaned_lines.append(line)

        if inside_invoice_block:
            flush_invoice_block()

        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(cleaned_lines)

    # ------------------------------------------------------------------
    # PART 2 : INVOICE OUTPUT (FIRST WINS)
    # ------------------------------------------------------------------
    def clean_invoice_output(self, file_path):
        if not os.path.exists(file_path):
            return

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        json_blocks = []
        buffer = []
        brace_count = 0

        for line in lines:
            if line.strip() == SEPARATOR_LINE:
                continue

            for char in line:
                if char == "{":
                    brace_count += 1
                if brace_count > 0:
                    buffer.append(char)
                if char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        json_blocks.append("".join(buffer))
                        buffer = []

        invoices = {}

        for block in json_blocks:
            try:
                data = json.loads(block)
                invoice_no = data["invoice"]["invoice_number"]

                if invoice_no not in invoices:
                    invoices[invoice_no] = data
                else:
                    print(f"[INVOICE_OUTPUT] Removed duplicate invoice {invoice_no}")
            except Exception:
                pass

        with open(file_path, "w", encoding="utf-8") as f:
            for invoice in invoices.values():
                f.write(SEPARATOR_LINE + "\n")
                f.write(json.dumps(invoice, indent=2))
                f.write("\n\n")

    # ------------------------------------------------------------------
    # PART 3 : AWB OUTPUT (FIRST / LAST TOGGLE)
    # ------------------------------------------------------------------
    def clean_awb_output(self, file_path):
        if not os.path.exists(file_path):
            return

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        json_blocks = []
        buffer = []
        brace_count = 0

        for line in lines:
            if line.strip() == SEPARATOR_LINE:
                continue

            for char in line:
                if char == "{":
                    brace_count += 1
                if brace_count > 0:
                    buffer.append(char)
                if char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        json_blocks.append("".join(buffer))
                        buffer = []

        awb_records = {}

        for block in json_blocks:
            try:
                data = json.loads(block)
                awb = data.get("awb", {})

                hawb = awb.get("hawb", "").strip()
                invoice_numbers = tuple(sorted(awb.get("invoice_numbers", [])))
                vin_no = awb.get("vin_no", "").strip()

                key = (hawb, invoice_numbers, vin_no)

                if key not in awb_records:
                    awb_records[key] = data
                else:
                    if KEEP_AWB == "LAST":
                        awb_records[key] = data
                        print(f"[AWB_OUTPUT] Removed earlier duplicate AWB {key}")
                    else:
                        print(f"[AWB_OUTPUT] Removed later duplicate AWB {key}")
            except Exception:
                pass

        with open(file_path, "w", encoding="utf-8") as f:
            for awb_json in awb_records.values():
                f.write(SEPARATOR_LINE + "\n")
                f.write(json.dumps(awb_json, indent=2))
                f.write("\n\n")


def start_watcher():
    handler = MatchedResultsHandler()

    # ------------------------------------------------------
    # 🔹 INITIAL CLEANUP PASS (runs even without modifications)
    # ------------------------------------------------------
    print("Running initial cleanup...\n")
    handler.clean_matched_file(MATCHED_RESULTS_FILE)
    handler.clean_invoice_output(INVOICE_ALL_OUTPUT_FILE)
    handler.clean_awb_output(AWB_ALL_OUTPUT_FILE)

    folders_to_watch = {
        os.path.dirname(MATCHED_RESULTS_FILE),
        os.path.dirname(INVOICE_ALL_OUTPUT_FILE),
        os.path.dirname(AWB_ALL_OUTPUT_FILE)
    }

    observer = Observer()

    for folder in folders_to_watch:
        observer.schedule(handler, folder, recursive=False)

    observer.start()
    print("Watching files...\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    start_watcher()
