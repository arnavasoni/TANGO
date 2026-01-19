import os

MATCHED_RESULTS_FILE = r"C:\Coding\EXIM\watch_dog\matched_results_test.txt"


def clean_file(file_path):
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

        invoice_block = []
        current_invoice_no = None

    for line in lines:
        if line.startswith("AWB FILE:"):
            if inside_invoice_block:
                flush_invoice_block()

            cleaned_lines.append(line)
            seen_invoices_per_awb.clear()
            inside_invoice_block = False
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

    print("Initial cleanup completed successfully.")


if __name__ == "__main__":
    if not os.path.isfile(MATCHED_RESULTS_FILE):
        raise FileNotFoundError(f"File not found: {MATCHED_RESULTS_FILE}")

    clean_file(MATCHED_RESULTS_FILE)
