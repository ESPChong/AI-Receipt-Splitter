# utils.py
import re

def find_currency(text: str):
    m = re.search(r"(USD|SGD|MYR|RM|\$|€|EUR)", text, re.I)
    return m.group(0) if m else None