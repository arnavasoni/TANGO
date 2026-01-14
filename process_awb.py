import os
import sys
import json
import base64
import fitz  # PyMuPDF
from io import BytesIO
from datetime import datetime
from typing import Optional, List, Union

from pydantic import BaseModel
from PIL import Image

# ---------------------------
# LangChain
# ---------------------------
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from langchain.schema import BaseCache, ChatGeneration, ChatResult, SystemMessage, HumanMessage, AIMessage
from langchain.chat_models.base import BaseChatModel
from langchain.callbacks.base import Callbacks

# ---------------------------
# Gemini Nexus (NEW)
# ---------------------------
from google import genai
from google.genai.types import HttpOptions

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
AWB_JSON_FOLDER = r"C:\Users\SONIARN\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\TANGO\AWB_JSON"
# AWB_COMBINED_OUTPUT = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\TANGO\awb_all_output.txt"

# ---------------------------
# Gemini Nexus Client (NEW)
# ---------------------------
nexus_client = genai.Client(
    http_options=HttpOptions(base_url=NEXUS_BASE_URL),
    api_key=NEXUS_API_KEY
)


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
    gross_weight: str
    goods_name: Optional[str] = ""
    order_no: Optional[str] = ""
    vin_no: Optional[str] = ""
    flight_date_2: Optional[str] = ""
    other_reference_numbers: Optional[List[str]] = []

awb_parser = PydanticOutputParser(pydantic_object=AirwayBill)

# ---------------------------
# 2. Gemini ↔ LangChain Adapter (NEW)
# ---------------------------
class NexusGeminiChat(BaseChatModel):
    model_name: str = "gemini-2.5-pro"

    def _generate(self, messages, stop=None):
        prompt = "\n".join(
            m.content for m in messages if isinstance(m, (SystemMessage, HumanMessage))
        )

        response = nexus_client.models.generate_content(
            model=self.model_name,
            contents=[prompt],
        )

        generation = ChatGeneration(
            message=AIMessage(content=response.text)
        )

        return ChatResult(generations=[generation])

    @property
    def _llm_type(self) -> str:
        return "nexus-gemini"

# ✅ Rebuild model
NexusGeminiChat.model_rebuild()

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


def get_mime_type(ext): # ext: a file extension string (eg. ".jpg", ".png")
    ext = ext.lower()
    if ext in [".jpg", ".jpeg"]:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    return "application/octet-stream" # means unknown or binary data; a safe generic fallback by many systems


def compress_image(image_path, max_width=1000, quality=60):
    img = Image.open(image_path).convert("RGB")
    if img.width > max_width:
        ratio = max_width / img.width
        new_h = int(img.height * ratio)
        img = img.resize((max_width, new_h), Image.LANCZOS)

    compressed_path = os.path.splitext(image_path)[0] + "_compressed.jpg"
    img.save(compressed_path, "JPEG", quality=quality, optimize=True)
    return compressed_path


def pdf_to_image_path(pdf_bytes):
    """Convert first page of PDF to PNG file."""
    if hasattr(pdf_bytes, "seek"): # check whether pdf_bytes has a seek method; allows the function to accept different types of input
        pdf_bytes.seek(0) # moves read cursor to the beginning of the byte stream
    data = pdf_bytes.read()

    doc = fitz.open(stream=data, filetype="pdf")
    if doc.page_count == 0:
        raise ValueError("PDF has no pages")

    page = doc.load_page(0)
    pix = page.get_pixmap() # renders the page as a pixmap (image) default resolution is 72 DPI unless specified otherwise
    image_path = "temp_awb_page.png"
    pix.save(image_path)
    doc.close()
    return image_path


def process_image_with_groq(image_path):
    with open(image_path, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode()
    mime = get_mime_type(os.path.splitext(image_path)[1])
    return f"data:{mime};base64,{b64}"


# ----------------------------------------
# 3. Build Prompt
# ----------------------------------------
def build_prompt():
    return ChatPromptTemplate.from_messages([
        ("system",
         """You are an expert in logistics document processing. Format output strictly as JSON using the schema provided.
         Follow these rules strictly:
         - shipper_name: Organization (return as Mercedes brand-related), shipper_add: Full address of shipper (Mercedes brand-related). Not carrier name or address.
         - consignee_name: Indian organization name (do not consider name of individual person if present), consignee_add: Complete Indian consignee street address
         - Remove all hyphens, spaces, or other separators from mawb/hawb. Ensure exact char lengths.
         - mawb: 14 chars (3 digits + 3 uppercase letters + 8 digits) → Example: 020FRA33119542
         - hawb: 11 chars (3 letters + 8 digits, remove hyphens/whitespaces) → Example: FRA-25630746 becomes FRA25630746
         - shipment_id: Document or shipment reference number (alphanumeric), tracking_no: Tracking or reference number for shipment
         - container_number: Container/box identifier. Example: '8252540095M'
         - invoice_numbers: only include 10-digit numbers starting strictly with 106, 1100, 1106, 150, or 490. Ignore all other 10-digit numbers (e.g., 653..., 930...). Example valid: 1063194729, 1063938444. Example invalid: 6531337742, 6531355428.
         - origin_airport: IATA code or city name (3-letter code preferred), destination_airport: IATA code or city name (3-letter code preferred)
         - no_pieces: Integer only (e.g., 5, not "5 pieces")
         - Convert all weights to numeric values with a dot as decimal separator. Remove all units like K, KG, LBS.
         - gross_weight: Numeric / decimal numbers only, no units; Examples: "0,800 K" → "0.8" | "42,000 KG" → "42.0" | "2,914" → "2.914"
         - goods_name: Cargo/commodity description
         - order_no: Remove all spaces or non-numeric characters from order_no to ensure a continuous 10-digit number. No alphabets (format "XX XXX XXXXX" → "XXXXXXXXXX") → Example: detected "05 825 12011" becomes "0582512011"
         - vin_no: 17-char alphanumeric, often starts W1ND → Example: W1NDM2EB2TA039689
         - flight_date_2: Second flight date if present in document
         - other_reference_numbers: Numeric/alphanumeric strings 3-5 lines above invoice section (exclude valid invoices)
         - Return JSON only, no markdown, no explanations
         - Do NOT invent or hallucinate values
         - If a value is missing or not present, always use "" for strings, [] for lists, and 0 for numbers. Never use null."""
        ),
        ("human",
         """Extract structured data from this AWB document:\n
            {awb_text}\n
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
            "gross_weight": "",
            "goods_name": "",
            "order_no": "",
            "vin_no": "",
            "flight_date_2": "",
            "other_reference_numbers": []
            }}"""
        )
    ])


# ----------------------------------------
# 5. Model Runner
# ----------------------------------------
def run_model(prompt, awb_text: str):
    llm = NexusGeminiChat(model_name="gemini-2.5-pro")
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
    if not text:
        raise RuntimeError(
            "Scanned PDFs not supported in Gemini text-only mode"
        )

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
