import json
import os
import re
from typing import List, Dict, Any

MATCH_SCOPE_SINGLE = "SINGLE"
MATCH_SCOPE_GROUP = "GROUP"

# ---- Local imports ----
from tango_classifier import DocumentClassifier

# Utility (copied from shared_utils logic)
def _get(d, key, default=None):
    return d.get(key, default) if d else default

# def normalize_weight(w):
#     if not w:
#         return 0.0
#     try:
#         return float(str(w).replace(",", "").strip())
#     except:
#         return 0.0

def normalize_weight(w):
    if not w:
        return 0.0

    s = str(w).strip().lower()

    # Remove units
    for unit in ["kg", "kgs"]:
        s = s.replace(unit, "")

    s = s.strip()

    # Handle European numbers: 28.877,56 → 28877.56
    if "," in s and s.count(",") == 1 and "." in s:
        # European format
        s = s.replace(".", "").replace(",", ".")
    else:
        # Normal format: remove thousands
        s = s.replace(",", "")

    try:
        return float(s)
    except:
        return 0.0


def _weights_approximately_equal(a, b, tolerance=1.0):
    try:
        return abs(float(a) - float(b)) <= tolerance
    except:
        return False


# ============================================================================
# MATCHING FUNCTIONS (directly aligned with match_script_2 logic)
# ============================================================================

def match_mbag_production_parts(awb, inv, **kwargs):
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    weight_match = _weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))

    awb_container = _get(awb, 'container_number')
    inv_container = _get(inv, 'container_number')
    awb_refs = _get(awb, 'other_reference_numbers') or []

    container_match = False
    if inv_container:
        if awb_container and awb_container == inv_container:
            container_match = True
        elif inv_container in awb_refs:
            container_match = True

    return pieces_match and weight_match and container_match, {
        "pieces_match": pieces_match,
        "weight_match": weight_match,
        "container_match": container_match
    }


# def match_mbag_after_sales_parts(awb, inv, all_invoices=None, **kwargs):
#     awb_inv_nums = set(str(x).strip() for x in (awb.get("invoice_numbers") or []))
#     inv_num = str(inv.get("invoice_number", "")).strip()

#     # Only consider invoices listed in the AWB
#     is_invoice_candidate = inv_num in awb_inv_nums

#     if not is_invoice_candidate:
#         return False, {
#             "reason": "invoice_number_not_listed_in_awb",
#             "invoice_match": False
#         }

#     # Filter only invoices that belong to this AWB
#     related_invoices = [
#         i for i in all_invoices
#         if str(i.get("invoice_number", "")).strip() in awb_inv_nums
#     ]

#     if not related_invoices:
#         # Defensive: no matching invoices found
#         return False, {
#             "reason": "no_related_invoices_found",
#             "invoice_match": True,
#             "invoices_in_awb": list(awb_inv_nums)
#         }

#     # Aggregate pieces and weight if multiple invoices
#     total_pieces = sum(_get(i, "no_pieces") or 0 for i in related_invoices)
#     total_weight = sum(normalize_weight(_get(i, "gross_weight")) for i in related_invoices)

#     pieces_match = int(total_pieces) == int(_get(awb, "no_pieces") or 0)
#     weight_match = _weights_approximately_equal(
#         normalize_weight(_get(awb, "gross_weight")),
#         total_weight
#     )

#     all_match = pieces_match and weight_match

#     return all_match, {
#         "invoice_match": True,
#         "pieces_match": pieces_match,
#         "weight_match": weight_match,
#         "invoices_in_awb": list(awb_inv_nums),
#         "related_invoice_count": len(related_invoices),
#         "total_pieces": total_pieces,
#         "total_weight": total_weight
#     }

