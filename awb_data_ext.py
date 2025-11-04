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
            print(f"AWB TEXT:\n{awb_text}")
            return awb_text
    except Exception:
        pass

    return None # indicates a scanned copy

def clean_awb_text(text):
    # Remove excessive newlines and spaces
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Combine lines into a single paragraph or logical sections
    cleaned_text = " ".join(lines)
    # Optionally, collapse multiple spaces into one
    cleaned_text = ' '.join(cleaned_text.split())
    print(f"CLEANED TEXT: {cleaned_text}")
    return cleaned_text



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
    """Return the reusable system & human prompt templates optimized for TPM."""
    return ChatPromptTemplate.from_messages([
        ("system", 
         """You are an expert in logistics document processing. Format output strictly as JSON using the schema provided. 
         Follow these rules strictly:
         - Invoice numbers: exactly 10 digits, starting with 490, 106, 150, 1106, or 1100. No letters, hyphens, or spaces. Example: 4901234567, 1509876543. Sample numbers that are not invoice numbers: 6530957871, 930093.
         - MAWB: 14 characters, format 3 digits + 3 letters + 8 digits. Example: 020FRA33119542, 157ATL08613286
         - HAWB: 11 characters, 3 letters + 8 digits; remove hyphens/spaces. Example: FRA-25630746; return -> FRA25630746
         - Gross weight: numeric only, convert commas to decimal, remove units (K/KG).
         - No. of Pieces: integer only (e.g., 5, not "5 pieces").
         - Order Number: 10 digits, format 'XX XXX XXXXX' → 'XXXXXXXXXX'.
         - VIN Number: 17-character alphanumeric, often starts with 'W1ND'.
         - Shipper Name: organization (Mercedes brand), Shipper Address: full address.
         - Consignee Name: Indian organization, Consignee Address: full address.
         - Origin/Destination Airport: IATA code or city.
         - Other reference numbers: numeric/alphanumeric strings within 3–5 lines above invoice, but not valid invoices.
         - Extract all valid invoice numbers and other fields in the schema; if missing, use empty string, 0, or [].
         - Return ONLY JSON, no markdown, no explanations."""
        ),
        ("human", 
         """Extract structured data from this AWB document:\n\n{awb_text}\n\n
         Return ONLY the JSON using this schema:
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
            }}"""
        )
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
        awb_text = clean_awb_text(awb_text)
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
    # extract_awb(r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\MBAG_Prod_Parts_AWB.pdf")
    extract_awb(r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\MBUSI_AWB.PDF")
    # extract_awb(r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\EQS_awb.PDF")
