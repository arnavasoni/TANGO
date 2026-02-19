# 02-19-2026
import os
import sys
import json
import base64
import fitz  # PyMuPDF
from io import BytesIO
from datetime import datetime
from typing import Optional, List, Union

from pydantic import BaseModel
import cv2
import numpy as np
from PIL import Image

import pytesseract
# changed path for POC PC
# pytesseract.pytesseract.tesseract_cmd = r"C:\Coding\Tesseract OCR\tesseract.exe"
pytesseract.pytesseract.tesseract_cmd = r"C:\CODING\Tesseract OCR\tesseract.exe"

# ---------------------------
# LangChain
# ---------------------------
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from langchain.schema import BaseCache, ChatGeneration, ChatResult, SystemMessage, HumanMessage, AIMessage
from langchain.chat_models.base import BaseChatModel
from langchain.callbacks.base import Callbacks
from langchain_google_genai import ChatGoogleGenerativeAI


# ---------------------------
# Gemini Nexus (NEW)
# ---------------------------
# from google import genai
# from google.genai.types import HttpOptions

# ---------------------------
# CONFIG
# ---------------------------
from dotenv import load_dotenv
load_dotenv()

NEXUS_BASE_URL = "https://genai-nexus.int.api.corpinter.net"
NEXUS_API_KEY = os.getenv("NEXUS_API_KEY")

# Output paths
# AWB_JSON_FOLDER = r"C:\Users\SONIARN\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\AWB\Processed"
# AWB_COMBINED_OUTPUT = r"C:\Users\SONIARN\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\TANGO\awb_all_output.txt"
AWB_JSON_FOLDER = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\TANGO\AWB_JSON"
# AWB_COMBINED_OUTPUT = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\TANGO\awb_all_output.txt"
AWB_COMBINED_OUTPUT = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\awb_all_output.txt"
# AWB_COMBINED_OUTPUT = r"C:\Users\SONIARN\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\awb_all_output.txt"

# ---------------------------
# Gemini Nexus Client (NEW)
# ---------------------------
# nexus_client = genai.Client(
#     http_options=HttpOptions(base_url=NEXUS_BASE_URL),
#     api_key=NEXUS_API_KEY
# )

class Classification(BaseModel):
    country: str
    category: str
    requires_invoice: bool
    matched_rules: List[str]

# ----------------------------------------
# 1. DATA SCHEMA
# ----------------------------------------
class AirwayBill(BaseModel):
    shipper_name: str
    shipper_add: str
    consignee_name: str
    consignee_add: str
    mawb: Optional[str] = ""
    hawb: Optional[str] = ""
    shipment_id: Optional[str] = ""
    tracking_no: Optional[str] = ""
    container_number: Optional[str] = ""
    invoice_numbers: Optional[List[str]] = []
    origin_airport: str
    destination_airport: str
    no_pieces: int
    gross_weight: float # changed from str to float
    goods_name: Optional[str] = ""
    order_no: Optional[str] = ""
    vin_no: Optional[str] = ""
    second_flight_date: Optional[str] = ""
    executed_on_date: Optional[str] = ""
    other_reference_numbers: Optional[List[str]] = []

awb_parser = PydanticOutputParser(pydantic_object=AirwayBill)

# NexusGeminiChat.model_rebuild()

# ----------------------------------------
# 3. Helper Functions
# ----------------------------------------
def extract_text_from_pdf_bytes(pdf_bytes: BytesIO): # BytesIO (an in-memory byte stream)
    """Extract text using PyMuPDF; if pure image PDF, returns None."""
    # try & except, so the entire operation is wrapped in error handling to prevent program from crashing
    try:
        pdf_bytes.seek(0) # Moves the "cursor" of the BytesIO object back to beginning. w/o this, .read() might return empty data.
        data = pdf_bytes.read()
        doc = fitz.open(stream=data, filetype="pdf")
        '''
        fitz.open() creates a PDF document object
        stream = data tells PyMuPDF to open from bytes (not a file path)
        filetype="pdf" tells PyMuPDF to expect a PDF file

        doc now represents the enitire PDF document.
        '''
        text = ""
        for page in doc:
            t = page.get_text().strip()
            if t:
                text += t + "\n"
        doc.close()
        return text.strip() if text.strip() else None
    except:
        return None


def clean_awb_text(text):
    # Normalize whitespace
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    #  ^ splits the string into a list of lines; handles different newline types (\n, \r, \r\n); removes leading & trailing whitespace from each line; filters out empty or whitespace-only lines.
    cleaned = " ".join(lines) # all lines into a single string, one space inserted between each line, removes all OG line breaks
    cleaned = " ".join(cleaned.split()) # remove extra spaces
    print("AWB text cleaned.\n")
    return cleaned

