import os
import json

# ---------------- CONFIG ----------------
INVOICE_ALL_OUTPUT_FILE = r""   # PUT YOUR TXT FILE PATH HERE
SEPARATOR_LINE = "-" * 80
# ----------------------------------------


def clean_invoice_output(file_path):
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    json_blocks = []
    buffer = []
    brace_count = 0

    for line in lines:
        # Skip separator lines completely
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
            print("Skipped invalid JSON block:", e)

    with open(file_path, "w", encoding="utf-8") as f:
        for invoice in latest_invoices.values():
            f.write(SEPARATOR_LINE + "\n")
            f.write(json.dumps(invoice, indent=2))
            f.write("\n\n")

    print(
        "Cleanup completed successfully\n"
        f"Unique invoices kept: {len(latest_invoices)}"
    )


if __name__ == "__main__":
    clean_invoice_output(INVOICE_ALL_OUTPUT_FILE)