def match_mbag_after_sales_parts(awb, inv, all_invoices=None, **kwargs):
    awb_inv_nums = set(str(x).strip() for x in (awb.get("invoice_numbers") or []))
 
    # Decide scope dynamically
    match_scope = (
        MATCH_SCOPE_GROUP
        if len(awb_inv_nums) > 1
        else MATCH_SCOPE_SINGLE
    )
 
    # ------------------
    # GROUP MODE
    # ------------------
    if match_scope == MATCH_SCOPE_GROUP:
        related_invoices = [
            i for i in all_invoices
            if str(i.get("invoice_number", "")).strip() in awb_inv_nums
        ]
 
        if not related_invoices:
            return False, {"reason": "no_related_invoices"}, match_scope
 
        total_pieces = sum(i.get("no_pieces") or 0 for i in related_invoices)
        total_weight = sum(normalize_weight(i.get("gross_weight")) for i in related_invoices)
 
        pieces_match = total_pieces == (awb.get("no_pieces") or 0)
        weight_match = _weights_approximately_equal(
            normalize_weight(awb.get("gross_weight")),
            total_weight
        )
 
        return (
            pieces_match and weight_match,
            {
                "mode": "GROUP",
                "invoice_count": len(related_invoices),
                "total_pieces": total_pieces,
                "total_weight": total_weight,
                "pieces_match": pieces_match,
                "weight_match": weight_match
            },
            match_scope
        )
 
    # ------------------
    # SINGLE MODE
    # ------------------
    inv_num = str(inv.get("invoice_number", "")).strip()
    if inv_num not in awb_inv_nums:
        return False, {"reason": "invoice_not_in_awb"}, match_scope
 
    pieces_match = inv.get("no_pieces") == awb.get("no_pieces")
    weight_match = _weights_approximately_equal(
        inv.get("gross_weight"),
        awb.get("gross_weight")
    )
 
    return (
        pieces_match and weight_match,
        {
            "mode": "SINGLE",
            "pieces_match": pieces_match,
            "weight_match": weight_match
        },
        match_scope
    )



def match_mbag_cbu(awb, inv, **kwargs):
    vin_match = _get(awb, 'vin_no') == _get(inv, 'vin_no')
    order_match = _get(awb, 'order_no') == _get(inv, 'order_no')
    return vin_match and order_match, {
        "vin_match": vin_match,
        "order_match": order_match
    }


def match_mbusa_cbu(awb, inv, **kwargs):
    shipper_add = str(_get(awb, 'shipper_add')).lower()
    if not any(x in shipper_add for x in ["us", "usa", "united states"]):
        return False, {"shipper_add_check": False}
    return match_mbag_cbu(awb, inv)


def match_mbusI(awb, inv, **kwargs):
    hawb_match = _get(awb, 'hawb') == _get(inv, 'container_number')
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    weight_match = _weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))

    all_match = hawb_match and pieces_match and weight_match
    return all_match, {
        "hawb_match": hawb_match,
        "pieces_match": pieces_match,
        "weight_match": weight_match
    }


def match_bbac_production_parts(awb, inv, **kwargs):
    invoice_match = str(_get(inv, 'invoice_number')).startswith("150")
    hawb_match = _get(awb, 'hawb') == _get(inv, 'hawb')
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    weight_match = _weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))

    all_match = invoice_match and hawb_match and pieces_match and weight_match
    return all_match, {
        "invoice_prefix_150": invoice_match,
        "hawb_match": hawb_match,
        "pieces_match": pieces_match,
        "weight_match": weight_match
    }


def match_bbac_after_sales(awb, inv, **kwargs):
    invoice_match = str(_get(inv, 'invoice_number')).startswith("1106")
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    weight_match = _weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))

    all_match = invoice_match and pieces_match and weight_match
    return all_match, {
        "invoice_prefix_1106": invoice_match,
        "pieces_match": pieces_match,
        "weight_match": weight_match
    }


def match_mb_parts_logistics_apac(awb, inv, **kwargs):
    invoice_match = str(_get(inv, 'invoice_number')).startswith("1100")
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    weight_match = _weights_approximately_equal(_get(awb, 'gross_weight'), _get(inv, 'gross_weight'))

    all_match = invoice_match and pieces_match and weight_match
    return all_match, {
        "invoice_prefix_1100": invoice_match,
        "pieces_match": pieces_match,
        "weight_match": weight_match
    }


CATEGORY_MATCHERS = {
    "MBAG Production Parts": match_mbag_production_parts,
    "MBAG After Sales Parts": match_mbag_after_sales_parts,
    "MBAG CBU": match_mbag_cbu,
    "MBUSA CBU": match_mbusa_cbu,
    "MBUSI": match_mbusI,
    "BBAC Production Parts": match_bbac_production_parts,
    "BBAC After Sales Parts": match_bbac_after_sales,
    "MB Parts Logistics APAC": match_mb_parts_logistics_apac
}


