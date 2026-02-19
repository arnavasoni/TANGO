# 19-02-2026
import json
import os
import re
from typing import List, Dict, Any

MATCH_SCOPE_SINGLE = "SINGLE"
MATCH_SCOPE_GROUP = "GROUP"

# ---- Local imports ----
from tango_classifier import DocumentClassifier

LOCK_FILE = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\matching.lock"

# Utility (copied from shared_utils logic)
def _get(d, key, default=None):
    return d.get(key, default) if d else default

def normalize_invoice_number(x):
    if not x:
        return ""
    return re.sub(r"\D", "", str(x))

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

def single_result(matched, details):
    return matched, details, MATCH_SCOPE_SINGLE

# ============================================================================
# MATCHING FUNCTIONS (directly aligned with match_script_2 logic)
# ============================================================================

def match_mbag_production_parts(awb, inv, **kwargs):
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    weight_match = _weights_approximately_equal(
        _get(awb, 'gross_weight'),
        _get(inv, 'gross_weight')
    )
 
    awb_container = _get(awb, 'container_number')
    inv_container = _get(inv, 'container_number')
    awb_refs = _get(awb, 'other_reference_numbers') or []
 
    container_match = False
    if inv_container:
        container_match = (
            awb_container == inv_container or
            inv_container in awb_refs
        )
 
    matched = pieces_match and weight_match and container_match
 
    return matched, {
        "pieces_match": pieces_match,
        "weight_match": weight_match,
        "container_match": container_match
    }, MATCH_SCOPE_SINGLE

def match_mbag_after_sales_parts(awb, inv, all_invoices=None, **kwargs):
    
    awb_inv_nums = set(normalize_invoice_number(x) for x in (awb.get("invoice_numbers") or []))


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
        if normalize_invoice_number(i.get("invoice_number")) in awb_inv_nums
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
 
    matched = vin_match and order_match
 
    return matched, {
        "vin_match": vin_match,
        "order_match": order_match
    }, MATCH_SCOPE_SINGLE

def match_mbusa_cbu(awb, inv, **kwargs):
    shipper_add = str(_get(awb, 'shipper_add', '')).lower()
    if not any(x in shipper_add for x in ["us", "usa", "united states"]):
        return False, {"shipper_add_check": False}, MATCH_SCOPE_SINGLE
 
    return match_mbag_cbu(awb, inv)

def match_mbusI(awb, inv, all_invoices=None, **kwargs):
    awb_inv_nums = set(
        normalize_invoice_number(x)
        for x in (awb.get("invoice_numbers") or [])
    )

    # GROUP
    if len(awb_inv_nums) > 1:
        related = [
            i for i in (all_invoices or [])
            if normalize_invoice_number(i.get("invoice_number")) in awb_inv_nums
        ]

        total_pieces = sum(i.get("no_pieces") or 0 for i in related)
        total_weight = sum(normalize_weight(i.get("gross_weight")) for i in related)

        pieces_match = total_pieces == (awb.get("no_pieces") or 0)
        weight_match = _weights_approximately_equal(
            normalize_weight(awb.get("gross_weight")),
            total_weight
        )

        return (
            pieces_match and weight_match,
            {
                "mode": "GROUP",
                "invoice_count": len(related),
                "pieces_match": pieces_match,
                "weight_match": weight_match
            },
            MATCH_SCOPE_GROUP
        )

    # SINGLE
    inv_num = normalize_invoice_number(inv.get("invoice_number"))
    if awb_inv_nums and inv_num not in awb_inv_nums:
        return False, {"reason": "invoice_not_in_awb"}, MATCH_SCOPE_SINGLE

    hawb_match = _get(awb, 'hawb') == _get(inv, 'container_number')
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    weight_match = _weights_approximately_equal(
        _get(awb, 'gross_weight'),
        _get(inv, 'gross_weight')
    )

    return (
        hawb_match and pieces_match and weight_match,
        {
            "mode": "SINGLE",
            "hawb_match": hawb_match,
            "pieces_match": pieces_match,
            "weight_match": weight_match
        },
        MATCH_SCOPE_SINGLE
    )

