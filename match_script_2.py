import os
import json
from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer
import httpx

from awb_data_ext import extract_awb
from inv_data_ext import extract_invoice

# ---------------------------
# HTTP client (disable SSL verify if needed)
# ---------------------------
custom_client = httpx.Client(verify=False)

# ---------------------------
# Load & cache embedding model
# ---------------------------
import streamlit as st

@st.cache_resource
def load_embedding_model():
    """
    Load SentenceTransformer model and cache it for Streamlit Cloud.
    """
    model_cache = os.path.join("models", "all-MiniLM-L6-v2")
    return SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', cache_folder=model_cache)

embedding_model = load_embedding_model()

# ---------------------------
# Fuzzy similarity helper
# ---------------------------
def fuzzy_similarity(text1: str, text2: str) -> float:
    """Return fuzzy similarity score 0-100"""
    if not text1 or not text2:
        return 0.0
    return fuzz.token_set_ratio(str(text1).lower(), str(text2).lower())

# ---------------------------
# Generic matching rules
# ---------------------------
def _get(obj, key):
    """Safe get from dict or object attribute"""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)

def generic_match(awb, inv, thresholds=None, check_invoice=True):
    thresholds = thresholds or {"supplier": 85, "consignee": 85, "address": 75}

    # Handle multiple invoice numbers in AWB
    invoice_match = True
    if check_invoice:
        awb_invoices = _get(awb, 'invoice_numbers') or []
        if not isinstance(awb_invoices, list):
            awb_invoices = [awb_invoices]
        invoice_match = str(_get(inv, 'invoice_number')) in [str(i) for i in awb_invoices]

    supplier_score = fuzz.partial_ratio(str(_get(awb, 'shipper_name')).lower(), str(_get(inv, 'supplier_name')).lower())
    consignee_score = fuzzy_similarity(_get(awb, 'consignee_name'), _get(inv, 'consignee_name'))
    address_score = fuzzy_similarity(_get(awb, 'consignee_add'), _get(inv, 'consignee_add'))

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

# ---------------------------
# Weight helpers
# ---------------------------
def normalize_weight(weight_str):
    if not weight_str:
        return 0.0
    weight_str = str(weight_str).replace(",", "").replace("kgs", "").replace("kg", "").strip().upper()
    try:
        return float(weight_str)
    except ValueError:
        return 0.0

def weights_approximately_equal(weight1, weight2, tolerance=0.1):
    w1, w2 = normalize_weight(weight1), normalize_weight(weight2)
    if w1 == 0 and w2 == 0:
        return True
    diff = abs(w1 - w2)
    avg = (w1 + w2) / 2
    return diff <= (avg * tolerance)

# ---------------------------
# Category-specific matchers
# ---------------------------
def match_mbag_production_parts(awb, inv):
    matched, scores = generic_match(awb, inv)
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    gross_weight_match = weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))

    # Container number matching
    awb_container, inv_container = _get(awb, 'container_number'), _get(inv, 'container_number')
    awb_refs = _get(awb, 'other_reference_numbers') or []
    container_match = inv_container and ((awb_container and awb_container == inv_container) or (inv_container in awb_refs))

    all_match = matched and pieces_match and gross_weight_match and container_match
    return all_match, scores

def match_mbag_after_sales_parts(awb, inv):
    matched, scores = generic_match(awb, inv)
    gross_weight_match = weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    return matched and pieces_match and gross_weight_match, scores

def match_mbag_cbu(awb, inv):
    vin_match = _get(awb, 'vin_no') == _get(inv, 'vin_no')
    order_match = _get(awb, 'order_no') == _get(inv, 'order_no')
    matched, scores = generic_match(awb, inv, check_invoice=False)
    return matched and vin_match and order_match, scores

def match_mbusa_cbu(awb, inv):
    shipper_add = str(_get(awb, 'shipper_add')).lower()
    if not any(x in shipper_add for x in ["us", "usa", "united states"]):
        return False, {}
    return match_mbag_cbu(awb, inv)

def match_mbusI(awb, inv):
    hawb_match = _get(awb, 'hawb') == _get(inv, 'container_number')
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    gross_weight_match = weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))
    matched, scores = generic_match(awb, inv, check_invoice=False)
    return hawb_match and pieces_match and gross_weight_match and matched, scores

def match_bbac_production_parts(awb, inv):
    invoice_match = str(_get(inv, 'invoice_number')).startswith("150")
    hawb_match = _get(awb, 'hawb') == _get(inv, 'hawb')
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    gross_weight_match = weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))
    matched, scores = generic_match(awb, inv, check_invoice=True)
    return invoice_match and hawb_match and pieces_match and gross_weight_match and matched, scores

def match_bbac_after_sales(awb, inv):
    invoice_match = str(_get(inv, 'invoice_number')).startswith("1106")
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    gross_weight_match = normalize_weight(_get(awb, 'gross_weight')) == normalize_weight(_get(inv, 'gross_weight'))
    matched, scores = generic_match(awb, inv, check_invoice=True)
    return invoice_match and pieces_match and gross_weight_match and matched, scores

def match_mb_spare_parts_singapore(awb, inv):
    invoice_match = str(_get(inv, 'invoice_number')).startswith("1100")
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    gross_weight_match = weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))
    matched, scores = generic_match(awb, inv, check_invoice=True)
    return invoice_match and pieces_match and gross_weight_match and matched, scores

# ---------------------------
# Category matcher map
# ---------------------------
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

# ---------------------------
# Main matching function
# ---------------------------
def match_awb_with_invoices(awb_data, invoices_data_list, classification):
    category = classification.get("category")
    requires_invoice = classification.get("requires_invoice", True)
    matcher_fn = CATEGORY_MATCHERS.get(category)
    results = []

    if not matcher_fn:
        return {
            "awb_id": awb_data.get("awb_number", "unknown"),
            "category": category,
            "country": classification.get("country"),
            "requires_invoice": requires_invoice,
            "error": f"No matcher defined for category: {category}",
            "results": []
        }

    for inv in invoices_data_list:
        result, scores = matcher_fn(awb_data, inv)
        results.append({
            "invoice_number": inv.get("invoice_number"),
            "matched": bool(result),
            "scores": scores,
        })

    matched_invoices = [r for r in results if r["matched"]]

    return {
        "awb_id": awb_data.get("awb_number", "unknown"),
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
