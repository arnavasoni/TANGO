# tango_classifier.py
import re
import json
import sys
from typing import Dict, Any, List, Optional
from datetime import datetime

# ----------------------------------------
# Rule-Based Document Classifier
# ----------------------------------------
class DocumentClassifier:
    def __init__(self):
        self.vin_pattern = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
        self.prefix_map = {
            "490": ("Germany", "MBAG Production Parts"),
            "106": ("Germany", "MBAG After Sales Parts"),
            "150": ("China", "BBAC Production Parts"),
            "1106": ("China", "BBAC After Sales Parts"),
            "1100": ("Singapore", "MB Parts Logistics APAC"),
        }
        self.requires_invoice_categories = {
            "MBAG Production Parts",
            "MBAG After Sales Parts",
            "BBAC Production Parts",
            "BBAC After Sales Parts",
            "MB Parts Logistics APAC",
        }

    def normalize_text(self, text: Optional[str]) -> str:
        if not text:
            return ""
        return text.lower().replace("–", "-").replace("—", "-").strip()

    # def classify(self, awb: Dict[str, Any], inv: Dict[str, Any]) -> Dict[str, Any]:
    # def classify(self, awb: Dict[str, Any], inv: None) -> Dict[str, Any]:
    def classify(self, awb: Dict[str, Any], inv: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Classify AWB + optional Invoice into Country & Category.
        """
        if inv is None:
            inv = {}

        matched_rules: List[str] = []
        country, category = None, None

        # Normalize relevant fields
        shipper = self.normalize_text(awb.get("shipper_name") or inv.get("supplier_name"))
        shipper_add = self.normalize_text(awb.get("shipper_add") or inv.get("supplier_address"))
        consignee = self.normalize_text(awb.get("consignee_name") or inv.get("consignee_name"))
        consignee_add = self.normalize_text(awb.get("consignee_add") or inv.get("consignee_add"))
        goods_desc = self.normalize_text(awb.get("goods_name"))
        hawb = self.normalize_text(awb.get("hawb"))
        container = self.normalize_text(awb.get("hawb") or inv.get("container_number"))
        vin_no = self.normalize_text(awb.get("vin_no"))
        order_no = self.normalize_text(awb.get("order_no"))

        awb_invoice_numbers = awb.get("invoice_numbers") or []
        awb_invoice_no = awb_invoice_numbers[0] if awb_invoice_numbers else ""
        invoice_no = awb_invoice_no

       # --- GERMANY: MBAG Production Parts ---
        if "mercedes-benz ag" in shipper and invoice_no.startswith("490"):
            country, category = "Germany", "MBAG Production Parts"
            matched_rules.append("Shipper: Mercedes-Benz AG + InvPrefix: 490")

        """HAVE CHANGED THIS"""
        # --- GERMANY: MBAG After Sales Parts ---
        elif invoice_no.startswith("106") and ("mercedes-benz ag" in shipper or "germany" in shipper_add or "after sales-parts" in consignee or "after sales-parts" in consignee_add):
            country, category = "Germany", "MBAG After Sales Parts"
            matched_rules.append("Consignee: After Sales + InvPrefix: 106")

        # --- GERMANY: MBAG CBU ---
        elif "mercedes-benz ag" in shipper and self.vin_pattern.search(vin_no) and order_no:
            country, category = "Germany", "MBAG CBU"
            matched_rules.append("VIN + OrderNo detected → MBAG CBU")

        # --- USA: MBUSA CBU ---
        elif "mercedes benz us" in shipper and any(x in shipper_add for x in ["us", "usa", "united states"]):
            if self.vin_pattern.search(vin_no) and order_no:
                country, category = "USA", "MBUSA CBU"
                matched_rules.append("VIN + OrderNo detected → MBUSA CBU")

        # --- USA: MBUSI ---
        elif any(x in shipper_add for x in ["us", "usa", "united states"]):
            if hawb and hawb in container:
                country, category = "USA", "MBUSI"
                matched_rules.append("Consignee Address: USA + HAWB match → MBUSI")

        # --- CHINA: BBAC Production Parts ---
        elif ("beijing" in shipper or "shanghai" in shipper_add) and invoice_no.startswith("150"):
            country, category = "China", "BBAC Production Parts"
            matched_rules.append("Shipper: BBAC + InvPrefix: 150")

        # --- CHINA: BBAC After Sales Parts ---
        elif "parts trading" in shipper and invoice_no.startswith("1106"):
            country, category = "China", "BBAC After Sales Parts"
            matched_rules.append("Shipper: MB Beijing Parts + InvPrefix: 1106")

        # --- SINGAPORE: MB Parts Logistics APAC ---
        elif ("senai" in shipper_add or "malaysia" in shipper_add) and invoice_no.startswith("1100"):
            country, category = "Singapore", "MB Parts Logistics APAC"
            matched_rules.append("Shipper: MB Parts APAC + InvPrefix: 1100")

        # --- Fallback by invoice prefix ---
        elif invoice_no[:4] in self.prefix_map:
            country, category = self.prefix_map[invoice_no[:4]]
            matched_rules.append(f"Fallback prefix mapping: {invoice_no[:4]}")

        requires_invoice = category in self.requires_invoice_categories

        return {
            "country": country or "Unknown",
            "category": category or "Unclassified",
            "requires_invoice": requires_invoice,
            "matched_rules": matched_rules,
        }

# ----------------------------------------
# Main Function
# ----------------------------------------
def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python tango_classifier.py <awb_combined_txt_file>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = input_file.replace("awb_all_output.txt", "awb_classified.json")
    classifier = DocumentClassifier()
    results = []

    # Read combined AWB file
    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = [b.strip() for b in content.split("--------------------------------------------------------------------------------") if b.strip()]

    for block in blocks:
        try:
            entry = json.loads(block)
            awb_data = entry.get("awb") or entry
            classification = classifier.classify(awb_data, inv={})
            results.append({
                "_source_file": entry.get("_source_file", "Unknown"),
                "_timestamp": entry.get("_timestamp", datetime.now().isoformat()),
                "awb_classification": classification
            })
        except Exception as e:
            print(f"[WARN] Failed to classify block: {e}")
            continue

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"✔ Classification finished. Results saved to: {output_file}")


if __name__ == "__main__":
    main()
