import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import json

# ---------------- CONFIG ----------------
MATCHED_RESULTS_FILE = r"" # PLACEHOLDER
INVOICE_ALL_OUTPUT_FILE = r"" #PLACEHOLDER
AWB_ALL_OUTPUT_FILE = r"" #PLACEHOLDER
SEPARATOR_LINE = "-" * 80
# ----------------------------------------


class MatchedResultsHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory:
            return

        src_path = os.path.abspath(event.src_path)

        if src_path == os.path.abspath(MATCHED_RESULTS_FILE):
            print("[MATCHED_RESULTS] Change detected. Cleaning duplicate invoices...")
            self.clean_matched_file(MATCHED_RESULTS_FILE)

        elif src_path == os.path.abspath(INVOICE_ALL_OUTPUT_FILE):
            print("[INVOICE_OUTPUT] Change detected. Deduplicating invoices...")
            self.clean_invoice_output(INVOICE_ALL_OUTPUT_FILE)
    
        elif src_path == os.path.abspath(AWB_ALL_OUTPUT_FILE):
            print("[AWB_OUTPUT] Change detected. Deduplicating AWBs...")
            self.clean_awb_output(AWB_ALL_OUTPUT_FILE)


    # ------------------------------------------------------------------
    # PART 1 : EXISTING LOGIC (UNCHANGED)
    # ------------------------------------------------------------------

    def clean_matched_file(self, file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        cleaned_lines = []
        seen_invoices_per_awb = set()

        current_awb = None
        current_invoice_no = None
        invoice_block = []
        inside_invoice_block = False

        def flush_invoice_block():
            """Decide whether to keep or discard the collected invoice block"""
            nonlocal invoice_block, current_invoice_no

            if current_invoice_no not in seen_invoices_per_awb:
                cleaned_lines.extend(invoice_block)
                seen_invoices_per_awb.add(current_invoice_no)
            else:
                print(f"[MATCHED_RESULTS] Duplicate removed: Invoice {current_invoice_no}")

            invoice_block = []
            current_invoice_no = None

        for line in lines:
            # New AWB detected → reset invoice tracking
            if line.startswith("AWB FILE:"):
                # Flush any pending invoice block
                if inside_invoice_block:
                    flush_invoice_block()
                    inside_invoice_block = False

                cleaned_lines.append(line)
                current_awb = line.strip()
                seen_invoices_per_awb.clear()
                continue

            # Start of a new MATCHED INVOICE block
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

                # End of invoice block heuristic:
                # next MATCHED INVOICE or next AWB or EOF handles flushing
                continue

            # Normal line
            cleaned_lines.append(line)

        # Flush last invoice block if file ends
        if inside_invoice_block:
            flush_invoice_block()

        # Write cleaned content back
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(cleaned_lines)

        print("[MATCHED_RESULTS] Cleanup completed.\n")
    
    # ------------------------------------------------------------------
    # PART 2 : NEW LOGIC FOR invoice_all_output.txt
    # ------------------------------------------------------------------
    def clean_invoice_output(self, file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        json_blocks = []
        buffer = []
        brace_count = 0

        for line in lines:
            # Ignore separator lines
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

        latest_invoices = {}

        for block in json_blocks:
            try:
                data = json.loads(block)
                invoice_no = data["invoice"]["invoice_number"]
                # Last occurrence wins
                latest_invoices[invoice_no] = data
            except Exception as e:
                print("[INVOICE_OUTPUT] Skipped invalid JSON block:", e)

        with open(file_path, "w", encoding="utf-8") as f:
            for invoice in latest_invoices.values():
                f.write(SEPARATOR_LINE + "\n")
                f.write(json.dumps(invoice, indent=2))
                f.write("\n\n")

        print(f"[INVOICE_OUTPUT] Kept {len(latest_invoices)} unique invoices\n")
    
        # ------------------------------------------------------------------
    # PART 3 : NEW LOGIC FOR awb_all_output.txt
    # ------------------------------------------------------------------
    def clean_awb_output(self, file_path):
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

        seen_hawb = set()
        seen_invoices = set()
        seen_vins = set()

        kept_blocks = []

        for block in json_blocks:
            try:
                data = json.loads(block)
                awb = data.get("awb", {})

                hawb = awb.get("hawb", "").strip()
                invoice_numbers = awb.get("invoice_numbers", [])
                vin_no = awb.get("vin_no", "").strip()

                duplicate = False

                if hawb and hawb in seen_hawb:
                    duplicate = True

                for inv in invoice_numbers:
                    if inv in seen_invoices:
                        duplicate = True

                if vin_no and vin_no in seen_vins:
                    duplicate = True

                if duplicate:
                    print(f"[AWB_OUTPUT] Duplicate removed: HAWB={hawb}, VIN={vin_no}, INV={invoice_numbers}")
                    continue

                # Mark as seen
                if hawb:
                    seen_hawb.add(hawb)
                for inv in invoice_numbers:
                    seen_invoices.add(inv)
                if vin_no:
                    seen_vins.add(vin_no)

                kept_blocks.append(data)

            except Exception as e:
                print("[AWB_OUTPUT] Skipped invalid JSON block:", e)

        with open(file_path, "w", encoding="utf-8") as f:
            for awb_json in kept_blocks:
                f.write(SEPARATOR_LINE + "\n")
                f.write(json.dumps(awb_json, indent=2))
                f.write("\n\n")

        print(f"[AWB_OUTPUT] Kept {len(kept_blocks)} unique AWB records\n")

def start_watcher():
    folders_to_watch = {
        os.path.dirname(MATCHED_RESULTS_FILE),
        os.path.dirname(INVOICE_ALL_OUTPUT_FILE),
        os.path.dirname(AWB_ALL_OUTPUT_FILE)
    }

    handler = MatchedResultsHandler()
    observer = Observer()

    for folder in folders_to_watch:
        if not os.path.isdir(folder):
            raise Exception(f"Folder does not exist: {folder}")
        observer.schedule(handler, folder, recursive=False)

    observer.start()
    print("Watching matched results & invoice output files...\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    start_watcher()

    # remove after AWB one-time cleanup
    handler = MatchedResultsHandler()
    handler.clean_awb_output(AWB_ALL_OUTPUT_FILE)