def pdf_to_image_path(pdf_bytes):
    """Convert first page of PDF to high-resolution PNG file (300 DPI)."""
    if hasattr(pdf_bytes, "seek"):
        pdf_bytes.seek(0)

    data = pdf_bytes.read()
    doc = fitz.open(stream=data, filetype="pdf")

    if doc.page_count == 0:
        raise ValueError("PDF has no pages")

    page = doc.load_page(0)

    # 🔥 300 DPI rendering (major improvement)
    zoom = 300 / 72
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix)

    image_path = "temp_awb_page.png"
    pix.save(image_path)

    doc.close()
    return image_path


def ocr_first_page_from_pdf(pdf_bytes: BytesIO) -> str:
    """
    Perform OCR on the FIRST PAGE ONLY of a scanned PDF.
    Uses 300 DPI rendering + adaptive thresholding.
    """
    image_path = pdf_to_image_path(pdf_bytes)

    try:
        img = cv2.imread(image_path)

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 🔥 Adaptive Thresholding (major improvement)
        thresh = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,   # block size
            2     # constant subtracted from mean
        )

        # OCR config optimized for structured documents
        custom_config = r'--oem 3 --psm 6'

        text = pytesseract.image_to_string(
            thresh,
            lang="eng",
            config=custom_config
        )

        return text.strip()

    finally:
        if os.path.exists(image_path):
            os.remove(image_path)


# ----------------------------------------
# 3. Build Prompt
# ----------------------------------------
def build_prompt():
    return ChatPromptTemplate.from_messages([
    ("system",
        """You are a strict logistics document extraction engine.
 
        Extract ONLY explicitly stated values from the provided AWB text.
        Do NOT infer, assume, or guess.
        If a value is missing, return:
        - "" for strings
        - [] for arrays
        - 0 for numbers
        Never use null.
        Return valid JSON only. No markdown. No explanations.
 
        FIELD RULES:
 
        PARTIES
        - shipper_name: Mercedes brand-related organization only (NOT carrier).
        - shipper_add: Full Mercedes-related shipper address.
        - consignee_name: Indian organization name only (ignore person names).
        - consignee_add: Full Indian consignee street address.
 
        AIRWAY BILL
        - mawb: 14 chars → 3 digits + 3 uppercase letters + 8 digits (remove all separators).
        - hawb: 11 chars → 3 letters + 8 digits (remove hyphens/spaces).
        - shipment_id: Shipment/document reference (alphanumeric).
        - tracking_no: Shipment tracking/reference number.
        - container_number: Container/box ID.
 
        INVOICES
        - invoice_numbers: Include ONLY 10-digit numbers starting strictly with:
        106, 1100, 1106, 150, or 490.
        Ignore all other 10-digit numbers.
        - other_reference_numbers: Numeric/alphanumeric strings located 3–5 lines above invoice section.
        Exclude valid invoice_numbers.
 
        AIRPORTS & FLIGHTS
        - origin_airport / destination_airport: Prefer 3-letter IATA code.
        - second_flight_date: Format like LH8022/31.
        If two flights exist, extract the one corresponding to the SECOND flight date.
        - second_flight_date: Extract second flight date if present.
        - executed_on_date: Date printed at bottom of AWB. Written around 'Executed on (date)'. Could be in different formats, return in dd-mm-yyyy
 
        SHIPMENT DETAILS
        - no_pieces: Integer only.
        - gross_weight: Numeric only. Remove units (KG, K, LBS). Use dot as decimal separator.
        - goods_name: Cargo description.
 
        ORDER & VEHICLE
        - order_no: Continuous 10-digit number. Remove spaces and non-numeric characters.
        - vin_no: 17-character alphanumeric (often starts with W1ND).
 
        --- FEW-SHOT EXAMPLES ---
 
        Example 1:
 
        AWB TEXT:
        MAWB: 020-FRA-33119542
        HAWB: FRA-25630746
        Flight: LH8001
        Flight: LH8022/31
        Invoice: 1063194729
        Invoice: 6531337742
        Gross Weight: 42,000 KG
        No. of pieces: 5
 
        Expected Output:
        {{
        "shipper_name": "",
        "shipper_add": "",
        "consignee_name": "",
        "consignee_add": "",
        "mawb": "020FRA33119542",
        "hawb": "FRA25630746",
        "shipment_id": "",
        "tracking_no": "",
        "container_number": "",
        "invoice_numbers": ["1063194729"],
        "origin_airport": "",
        "destination_airport": "",
        "no_pieces": 5,
        "gross_weight": 42.0,
        "goods_name": "",
        "order_no": "",
        "vin_no": "",
        "second_flight_date": "LH8022/31",
        "executed_on_date": "16-10-2024",
        "other_reference_numbers": []
        }}
 
        Now extract from the provided AWB text using the same rules.
        """
        ),
        ("human",
            """AWB TEXT:
            {awb_text}
 
            Return ONLY JSON in this schema:
            {{
            "shipper_name": "",
            "shipper_add": "",
            "consignee_name": "",
            "consignee_add": "",
            "mawb": "",
            "hawb": "",
            "shipment_id": "",
            "tracking_no": "",
            "container_number": "",
            "invoice_numbers": [],
            "origin_airport": "",
            "destination_airport": "",
            "no_pieces": 0,
            "gross_weight": 0,
            "goods_name": "",
            "order_no": "",
            "vin_no": "",
            "second_flight_date": "",
            "executed_on_date": "",
            "other_reference_numbers": []
            }}
            """)
        ])

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-pro",
    google_api_key=NEXUS_API_KEY,
    client_options={"api_endpoint": NEXUS_BASE_URL},
    transport="rest",
    temperature=0,
)

