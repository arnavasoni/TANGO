
import re
from typing import Dict, Any, List, Optional

class DocumentClassifier:
    """Pure rule-based classifier for determining country & category from extracted AWB/Invoice data.
    Does NOT perform any matching or invoice number comparison.
    """

    def __init__(self):
        self.vin_pattern = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
        self.prefix_map = {
            "490": ("Germany", "MBAG Production Parts"),
            "106": ("Germany", "MBAG After Sales Parts"),
            "150": ("China", "BBAC Production Parts"),
            "1106": ("China", "BBAC After Sales Parts"),
            "1100": ("Singapore", "MB Spare Parts Singapore"),
        }

        # For later use: which categories require invoice-level comparison
        self.requires_invoice_categories = {
            "MBAG Production Parts",
            "MBAG After Sales Parts",
            "BBAC Production Parts",
            "BBAC After Sales Parts",
            "MB Spare Parts Singapore",
        }

    # ----------------------------
    def normalize_text(self, text: Optional[str]) -> str:
        if not text:
            return ""
        return text.lower().replace("–", "-").replace("—", "-").strip()

    # ----------------------------
    def classify(self, awb: Dict[str, Any], inv: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classify AWB + Invoice pair into Country & Category.
        No matching logic, just classification.
        """
        matched_rules: List[str] = []
        country, category = None, None

        # Normalize relevant fields
        shipper = self.normalize_text(awb.get("shipper_name") or inv.get("supplier_name"))
        shipper_add = self.normalize_text(awb.get("shipper_add"))
        consignee = self.normalize_text(awb.get("consignee_name") or inv.get("consignee_name"))
        consignee_add = self.normalize_text(awb.get("consignee_add") or inv.get("consignee_add"))
        goods_desc = self.normalize_text(awb.get("goods_name"))
        hawb = self.normalize_text(awb.get("hawb"))
        container = self.normalize_text(inv.get("container_number"))
        vin_no = self.normalize_text(awb.get("vin_no"))
        order_no = self.normalize_text(awb.get("order_no"))

        awb_invoice_numbers = awb.get("invoice_numbers") or []
        awb_invoice_no = awb_invoice_numbers[0] if awb_invoice_numbers else None
        invoice_no = self.normalize_text(inv.get("invoice_number") or awb_invoice_no)

        # --- GERMANY: MBAG Production Parts ---
        if "mercedes-benz ag" in shipper and invoice_no.startswith("490"):
            country, category = "Germany", "MBAG Production Parts"
            matched_rules.append("Shipper: Mercedes-Benz AG + InvPrefix: 490")

        # --- GERMANY: MBAG After Sales Parts ---
        elif ("after sales-parts" in consignee or "after sales-parts" in consignee_add) and invoice_no.startswith("106"):
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
        elif "beijing" in shipper and invoice_no.startswith("150"):
            country, category = "China", "BBAC Production Parts"
            matched_rules.append("Shipper: BBAC + InvPrefix: 150")

        # --- CHINA: BBAC After Sales Parts ---
        elif "parts trading" in shipper and invoice_no.startswith("1106"):
            country, category = "China", "BBAC After Sales Parts"
            matched_rules.append("Shipper: MB Beijing Parts + InvPrefix: 1106")

        # --- SINGAPORE: MB Spare Parts Singapore ---
        elif "spare parts" in goods_desc and invoice_no.startswith("1100"):
            country, category = "Singapore", "MB Spare Parts Singapore"
            matched_rules.append("GoodsDesc: Spare Parts + InvPrefix: 1100")

        # --- Fallback (based on invoice prefix only) ---
        elif invoice_no[:4] in self.prefix_map:
            country, category = self.prefix_map[invoice_no[:4]]
            matched_rules.append(f"Fallback prefix mapping: {invoice_no[:4]}")

        # --- Determine if invoice-level match should be done ---
        requires_invoice = category in self.requires_invoice_categories

        return {
            "country": country or "Unknown",
            "category": category or "Unclassified",
            "requires_invoice": requires_invoice,
            "matched_rules": matched_rules,
        }


# Wrapper
def classify_awb(awb_data, inv_data):
    classifier = DocumentClassifier()
    return classifier.classify(awb_data, inv_data)


# Demo usage
if __name__ == "__main__":
    from awb_data_ext import extract_awb
    from inv_data_ext import extract_invoice
    import json

    # awb_path = r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\spare_awb_2_inv.pdf"
    # inv_path = r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\spare_inv_2_inv1.pdf"
    awb_path = r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\MBAG_Prod_Parts_AWB.pdf"
    inv_path = r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\MBAG_Prod_Parts_inv.PDF"

    awb_data = extract_awb(awb_path).model_dump()
    inv_data = extract_invoice(inv_path).model_dump()

    classifier = DocumentClassifier()
    result = classifier.classify(awb_data, inv_data)

    print("\n=== CLASSIFICATION RESULT ===")
    print(json.dumps(result, indent=2))
