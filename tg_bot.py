# tg_bot.py
import os
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, ConversationHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)
from ocr import extract_text_from_image
from ai_parser import parse_receipt_text

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# --- Conversation States ---
WAIT_RECEIPT, ASK_SPLIT_MODE, ASK_NAMES, CONFIRM_PEOPLE, ITEM_SELECTION = range(5)


# --- Keyboards ---
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🚀 Start Receipt Splitter"), KeyboardButton("🔄 Restart")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def split_mode_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("Even Split"), KeyboardButton("Each Pays Their Own"), KeyboardButton("🔄 Restart")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


# --- Handlers ---
async def handle_receipt_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to the Receipt Splitter bot!\n📸 Please send a clear photo of the receipt to start.",
        reply_markup=main_menu_keyboard()
    )
    return WAIT_RECEIPT


async def handle_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.chat_data.clear()
    await update.message.reply_text(
        "👋 Welcome to the Receipt Splitter bot!\n📸 Please send a clear photo of the receipt to start.",
        reply_markup=main_menu_keyboard()
    )
    return WAIT_RECEIPT


async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = await update.message.photo[-1].get_file()
    img_path = "temp_receipt.jpg"
    await photo.download_to_drive(img_path)

    context.user_data["receipt_path"] = img_path
    await update.message.reply_text(
        "Got it! How would you like to split the bill?",
        reply_markup=split_mode_keyboard()
    )
    return ASK_SPLIT_MODE


