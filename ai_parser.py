# ai_parser.py
import os, requests, json, re
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
  "discounts": [{{"description": "string", "amount": float, "item": "string|null"}}],
  "currency": "string|null"
}}

### RULES
- Always include item names and line totals shown before "Subtotal" or "Total".
- Do NOT include discount lines in "items" (put them in "discounts").
- Discounts may be negative amounts or labelled (Xmas Special, Discount, Promo).
- Taxes and service charge may appear as labels like TAX/GST/SERVICE/SST.
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
        s = s.replace('−', '-').replace('—', '-').replace('–', '-')
        s = s.replace(',', '.')
        s = s.replace('$', '').replace('RM', '').strip()
        m = re.search(r'-?[0-9]+(?:\.[0-9]{1,2})?', s)
        return float(m.group(0)) if m else 0.0
    except Exception:
        return 0.0

def detect_item_discounts(ocr_text: str, parsed_items: list):
    """
    Detect and apply discounts from OCR text, attaching each to its respective item.
    Returns (parsed_items_modified, detected_discounts_list).
    Each detected discount item is a dict: {"description": str, "amount": float, "item": str}
    """
    lines = [ln.rstrip() for ln in ocr_text.splitlines() if ln.strip()]
    item_line_re = re.compile(
        r'^\s*(\d+)?\s*[xX]?\s*([A-Za-z0-9 .&()\'\-]+?)\s+[-]?\$?\s*([0-9]+(?:[.,][0-9]{2}))\s*$',
        re.I
    )

    def norm(s):
        return re.sub(r'\s+', ' ', (s or '').strip()).lower()

    used_indices = set()
    detected_discounts = []  # collects structured discount info

    for idx, raw_line in enumerate(lines):
        if not raw_line.strip():
            continue

        line = raw_line.strip().replace('—', '-').replace('–', '-').replace(',', '.')
        has_discount_keyword = bool(re.search(r'(discount|off|offer|promo|rebate|special|xmas)', line, re.I))
        has_negative_value = bool(re.search(r'-\s*\$?\s*[0-9]+(?:[.,][0-9]{2})', line))
        has_positive_price = bool(re.search(r'\$?\s*[0-9]+(?:[.,][0-9]{2})', line))

        # interpret "Xmas Special $2.00" as a discount (keyword + positive price) OR any negative price
        is_discount_line = (has_discount_keyword and has_positive_price) or has_negative_value
        if not is_discount_line:
            continue

        # extract numeric discount value
        mval = re.search(r'-?\s*\$?\s*([0-9]+(?:[.,][0-9]{2}))', line)
        if not mval:
            continue
        disc_amt = abs(to_float(mval.group(1)))

        # find immediate previous non-discount item-like line
        j = idx - 1
        while j >= 0:
            prev = lines[j].strip()
            # skip previous discount-like lines
            if re.search(r'(discount|offer|promo|special|xmas|rebate|-\s*\$?\s*[0-9]+)', prev, re.I):
                j -= 1
                continue
            if item_line_re.match(prev):
                break
            j -= 1
        if j < 0:
            continue

        prev_line = lines[j].replace(',', '.').strip()
        m = item_line_re.match(prev_line)
        if not m:
            continue

        prev_qty = int(m.group(1)) if m.group(1) else 1
        prev_name = m.group(2).strip()
        prev_price = to_float(m.group(3))

        # find best matching parsed item (exact name match first)
        target_index = None
        for k, it in enumerate(parsed_items):
            if k in used_indices:
                continue
            if not it.get("name"):
                continue
            if norm(it.get("name")) == norm(prev_name):
                item_total = to_float(it.get("total_price", it.get("unit_price", 0)))
                if abs(item_total - prev_price) <= 1.5 or abs(item_total - (prev_price * prev_qty)) <= 1.5:
                    target_index = k
                    break

        # fallback fuzzy token overlap
        if target_index is None:
            best_k = None
            best_overlap = 0
            prev_tokens = set(re.sub(r'[^a-z0-9 ]', ' ', prev_name.lower()).split())
            for k, it in enumerate(parsed_items):
                if k in used_indices:
                    continue
                name_tokens = set(re.sub(r'[^a-z0-9 ]', ' ', (it.get("name") or "").lower()).split())
                overlap = len(prev_tokens & name_tokens)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_k = k
            if best_k is not None and best_overlap > 0:
                target_index = best_k

        if target_index is None:
            continue

        target = parsed_items[target_index]
        orig_total = to_float(target.get("total_price", 0))
        target["discount"] = {"type": "flat", "amount": round(disc_amt, 2)}
        target["total_price"] = round(orig_total - disc_amt, 2)
        used_indices.add(target_index)

        detected_discounts.append({
            "description": re.sub(r'\s+', ' ', line),
            "amount": round(disc_amt, 2),
            "item": target.get("name")
        })

        print(f"[DEBUG] Applied discount ${disc_amt:.2f} to item '{target.get('name')}' from line: '{line}'")

    if detected_discounts:
        print("\n[DEBUG] Detected item-linked discounts:")
        for d in detected_discounts:
            print(f"  - {d['item']}: {d['description']} (${d['amount']})")

    return parsed_items, detected_discounts


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

    # --- Normalize: move any LLM-returned discount-like items into parsed["discounts"] ---
    cleaned_items = []
    extra_discounts = parsed.get("discounts", []) or []
    for it in parsed.get("items", []):
        name = (it.get("name") or "").strip()
        total = to_float(it.get("total_price"))
        # If LLM returned a negative price or discount-like name, treat as discount
        if total < 0 or re.search(r'(discount|promo|special|xmas|off|rebate)', name, re.I):
            extra_discounts.append({"description": name or "discount", "amount": abs(total), "item": None})
            continue
        # else keep as line-level item
        qty = int(it.get("qty") or 1)
        unit = to_float(it.get("unit_price"))
        if (not unit or unit == 0.0) and qty > 0 and total:
            unit = total / qty
        if (not total or total == 0.0) and unit:
            total = unit * qty
        cleaned_items.append({
            "name": name,
            "qty": qty,
            "unit_price": round(unit or 0.0, 2),
            "total_price": round(total or 0.0, 2),
        })

    parsed["items"] = cleaned_items
    parsed["discounts"] = extra_discounts

    # --- Apply OCR-detected discounts (line-level heuristics) ---
    parsed["items"], detected_discounts = detect_item_discounts(ocr_text, parsed["items"])

    # ensure parsed["discounts"] exists and is a list
    if parsed.get("discounts") is None:
        parsed["discounts"] = []

    # merge with dedupe based on (description, amount, item)
    existing = set(
        (
            (d.get("description") or "").strip().lower(),
            round(to_float(d.get("amount")), 2),
            (d.get("item") or "").strip().lower()
        )
        for d in parsed["discounts"]
    )
    for dd in detected_discounts:
        key = (
            (dd.get("description") or "").strip().lower(),
            round(to_float(dd.get("amount")), 2),
            (dd.get("item") or "").strip().lower()
        )
        if key not in existing:
            parsed["discounts"].append(dd)
            existing.add(key)

    # --- Attach any LLM-reported global discounts to nearest preceding line item (line-level)
    if parsed.get("discounts"):
        lines = [ln.strip().replace('—', '-').replace('–', '-') for ln in ocr_text.splitlines() if ln.strip()]
        used_lines = set()
        for d in parsed.get("discounts", []):
            # skip discounts already tied to an item (these were applied earlier)
            if d.get("item"):
                continue

            desc = (d.get("description") or "").strip().lower()
            amt = to_float(d.get("amount"))
            if amt == 0:
                continue

            # find discount line index in OCR text that matches description or pattern
            matched_idx = None
            for i, line in enumerate(lines):
                if desc and desc in line.lower():
                    matched_idx = i
                    break
                if re.search(r'-\s*\$?\s*[0-9]+(?:\.[0-9]{2})', line):
                    matched_idx = i
                    break
            if matched_idx is None:
                continue
            # find previous item line index
            j = matched_idx - 1
            while j >= 0:
                prev = lines[j]
                if re.search(r'\d', prev) and re.search(r'[A-Za-z]', prev):
                    break
                j -= 1
            if j < 0:
                continue
            prev_line = lines[j]
            # match to parsed item by fuzzy token overlap
            prev_norm = re.sub(r'[^a-z0-9 ]', ' ', prev_line.lower())
            best_k = None
            best_overlap = 0
            for k, it in enumerate(parsed["items"]):
                name_norm = re.sub(r'[^a-z0-9 ]', ' ', (it.get("name") or "").lower())
                overlap = len(set(prev_norm.split()) & set(name_norm.split()))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_k = k
            if best_k is not None and best_overlap > 0:
                target = parsed["items"][best_k]
                orig_total = to_float(target.get("total_price", 0))
                target["discount"] = {"type": "flat", "amount": round(amt, 2), "description": desc}
                target["total_price"] = round(orig_total - amt, 2)

    # --- AFTER ALL LINE-LEVEL DISCOUNTS APPLIED: expand into per-unit items for the bot -->
    expanded = []
    for it in parsed["items"]:
        qty = int(it.get("qty", 1) or 1)
        line_total = to_float(it.get("total_price", 0))
        per_unit = round((line_total / qty) if qty else 0.0, 2)
        for _ in range(qty):
            expanded.append({
                "name": it.get("name"),
                "qty": 1,
                "unit_price": per_unit,
                "total_price": per_unit,
                # carry line discount info optionally
                # "line_discount": it.get("discount")
            })
    parsed["items_expanded"] = expanded
    parsed["items"] = expanded  # main bot expects unit list

    # --- Infer taxes/service if model missed them ---
    if not parsed.get("taxes"):
        m_tax = re.findall(r'(SST|GST|TAX|VAT|SERVICE|SERVICE CHARGE)[^\d]*([0-9,\.]+\d{2})', ocr_text, re.I)
        inferred = []
        for label, val in m_tax:
            inferred.append({"type": label.strip(), "amount": to_float(val)})
        parsed["taxes"] = inferred

    if parsed.get("service_charge") and isinstance(parsed["service_charge"], dict):
        parsed["service_charge"]["amount"] = to_float(parsed["service_charge"].get("amount"))

    # Move any service-like entries from taxes into service_charge
    if (not parsed.get("service_charge") or not parsed["service_charge"].get("amount")) and parsed.get("taxes"):
        for t in list(parsed["taxes"]):
            if "service" in t.get("type", "").lower() or "svc" in t.get("type", "").lower():
                parsed["service_charge"] = {"percent": None, "amount": to_float(t["amount"])}
                parsed["taxes"].remove(t)
                break

    # --- Final computed total (derived from adjusted line totals) ---
    subtotal = sum(to_float(it.get("total_price", 0)) for it in parsed.get("items_expanded", []))
    # If you want subtotal at line-level instead use parsed["items"] before expansion
    service_amt = to_float(parsed.get("service_charge", {}).get("amount", 0))
    tax_amt = sum(to_float(t.get("amount")) for t in parsed.get("taxes", []))
    parsed["computed_total"] = round(subtotal + service_amt + tax_amt, 2)

    # --- DEBUG: Final item prices after all discounts applied ---
    print("\n[DEBUG] Final item totals after discounts:")
    for item in parsed.get("items", []):
        name = item.get("name", "UNKNOWN")
        qty = item.get("qty", 1)
        unit = item.get("unit_price", 0.0)
        total = item.get("total_price", 0.0)
        print(f"  - {name}: qty={qty}, unit={unit:.2f}, total={total:.2f}")

    # Also, show subtotal, taxes, and total summary if available
    subtotal_display = sum(i.get("total_price", 0) for i in parsed.get("items", []))
    tax_total = sum(t.get("amount", 0) for t in parsed.get("taxes", []))
    service = parsed.get("service_charge", {}).get("amount") or 0
    grand_total = subtotal_display + tax_total + service

    print(f"\n[DEBUG] Receipt summary:")
    print(f"  Subtotal after discounts: ${subtotal_display:.2f}")
    print(f"  Tax total: ${tax_total:.2f}")
    print(f"  Service charge: ${service:.2f}")
    print(f"  Grand total (calculated): ${grand_total:.2f}")
    print("-" * 50)

    return parsed
