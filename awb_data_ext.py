from langchain_community.document_loaders import PyPDFLoader
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel
from langchain_groq import ChatGroq
from typing import Optional, List

from PIL import Image
import fitz  # PyMuPDF
import base64
import io
import os
import httpx
from dotenv import load_dotenv
load_dotenv()

# ------------------------------------------------------------------
# 1. GLOBAL SETTINGS
# ------------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
custom_client = httpx.Client(verify=False)

# ------------------------------------------------------------------
# 2. DATA SCHEMA
# ------------------------------------------------------------------
class AirwayBill(BaseModel):
    shipper_name: str
    shipper_add: str
    consignee_name: str
    consignee_add: str
    mawb: Optional[str] = None
    hawb: Optional[str] = None
    shipment_id: Optional[str] = None
    tracking_no: Optional[str] = None
    container_number: Optional[str] = None
    # invoice_number: Optional[str] = None
    invoice_numbers: Optional[List[str]] = []
    origin_airport: str
    destination_airport: str
    no_pieces: int
    gross_weight: str
    goods_name: Optional[str] = None
    order_no: Optional[str] = None
    vin_no: Optional[str] = None
    other_reference_numbers: Optional[List[str]] = []

awb_parser = PydanticOutputParser(pydantic_object = AirwayBill)

# ------------------------------------------------------------------
# 3. HELPER FUNCTIONS
# ------------------------------------------------------------------
def extract_text_from_pdf(pdf_path: str) -> Optional[str]:
    """Attempt to extract text using PyPDFLoader"""
    try:
        loader = PyPDFLoader(pdf_path, extract_images = False)
        docs = loader.load()
        awb_text = docs[0].page_content.strip()
        if awb_text:
            return awb_text
    except Exception:
        pass

    return None # indicates a scanned copy

def get_mime_type(ext):
    ext = ext.lower()
    if ext in [".jpg", ".jpeg"]:
        return "image/jpeg"
    elif ext == ".png":
        return "image/png"
    else:
        return "application/octet-stream"

def compress_image(image_path: str, max_width=1000, quality=60):
    """
    Compress an image by resizing and converting it to JPEG (lossy compression).
    This reduces the file size substantially for scanned AWB documents.
    """
    original_size = os.path.getsize(image_path)
    print(f"Original file size: {original_size / 1024:.2f} KB")

    img = Image.open(image_path).convert("RGB")  # convert to RGB (drops alpha for JPEG)
    
    # Resize while maintaining aspect ratio
    if img.width > max_width:
        w_percent = max_width / float(img.width)
        h_size = int(float(img.height) * w_percent)
        img = img.resize((max_width, h_size), Image.LANCZOS)

    compressed_path = os.path.splitext(image_path)[0] + "_compressed.jpg"
    
    # Save as JPEG (lossy compression) with moderate quality
    img.save(compressed_path, format="JPEG", quality=quality, optimize=True)

    compressed_size = os.path.getsize(compressed_path)
    print(f"Compressed file size: {compressed_size / 1024:.2f} KB")

    # Show reduction percentage
    reduction = (1 - (compressed_size / original_size)) * 100
    print(f"Compression reduced size by: {reduction:.1f}%")
    print(f"Compressed image saved to: {compressed_path}")
    return compressed_path    

def process_image_with_groq(image_path):
    with open(image_path, "rb") as img_file:
        image_bytes = img_file.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    mime_type = get_mime_type(os.path.splitext(image_path)[1])
    return f"data:{mime_type};base64,{image_b64}"

def pdf_to_image_path(pdf_path: str) -> str:
    """Convert first page to PNG & return the temporary image path"""
    doc = fitz.open(pdf_path)
    page = doc.load_page(0)
    pix = page.get_pixmap()
    img_path = os.path.splitext(pdf_path)[0] + "_page1.png"
    pix.save(img_path)
    return img_path

