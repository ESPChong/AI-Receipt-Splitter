# ocr.py
import os
from PIL import Image
import pytesseract

# Check if Google Vision is enabled via environment variable
USE_GOOGLE = os.getenv('USE_GOOGLE_VISION', '0') == '1'

if USE_GOOGLE:
    from google.cloud import vision


def clean_ocr_text(text):
    import re

    # Merge amounts split over lines (e.g. "$64.\n49" → "$64.49")
    text = re.sub(r'\$\s*([0-9]+)\.\s*\n?\s*([0-9]{2})', r'$\1.\2', text)

    # Merge numbers split like "3.\n49" → "3.49"
    text = re.sub(r'([0-9]+)\.\s*\n?\s*([0-9]{2})', r'\1.\2', text)

    # Merge quantities split from names ("2\nAGLIO OLIO" → "2 AGLIO OLIO")
    text = re.sub(r'(\n|^)\s*(\d+)\s*\n\s*([A-Za-z])', r'\1\2 \3', text)

    # Fix malformed currencies like "$3.26.80" → "$326.80"
    text = re.sub(r'\$([0-9])\.([0-9]{2})\.([0-9]{2})', r'$\1\2.\3', text)

    # Merge any leftover line fragments with too many dots (e.g. "$3.05.42")
    text = re.sub(r'\$(\d)\.(\d{2})\.(\d{2})', r'$\1\2.\3', text)

    # Remove stray uppercase noise (only lines with no digits, no $, and no spaces)
    text = "\n".join([
        line for line in text.splitlines()
        if not (re.fullmatch(r'[A-Z]{5,}', line.strip()) and
                not any(c.isdigit() or c in "$:." for c in line))
    ])

    # Trim extra spaces per line
    text = "\n".join(line.strip() for line in text.splitlines())


    # Collapse multiple newlines and spaces
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'\n+', '\n', text)

    return text.strip()


def extract_text_from_image(path: str) -> str:
    """
    Extracts text from a receipt image using either Google Vision or Tesseract,
    then cleans it to improve number and price accuracy.
    """
    if USE_GOOGLE:
        # Google Cloud Vision OCR
        from google.cloud import vision
        client = vision.ImageAnnotatorClient()
        with open(path, 'rb') as img:
            content = img.read()
        image = vision.Image(content=content)
        response = client.text_detection(image=image)
        texts = response.text_annotations
        if texts:
            raw_text = texts[0].description
        else:
            raw_text = ''
    else:
        # pytesseract fallback (use line-based mode with better spacing)
        img = Image.open(path).convert('RGB')
        raw_text = pytesseract.image_to_string(
            img,
            config="--psm 6 -c preserve_interword_spaces=1"
        )

    # Clean the OCR text before returning
    cleaned_text = clean_ocr_text(raw_text)

    print("\n--- RAW OCR TEXT ---")
    print(raw_text[:500])
    print("\n--- CLEANED OCR TEXT ---")
    print(cleaned_text[:500])
    print("------------------------\n")

    return cleaned_text
