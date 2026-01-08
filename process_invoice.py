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
from langchain.chat_models.base import BaseChatModel
from langchain.schema import BaseCache, AIMessage, HumanMessage, SystemMessage, ChatGeneration, ChatResult
from langchain.callbacks.base import Callbacks
from google import genai
from google.genai.types import HttpOptions

from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------
# CONFIG
# ---------------------------------------------------
NEXUS_BASE_URL = "https://genai-nexus.int.api.corpinter.net"
NEXUS_API_KEY = os.getenv("NEXUS_API_KEY")

nexus_client = genai.Client(
    http_options=HttpOptions(base_url=NEXUS_BASE_URL),
    api_key=NEXUS_API_KEY
)

INVOICE_JSON_FOLDER = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\Invoice\Processed"
# INVOICE_JSON_FOLDER = r"C:\Users\SONIARN\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\DWT_TANGO - Documents\Invoice\Processed"
INVOICE_COMBINED_OUTPUT = r"C:\Users\HEKOLLI\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\TANGO\invoice_all_output.txt"
# INVOICE_COMBINED_OUTPUT = r"C:\Users\SONIARN\OneDrive - Mercedes-Benz (corpdir.onmicrosoft.com)\TANGO\invoice_all_output.txt"


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

# ---------------------------
# 2. Gemini ↔ LangChain Adapter (NEW)
# ---------------------------
class NexusGeminiChat(BaseChatModel):
    model_name: str = "gemini-2.5-pro"

    def _generate(self, messages, stop=None):
        prompt = "\n".join(
            m.content for m in messages
            if isinstance(m, (SystemMessage, HumanMessage))
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


NexusGeminiChat.model_rebuild()


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
        return ChatPromptTemplate.from_messages(
        [
            ("system", """You are an expert in reading and extracting structured data from invoices.
            Invoices may appear in different formats, with varying field names.
            Invoice number is also known as Document No.
            'Buyer' = 'Consignee', 'Bill To' = 'Consignee', 'Shipper' = 'Supplier'

            CRITICAL FIELD RULES:
            - Consider "Gross" weights only: European commas → decimal periods
                - European number format: commas are decimal separators, periods are thousand separators- For example, interpret "28.877,56" as 28877.56 (twenty-eight thousand eight hundred seventy-seven point fifty-six)
                - Strip all units (KG, kg, etc.)
            - no_pieces: integer only
            - order_no: 10-digit continuous (e.g., "05 825 12011" → "0582512011")
            - vin_no: 17-char alphanumeric starting 'W1ND'
            - Extract charges fields if present:
               Subtotal, Packing, Ex Factory, Air or Sea freight charges, FCA Charges, DGR Fee, Loading Charges,
               Value CFR, Transport insurance, Value added Tax, Total Price (or Total Amount)
            - Extract currency if mentioned (e.g., EUR, USD)
            - Missing fields → null
            - Unknown fields → other_fields dict

            The invoice may have charges split across pages or as carry-ons.
            Return valid JSON strictly matching the schema. Prioritize accuracy and completeness.
            """),
            ("human", """
                Invoice Text (all pages combined): 
                {page_text}

                Schema to follow:
                {schema}

                Extract all invoice-related data, including charges and currency, from the combined text and return as valid JSON matching the schema.
                """)
        ]
    )

    # ---------------------------------------------------
    # Model
    # ---------------------------------------------------
    def run_invoice_model(prompt, combined_text: str):
        llm = NexusGeminiChat(model_name="gemini-2.5-pro")
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