def match_bbac_production_parts(awb, inv, all_invoices=None, **kwargs):
    awb_inv_nums = set(
        normalize_invoice_number(x)
        for x in (awb.get("invoice_numbers") or [])
    )

    # GROUP
    if len(awb_inv_nums) > 1:
        related = [
            i for i in (all_invoices or [])
            if normalize_invoice_number(i.get("invoice_number")) in awb_inv_nums
        ]

        total_pieces = sum(i.get("no_pieces") or 0 for i in related)
        total_weight = sum(normalize_weight(i.get("gross_weight")) for i in related)

        pieces_match = total_pieces == (awb.get("no_pieces") or 0)
        weight_match = _weights_approximately_equal(
            normalize_weight(awb.get("gross_weight")),
            total_weight
        )

        return (
            pieces_match and weight_match,
            {
                "mode": "GROUP",
                "invoice_prefix_150": True,
                "invoice_count": len(related),
                "pieces_match": pieces_match,
                "weight_match": weight_match
            },
            MATCH_SCOPE_GROUP
        )

    # SINGLE
    inv_num = normalize_invoice_number(inv.get("invoice_number"))
    if awb_inv_nums and inv_num not in awb_inv_nums:
        return False, {"reason": "invoice_not_in_awb"}, MATCH_SCOPE_SINGLE

    invoice_match = inv_num.startswith("150")
    hawb_match = _get(awb, 'hawb') == _get(inv, 'hawb')
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    weight_match = _weights_approximately_equal(
        _get(awb, 'gross_weight'),
        _get(inv, 'gross_weight')
    )

    return (
        invoice_match and hawb_match and pieces_match and weight_match,
        {
            "mode": "SINGLE",
            "invoice_prefix_150": invoice_match,
            "hawb_match": hawb_match,
            "pieces_match": pieces_match,
            "weight_match": weight_match
        },
        MATCH_SCOPE_SINGLE
    )


def match_bbac_after_sales(awb, inv, all_invoices=None, **kwargs):
    awb_inv_nums = set(
        normalize_invoice_number(x)
        for x in (awb.get("invoice_numbers") or [])
    )

    # GROUP
    if len(awb_inv_nums) > 1:
        related = [
            i for i in (all_invoices or [])
            if normalize_invoice_number(i.get("invoice_number")) in awb_inv_nums
        ]

        total_pieces = sum(i.get("no_pieces") or 0 for i in related)
        total_weight = sum(normalize_weight(i.get("gross_weight")) for i in related)

        pieces_match = total_pieces == (awb.get("no_pieces") or 0)
        weight_match = _weights_approximately_equal(
            normalize_weight(awb.get("gross_weight")),
            total_weight
        )

        return (
            pieces_match and weight_match,
            {
                "mode": "GROUP",
                "invoice_count": len(related),
                "pieces_match": pieces_match,
                "weight_match": weight_match
            },
            MATCH_SCOPE_GROUP
        )

    # SINGLE
    inv_num = normalize_invoice_number(inv.get("invoice_number"))
    if awb_inv_nums and inv_num not in awb_inv_nums:
        return False, {"reason": "invoice_not_in_awb"}, MATCH_SCOPE_SINGLE

    invoice_match = inv_num.startswith("1106")
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    weight_match = _weights_approximately_equal(
        _get(awb, 'gross_weight'),
        _get(inv, 'gross_weight')
    )

    return (
        invoice_match and pieces_match and weight_match,
        {
            "mode": "SINGLE",
            "invoice_prefix_1106": invoice_match,
            "pieces_match": pieces_match,
            "weight_match": weight_match
        },
        MATCH_SCOPE_SINGLE
    )


