# ai_parser.py
import os
import requests
import json
import re
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL")

PROMPT_TEMPLATE = """
You are a data extraction model for restaurant receipts.

From the following OCR text, extract all relevant information and return ONLY valid JSON
matching the structure below. You MUST extract each menu item and its price correctly.

### OUTPUT JSON FORMAT
{{
  "items": [
    {{"name": "string", "qty": float, "unit_price": float|null, "total_price": float}}
  ],
  "taxes": [{{"type": "string", "amount": float}}],
  "service_charge": {{"percent": float|null, "amount": float|null}},
  "discounts": [{{"description": "string", "amount": float}}],
  "currency": "string|null"
}}

### RULES
- Always include all item names and prices shown before "Subtotal" or "Total".
- If an item shows a quantity before the name (e.g. "2 AGLIO OLIO $64.49"), extract:
  {{"name": "AGLIO OLIO", "qty": 2, "unit_price": 32.245, "total_price": 64.49}}
- If multiple quantities of an item exist, you must still record the quantity count.
- Convert currency symbols ($, RM, etc.) into floats.
- Use "Tax" or "Service" to fill `taxes` or `service_charge`.

### OCR TEXT:
{ocr}
"""


def call_openrouter(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "X-Title": "AI Receipt Splitter Bot",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 800,
    }

    resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
    if resp.status_code != 200:
        raise Exception(f"OpenRouter API error {resp.status_code}: {resp.text}")

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def to_float(x):
    try:
        if x is None:
            return 0.0
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        s = s.replace('$', '').replace('RM', '').replace(',', '').strip()
        m = re.search(r'[-+]?[0-9]*\.?[0-9]+', s)
        return float(m.group(0)) if m else 0.0
    except Exception:
        return 0.0


def parse_receipt_text(ocr_text: str, participants: list = None) -> dict:
    participants = participants or []
    prompt = PROMPT_TEMPLATE.format(ocr=ocr_text)
    raw = call_openrouter(prompt)

    print("\n--- RAW AI RESPONSE START ---")
    print(raw)
    print("--- RAW AI RESPONSE END ---\n")

    try:
        parsed = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            parsed = json.loads(m.group(0))
        else:
            parsed = {"items": [], "taxes": [], "service_charge": None, "discounts": [], "currency": None}

    # === POSTPROCESS ITEMS ===
    cleaned_items = []
    for it in parsed.get("items", []):
        name = it.get("name", "").strip()

        # Detect quantity in name if AI missed it
        qty = it.get("qty")
        if qty is None:
            m = re.match(r'^\s*(\d+)\s*[xX]?\s*(.*)', name)
            if m:
                qty = int(m.group(1))
                name = m.group(2).strip()
            else:
                qty = 1
        try:
            qty = int(qty)
        except Exception:
            qty = 1
        qty = max(1, qty)

        total = to_float(it.get("total_price", None))
        unit = to_float(it.get("unit_price", None))

        # Derive missing values
        if not unit and qty > 0 and total:
            unit = total / qty
        if not total and unit:
            total = unit * qty

        unit = round(unit or 0.0, 2)
        total = round(total or 0.0, 2)

        # Expand into multiple items if qty > 1 (for selection purposes)
        for _ in range(qty):
            cleaned_items.append({
                "name": name,
                "qty": 1,
                "unit_price": unit,
                "total_price": unit,
            })

    parsed["items"] = cleaned_items
    return parsed
