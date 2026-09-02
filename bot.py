import os, json, re, requests, asyncio, random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest

BOT_TOKEN = os.environ.get("BOT_TOKEN")
IPRN_TOKEN = os.environ.get("IPRN_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

BASE_URL = "https://api.iprn.pro"
HEADERS = {"Authorization": f"Bearer {IPRN_TOKEN}", "Accept": "application/json"}

ALLOWED_FILE = "allowed_users.json"
DATA_FILE = "user_stats.json"
STOCK_FILE = "custom_stock.json"
SEEN_FILE = "seen_sms.json"

def load_json(f, d):
    try:
        with open(f,'r') as fp: return json.load(fp)
    except: return d
def save_json(f, d):
    with open(f,'w') as fp: json.dump(d, fp, indent=2)

def is_allowed(uid): return uid in load_json(ALLOWED_FILE, [ADMIN_ID])
def is_admin(uid): return uid == ADMIN_ID

def clean_num(n):
    return re.sub(r'\D','', str(n))[-10:] # last 10 digit diye match

def extract_otp(t):
    m=re.search(r'\b\d{4,8}\b', t)
    return m.group(0) if m else None

def api_get(e,p={}):
    try:
        r=requests.get(f"{BASE_URL}{e}", headers=HEADERS, params=p, timeout=15)
        print(f"API {e} -> {r.status_code}")
        return r.json()
    except Exception as ex:
        print(f"API Error {ex}")
        return {}

seen_sms=set(load_json(SEEN_FILE, []))

async def auto_forwarder(app):
    global seen_sms
    print("✅ Auto Forwarder Started...")
    while True:
        await asyncio.sleep(8)
        try:
            day=datetime.now().strftime("%Y-%m-%d")
            # 1st try with day, 2nd try without day
            data=api_get("/api/stock/public/edr",{"page":1,"perPage":100,"day":day})
            all_sms=data.get('data',[])
            if not all_sms:
                data=api_get("/api/stock/public/edr",{"page":1,"perPage":100})
                all_sms=data.get('data',[])

            if not all_sms: continue

            stats=load_json(DATA_FILE,{})
            for sms in all_sms:
                mid=str(sms.get('id'))
                if mid in seen_sms: continue

                api_b = clean_num(sms.get('b_number',''))

                for uid_str, ud in stats.items():
                    for un in ud.get('numbers',[]):
                        if clean_num(un) == api_b:
                            # MATCH FOUND
                            seen_sms.add(mid)
                            save_json(SEEN_FILE, list(seen_sms))
                            otp=extract_otp(sms.get('message',''))
                            txt=f"🔔 **NEW OTP RECEIVED**\n\n📱 Number: `{un}`\n📩 From: `{sms.get('a_number','')}`\n\n**Message:**\n{sms.get('message','')}"
                            if otp: txt+=f"\n\n🔑 **OTP: `{otp}`**"
                            try:
                                await app.bot.send_message(chat_id=int(uid_str), text=txt, parse_mode='Markdown')
                                print(f"Sent OTP to {uid_str} for {un}")
                                ud['count']=ud.get('count',0)+1
                                save_json(DATA_FILE, stats)
                            except Exception as e:
                                print(f"Send fail {uid_str}: {e}")
                            break
        except Exception as e:
            print(f"Forwarder Loop Error: {e}")

def main_menu(uid):
    kb=[[InlineKeyboardButton("🎁 Get 3 Numbers", callback_data="get_3_numbers"), InlineKeyboardButton("📞 My Numbers", callback_data="my_numbers")]]
    if is_admin(uid): kb.append([InlineKeyboardButton("📦 Manage Stock", callback_data="manage_stock"), InlineKeyboardButton("📈 Admin Stats", callback_data="admin_stats")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text(f"⛔ Access Denied. ID: `{uid}`"); return
    stock=load_json(STOCK_FILE,[])
    await update.message.reply_text(f"👋 **Welcome**\n📦 Stock: {len(stock)}", reply_markup=main_menu(uid), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    uid=query.from_user.id
    if not is_allowed(uid): return
    stats=load_json(DATA_FILE,{})
    if str(uid) not in stats: stats[str(uid)]={"count":0,"numbers":[]}
    stock=load_json(STOCK_FILE,[])
    try:
        if query.data=="get_3_numbers":
            taken=[]
            for u in stats.values(): taken.extend([str(x) for x in u.get('numbers',[])])
            free=[n for n in stock if clean_num(n) not in [clean_num(x) for x in taken]]
            if len(free)<3:
                await query.edit_message_text(f"⚠️ Stock Low: {len(free)}", reply_markup=main_menu(uid)); return
            picked=random.sample(free,3)
            stats[str(uid)]["numbers"].extend(picked)
            save_json(DATA_FILE, stats)
            await query.edit_message_text(f"✅ 3 Numbers:\n" + "\n".join([f"`{n}`" for n in picked]), reply_markup=main_menu(uid), parse_mode='Markdown')
        elif query.data=="my_numbers":
            nums=stats[str(uid)].get("numbers",[])
            txt=f"📞 Your Numbers ({len(nums)})\n\n" + "\n".join([f"`{n}`" for n in nums]) if nums else "📭 No numbers yet."
            await query.edit_message_text(txt, reply_markup=main_menu(uid), parse_mode='Markdown')
        elif query.data=="manage_stock" and is_admin(uid):
            taken=[]
            for u in stats.values(): taken.extend(u.get('numbers',[]))
            free=len([n for n in stock if clean_num(n) not in [clean_num(x) for x in taken]])
            await query.edit_message_text(f"📦 Stock: {len(stock)} | Free: {free}\n/addstock 1202.. \n/stock", reply_markup=main_menu(uid))
        elif query.data=="admin_stats" and is_admin(uid):
            msg="📈 **STATS**\n\n"
            for u_id,d in stats.items(): msg+=f"`{u_id}` | OTPs: {d.get('count',0)} | Nums: {len(d.get('numbers',[]))}\n"
            await query.edit_message_text(msg, reply_markup=main_menu(uid), parse_mode='Markdown')
    except BadRequest:
        pass # Ignore same message error

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    stock=load_json(STOCK_FILE,[])
    nums=[re.sub(r'\D','',x) for x in context.args]
    added=0
    for n in nums:
        if n not in stock and len(n)>=8: stock.append(n); added+=1
    save_json(STOCK_FILE, stock)
    await update.message.reply_text(f"✅ Added {added} | Total {len(stock)}")

async def stock_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    stock=load_json(STOCK_FILE,[])
    await update.message.reply_text(f"📦 {len(stock)}:\n" + "\n".join(stock[:50]))

async def clear_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    save_json(STOCK_FILE, [])
    await update.message.reply_text("🗑 Cleared")

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
    app.run_polling()

if __name__=="__main__": main()