# ============================================================================
# LOADING JSON BLOCKS FROM .TXT
# ============================================================================

def load_json_blocks(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        print(f"ERROR: File not found → {path}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    blocks = raw.split("--------------------------------------------------------------------------------")
    json_objects = []

    for b in blocks:
        b = b.strip()
        if not b:
            continue
        try:
            obj = json.loads(b)
            json_objects.append(obj)
        except json.JSONDecodeError:
            continue

    return json_objects


# ============================================================================
# MATCHING ENGINE
# ============================================================================

def match_awb_with_invoices(awb: Dict[str, Any], invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
    awb_core = awb["awb"]
    classification = awb_core.get("classification", {})

    category = classification.get("category")
    matcher = CATEGORY_MATCHERS.get(category)

    if not matcher:
        return {
            "awb_file": awb["_source_file"],
            "error": f"No matching function for category '{category}'",
            "matches": []
        }

    results = []
 
    for inv in invoices:
        inv_core = inv["invoice"]
    
        matched, details, scope = matcher(
            awb_core,
            inv_core,
            all_invoices=[i["invoice"] for i in invoices]
        )
    
        if not matched:
            continue
    
        if scope == MATCH_SCOPE_GROUP:
            # Add ALL invoices referenced by the AWB once
            for i in invoices:
                inv_i = i["invoice"]
                if str(inv_i.get("invoice_number")) in awb_core.get("invoice_numbers", []):
                    results.append({
                        "invoice_file": i["_source_file"],
                        "invoice_number": inv_i.get("invoice_number"),
                        "details": details
                    })
            break  # GROUP match handled once
    
        else:  # SINGLE
            results.append({
                "invoice_file": inv["_source_file"],
                "invoice_number": inv_core.get("invoice_number"),
                "details": details
            })


# ============================================================================
# MAIN SCRIPT
# ============================================================================

def main():
    # === USE YOUR EXACT PATHS ===
    AWB_PATH = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\TANGO\awb_all_output.txt"
    INV_PATH = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\TANGO\invoice_all_output.txt"
    OUT_DIR = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\TANGO"

    os.makedirs(OUT_DIR, exist_ok=True)

    print("Loading AWB + Invoice data...")

    awbs = load_json_blocks(AWB_PATH)
    invoices = load_json_blocks(INV_PATH)

    print(f"Loaded {len(awbs)} AWB entries")
    print(f"Loaded {len(invoices)} Invoice entries")

    all_results = []
    for awb in awbs:
        result = match_awb_with_invoices(awb, invoices)
        all_results.append(result)

    # === Output ===
    out_json = os.path.join(OUT_DIR, "matched_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    # === Output JSON ===
    out_json = os.path.join(OUT_DIR, "matched_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    # === SAVE matched_results.txt (NEW) ===
    # out_txt = os.path.join(OUT_DIR, "matched_results.txt")

    # Replaced the output path of matched_results.txt to DWT_TANGO.

    TXT_DIR = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents"
    os.makedirs(TXT_DIR, exist_ok=True)
    out_txt = os.path.join(TXT_DIR, "matched_results.txt")

    with open(out_txt, "w", encoding="utf-8") as f:
        for entry in all_results:
            f.write(f"AWB FILE: {entry['awb_file']}\n")
            f.write(f"CLASSIFICATION: {entry.get('classification')}\n")

            matches = entry.get("matched_invoices", [])
            if not matches:
                f.write("  → No matches found\n\n")
                continue

            for m in matches:
                f.write("  MATCHED INVOICE:\n")
                f.write(f"    File: {m.get('invoice_file')}\n")
                f.write(f"    Invoice No: {m.get('invoice_number')}\n")
                f.write(f"    Details: {json.dumps(m.get('details', {}), indent=4)}\n")
            f.write("\n")
    log_file = os.path.join(OUT_DIR, "match_log.txt")
    with open(log_file, "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(f"AWB: {r['awb_file']}\n")
            if not r.get("matched_invoices"):
                f.write("  → No matches found\n\n")
                continue
            for m in r["matched_invoices"]:
                f.write(f"  MATCH → Invoice: {m['invoice_file']} | {m['invoice_number']}\n")
            f.write("\n")

    print("\n✓ Matching complete!")
    print(f"→ Results saved to: {out_txt}")
    print(f"→ Log saved to: {log_file}")



if __name__ == "__main__":
    main()
