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

# --- AUTO FORWARD SYSTEM ---
seen_sms = set()
async def auto_forwarder(app):
    print("Auto Forwarder Started...")
    while True:
        await asyncio.sleep(10) # 10 sec por por check
        try:
            day = datetime.now().strftime("%Y-%m-%d")
            all_sms = api_get("/api/stock/public/edr", {"page":1,"perPage":50,"day":day}).get('data',[])
            stats = load_json(DATA_FILE, {})

            for sms in all_sms:
                uid = f"{sms['b_number']}_{sms['created_at']}"
                if uid in seen_sms: continue
                seen_sms.add(uid)

                # kon user er number e sms asche khujo
                for user_id_str, data in stats.items():
                    if str(sms['b_number']) in [str(n) for n in data.get('numbers',[])]:
                        otp = extract_otp(sms['message'])
                        text = f"🔔 **NEW OTP AUTO FORWARD**\n\n📱 To: `{sms['b_number']}`\n📩 From: {sms['a_number']}\n\n{sms['message']}"
                        if otp: text += f"\n\n🔑 **CODE: `{otp}`**"
                        try:
                            await app.bot.send_message(chat_id=int(user_id_str), text=text, parse_mode='Markdown')
                            # count barao
                            stats[user_id_str]['count'] = stats[user_id_str].get('count',0)+1
                            save_json(DATA_FILE, stats)
                        except Exception as e:
                            print(f"Forward fail {user_id_str}: {e}")
                        break
        except Exception as e:
            print(f"Auto loop error: {e}")

def main_menu(uid):
    kb = [
        [InlineKeyboardButton("🎁 Get 3 Numbers", callback_data="get_3_numbers"), InlineKeyboardButton("📞 My Numbers", callback_data="my_numbers")],
        [InlineKeyboardButton("📩 Live OTPs", callback_data="my_otps")],
    ]
    if is_admin(uid):
        kb.append([InlineKeyboardButton("📊 Admin Stats", callback_data="admin_stats"), InlineKeyboardButton("👥 Users", callback_data="manage_users")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text(f"❌ Access Denied\nID: `{uid}`"); return
    await update.message.reply_text(f"👋 **Welcome to Private IPRN Bot**\n\n🎁 Get 3 Numbers e click kore 3 ta number nao.\nTarpor OTP auto tomar inbox e asbe.", reply_markup=main_menu(uid), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if not is_allowed(uid): return

    stats = load_json(DATA_FILE, {})
    if str(uid) not in stats: stats[str(uid)] = {"count":0, "numbers":[]}

    if query.data == "get_3_numbers":
        if len(stats[str(uid)]["numbers"]) >= 3:
            await query.edit_message_text(f"❌ Tumi already 3 ta niye niso:\n{stats[str(uid)]['numbers']}", reply_markup=main_menu(uid)); return

        # IPRN theke available number ano
        await query.edit_message_text("🔍 Tomar jonno 3 ta number khujchi...", reply_markup=main_menu(uid))
        data = api_get("/api/stock/public/assigned-numbers", {"page":1,"perPage":50}).get('data',[])

        all_available = []
        for item in data:
            all_available.extend([str(n) for n in item['numbers']])

        # jeta onno user ney nai seta filter
        taken = []
        for u in stats.values(): taken.extend(u.get('numbers',[]))
        free = [n for n in all_available if n not in taken]

        if len(free) < 3:
            await query.edit_message_text(f"❌ Stock e 3 ta free number nai. Available: {len(free)}\nAdmin ke bolo number kinte.", reply_markup=main_menu(uid)); return

        picked = random.sample(free, 3)
        stats[str(uid)]["numbers"] = picked
        save_json(DATA_FILE, stats)
        await query.edit_message_text(f"✅ **Tomar 3 ta Number:**\n\n" + "\n".join([f"`{n}`" for n in picked]) + "\n\nEkhon theke OTP auto forward hobe.", reply_markup=main_menu(uid), parse_mode='Markdown')

    elif query.data == "my_numbers":
        nums = stats[str(uid)].get("numbers",[])
        if not nums: await query.edit_message_text("📭 Kono number nai. 🎁 Get 3 Numbers e click koro.", reply_markup=main_menu(uid))
        else: await query.edit_message_text(f"📞 Your Numbers ({len(nums)}/3):\n" + "\n".join([f"`{n}`" for n in nums]), reply_markup=main_menu(uid), parse_mode='Markdown')

    elif query.data == "admin_stats" and is_admin(uid):
        msg = "📊 **ADMIN STATS**\n\n"
        for u_id, d in stats.items():
            msg += f"👤 `{u_id}`\nCount: {d.get('count',0)} | Numbers: {d.get('numbers',[])}\n\n"
        await query.edit_message_text(msg, reply_markup=main_menu(uid), parse_mode='Markdown')

    elif query.data == "my_otps":
        await query.edit_message_text("✅ Auto Forward ON ache. OTP asle auto inbox e chole asbe.", reply_markup=main_menu(uid))

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    # search still allowed
    b_num = re.sub(r'\D','', update.message.text)
    day = datetime.now().strftime("%Y-%m-%d")
    all_sms = api_get("/api/stock/public/edr", {"page":1,"perPage":100,"day":day}).get('data',[])
    found = [x for x in all_sms if b_num in str(x['b_number'])]
    if not found: await update.message.reply_text("No SMS today"); return
    for sms in found[-2:]:
        otp = extract_otp(sms['message'])
        txt = f"To: {sms['b_number']}\n{sms['message']}"
        if otp: txt+=f"\n\nOTP: {otp}"
        await update.message.reply_text(txt)

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    users = load_json(ALLOWED_FILE, [])
    nid = int(context.args[0]);
    if nid not in users: users.append(nid); save_json(ALLOWED_FILE, users)
    await update.message.reply_text(f"Added {nid}")

async def post_init(app):
    # auto forwarder background e chalu
    asyncio.create_task(auto_forwarder(app))

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_user))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
    print("Bot with Auto Forward Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
