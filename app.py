# app.py
import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from ocr import extract_text_from_image
from ai_parser import parse_receipt_text
from split_calc import compute_splits

load_dotenv()

app = Flask(__name__)

@app.route('/health')
def health():
    return 'ok'

@app.route('/process', methods=['POST'])
def process():
    # expects multipart form-data with 'image' file and optional 'participants' json list
    if 'image' not in request.files:
        return jsonify({'error': 'image missing'}), 400
    f = request.files['image']
    participants = request.form.get('participants')
    try:
        participants = [] if not participants else eval(participants)
    except Exception:
        participants = []

    # save temporarily
    import tempfile
    path = os.path.join(tempfile.gettempdir(), f.filename)
    f.save(path)

    ocr_text = extract_text_from_image(path)

    # AI parse
    parsed = parse_receipt_text(ocr_text, participants)

    # compute splits
    splits = compute_splits(parsed, participants)

    return jsonify({'ocr_text': ocr_text, 'parsed': parsed, 'splits': splits})

if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    app.run(host='0.0.0.0', port=port)

