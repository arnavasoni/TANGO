import streamlit as st
import pandas as pd
import tempfile
import os
import json
from datetime import datetime

# Import your existing pipeline functions
from awb_data_ext import extract_awb
from inv_data_ext import extract_invoice
from classifier import classify_awb
from match_script_2 import match_awb_with_invoices  # updated to accept classification

# ----------------------------
# 0. Global Constants
# ----------------------------
LOG_FILE = "comparison_log.txt"
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, LOG_FILE)

# ----------------------------
# 1. Page Config
# ----------------------------
st.set_page_config(page_title="EXIM Matching Dashboard", layout="wide")
st.title("📦 EXIM AWB–Invoice Matching Dashboard")

# ----------------------------
# 2. File Upload Section
# ----------------------------
st.sidebar.header("📁 Upload Files")
awb_pdf = st.sidebar.file_uploader("Upload AWB PDF", type=["pdf"])
inv_pdfs = st.sidebar.file_uploader("Upload Invoice PDF(s)", type=["pdf"], accept_multiple_files=True)

run_pipeline = st.sidebar.button("🚀 Run Matching Pipeline")

# ----------------------------
# 3. Run the pipeline if button clicked
# ----------------------------
awb_data, invoices_data, match_results, classification = None, [], None, {}

if run_pipeline and awb_pdf and inv_pdfs:
    # Save uploaded files temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_awb:
        temp_awb.write(awb_pdf.read())
        awb_path = temp_awb.name

    invoice_paths = []
    for inv_file in inv_pdfs:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_inv:
            temp_inv.write(inv_file.read())
            invoice_paths.append(temp_inv.name)

    # --- Pipeline execution ---
    with st.spinner("Extracting AWB data..."):
        awb_data = extract_awb(awb_path).model_dump()

    with st.spinner(f"📄 Extracting {len(invoice_paths)} invoice(s)..."):
        for path in invoice_paths:
            inv_data = extract_invoice(path).model_dump()
            invoices_data.append(inv_data)

    with st.spinner("Classifying..."):
        classification = classify_awb(awb_data, invoices_data[0])

    with st.spinner("Matching AWB & Invoice..."):
        match_results = match_awb_with_invoices(awb_data, invoices_data, classification)

    # ----------------------------
    # 4. Logging (Append to text file)
    # ----------------------------
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write("\n" + "="*60 + "\n")
        f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"AWB File: {awb_pdf.name}\n")
        f.write(f"Invoice Files: {[f.name for f in inv_pdfs]}\n")
        f.write(f"Country: {classification.get('country')}\n")
        f.write(f"Category: {classification.get('category')}\n")

        matched_invs = [inv.get('invoice_number') for inv in match_results.get('matched_invoices', [])]
        f.write(f"Matched Invoices: {matched_invs if matched_invs else 'None'}\n")
        f.write(f"Match Status: {'Matched' if matched_invs else 'Unmatched'}\n")
        f.write("="*60 + "\n")

    # Clean up temp files
    os.unlink(awb_path)
    for path in invoice_paths:
        os.unlink(path)

# ----------------------------
# 5. Display Results
# ----------------------------
if awb_data and invoices_data:
    st.subheader("📜 Extracted AWB and Invoice Data")
    st.write(f"**AWB contains {len(invoices_data)} invoice(s)**")

    awb_df = pd.DataFrame.from_dict(awb_data, orient="index", columns=["AWB"])
    st.dataframe(awb_df, use_container_width=True)

    for i, inv in enumerate(invoices_data, start=1):
        st.markdown(f"### Invoice {i}: {inv.get('invoice_number', '(Unknown)')}")
        inv_df = pd.DataFrame.from_dict(inv, orient="index", columns=["Invoice"])
        st.dataframe(inv_df, use_container_width=True)

if classification:
    st.subheader("🌍 Classification Result")
    col1, col2 = st.columns(2)
    col1.metric("Country", classification.get("country", "Unknown"))
    col2.metric("Category", classification.get("category", "Unclassified"))

if match_results:
    st.subheader("✅ Matching Results Summary")
    all_results = match_results.get("all_results", [])
    results_df = pd.DataFrame(all_results)
    st.dataframe(results_df, use_container_width=True)

    matched_invoices = match_results.get("matched_invoices", [])
    if matched_invoices:
        st.success(f"🎯 Matched {len(matched_invoices)} invoice(s): "
                   f"{', '.join([r['invoice_number'] for r in matched_invoices])}")
    else:
        st.error("❌ No invoices matched this AWB.")

# ----------------------------
# 6. Review Log
# ----------------------------
st.sidebar.markdown("---")
if st.sidebar.button("📖 View Comparison Log"):
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            log_content = f.read()
        st.subheader("📚 Comparison Log History")
        st.text_area("Log Content", log_content, height=300)
    else:
        st.warning("No comparison log found yet.")