# REVISED
def match_mb_parts_logistics_apac(awb, inv, all_invoices=None, **kwargs):
    awb_inv_nums = set(
        normalize_invoice_number(x)
        for x in (awb.get("invoice_numbers") or [])
    )

    # ------------------
    # GROUP MODE
    # ------------------
    if len(awb_inv_nums) > 1:
        related = [
            i for i in (all_invoices or [])
            if normalize_invoice_number(i.get("invoice_number")) in awb_inv_nums
        ]

        if not related:
            return False, {"reason": "no_related_invoices"}, MATCH_SCOPE_GROUP

        total_pieces = sum(i.get("no_pieces") or 0 for i in related)
        total_weight = sum(normalize_weight(i.get("gross_weight")) for i in related)

        pieces_match = total_pieces == (awb.get("no_pieces") or 0)
        weight_match = _weights_approximately_equal(
            normalize_weight(awb.get("gross_weight")),
            total_weight
        )

        return (
            pieces_match and weight_match,
            {
                "mode": "GROUP",
                "invoice_count": len(related),
                "total_pieces": total_pieces,
                "total_weight": total_weight,
                "pieces_match": pieces_match,
                "weight_match": weight_match
            },
            MATCH_SCOPE_GROUP
        )

    # ------------------
    # SINGLE MODE
    # ------------------
    inv_num = normalize_invoice_number(inv.get("invoice_number"))

    if awb_inv_nums and inv_num not in awb_inv_nums:
        return False, {"reason": "invoice_not_in_awb"}, MATCH_SCOPE_SINGLE

    invoice_match = inv_num.startswith("1100")
    pieces_match = _get(awb, 'no_pieces') == _get(inv, 'no_pieces')
    weight_match = _weights_approximately_equal(
        _get(awb, 'gross_weight'),
        _get(inv, 'gross_weight')
    )

    return (
        invoice_match and pieces_match and weight_match,
        {
            "mode": "SINGLE",
            "invoice_prefix_1100": invoice_match,
            "pieces_match": pieces_match,
            "weight_match": weight_match
        },
        MATCH_SCOPE_SINGLE
    )

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
            "matched_invoices": []
        }

    results = []

    # ------------------------------------------------
    # FIRST: Check if this category supports GROUP
    # ------------------------------------------------
    dummy_invoice = invoices[0]["invoice"] if invoices else {}

    # matched, details, scope = matcher(
    #     awb_core,
    #     dummy_invoice,
    #     all_invoices=[i["invoice"] for i in invoices]
    # )

    matched, details, scope = matcher(
        awb_core,
        {},
        all_invoices=[i["invoice"] for i in invoices]
    )


    # ------------------
    # GROUP MATCH
    # ------------------
    if matched and scope == MATCH_SCOPE_GROUP:
        # awb_inv_nums = set(str(x).strip() for x in (awb_core.get("invoice_numbers") or []))
        awb_inv_nums = set(normalize_invoice_number(x) for x in (awb_core.get("invoice_numbers") or []))

        for i in invoices:
            inv_i = i["invoice"]
            # if str(inv_i.get("invoice_number", "")).strip() in awb_inv_nums:
            if normalize_invoice_number(inv_i.get("invoice_number")) in awb_inv_nums:
                results.append({
                    "invoice_file": i["_source_file"],
                    "invoice_number": inv_i.get("invoice_number"),
                    "details": details
                })

        return {
            "awb_file": awb["_source_file"],
            "classification": classification,
            "matched_invoices": results
        }

    # ------------------
    # SINGLE MATCH
    # ------------------
    for inv in invoices:
        inv_core = inv["invoice"]

        matched, details, scope = matcher(
            awb_core,
            inv_core,
            all_invoices=[i["invoice"] for i in invoices]
        )

        if not matched or scope != MATCH_SCOPE_SINGLE:
            continue

        results.append({
            "invoice_file": inv["_source_file"],
            "invoice_number": inv_core.get("invoice_number"),
            "details": details
        })

    return {
        "awb_file": awb["_source_file"],
        "classification": classification,
        "matched_invoices": results
    }

# ============================================================================
# MAIN SCRIPT
# ============================================================================

def main():
    # === PATHS ===
    AWB_PATH = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\awb_all_output.txt"
    INV_PATH = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\invoice_all_output.txt"
    OUT_DIR = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents"

    os.makedirs(OUT_DIR, exist_ok=True)

    previous_matches_path = os.path.join(OUT_DIR, "matched_results.json")

    # ----------------------------------------------------
    # LOAD PREVIOUS RESULTS (if any)
    # ----------------------------------------------------
    old_results = []
    already_processed_awbs = set()

    if os.path.exists(previous_matches_path):
        with open(previous_matches_path, "r", encoding="utf-8") as f:
            old_results = json.load(f)

        for r in old_results:
            already_processed_awbs.add(r.get("awb_file"))

    # ----------------------------------------------------
    # LOAD DATA (ONLY ONCE)
    # ----------------------------------------------------
    print("Loading AWB + Invoice data...")

    awbs = load_json_blocks(AWB_PATH)
    invoices = load_json_blocks(INV_PATH)

    print(f"Loaded {len(awbs)} AWB entries")
    print(f"Loaded {len(invoices)} Invoice entries")

    # ----------------------------------------------------
    # MATCHING
    # ----------------------------------------------------
    all_results = old_results.copy()

    for awb in awbs:
        if awb["_source_file"] in already_processed_awbs:
            continue  # Skip already matched AWBs

        result = match_awb_with_invoices(awb, invoices)
        all_results.append(result)

    # ----------------------------------------------------
    # SAVE JSON RESULTS
    # ----------------------------------------------------
    out_json = os.path.join(OUT_DIR, "matched_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    # ----------------------------------------------------
    # SAVE TXT REPORT
    # ----------------------------------------------------
    out_txt = os.path.join(OUT_DIR, "matched_results.txt")

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

    # ----------------------------------------------------
    # SAVE MATCH LOG
    # ----------------------------------------------------
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
    # -------------------------------
    # CREATE READ-LOCK
    # -------------------------------
    open(LOCK_FILE, "w").close()

    try:
        main()
    finally:
        # -------------------------------
        # RELEASE READ-LOCK
        # -------------------------------
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)