def build_prompt():
    """Return the reusable system & human prompt templates."""
    return ChatPromptTemplate.from_messages([
        ("system", "You are an expert in logistics document processing. Format your output strictly as JSON for the schema provided by user/human."),
        ("human", """
            You are extracting structured data from Air Waybill (AWB) documents.

            === CRITICAL VALIDATION RULES FOR INVOICE NUMBERS ===

            INVOICE NUMBER RULES (MUST follow ALL criteria):
            1. MUST be EXACTLY 10 digits long
            2. MUST start with one of these EXACT prefixes:
            - "490" (followed by 7 more digits) → Example: 4901234567
            - "106" (followed by 7 more digits) → Example: 1067654321  
            - "150" (followed by 7 more digits) → Example: 1509876543
            - "1106" (followed by 6 more digits) → Example: 1106123456
            - "1100" (followed by 6 more digits) → Example: 1100987654

            3. NO hyphens, NO spaces, NO letters - ONLY digits
            4. Total length = 10 digits (not 11, not 9, exactly 10)

            === FEW-SHOT EXAMPLES ===

            Example 1 - VALID Invoice Numbers:
            - "4901234567" ✓ (starts with 490, exactly 10 digits)
            - "1063183271" ✓ (starts with 106, exactly 10 digits)
            - "1500998877" ✓ (starts with 150, exactly 10 digits)
            - "1106445566" ✓ (starts with 1106, exactly 10 digits)
            - "1100223344" ✓ (starts with 1100, exactly 10 digits)

            Example 2 - INVALID (DO NOT EXTRACT as invoice):
            - "6530957871" ✗ (starts with 653, not in allowed prefixes)
            - "930093" ✗ (only 6 digits, too short)
            - "12345678901" ✗ (11 digits, too long)
            - "ABC1234567" ✗ (contains letters)
            - "49-0123456" ✗ (contains hyphens)
            - "ECD:25FRD92008458948A6" ✗ (alphanumeric reference, not invoice)

            === EXTRACTION LOGIC ===

            STEP 1: Locate all 10-digit numbers in the document
            STEP 2: For each 10-digit number, check if it starts with: 490, 106, 150, 1106, or 1100
            STEP 3: If YES → it's a valid invoice number
            STEP 4: If NO → categorize as "other_reference_numbers" (if near invoice section)

            STEP 5: Put ALL valid invoices (even if only one) in "invoice_numbers" list.
                    Do NOT use any separate field for single invoice.

            === OTHER FIELDS EXTRACTION RULES ===

            - Shipper Name: Organization associated with Mercedes brand
            - Shipper Address: Full address of shipper
            - Consignee Name: Indian organization (not individual person)
            - Consignee Address: Full address of consignee
            - MAWB: 14 characters → format: 3 digits + 3 uppercase letters + 8 digits
            Example: '020FRA33119542', '157ATL08613286'
            - HAWB: 11 characters → format: 3 letters + 8 digits (remove hyphens/spaces)
            Example: 'ABC-12345678' → return 'ABC12345678'
            - Origin Airport: IATA code or city name
            - Destination Airport: IATA code or city name
            - No. of Pieces: Integer only (e.g., 5, not "5 pieces")
            - Gross Weight: 
            * Numeric value only (no units)
            * Convert comma to decimal: '0,800' → '0.8', '42,000' → '42.0'
            * Remove 'K' or 'KG': '0,800 K' → '0.8'
            - Goods Name: General cargo description
            - Order Number: 10 digits, format 'XX XXX XXXXX' → 'XXXXXXXXXX'
            Example: '05 825 12011' → '0582512011'
            - VIN Number: 17-character alphanumeric, often starts with 'W1ND'
            Example: 'W1NDM2EB2TA039689'
            - Other Reference Numbers: Numeric/alphanumeric strings within 3-5 lines above invoice
            (but NOT valid invoice numbers)

            === OUTPUT JSON SCHEMA ===

            Return ONLY this JSON structure (no markdown, no code blocks, no explanations):

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
            "gross_weight": "",
            "goods_name": "",
            "order_no": "",
            "vin_no": "",
            "other_reference_numbers": []
            }}

            Use "" for empty strings, [] for empty lists, 0 for missing numbers.
            If field not found → return empty value (don't use null).

            === AWB DOCUMENT CONTENT ===

            {awb_text}

            === EXTRACTION OUTPUT ===
            """)
    ])

def run_model(prompt, awb_text = None, image_path = None):
    llm = ChatGroq(
                    api_key=GROQ_API_KEY,
                    http_client=custom_client,
                    model="meta-llama/llama-4-scout-17b-16e-instruct",
                    temperature=0
                )

    # ---- Build the chain ----
    chain = prompt | llm | awb_parser

    if awb_text:
        # Normal text-based AWB
        return chain.invoke({"awb_text": awb_text})
    else:
        # Vision path: convert to image url & send properly
        image_data_url = process_image_with_groq(image_path)
        image_input = [
            {"type": "image_url", "image_url": {"url": image_data_url}}
        ]
        return chain.invoke({"awb_text": image_input})

# ------------------------------------------------------------------
# 4. MAIN PIPELINE FUNCTION
# ------------------------------------------------------------------
def extract_awb(pdf_path: str):
    print(f"Processing AWB: {pdf_path}")
    prompt = build_prompt()
    awb_text = extract_text_from_pdf(pdf_path)

    if awb_text:
        print("Text detected in PDF - using text-based extraction.")
        result = run_model(prompt, awb_text = awb_text)
    else:
        print("Scanned PDF detected - converting to image for vision model.")
        image_path = pdf_to_image_path(pdf_path)
        compressed_path = compress_image(image_path)
        result = run_model(prompt, image_path = compressed_path)
    
    print(f"\nAWB Extraction Result:\n{result}\n")
    return result

# ------------------------------------------------------------------
# 5. STANDALONE RUN
# ------------------------------------------------------------------
if __name__ == "__main__":
    # extract_awb(r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\CAP25070431_2_inv_nos.pdf")
    # extract_awb(r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\spare_awb_2_inv.pdf")
    # extract_awb(r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\MBAG_Spare_Parts_AWB.pdf")
    extract_awb(r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\MBAG_Prod_Parts_AWB.pdf")
    # extract_awb(r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\MBUSI_AWB.PDF")
    # extract_awb(r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\EQS_awb.PDF")