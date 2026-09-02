import os, json, re, requests, asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
IPRN_TOKEN = os.environ.get("IPRN_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

BASE_URL = "https://api.iprn.pro"
HEADERS = {"Authorization": f"Bearer {IPRN_TOKEN}", "Accept": "application/json"}

ALLOWED_FILE = "allowed_users.json"

def load_users():
    try:
        with open(ALLOWED_FILE, 'r') as f: return json.load(f)
    except: return [ADMIN_ID]

def save_users(users):
    with open(ALLOWED_FILE, 'w') as f: json.dump(users, f)

def is_allowed(user_id): return user_id in load_users()
def is_admin(user_id): return user_id == ADMIN_ID

def extract_otp(text):
    m = re.search(r'\b\d{3,8}[- ]?\d{0,8}\b', text)
    return m.group(0) if m else None

def api_get(endpoint, params={}):
    try:
        r = requests.get(f"{BASE_URL}{endpoint}", headers=HEADERS, params=params, timeout=15)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

# --- PROFESSIONAL UI ---
def main_menu():
    keyboard = [
        [InlineKeyboardButton("📞 My Numbers", callback_data="numbers"), InlineKeyboardButton("📩 Live SMS", callback_data="live_sms")],
        [InlineKeyboardButton("🔍 Search Number", callback_data="search_info"), InlineKeyboardButton("👥 Sub Users", callback_data="subusers")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text(f"❌ Access Denied\nYour ID: `{user_id}`\nAdmin ke bolo add korte.", parse_mode='Markdown')
        return

    text = f"👋 Welcome {update.effective_user.first_name}!\n\n🔐 **IPRN Private Panel**\n\nBot Status: ✅ Online\nDate: {datetime.now().strftime('%d-%m-%Y')}\n\nNiche theke option select koro:"
    await update.message.reply_text(text, reply_markup=main_menu(), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not is_allowed(user_id): return

    if query.data == "numbers":
        data = api_get("/api/stock/public/assigned-numbers", {"page":1,"perPage":30})
        if "data" not in data:
            await query.edit_message_text(f"Error: {data}", reply_markup=main_menu()); return

        msg = "📞 **Your Active Numbers**\n\n"
        for item in data['data']:
            nums = "\n".join([f"`{n}`" for n in item['numbers']])
            msg += f"🌍 {item['destination']} ({item['tariff']})\n{nums}\n\n"
        await query.edit_message_text(msg, reply_markup=main_menu(), parse_mode='Markdown')

    elif query.data == "live_sms":
        day = datetime.now().strftime("%Y-%m-%d")
        data = api_get("/api/stock/public/edr", {"page":1,"perPage":10,"day":day})
        sms_list = data.get('data', [])
        if not sms_list:
            await query.edit_message_text(f"📭 Aj {day} te kono SMS nai.", reply_markup=main_menu()); return

        for sms in sms_list[:5]:
            otp = extract_otp(sms['message'])
            txt = f"📩 From: {sms['a_number']}\n📱 To: `{sms['b_number']}`\n🕒 {sms['created_at']}\n\n{sms['message'][:250]}"
            if otp: txt += f"\n\n🔑 **OTP: `{otp}`**"
            await context.bot.send_message(chat_id=query.message.chat_id, text=txt, parse_mode='Markdown')
        await query.edit_message_text("✅ Last 5 SMS sent above 👇", reply_markup=main_menu())

    elif query.data == "search_info":
        await query.edit_message_text("🔍 Amake ekta number send koro, jemon:\n`40751070597`\nAmi oi number er ajker SMS ber kore dibo.", parse_mode='Markdown', reply_markup=main_menu())

    elif query.data == "subusers":
        if not is_admin(user_id):
            await query.answer("Only Admin can see this", show_alert=True); return
        data = api_get("/api/stock/public/sub-users", {"page":1,"perPage":20})
        msg = "👥 **Sub Users**\n\n"
        for u in data.get('data',[]):
            msg += f"ID: {u['id']} | {u['name']} | {u['status']} | {u['total_balance']}\n"
        await query.edit_message_text(msg, reply_markup=main_menu())

    elif query.data == "refresh":
        await query.edit_message_text("🔄 Refreshed", reply_markup=main_menu())

async def handle_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    b_num = re.sub(r'\D','', update.message.text)
    if len(b_num) < 7: return

    day = datetime.now().strftime("%Y-%m-%d")
    data = api_get("/api/stock/public/edr", {"page":1,"perPage":100,"day":day}).get('data',[])
    found = [x for x in data if b_num in str(x['b_number'])]

    if not found:
        await update.message.reply_text(f"❌ `{b_num}` er jonno aj kono SMS nai.", parse_mode='Markdown', reply_markup=main_menu()); return

    for sms in found[-3:]:
        otp = extract_otp(sms['message'])
        txt = f"✅ Found for `{b_num}`\nFrom: {sms['a_number']}\n\n{sms['message']}"
        if otp: txt += f"\n\n🔑 **CODE: `{otp}`**"
        await update.message.reply_text(txt, parse_mode='Markdown')

# Admin Commands
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args: await update.message.reply_text("Use: /add 123456789"); return
    try:
        new_id = int(context.args[0])
        users = load_users()
        if new_id not in users:
            users.append(new_id); save_users(users)
            await update.message.reply_text(f"✅ Added {new_id}")
        else: await update.message.reply_text("Already allowed")
    except: await update.message.reply_text("Invalid ID")

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args: return
    users = load_users()
    nid = int(context.args[0])
    if nid in users and nid!= ADMIN_ID:
        users.remove(nid); save_users(users)
        await update.message.reply_text(f"❌ Removed {nid}")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    users = load_users()
    await update.message.reply_text(f"Allowed Users:\n{users}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_user))
    app.add_handler(CommandHandler("remove", remove_user))
    app.add_handler(CommandHandler("users", list_users))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_number))
    print("Private Professional Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
