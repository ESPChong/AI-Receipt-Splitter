# ocr.py
import os
from PIL import Image
import pytesseract

USE_GOOGLE = os.getenv('USE_GOOGLE_VISION', '0') == '1'

if USE_GOOGLE:
    from google.cloud import vision


def extract_text_from_image(path: str) -> str:
    if USE_GOOGLE:
        client = vision.ImageAnnotatorClient()
        with open(path, 'rb') as img:
            content = img.read()
        image = vision.Image(content=content)
        response = client.text_detection(image=image)
        texts = response.text_annotations
        if texts:
            return texts[0].description
        else:
            return ''
    else:
        # pytesseract fallback
        img = Image.open(path).convert('RGB')
        text = pytesseract.image_to_string(img)
        return text