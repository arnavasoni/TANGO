# 19-02-2026
import os
import sys
import json
import fitz
from io import BytesIO
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Union

from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser

# ✅ NEW — same as process_awb.py
from langchain_google_genai import ChatGoogleGenerativeAI

from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------
# CONFIG
# ---------------------------------------------------
NEXUS_BASE_URL = "https://genai-nexus.int.api.corpinter.net"
NEXUS_API_KEY = os.getenv("NEXUS_API_KEY")

INVOICE_JSON_FOLDER = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\Invoice\Processed"
INVOICE_COMBINED_OUTPUT = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\invoice_all_output.txt"

# ---------------------------------------------------
# 1. DATA SCHEMA (same as inv_data_ext.py)
# ---------------------------------------------------
class Invoice(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    delivery_note: Optional[str] = None
    supplier_name: str
    supplier_address: str
    consignee_name: str
    consignee_add: str
    no_pieces: Optional[int] = None
    gross_weight: Optional[Union[str, float]] = None
    container_number: Optional[str] = None
    order_no: Optional[str] = None
    vin_no: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    packing: Optional[float] = None
    ex_factory: Optional[float] = None
    air_or_sea_freight_charges: Optional[float] = None
    fca_charges: Optional[float] = None
    dgr_fee: Optional[float] = None
    loading_charges: Optional[float] = None
    value_cfr: Optional[float] = None
    transport_insurance: Optional[float] = None
    value_added_tax: Optional[float] = None
    total_price: Optional[float] = None
 
    other_fields: Optional[Dict[str, Any]] = {}

invoice_parser = PydanticOutputParser(pydantic_object=Invoice)

# ---------------------------------------------------
# 2. Gemini model (SAME STYLE AS AWB)
# ---------------------------------------------------
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-pro",
    google_api_key=NEXUS_API_KEY,
    client_options={"api_endpoint": NEXUS_BASE_URL},
    transport="rest",
    temperature=0,
)

# ---------------------------------------------------
# 3. Helper functions
# ---------------------------------------------------
def clean_inv_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned_text = " ".join(lines)
    cleaned_text = " ".join(cleaned_text.split())
    print("Invoice text cleaned.\n")
    return cleaned_text


