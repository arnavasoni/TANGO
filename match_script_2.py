from awb_data_ext import extract_awb
from inv_data_ext import extract_invoice
import json
import re
import numpy as np
from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer, util
import os

# Load embedding model for semantic similarity
model_path = os.path.join("models", "all-MiniLM-L6-v2")
embedding_model = SentenceTransformer(model_path)

def semantic_similarity(text1: str, text2: str) -> float:
    """Return similarity score 0-100"""
    if not text1 or not text2:
        return 0.0
    emb1 = embedding_model.encode(text1, convert_to_tensor=True)
    emb2 = embedding_model.encode(text2, convert_to_tensor=True)
    return float(util.cos_sim(emb1, emb2).item() * 100)


# Generic matching rules
def _get(obj, key):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)

def generic_match(awb, inv, thresholds=None, check_invoice = True):
    if thresholds is None:
        thresholds = {"supplier": 85, "consignee": 85, "address": 75}

    # Handle multiple invoice numbers in AWB
    if check_invoice:
        awb_invoices = _get(awb, 'invoice_numbers') or []
        if not isinstance(awb_invoices, list):
            awb_invoices = [awb_invoices]
        invoice_match = str(_get(inv, 'invoice_number')) in [str(i) for i in awb_invoices]
    else:
        invoice_match = True

    # invoice_match = (_get(awb, 'invoice_number') == _get(inv, 'invoice_number')) if check_invoice else True
    supplier_score = fuzz.partial_ratio(str(_get(awb, 'shipper_name')).lower(), str(_get(inv, 'supplier_name')).lower())
    consignee_score = semantic_similarity(_get(awb, 'consignee_name'), _get(inv, 'consignee_name'))
    address_score = semantic_similarity(str(_get(awb, 'consignee_add')).lower(), str(_get(inv, 'consignee_add')).lower())

    matched = (
        invoice_match
        and supplier_score >= thresholds["supplier"]
        and consignee_score >= thresholds["consignee"]
        and address_score >= thresholds["address"]
    )

    scores = {
        "invoice_match": invoice_match if check_invoice else "skipped",
        "supplier_score": round(supplier_score, 2),
        "consignee_score": round(consignee_score, 2),
        "address_score": round(address_score, 2),
    }
    return matched, scores


# Country & Category specific matching rules
def match_mbag_production_parts(awb, inv):
    matched, scores = generic_match(awb, inv)

    # --- Core existing checks ---
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    gross_weight_match = _weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))
    # --- Container match logic ---
    awb_container = _get(awb, 'container_number')
    inv_container = _get(inv, 'container_number')
    awb_other_refs = _get(awb, 'other_reference_numbers') or []
    container_match = False
    if inv_container:
        # 1. Direct container match (if AWB has explicit container number)
        if awb_container and awb_container == inv_container:
            container_match = True
        # 2. Fallback: match against other reference numbers list
        elif any(inv_container == ref for ref in awb_other_refs):
            container_match = True
    # --- Final all_match ---
    all_match = matched and pieces_match and gross_weight_match and container_match

    return all_match, scores


def match_mbag_after_sales_parts(awb, inv):
    matched, scores = generic_match(awb, inv, check_invoice = True)
    # normalize and compare weights due to different formats
    gross_weight_match = _weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    all_match = matched and pieces_match and gross_weight_match
    return all_match, scores

def match_mbag_cbu(awb, inv):
    # VIN and order number must match exactly
    vin_match = _get(awb, 'vin_no') == _get(inv, 'vin_no')
    order_match = _get(awb, 'order_no') == _get(inv, 'order_no')
    matched, scores = generic_match(awb, inv, check_invoice = False)
    all_match = matched and vin_match and order_match
    return all_match, scores

def match_mbusa_cbu(awb, inv):
    # Similar to MBAG CBU but check for US address
    shipper_add = str(_get(awb, 'shipper_add')).lower()
    if not any(x in shipper_add for x in ["us", "usa", "united states"]):
        return False, {}
    return match_mbag_cbu(awb, inv)

def match_mbusI(awb, inv):
    # Check HAWB vs container + number of pieces + gross weight
    hawb_match = _get(awb, 'hawb') == _get(inv, 'container_number')
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    gross_weight_match = _weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))
    all_match = hawb_match and pieces_match and gross_weight_match
    matched, scores = generic_match(awb, inv, check_invoice = False)
    all_match = all_match and matched
    return all_match, scores

def match_bbac_production_parts(awb, inv):
    # Shipper: Beijing Benz, check invoice prefix 150, HAWB match, pieces & weight
    invoice_match = str(_get(inv, 'invoice_number')).startswith("150")
    hawb_match = _get(awb, 'hawb') == _get(inv, 'hawb')
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    gross_weight_match = _weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))
    all_match = invoice_match and hawb_match and pieces_match and gross_weight_match
    matched, scores = generic_match(awb, inv, check_invoice = True)
    all_match = all_match and matched
    return all_match, scores

def match_bbac_after_sales(awb, inv):
    # Shipper: MB Beijing Parts Trading, invoice prefix 1106
    invoice_match = str(_get(inv, 'invoice_number')).startswith("1106")
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    gross_weight_match = normalize_weight(_get(awb, 'gross_weight')) == normalize_weight(_get(inv, 'gross_weight'))
    all_match = invoice_match and pieces_match and gross_weight_match
    matched, scores = generic_match(awb, inv, check_invoice = True)
    all_match = all_match and matched
    return all_match, scores

