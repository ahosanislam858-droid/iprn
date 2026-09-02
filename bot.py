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
STOCK_FILE = "custom_stock.json"

def load_json(f, d):
    try:
        with open(f,'r') as fp: return json.load(fp)
    except: return d
def save_json(f, d):
    with open(f,'w') as fp: json.dump(fp,d, indent=2) if False else json.dump(d, fp, indent=2)

def is_allowed(uid): return uid in load_json(ALLOWED_FILE, [ADMIN_ID])
def is_admin(uid): return uid == ADMIN_ID
def extract_otp(t): return (re.search(r'\b\d{4,8}\b', t).group(0) if re.search(r'\b\d{4,8}\b', t) else None)
def api_get(e,p={}):
    try:
        r=requests.get(f"{BASE_URL}{e}", headers=HEADERS, params=p, timeout=15)
        return r.json()
    except: return {}

seen_sms=set()
async def auto_forwarder(app):
    print("Auto Forwarder Started...")
    while True:
        await asyncio.sleep(8)
        try:
            day=datetime.now().strftime("%Y-%m-%d")
            all_sms=api_get("/api/stock/public/edr",{"page":1,"perPage":100,"day":day}).get('data',[])
            stats=load_json(DATA_FILE,{})
            for sms in all_sms:
                key=f"{sms['b_number']}_{sms['id']}"
                if key in seen_sms: continue
                seen_sms.add(key)
                for uid_str, data in stats.items():
                    if str(sms['b_number']) in [str(n) for n in data.get('numbers',[])]:
                        otp=extract_otp(sms['message'])
                        txt=f"🔔 **NEW OTP RECEIVED**\n\n📱 Number: `{sms['b_number']}`\n📩 From: `{sms['a_number']}`\n\n**Message:**\n{sms['message']}"
                        if otp: txt+=f"\n\n🔑 **OTP CODE: `{otp}`**"
                        try:
                            await app.bot.send_message(chat_id=int(uid_str), text=txt, parse_mode='Markdown')
                            stats[uid_str]['count']=stats[uid_str].get('count',0)+1
                            save_json(DATA_FILE, stats)
                        except: pass
                        break
        except Exception as e: print(e)

def main_menu(uid):
    kb=[[InlineKeyboardButton("🎁 Get 3 Numbers", callback_data="get_3_numbers"), InlineKeyboardButton("📞 My Numbers", callback_data="my_numbers")]]
    if is_admin(uid): kb.append([InlineKeyboardButton("📦 Manage Stock", callback_data="manage_stock"), InlineKeyboardButton("📈 Admin Stats", callback_data="admin_stats")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text(f"⛔ Access Denied. ID: `{uid}`"); return
    stock=load_json(STOCK_FILE,[])
    await update.message.reply_text(f"👋 **Welcome to IPRN Private Panel**\n\n📦 Current Fresh Stock: {len(stock)} Numbers\n• Click Get 3 Numbers\n• OTP will auto forward\n\nStatus: ✅ Active", reply_markup=main_menu(uid), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    uid=query.from_user.id
    if not is_allowed(uid): return
    stats=load_json(DATA_FILE,{})
    if str(uid) not in stats: stats[str(uid)]={"count":0,"numbers":[]}
    stock=load_json(STOCK_FILE,[])

    if query.data=="get_3_numbers":
        taken=[]
        for u in stats.values(): taken.extend([str(x) for x in u.get('numbers',[])])
        free=[n for n in stock if str(n) not in taken]
        if len(free)<3:
            await query.edit_message_text(f"⚠️ **Stock Low**\n\nAvailable Fresh Numbers: {len(free)}\nRequired: 3\n\nPlease contact Admin to refill stock.", reply_markup=main_menu(uid), parse_mode='Markdown'); return
        picked=random.sample(free,3)
        stats[str(uid)]["numbers"].extend(picked)
        save_json(DATA_FILE, stats)
        await query.edit_message_text(f"✅ **3 Fresh Numbers Assigned**\n\n" + "\n".join([f"`{n}`" for n in picked]) + f"\n\nTotal Yours: {len(stats[str(uid)]['numbers'])}\nAuto Forward: Enabled", reply_markup=main_menu(uid), parse_mode='Markdown')

    elif query.data=="my_numbers":
        nums=stats[str(uid)].get("numbers",[])
        await query.edit_message_text(f"📞 **Your Numbers ({len(nums)})**\n\n" + "\n".join([f"`{n}`" for n in nums]) if nums else "📭 No numbers yet.", reply_markup=main_menu(uid), parse_mode='Markdown')

    elif query.data=="manage_stock" and is_admin(uid):
        taken=[]
        for u in stats.values(): taken.extend(u.get('numbers',[]))
        free=len([n for n in stock if str(n) not in taken])
        await query.edit_message_text(f"📦 **STOCK MANAGEMENT**\n\nTotal Stock: {len(stock)}\nAssigned: {len(taken)}\nFree Fresh: {free}\n\n**Commands:**\n/addstock 12025551234 12025555678\n/removestock 12025551234\n/clearstock\n/stock - show all", reply_markup=main_menu(uid), parse_mode='Markdown')

    elif query.data=="admin_stats" and is_admin(uid):
        msg="📈 **ADMIN STATS**\n\n"
        for u_id,d in stats.items():
            msg+=f"👤 `{u_id}` | OTPs: {d.get('count',0)} | Nums: {len(d.get('numbers',[]))}\n"
        msg+=f"\n📦 Stock Total: {len(stock)}"
        await query.edit_message_text(msg, reply_markup=main_menu(uid), parse_mode='Markdown')

# Admin Stock Commands
async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    stock=load_json(STOCK_FILE,[])
    nums=[re.sub(r'\D','',x) for x in context.args]
    nums=[n for n in nums if len(n)>=8]
    added=0
    for n in nums:
        if n not in stock: stock.append(n); added+=1
    save_json(STOCK_FILE, stock)
    await update.message.reply_text(f"✅ Added {added} numbers.\n📦 Total Stock: {len(stock)}")

async def stock_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    stock=load_json(STOCK_FILE,[])
    await update.message.reply_text(f"📦 Total {len(stock)}:\n" + "\n".join(stock[:50]) + ("\n...more" if len(stock)>50 else ""))

async def clear_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    save_json(STOCK_FILE, [])
    await update.message.reply_text("🗑️ Stock cleared.")

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    nid=int(context.args[0]); users=load_json(ALLOWED_FILE,[])
    if nid not in users: users.append(nid); save_json(ALLOWED_FILE, users)
    await update.message.reply_text(f"Added {nid}")

async def post_init(app): asyncio.create_task(auto_forwarder(app))

def main():
    app=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_user))
    app.add_handler(CommandHandler("addstock", add_stock))
    app.add_handler(CommandHandler("stock", stock_list))
    app.add_handler(CommandHandler("clearstock", clear_stock))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("Bot with Custom Stock Running...")
    app.run_polling()

if __name__=="__main__": main()
