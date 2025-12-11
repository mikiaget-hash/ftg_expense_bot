import telebot
import pytesseract
from PIL import Image
import io
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

BOT_TOKEN = "REPLACE_WITH_YOUR_BOT_TOKEN"
ADMIN_ID = 5623830516   # Your ID

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
gc = gspread.authorize(credentials)

WHITE_SHEET = gc.open_by_key("1VomOE8piToW3wcWChIrPEzT6vJUISRVefyhqbzCM66Y").sheet1
EXPENSE_SHEET = gc.open_by_key("1CqDAtmnr-8bnKMfA-ghbXUThcIQXi1w6RmTKew9DlHU").sheet1

bot = telebot.TeleBot(BOT_TOKEN)

user_state = {}
user_data = {}

REASONS = [
    "Tele Package",
    "Medicine",
    "Fuel",
    "Perdiem",
    "Labour",
    "Transportation",
    "Other"
]

def is_whitelisted(user_id):
    ids = WHITE_SHEET.col_values(1)
    return str(user_id) in ids

# ----------------- Registration -----------------

@bot.message_handler(commands=["register"])
def register(message):
    bot.send_message(ADMIN_ID, 
        f"🔔 *NEW REGISTRATION REQUEST*\n\n"
        f"ID: `{message.from_user.id}`\n"
        f"Name: {message.from_user.first_name}\n"
        f"Username: @{message.from_user.username}",
        parse_mode="Markdown"
    )
    bot.reply_to(message, 
        "✅ Your registration request has been sent.\n"
        "Tell the admin to approve you.\n\n"
        "👉 *To find your ID again:* Use /register"
    )

# ----------------- Start Command -----------------

@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    if not is_whitelisted(user_id):
        bot.reply_to(message, "❌ You are *not allowed* to use this bot.\nUse /register to request access.")
        return

    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("➕ Upload Expense", "📊 Expense Report")

    bot.send_message(
        message.chat.id,
        "👋 Welcome to *FTG Expense Bot*.\nChoose an option:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

# ----------------- Upload Expense -----------------

@bot.message_handler(func=lambda m: m.text == "➕ Upload Expense")
def ask_receipt(message):
    user_state[message.chat.id] = "WAITING_RECEIPT"
    bot.send_message(message.chat.id, "📸 Please upload the *receipt image*.")

@bot.message_handler(content_types=["photo"])
def handle_receipt(message):
    if user_state.get(message.chat.id) != "WAITING_RECEIPT":
        return

    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)

    image = Image.open(io.BytesIO(downloaded))
    ocr_text = pytesseract.image_to_string(image)

    # Extract amount
    import re
    amount_matches = re.findall(r"\b\d{2,6}\b", ocr_text)
    amount = amount_matches[0] if amount_matches else "0"

    # Extract date
    date_matches = re.findall(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", ocr_text)
    date_text = date_matches[0] if date_matches else datetime.datetime.now().strftime("%Y-%m-%d")

    user_data[message.chat.id] = {
        "amount": amount,
        "date": date_text,
        "receipt": downloaded
    }

    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    for r in REASONS:
        markup.add(r)

    bot.send_message(
        message.chat.id,
        f"🧾 OCR Extracted:\nAmount: *{amount}*\nDate: *{date_text}*\n\nSelect the reason:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    user_state[message.chat.id] = "WAITING_REASON"

@bot.message_handler(func=lambda m: m.text in REASONS)
def save_expense(message):
    if user_state.get(message.chat.id) != "WAITING_REASON":
        return

    reason = message.text
    data = user_data.get(message.chat.id)

    amount = data["amount"]
    date = data["date"]
    uploader = message.from_user.first_name

    # Upload receipt to Drive folder
    folder_id = "1N16eSW8hxB8wGkxMMeU2FBf3JLdimm4g"  # Replace with your drive folder ID
    upload_file = gc.upload(file_name="receipt.jpg", content=data["receipt"], folder_id=folder_id)

    file_link = f"https://drive.google.com/file/d/{upload_file['id']}"

    EXPENSE_SHEET.append_row([date, amount, reason, uploader, file_link])

    bot.send_message(
        message.chat.id,
        "✅ *Expense saved successfully!*\n\n"
        f"📅 Date: {date}\n"
        f"💰 Amount: {amount}\n"
        f"📌 Reason: {reason}\n"
        f"👤 Uploaded by: {uploader}",
        parse_mode="Markdown"
    )

    user_state.pop(message.chat.id)
    user_data.pop(message.chat.id)

# ----------------- Reports -----------------

@bot.message_handler(func=lambda m: m.text == "📊 Expense Report")
def report_menu(message):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🗓 Weekly", "📆 Monthly")
    bot.send_message(message.chat.id, "Choose report type:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text in ["🗓 Weekly", "📆 Monthly"])
def generate_report(message):
    rows = EXPENSE_SHEET.get_all_records()

    today = datetime.datetime.now()
    if message.text == "🗓 Weekly":
        threshold = today - datetime.timedelta(days=7)
    else:
        threshold = today - datetime.timedelta(days=30)

    filtered = [r for r in rows if datetime.datetime.strptime(r["Date"], "%Y-%m-%d") >= threshold]

    if not filtered:
        bot.send_message(message.chat.id, "No expenses found in this period.")
        return

    total = sum(int(r["Amount"]) for r in filtered)
    response = f"📊 *Expense Report*\nTotal: *{total}*\n\nDetails:\n"

    for r in filtered:
        response += f"- {r['Date']} | {r['Reason']} | {r['Amount']}\n"

    bot.send_message(message.chat.id, response, parse_mode="Markdown")

bot.polling(none_stop=True)
