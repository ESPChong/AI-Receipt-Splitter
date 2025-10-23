# tg_bot.py
import os
import json
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, ConversationHandler, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from ocr import extract_text_from_image
from ai_parser import parse_receipt_text
from split_calc import compute_splits

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# --- Conversation States ---
WAIT_RECEIPT, ASK_SPLIT_MODE, ASK_NAMES, CONFIRM_PEOPLE, ITEM_SELECTION = range(5)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please send a clear photo of the receipt to start.")
    return WAIT_RECEIPT


async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = await update.message.photo[-1].get_file()
    img_path = "temp_receipt.jpg"
    await photo.download_to_drive(img_path)

    context.user_data["receipt_path"] = img_path
    await update.message.reply_text(
        "Got it! How would you like to split the bill?",
        reply_markup=ReplyKeyboardMarkup([["Even Split", "Each Pays Their Own"]], one_time_keyboard=True)
    )
    return ASK_SPLIT_MODE


async def ask_names(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = update.message.text.strip().lower()
    context.user_data["split_mode"] = "even" if "even" in mode else "own"

    await update.message.reply_text(
        "Please list the names or @handles of everyone who was present, separated by commas."
    )
    return ASK_NAMES


async def confirm_people(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names = [n.strip() for n in update.message.text.split(",") if n.strip()]
    context.user_data["participants"] = names
    count = len(names)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="yes"),
         InlineKeyboardButton("❌ No", callback_data="no")]
    ])
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
        await query.edit_message_text("Okay, please re-enter the names separated by commas.")
        return ASK_NAMES

    # If confirmed, proceed to parsing and splitting
    await query.edit_message_text("Perfect! Processing your receipt now...")

    img_path = context.user_data["receipt_path"]
    participants = context.user_data["participants"]
    split_mode = context.user_data["split_mode"]

    # OCR and parsing
    ocr_text = extract_text_from_image(img_path)
    parsed = parse_receipt_text(ocr_text, participants)

    context.chat_data["parsed"] = parsed
    context.chat_data["assignments"] = {p: [] for p in participants}

    if split_mode == "even":
        result = compute_splits(parsed, participants)
        msg = "💰 *Even Split:*\n"
        for p, amt in result.items():
            msg += f"{p}: ${amt:.2f}\n"
        await query.message.reply_text(msg, parse_mode="Markdown")
        return ConversationHandler.END

    # Otherwise, start interactive assignment
    context.chat_data["current_selector"] = 0
    await ask_next_person(query, context)
    return ITEM_SELECTION

async def ask_next_person(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    # Handles both update and query input
    msg = update_or_query.message if hasattr(update_or_query, "message") else update_or_query
    parsed = context.chat_data.get("parsed", {})
    idx = context.chat_data.get("current_selector", 0)
    participants = context.user_data.get("participants", [])

    if idx >= len(participants):
        await finalize_split(msg, context)
        return ConversationHandler.END

    current_person = participants[idx]

    # Build list of individual selectable units.
    # unit_list entries: (global_item_index, unit_seq, display_name, unit_price)
    unit_list = []
    next_unit_seq = 0
    for i, item in enumerate(parsed.get("items", [])):
        qty = int(item.get("qty", 1) or 1)
        total_price = float(item.get("total_price", 0) or 0)
        # compute per-unit price (safe)
        unit_price = (total_price / qty) if qty > 0 else float(item.get("unit_price") or 0.0)

        # how many units already assigned (length of assigned_to list)
        assigned_count = len(item.get("assigned_to", [])) if "assigned_to" in item else 0
        remaining = max(0, qty - assigned_count)

        for _ in range(remaining):
            unit_list.append((i, next_unit_seq, item["name"], unit_price))
            next_unit_seq += 1

    if not unit_list:
        await finalize_split(msg, context)
        return ConversationHandler.END

    # Build buttons (one per remaining unit). callback_data: select|<item_index>|<unit_seq>
    buttons = []
    for global_idx, seq, name, price in unit_list:
        text = f"{name} (${price:.2f})"
        cb = f"select|{global_idx}|{seq}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=cb)])

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
    if not participants:
        await query.message.reply_text("No participants found; please restart (/start).")
        return ConversationHandler.END
    current_person = participants[idx]

    if data == "done":
        # move to next person
        context.chat_data["current_selector"] = idx + 1
        await query.message.reply_text(f"Thanks, {current_person}!")
        # ask next person - pass query so it replies in same chat
        await ask_next_person(query, context)
        return ITEM_SELECTION

    if data.startswith("select|"):
        # data format: select|<item_index>|<unit_seq>
        try:
            _, item_index_str, unit_seq_str = data.split("|")
            item_index = int(item_index_str)
        except Exception:
            await query.message.reply_text("Selection parsing error. Try again.")
            return ITEM_SELECTION

        items = parsed.get("items", [])
        if item_index < 0 or item_index >= len(items):
            await query.message.reply_text("Invalid item selection.")
            return ITEM_SELECTION

        item = items[item_index]
        # ensure assigned_to list exists
        if "assigned_to" not in item or not isinstance(item["assigned_to"], list):
            item["assigned_to"] = []

        # assign one unit to this person
        item["assigned_to"].append(current_person)
        # record for quick lookup
        assignments = context.chat_data.setdefault("assignments", {})
        assignments.setdefault(current_person, []).append(item["name"])

        await query.message.reply_text(f"Added {item['name']} to {current_person}'s order.")
        # After selecting, re-show the same person's menu so they can select more until 'Done'
        await ask_next_person(query, context)
        return ITEM_SELECTION
    

async def finalize_split(update, context: ContextTypes.DEFAULT_TYPE):
    parsed = context.chat_data["parsed"]
    participants = context.user_data["participants"]

    subtotal = sum(item["total_price"] for item in parsed["items"])
    tax_amount = sum(t.get("amount", 0) for t in parsed.get("taxes", []))
    service_amount = 0
    if parsed.get("service_charge"):
        service_amount = parsed["service_charge"].get("amount") or 0
    subtotal = subtotal or 1  # avoid division by zero

    # Compute proportional rates
    tax_rate = tax_amount / subtotal
    service_rate = service_amount / subtotal

    per_person = {p: 0 for p in participants}
    for item in parsed["items"]:
        if "assigned_to" not in item or not item["assigned_to"]:
            continue
        cost_share = item["total_price"] / len(item["assigned_to"])
        for person in item["assigned_to"]:
            per_person[person] += cost_share

    # Apply proportional tax and service to each person's subtotal
    for p in per_person:
        per_person[p] *= (1 + tax_rate + service_rate)


    msg = "💰 *Final Split:*\n"
    for p, amt in per_person.items():
        msg += f"{p}: ${amt:.2f}\n"

    await update.reply_text(msg, parse_mode="Markdown")


def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAIT_RECEIPT: [MessageHandler(filters.PHOTO, handle_receipt)],
            ASK_SPLIT_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_names)],
            ASK_NAMES: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_people)],
            CONFIRM_PEOPLE: [CallbackQueryHandler(confirm_people_response)],
            ITEM_SELECTION: [CallbackQueryHandler(handle_selection)],
        },
        fallbacks=[],
    )

    application.add_handler(conv)
    print("Bot started (polling)")
    application.run_polling()


if __name__ == "__main__":
    main()
