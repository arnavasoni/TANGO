from langchain_community.document_loaders import PyPDFLoader
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel
from langchain_groq import ChatGroq
from typing import Optional, Dict, Any, List

import os
from dotenv import load_dotenv
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

import httpx
custom_client = httpx.Client(verify = False)

# --------------------------
# 1. Define Invoice Schema
# --------------------------
class InvoiceItem(BaseModel):
    part_no: Optional[str] = None # Optional, as not all invoices have part numbers
    description: Optional[str] = None
    quantity: Optional[str] = None

class Invoice(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    delivery_note: Optional[str] = None
    supplier_name: str
    supplier_address: str
    consignee_name: str
    consignee_add: str
    no_pieces: Optional[int] = None
    gross_weight: Optional[str] = None
    container_number: Optional[str] = None
    items: Optional[list[InvoiceItem]] = []  # Optional;  list of line items
    order_no: Optional[str] = None # new optional
    vin_no: Optional[str] = None # new optional
    # Catch-all for unknown / template-specific fields
    other_fields: Optional[Dict[str, Any]] = {}

invoice_parser = PydanticOutputParser(pydantic_object=Invoice)

# --------------------------
# 2. Clean Invoice Text
# --------------------------
def clean_inv_text(text: str) -> str:
    """Normalize invoice page text: remove extra whitespace and join lines."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned_text = " ".join(lines)
    cleaned_text = ' '.join(cleaned_text.split())  # collapse multiple spaces
    print(f"CLEANED INVOICE TEXT:\n{cleaned_text}\n\n")
    return cleaned_text

def extract_invoice(pdf_path: str) -> Invoice:
    loader = PyPDFLoader(pdf_path, extract_images = False)
    docs = loader.load() # Returns a list of Document objects, one per page

    raw_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", """You are an expert in reading invoices.
        Invoices may appear in different formats, with verifying field names.
        Invoice number is also knows as Document No.
        'Buyer' = 'Consignee', 'Bill To' = 'Consignee', 'Shipper' = 'Supplier'
        Extract all invoice-relared data in raw form."""),
        ("human", """
        Invoice Page Text: \n\n {page_text}

        Return all relevant invoice-related information in a simple, raw text form. Do not worry about formatting yet.
        """)
    ]
    )

    # --------------------------
    # 4. Initialize model
    # --------------------------
    llm = ChatGroq(
                    api_key=GROQ_API_KEY,
                    http_client=custom_client,
                    model="meta-llama/llama-4-scout-17b-16e-instruct",
                    temperature=0
                )

    # --------------------------
    # 5. Extract raw data per page
    # --------------------------
    raw_results = []
    for doc in docs:
        page_text = clean_inv_text(doc.page_content)
        raw_chain = raw_prompt | llm
        raw_output = raw_chain.invoke({"page_text": page_text})
        raw_results.append(raw_output.content)

    # Combine all raw results
    combined_raw = "\n".join(raw_results)

    # --------------------------
    # 6. Contextual refinement prompt
    # --------------------------
    refine_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", """You are an expert invoice processor. Output valid JSON matching the schema exactly. Prioritize accuracy over completeness."""),
            ("human", """CRITICAL - Numeric Conversion Rules:
                - European commas → decimal periods
                - Strip ALL units (KG, kg, etc.)
                - Examples: "0,800 KG" → 0.8 | "42,000 KG" → 42.0 | "2,914 KG" → 2.914 | "4,960 KG" → 4.960
                - Do NOT hallucinate values

                Field Rules:
                - gross_weight: Numeric string, no units, decimal period (null if missing)
                - order_no: 10-digit continuous (e.g., "05 825 12011" → "0582512011")
                - vin_no: 17-char alphanumeric starting "W1ND"
                - Missing fields: null
                - Unknown fields: other_fields dict

                Schema: {schema}
                Raw Data: {raw_data}""")
        ]
    )


    # --------------------------
    # 7. Refinement chain
    # --------------------------
    refine_chain = refine_prompt | llm
    final_result = refine_chain.invoke({
        "raw_data": combined_raw,
        "schema": invoice_parser.get_format_instructions() # provides instructions for strict JSON output
    })

    # Get just the model output text
    # final_text = final_result.content

    # --------------------------
    # 8. Parse final result using Pydantic
    # --------------------------
    invoice_structured = invoice_parser.parse(final_result.content)
    print(f"Invoice Data:\n {invoice_structured}")
    return invoice_structured

# --------------------------
# 4. Example usage
# --------------------------
if __name__ == "__main__":
    extract_invoice(r"C:\Users\SONIARN\Desktop\EXIM Sample Docs\EQS_inv.pdf")