# ---------------------------------------------------
# 3. Invoice extraction
# ---------------------------------------------------
def extract_invoice_from_bytes(file_bytes: BytesIO) -> Invoice:
    file_bytes.seek(0)
    doc = fitz.open("pdf", file_bytes.read())

    pages_text = []
    for page in doc:
        raw = page.get_text()
        cleaned = clean_inv_text(raw)
        pages_text.append(cleaned)

    combined_text = "\n\n".join(pages_text)

    # ---------------------------------------------------
    # PROMPT — EXACT, UNCHANGED FROM inv_data_ext.py
    # ---------------------------------------------------
    def build_invoice_prompt():
        return ChatPromptTemplate.from_messages([
        (
        "system",
        """You are a strict invoice data extraction engine.
    
        Extract ONLY explicitly stated values from the provided invoice text.
        Do NOT infer, assume, calculate, or guess.
        If a field is missing, return null.
        Return valid JSON only. No markdown. No explanations.
        The output MUST strictly match the provided schema.
    
        ---------------------------------
        SYNONYMS
        ---------------------------------
        - Invoice Number = Document No.
        - Buyer = Consignee
        - Bill To = Consignee
        - Shipper = Supplier
    
        ---------------------------------
        DATE RULES
        ---------------------------------
        - Extract dates exactly as written.
        - Return the dates in the dd-mm-yyyy format.
    
        ---------------------------------
        WEIGHT RULES
        ---------------------------------
        - Extract GROSS weight only.
        - European format: commas = decimal separator, periods = thousands separator.
        Example:
            "28.877,56 KG" → 28877.56
        - Remove all units (KG, kg, etc.).
        - Return numeric value only.
        - Do NOT extract net weight.
    
        ---------------------------------
        QUANTITY RULES
        ---------------------------------
        - no_pieces must be an integer only, count package number or number of packages.
    
        ---------------------------------
        ORDER NUMBER
        ---------------------------------
        - order_no must be a continuous 10-digit number.
        - Remove spaces and non-numeric characters.
        Example:
            "05 825 12011" → "0582512011"
    
        ---------------------------------
        CONTAINER NUMBER
        ---------------------------------
        - If "Container Number" not explicitly labeled,
        search for 10-character alphanumeric beginning with "KNE" or "KNA".
    
        ---------------------------------
        VIN NUMBER
        ---------------------------------
        - vin_no must be 17-character alphanumeric starting with "W1ND".
    
        ---------------------------------
        CURRENCY
        ---------------------------------
        - Extract currency ONLY if explicitly stated (EUR, USD, etc.).
        - Do NOT infer currency from symbol alone unless code is written.
    
        ---------------------------------
        CHARGES
        ---------------------------------
        Extract ONLY if explicitly present:
    
        - subtotal
        - packing
        - ex_factory
        - air_or_sea_freight_charges
        - fca_charges
        - dgr_fee
        - loading_charges
        - value_cfr
        - transport_insurance
        - value_added_tax
        - total_price
    
        CHARGE RULES:
        - Extract numeric value only.
        - Apply European normalization if needed.
        - Do NOT calculate totals.
        - Do NOT derive missing charges.
        - Do NOT sum line items.
    
        ---------------------------------
        OTHER FIELDS
        ---------------------------------
        - Any structured field not part of schema → include inside "other_fields".
        - Do NOT invent new schema fields.
    
        ---------------------------------
        MULTI-PAGE RULE
        ---------------------------------
        - Invoice text may span multiple pages.
        - Charges may appear on different pages.
        - Extract across entire combined text.
        ---------------------------------
    
        Now extract invoice data using the same rules.
        """
        ),
        (
        "human",
        """
        Invoice Text (all pages combined):
        {page_text}
    
        Return valid JSON strictly matching this schema:
        {schema}
        """
        )
    ])

    # ---------------------------------------------------
    # Model
    # ---------------------------------------------------
    def run_invoice_model(prompt, combined_text: str):
        chain = prompt | llm | invoice_parser
        return chain.invoke({
            "page_text": combined_text,
            "schema": invoice_parser.get_format_instructions()
        })

    prompt = build_invoice_prompt()
    structured = run_invoice_model(prompt, combined_text)

    print("\nInvoice extracted successfully.\n")
    return structured


# ---------------------------------------------------
# 4. Save JSON
# ---------------------------------------------------
def save_invoice_json_combined(data: dict, source_file: str = ""):
    os.makedirs(os.path.dirname(INVOICE_COMBINED_OUTPUT), exist_ok=True)

    separator = "\n" + ("-" * 80) + "\n"  # distinguish from AWB separator

    entry = {
        "_source_file": os.path.abspath(source_file),
        "_timestamp": datetime.now().isoformat(),
        "invoice": data
    }

    with open(INVOICE_COMBINED_OUTPUT, "a", encoding="utf-8") as f:
        f.write(separator)
        f.write(json.dumps(entry, ensure_ascii=False, indent=2))
        f.write("\n")

    print(f"✔ Invoice appended to: {INVOICE_COMBINED_OUTPUT}")




# ---------------------------------------------------
# 5. Main extractor used by watcher
# ---------------------------------------------------
def extract_from_pdf(pdf_path: str) -> dict:
    with open(pdf_path, "rb") as f:
        file_bytes = BytesIO(f.read())

    result = extract_invoice_from_bytes(file_bytes)

    data_dict = result.model_dump()
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    # save_invoice_json(data_dict, base_name)
    save_invoice_json_combined(data_dict, pdf_path)

    return data_dict


# ---------------------------------------------------
# 6. ENTRY POINT for watch_dwt_tango.py
# ---------------------------------------------------
def main():
    if len(sys.argv) < 3:
        print("Usage: python process_invoice.py <input_file> <processed_folder>")
        sys.exit(1)

    input_file = sys.argv[1]
    processed_folder = sys.argv[2]

    print(f"\n--- Processing Invoice: {input_file} ---")

    extract_from_pdf(input_file)

    os.makedirs(processed_folder, exist_ok=True)
    dest = os.path.join(processed_folder, os.path.basename(input_file))
    os.replace(input_file, dest)

    print(f"✔ Invoice moved to processed folder: {dest}")
    print("✔ Invoice extraction completed.\n")


if __name__ == "__main__":
    main()
