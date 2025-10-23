# ai_parser.py
import os
import openai
from dotenv import load_dotenv
load_dotenv()
openai.api_key = os.getenv('OPENAI_API_KEY')

PROMPT_TEMPLATE = '''
You are an assistant that extracts structured line items from noisy receipt OCR text.
Given the raw OCR text delimited by triple backticks, return JSON with these keys:
- items: list of {name, qty (float), unit_price (float|null), total_price (float)}
- taxes: list of {type, amount}
- service_charge: {percent|null, amount|null}
- discounts: list of {description, amount}
- currency: string (if possible)

Return only valid JSON.

OCR_TEXT:
```

{ocr}

```
'''


def call_openai(prompt: str) -> str:
    resp = openai.ChatCompletion.create(
        model='gpt-4o-mini',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.0,
        max_tokens=800,
    )
    return resp['choices'][0]['message']['content']


def parse_receipt_text(ocr_text: str, participants: list = None) -> dict:
    participants = participants or []
    prompt = PROMPT_TEMPLATE.format(ocr=ocr_text)
    raw = call_openai(prompt)
    # attempt to load JSON
    import json
    try:
        parsed = json.loads(raw)
    except Exception:
        # try to recover by finding first { ... }
        import re
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            parsed = json.loads(m.group(0))
        else:
            parsed = {'items': [], 'taxes': [], 'service_charge': None, 'discounts': [], 'currency': None}
    return parsed