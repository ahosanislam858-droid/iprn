import os, json, re, requests, asyncio, random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
IPRN_TOKEN = os.environ.get("IPRN_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

BASE_URL = "https://api.iprn.pro"
HEADERS = {"Authorization": f"Bearer {IPRN_TOKEN}", "Accept": "application/json"}

ALLOWED_FILE = "allowed_users.json"
DATA_FILE = "user_stats.json"

def load_json(file, default):
    try:
        with open(file, 'r') as f: return json.load(f)
    except: return default
def save_json(file, data):
    with open(file, 'w') as f: json.dump(data, f, indent=2)

def is_allowed(uid): return uid in load_json(ALLOWED_FILE, [ADMIN_ID])
def is_admin(uid): return uid == ADMIN_ID
def extract_otp(text):
    m = re.search(r'\b\d{4,8}\b', text)
    return m.group(0) if m else None

def api_get(endpoint, params={}):
    try:
        r = requests.get(f"{BASE_URL}{endpoint}", headers=HEADERS, params=params, timeout=15)
        return r.json()
    except: return {}

# --- AUTO FORWARDER ---
seen_sms = set()
async def auto_forwarder(app):
    print("Auto Forwarder Started...")
    while True:
        await asyncio.sleep(10)
        try:
            day = datetime.now().strftime("%Y-%m-%d")
            all_sms = api_get("/api/stock/public/edr", {"page":1,"perPage":100,"day":day}).get('data',[])
            stats = load_json(DATA_FILE, {})
            for sms in all_sms:
                uid_key = f"{sms['b_number']}_{sms['created_at']}_{sms['id']}"
                if uid_key in seen_sms: continue
                seen_sms.add(uid_key)
                for user_id_str, data in stats.items():
                    if str(sms['b_number']) in [str(n) for n in data.get('numbers',[])]:
                        otp = extract_otp(sms['message'])
                        text = f"🔔 **NEW OTP RECEIVED**\n\n📱 Number: `{sms['b_number']}`\n📩 From: `{sms['a_number']}`\n🕒 Time: {sms['created_at']}\n\n**Message:**\n{sms['message']}"
                        if otp: text += f"\n\n🔑 **OTP CODE: `{otp}`**"
                        try:
                            await app.bot.send_message(chat_id=int(user_id_str), text=text, parse_mode='Markdown')
                            stats[user_id_str]['count'] = stats[user_id_str].get('count',0)+1
                            save_json(DATA_FILE, stats)
                        except: pass
                        break
        except Exception as e:
            print(f"Auto loop error: {e}")

def main_menu(uid):
    kb = [
        [InlineKeyboardButton("🎁 Get 3 Numbers", callback_data="get_3_numbers"), InlineKeyboardButton("📞 My Numbers", callback_data="my_numbers")],
        [InlineKeyboardButton("📊 My Stats", callback_data="my_stats")],
    ]
    if is_admin(uid):
        kb.append([InlineKeyboardButton("📈 Admin Panel", callback_data="admin_stats"), InlineKeyboardButton("👥 Users List", callback_data="manage_users")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text(f"⛔ Access Denied.\nYour ID: `{uid}`\nContact Admin."); return
    await update.message.reply_text(
        "👋 **Welcome to IPRN Private Panel**\n\n"
        "• Click **Get 3 Numbers** to get numbers\n"
        "• OTP will be auto forwarded to your inbox\n"
        "• No duplicate numbers will be assigned\n\n"
        "Status: ✅ Active",
        reply_markup=main_menu(uid), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if not is_allowed(uid): return

    stats = load_json(DATA_FILE, {})
    if str(uid) not in stats: stats[str(uid)] = {"count":0, "numbers":[]}

    if query.data == "get_3_numbers":
        await query.edit_message_text("🔍 Fetching 3 new numbers from stock...", reply_markup=main_menu(uid))

        data = api_get("/api/stock/public/assigned-numbers", {"page":1,"perPage":100}).get('data',[])
        all_available = []
        for item in data:
            all_available.extend([str(n) for n in item['numbers']])

        taken = []
        for u in stats.values(): taken.extend([str(x) for x in u.get('numbers',[])])

        free = [n for n in all_available if n not in taken]

        if len(free) < 3:
            await query.edit_message_text(
                f"⚠️ **Insufficient Stock**\n\nAvailable Free Numbers: {len(free)}\nRequired: 3\n\nPlease contact admin to add more numbers to IPRN panel.",
                reply_markup=main_menu(uid), parse_mode='Markdown'); return

        picked = random.sample(free, 3)
        stats[str(uid)]["numbers"].extend(picked)
        save_json(DATA_FILE, stats)

        await query.edit_message_text(
            f"✅ **3 Numbers Assigned Successfully**\n\n" + "\n".join([f"`{n}`" for n in picked]) +
            f"\n\n📦 Total Your Numbers: {len(stats[str(uid)]['numbers'])}\n🔔 Auto Forward: Enabled",
            reply_markup=main_menu(uid), parse_mode='Markdown')

    elif query.data == "my_numbers":
        nums = stats[str(uid)].get("numbers",[])
        if not nums: await query.edit_message_text("📭 You have no numbers. Click Get 3 Numbers.", reply_markup=main_menu(uid))
        else: await query.edit_message_text(f"📞 **Your Numbers ({len(nums)})**\n\n" + "\n".join([f"`{n}`" for n in nums]), reply_markup=main_menu(uid), parse_mode='Markdown')

    elif query.data == "my_stats":
        d = stats[str(uid)]
        await query.edit_message_text(f"📊 **Your Statistics**\n\nTotal Numbers: {len(d.get('numbers',[]))}\nTotal OTPs Received: {d.get('count',0)}", reply_markup=main_menu(uid), parse_mode='Markdown')

    elif query.data == "admin_stats" and is_admin(uid):
        msg = "📈 **ADMIN PANEL - DETAILED STATS**\n\n"
        total_numbers = 0
        total_otps = 0
        for u_id, d in stats.items():
            total_numbers += len(d.get('numbers',[]))
            total_otps += d.get('count',0)
            msg += f"👤 User: `{u_id}`\n Numbers: {len(d.get('numbers',[]))} | OTPs: {d.get('count',0)}\n `{', '.join(d.get('numbers',[])[:3])}{'...' if len(d.get('numbers',[]))>3 else ''}`\n\n"
        msg += f"\n---\n📦 Total Assigned: {total_numbers}\n📩 Total OTPs: {total_otps}"
        await query.edit_message_text(msg, reply_markup=main_menu(uid), parse_mode='Markdown')

    elif query.data == "manage_users" and is_admin(uid):
        users = load_json(ALLOWED_FILE, [])
        msg = f"👥 **Allowed Users ({len(users)})**\n\n" + "\n".join([f"`{u}`" for u in users]) + "\n\nCommands:\n/add <id>\n/remove <id>"
        await query.edit_message_text(msg, reply_markup=main_menu(uid), parse_mode='Markdown')

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        nid = int(context.args[0])
        users = load_json(ALLOWED_FILE, [])
        if nid not in users: users.append(nid); save_json(ALLOWED_FILE, users)
        await update.message.reply_text(f"✅ User {nid} added successfully.")
    except: await update.message.reply_text("Usage: /add 123456789")

async def post_init(app):
    asyncio.create_task(auto_forwarder(app))

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_user))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