async def ask_names(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text == "🔄 restart":
        return await handle_restart(update, context)

    context.user_data["split_mode"] = "even" if "even" in text else "own"
    await update.message.reply_text(
        "Please list the names of everyone present, separated by *spaces*.\n(Example: Alice Bob Charlie)\n⚠️ Don’t use the same name twice.",
        parse_mode="Markdown"
    )
    return ASK_NAMES


async def confirm_people(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "🔄 Restart":
        return await handle_restart(update, context)

    names = [n.strip() for n in update.message.text.split() if n.strip()]
    context.user_data["participants"] = names
    count = len(names)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="yes"),
        InlineKeyboardButton("❌ No", callback_data="no")
    ]])
    await update.message.reply_text(
        f"So there are *{count}* people present: {', '.join(names)}. Is that correct?",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    return CONFIRM_PEOPLE


async def confirm_people_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "no":
        await query.edit_message_text("Okay, please re-enter the names separated by spaces.")
        return ASK_NAMES

    await query.edit_message_text("Perfect! Processing your receipt now...")

    img_path = context.user_data["receipt_path"]
    participants = context.user_data["participants"]
    split_mode = context.user_data["split_mode"]

    # --- OCR & Parsing ---
    ocr_text = extract_text_from_image(img_path)
    parsed = parse_receipt_text(ocr_text, participants)
    context.chat_data["parsed"] = parsed
    context.chat_data["assignments"] = {p: [] for p in participants}

    # --- EVEN SPLIT MODE ---
    if split_mode == "even":
        # Use total from receipt
        total = parsed.get("total") or parsed.get("computed_total") or 0.0
        if not total:
            total = sum(item.get("total_price", 0) for item in parsed.get("items", []))
            total += sum(t.get("amount", 0) for t in parsed.get("taxes", []))
            total += parsed.get("service_charge", {}).get("amount") or 0
            total -= sum(d.get("amount", 0) for d in parsed.get("discounts", []))

        share = round(total / max(1, len(participants)), 2)
        result = {p: share for p in participants}

        msg = "*Even Split:*\n" + "\n".join(f"{p}: ${amt:.2f}" for p, amt in result.items())
        await query.message.reply_text(msg, parse_mode="Markdown")
        return ConversationHandler.END

    # --- ITEM SELECTION MODE ---
    context.chat_data["current_selector"] = 0
    await ask_next_person(query, context)
    return ITEM_SELECTION


async def ask_next_person(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    msg = update_or_query.message if hasattr(update_or_query, "message") else update_or_query
    parsed = context.chat_data.get("parsed", {})
    idx = context.chat_data.get("current_selector", 0)
    participants = context.user_data.get("participants", [])

    if idx >= len(participants):
        await finalize_split(msg, context)
        return ConversationHandler.END

    current_person = participants[idx]

    # Build unassigned item units
    unit_list = []
    next_unit_seq = 0
    for i, item in enumerate(parsed.get("items", [])):
        qty = int(item.get("qty", 1) or 1)
        total_price = float(item.get("total_price", 0) or 0)
        unit_price = (total_price / qty) if qty > 0 else float(item.get("unit_price") or 0.0)
        assigned_count = len(item.get("assigned_to", [])) if "assigned_to" in item else 0
        remaining = max(0, qty - assigned_count)

        for _ in range(remaining):
            unit_list.append((i, next_unit_seq, item["name"], unit_price))
            next_unit_seq += 1

    if not unit_list:
        await finalize_split(msg, context)
        return ConversationHandler.END

    # Inline buttons for selecting items
    buttons = [
        [InlineKeyboardButton(f"{name} (${price:.2f})", callback_data=f"select|{idx}|{seq}")]
        for idx, seq, name, price in unit_list
    ]
    buttons.append([InlineKeyboardButton("✅ Done", callback_data="done")])
    markup = InlineKeyboardMarkup(buttons)

    await msg.reply_text(
        f"Hi {current_person}, please select the items you ordered:",
        reply_markup=markup
    )
    return ITEM_SELECTION


async def handle_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    parsed = context.chat_data.get("parsed", {})
    idx = context.chat_data.get("current_selector", 0)
    participants = context.user_data.get("participants", [])
    current_person = participants[idx]

    if data == "done":
        context.chat_data["current_selector"] = idx + 1
        await query.message.reply_text(f"Thanks, {current_person}!")
        await ask_next_person(query, context)
        return ITEM_SELECTION

    if data.startswith("select|"):
        _, item_index_str, unit_seq_str = data.split("|")
        item_index = int(item_index_str)
        item = parsed["items"][item_index]
        item.setdefault("assigned_to", []).append(current_person)
        assignments = context.chat_data.setdefault("assignments", {})
        assignments.setdefault(current_person, []).append(item["name"])
        await query.message.reply_text(f"Added {item['name']} to {current_person}'s order.")
        await ask_next_person(query, context)
        return ITEM_SELECTION


async def finalize_split(update, context: ContextTypes.DEFAULT_TYPE):
    parsed = context.chat_data["parsed"]
    participants = context.user_data["participants"]

    subtotal = sum(item["total_price"] for item in parsed["items"])
    tax_amount = sum(t.get("amount", 0) for t in parsed.get("taxes", []))
    service_amount = (parsed.get("service_charge", {}) or {}).get("amount") or 0
    subtotal = subtotal or 1

    tax_rate = tax_amount / subtotal
    service_rate = service_amount / subtotal

    per_person = {p: 0 for p in participants}
    for item in parsed["items"]:
        if "assigned_to" not in item or not item["assigned_to"]:
            continue
        cost_share = item["total_price"] / len(item["assigned_to"])
        for person in item["assigned_to"]:
            per_person[person] += cost_share

    for p in per_person:
        per_person[p] *= (1 + tax_rate + service_rate)

    msg = "*Final Split:*\n" + "\n".join(f"{p}: ${amt:.2f}" for p, amt in per_person.items())
    await update.reply_text(msg, parse_mode="Markdown")


# --- Main entry ---
def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & filters.Regex("^🚀 Start Receipt Splitter$"), handle_receipt_start),
            MessageHandler(filters.TEXT & filters.Regex("^🔄 Restart$"), handle_restart),
        ],
        states={
            WAIT_RECEIPT: [MessageHandler(filters.PHOTO, handle_receipt),
                           MessageHandler(filters.TEXT & filters.Regex("^🔄 Restart$"), handle_restart)],
            ASK_SPLIT_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_names)],
            ASK_NAMES: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_people)],
            CONFIRM_PEOPLE: [CallbackQueryHandler(confirm_people_response)],
            ITEM_SELECTION: [CallbackQueryHandler(handle_selection)],
        },
        fallbacks=[],
    )

    application.add_handler(conv)
    print("Bot started (polling)...")
    application.run_polling()


if __name__ == "__main__":
    main()