# ----------------------------------------
# 5. Model Runner
# ----------------------------------------
# def run_model(prompt, awb_text: str):
#     llm = NexusGeminiChat(model_name="gemini-2.5-pro")
#     chain = prompt | llm | awb_parser
#     return chain.invoke({"awb_text": awb_text})
def run_model(prompt, awb_text: str):
    chain = prompt | llm | awb_parser
    return chain.invoke({"awb_text": awb_text})



# ----------------------------------------
# 6. Save JSON
# ----------------------------------------
def save_awb_json_combined(data: dict, source_file: str = ""):
    os.makedirs(os.path.dirname(AWB_COMBINED_OUTPUT), exist_ok=True)
    entry = {
        "_source_file": os.path.abspath(source_file),
        "_timestamp": datetime.now().isoformat(),
        "awb": data
    }
    with open(AWB_COMBINED_OUTPUT, "a", encoding="utf-8") as f:
        f.write("\n" + "-" * 80 + "\n")
        json.dump(entry, f, indent=2, ensure_ascii=False)
    print(f"✔ AWB appended to: {AWB_COMBINED_OUTPUT}")

# ----------------------------------------
# 7. AWB Extraction Pipeline
# ----------------------------------------
def extract_awb(pdf_path: str):
    with open(pdf_path, "rb") as f:
        file_bytes = BytesIO(f.read())

    prompt = build_prompt()

    text = extract_text_from_pdf_bytes(file_bytes)
    # 🧠 If no text → scanned PDF → OCR FIRST PAGE
    if not text:
        print("⚠ No embedded text detected — performing OCR on first page")
        ocr_text = ocr_first_page_from_pdf(file_bytes)

        if not ocr_text:
            raise RuntimeError("OCR failed — no text extracted from scanned PDF")

        text = ocr_text

    cleaned = clean_awb_text(text)
    print("✓ Text detected → Gemini extraction")
    return run_model(prompt, cleaned)


# ----------------------------------------
# 7. MAIN USED BY WATCHER
# ----------------------------------------
def main():
    if len(sys.argv) < 3:
        print("Usage: python process_awb.py <inputfile> <processed_folder>")
        sys.exit(1)

    input_file = sys.argv[1]
    processed_folder = sys.argv[2]

    print(f"\n--- Processing AWB: {input_file} ---")

    try:
        output = extract_awb(input_file)

        if output is None:
            print("[ERROR] extract_awb() returned None → cannot continue.")
            return

        # Convert Pydantic model to dictionary
        data = output.model_dump()

        from tango_classifier import DocumentClassifier

        classifier = DocumentClassifier()
        data["classification"] = classifier.classify(data)

        # Safety check — data must be a dict
        if not isinstance(data, dict):
            print("[ERROR] Parsed AWB data is not a dictionary.")
            return

        # Save JSON line into combined AWB file
        save_awb_json_combined(data, input_file) # need to add source file path here!!!

    except Exception as e:
        print(f"[AWB] Error processing file: {e}")
        import traceback
        traceback.print_exc()
        return

    # Move processed file only after success
    try:
        os.makedirs(processed_folder, exist_ok=True)
        dest = os.path.join(processed_folder, os.path.basename(input_file))
        os.replace(input_file, dest)
        print(f"✔ AWB moved to processed: {dest}")
    except Exception as e:
        print(f"[ERROR] Failed to move processed file: {e}")

    print("✔ AWB extraction finished.\n")



if __name__ == "__main__":
    main()
