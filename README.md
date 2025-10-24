# AI Receipt Splitter Bot

A Telegram bot that automatically splits restaurant bills using OCR (Optical Character Recognition) and AI-powered receipt parsing.  
It can read printed receipts, extract items, quantities, and taxes, then help friends split the bill either evenly or based on individual orders.

---

## Features

-  Upload a photo of your restaurant receipt  
-  AI-powered text parsing (via OpenRouter API)  
-  Automatically detects:
  - Items and prices
  - Quantities (e.g., "2 Aglio Olio")
  - Taxes and service charges (e.g., "SST", "GST", "SERVICE")  
-  Choose between:
  - **Even split** – divides total equally among participants  
  - **Each pays their own** – select items ordered by each person interactively  
-  Clean Telegram conversation flow  

---

## Project Structure

project/
│
├── ai_parser.py    # Handles AI extraction of structured data from OCR text
├── ocr.py          # Extracts text from images using Tesseract or Google Vision
├── split_calc.py   # Contains helper logic for computing even or per-person splits
├── tg_bot.py       # Telegram bot logic and conversation flow
├── .env            # Stores API keys and configuration
└── README.md       # Project documentation

---

##  Setup Instructions

### 1. Clone the repository

git clone https://github.com/yourusername/ai-receipt-splitter.git
cd ai-receipt-splitter

### 2. Create and activate a virtual environment

python -m venv venv
source venv/bin/activate    # on macOS/Linux
venv\Scripts\activate       # on Windows

### 3. Install dependencies

pip install -r requirements.txt

### 4. Configure environment variables

TELEGRAM_TOKEN=your_telegram_bot_token
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_MODEL=openrouter/model:name  # e.g. openai/gpt-4o-mini
USE_GOOGLE_VISION=0                     # Set to 1 if you want to use Google Vision OCR

---

## Running the Bot

python tg_bot.py

---

## How it works

1. You send a photo of a restaurant receipt.
2. The bot performs OCR to read text using:
    pytesseract (default), or
    Google Vision API (if enabled)
3. The extracted text is passed to an AI model through OpenRouter, which returns structured JSON data.
4. You choose how to split the bill — evenly or per person.
5. The bot computes the final total for each person, including taxes and service charges.

---

## Future Enhancements

1. Improve bot UI for more accessibility and control
2. Export split results to PDF or CSV
3. Support handwritten receipts
4. Integrate with Google Sheets or Splitwise
5. Detect multiple currencies automatically