def match_mb_spare_parts_singapore(awb, inv):
    # Spare parts in goods description, invoice prefix 1100
    invoice_match = str(_get(inv, 'invoice_number')).startswith("1100")
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    gross_weight_match = _weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))
    all_match = invoice_match and pieces_match and gross_weight_match
    matched, scores = generic_match(awb, inv, check_invoice = True)
    all_match = all_match and matched
    return all_match, scores

# helper function for comparing weights
def _weights_approximately_equal(weight1, weight2, tolerance=0.1):
    """Check if two weights are approximately equal within a tolerance.
    
    Args:
        weight1: First weight (string or number)
        weight2: Second weight (string or number)
        tolerance: Maximum allowed difference as a fraction (0.1 = 10%)
        
    Returns:
        bool: True if weights are within the tolerance, False otherwise
    """
    try:
        w1 = float(normalize_weight(weight1) or 0)
        w2 = float(normalize_weight(weight2) or 0)
        
        # Handle case where both weights are zero
        if w1 == 0 and w2 == 0:
            return True
            
        # Calculate the absolute difference and relative difference
        diff = abs(w1 - w2)
        avg = (w1 + w2) / 2
        
        # Consider them equal if within 10% of the average weight
        return diff <= (avg * tolerance)
    except (ValueError, TypeError):
        # If there's any error in conversion, fall back to exact match
        return normalize_weight(weight1) == normalize_weight(weight2)

# Helper to normalize weights like '26.3K' -> 26300 or '131.0 Kgs' -> 131000
def normalize_weight(weight_str):
    if not weight_str:
        return 0
    weight_str = str(weight_str).replace(",", "").replace("kgs", "").replace("kg", "").strip().upper()
    # KEEPING BELOW LINES OF CODE ON HOLD
    # if "K" in weight_str:
    #     return float(weight_str.replace("K", "")) * 1000
    return float(weight_str)

# Map classifier category -> matching function
CATEGORY_MATCHERS = {
    "MBAG Production Parts": match_mbag_production_parts,
    "MBAG After Sales Parts": match_mbag_after_sales_parts,
    "MBAG CBU": match_mbag_cbu,
    "MBUSA CBU": match_mbusa_cbu,
    "MBUSI": match_mbusI,
    "BBAC Production Parts": match_bbac_production_parts,
    "BBAC After Sales Parts": match_bbac_after_sales,
    "MB Spare Parts Singapore": match_mb_spare_parts_singapore,
}

def match_awb_with_invoices(awb_data, invoices_data_list, classification):
    """
    Compare one AWB with multiple invoice documents.
    Returns structured results showing which invoices matched and why.
    """
    category = classification.get("category")
    requires_invoice = classification.get("requires_invoice", True)
    matcher_fn = CATEGORY_MATCHERS.get(category)

    results = []

    if not matcher_fn:
        return {
            "awb_id": awb_data.get("awb_number") or "unknown",
            "category": category,
            "country": classification.get("country"),
            "requires_invoice": requires_invoice,
            "error": f"No matcher defined for category: {category}",
            "results": []
        }

    # Loop through all invoices and compare each with the AWB
    for inv in invoices_data_list:
        result, scores = matcher_fn(awb_data, inv)

        result_entry = {
            "invoice_number": inv.get("invoice_number"),
            "matched": bool(result),
            "scores": scores,
        }
        results.append(result_entry)

    # Choose best matching invoice (optional)
    matched_invoices = [r for r in results if r["matched"]]

    return {
        "awb_id": awb_data.get("awb_number") or "unknown",
        "category": category,
        "country": classification.get("country"),
        "requires_invoice": requires_invoice,
        "matched_invoices": matched_invoices,
        "all_results": results,
        "rules": classification.get("matched_rules"),
    }

if __name__ == "__main__":
    import json
    from classifier import DocumentClassifier
    from awb_data_ext import extract_awb
    from inv_data_ext import extract_invoice

    # === 🔧 CHANGE ONLY THESE PATHS ===
    # awb_path = r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\EQS_awb.pdf"
    # invoice_paths = [
    #     r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\EQS_inv.pdf"
    # ]
    # Or for multi-invoice:
    awb_path = r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\spare_awb_2_inv.pdf"
    invoice_paths = [
        r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\spare_inv_2_inv1.pdf",
        r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\spare_inv_2_inv2.pdf"
    ]

    print("\n=== Extracting AWB & Invoice Data ===")
    awb_data = extract_awb(awb_path).model_dump()

    invoices = []
    for path in invoice_paths:
        inv_data = extract_invoice(path).model_dump()
        invoices.append(inv_data)
        print(f"Loaded invoice: {inv_data.get('invoice_number', '(unknown)')}")

    # === Classification ===
    classifier = DocumentClassifier()
    # Use the first invoice for classification (it just helps pick the category)
    classification = classifier.classify(awb_data, invoices[0])
    print("\n=== CLASSIFICATION ===")
    print(json.dumps(classification, indent=2))

    # === Matching ===
    print("\n=== RUNNING MATCHING ===")
    result = match_awb_with_invoices(awb_data, invoices, classification)

    print("\n=== MATCH RESULTS ===")
    print(json.dumps(result, indent=2))
