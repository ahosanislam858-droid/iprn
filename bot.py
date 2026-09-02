import os, re, requests, asyncio, random, psycopg2
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest

BOT_TOKEN = os.environ.get("BOT_TOKEN")
IPRN_TOKEN = os.environ.get("IPRN_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DATABASE_URL = os.environ.get("DATABASE_URL")
BASE_URL = "https://api.iprn.pro"
HEADERS = {"Authorization": f"Bearer {IPRN_TOKEN}", "Accept": "application/json"}

def get_db(): return psycopg2.connect(DATABASE_URL)

def init_db():
    conn=get_db(); cur=conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS stock (number TEXT PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS user_numbers (user_id BIGINT, number TEXT, PRIMARY KEY(user_id, number))")
    cur.execute("CREATE TABLE IF NOT EXISTS seen (sms_id TEXT PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS otp_stats (user_id BIGINT PRIMARY KEY, count INT DEFAULT 0)")
    cur.execute("INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (ADMIN_ID,))
    conn.commit(); cur.close(); conn.close()
    print("DB Init Done - OTP Stats Added")

def clean_num(n): return re.sub(r'\D','', str(n))[-10:]

def api_get(e,p={}):
    try: return requests.get(f"{BASE_URL}{e}", headers=HEADERS, params=p, timeout=15).json()
    except: return {}

def extract_otp(t):
    m=re.search(r'\b\d{4,8}\b', str(t))
    return m.group(0) if m else None

async def auto_forwarder(app):
    print("✅ Forwarder Started - OTP will go to user inbox")
    while True:
        await asyncio.sleep(8)
        try:
            day=datetime.now().strftime("%Y-%m-%d")
            data=api_get("/api/stock/public/edr",{"page":1,"perPage":100,"day":day}).get('data',[])
            if not data: data=api_get("/api/stock/public/edr",{"page":1,"perPage":100}).get('data',[])
            if not data: continue
            conn=get_db(); cur=conn.cursor()
            for sms in data:
                mid=str(sms.get('id'))
                cur.execute("SELECT 1 FROM seen WHERE sms_id=%s",(mid,))
                if cur.fetchone(): continue
                api_b=clean_num(sms.get('b_number',''))
                cur.execute("SELECT user_id, number FROM user_numbers"); rows=cur.fetchall()
                for uid, unum in rows:
                    if clean_num(unum)==api_b:
                        # MATCH FOUND - SEND TO USER INBOX
                        cur.execute("INSERT INTO seen VALUES (%s) ON CONFLICT DO NOTHING",(mid,))
                        # OTP count barabo
                        cur.execute("INSERT INTO otp_stats (user_id, count) VALUES (%s,1) ON CONFLICT (user_id) DO UPDATE SET count = otp_stats.count + 1", (uid,))
                        conn.commit()
                        otp=extract_otp(sms.get('message',''))
                        txt=f"🔔 **NEW OTP RECEIVED**\n\n📱 Number: `{unum}`\n📩 From: `{sms.get('a_number','')}`\n\n**Message:**\n{sms.get('message','')}"
                        if otp: txt+=f"\n\n🔑 **OTP CODE: `{otp}`**"
                        try:
                            await app.bot.send_message(chat_id=int(uid), text=txt, parse_mode='Markdown')
                            print(f"OTP sent to {uid} for {unum}")
                        except Exception as e: print(f"Send fail {uid}: {e}")
                        break
            cur.close(); conn.close()
        except Exception as e: print(f"Forwarder Error {e}")

def main_menu(uid):
    kb=[[InlineKeyboardButton("🎁 Get 3 Numbers", callback_data="get_3_numbers"), InlineKeyboardButton("📞 My Numbers", callback_data="my_numbers")]]
    if uid==ADMIN_ID: kb.append([InlineKeyboardButton("📦 Manage Stock", callback_data="manage_stock"), InlineKeyboardButton("📈 Admin Stats", callback_data="admin_stats")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn=get_db(); cur=conn.cursor(); cur.execute("SELECT 1 FROM users WHERE user_id=%s",(update.effective_user.id,)); ok=cur.fetchone() or update.effective_user.id==ADMIN_ID; cur.close(); conn.close()
    if not ok: await update.message.reply_text(f"⛔ Access Denied. ID: `{update.effective_user.id}`"); return
    conn=get_db(); cur=conn.cursor(); cur.execute("SELECT COUNT(*) FROM stock"); c=cur.fetchone()[0]; cur.close(); conn.close()
    await update.message.reply_text(f"👋 **Welcome to IPRN Private Panel**\n📦 Current Fresh Stock: {c}\n\n• Click Get 3 Numbers\n• OTP will auto forward to your inbox", reply_markup=main_menu(update.effective_user.id), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query; await query.answer(); uid=query.from_user.id
    try:
        if query.data=="get_3_numbers":
            conn=get_db(); cur=conn.cursor(); cur.execute("SELECT number FROM stock"); all_stock=[r[0] for r in cur.fetchall()]; cur.execute("SELECT number FROM user_numbers"); taken=[r[0] for r in cur.fetchall()]
            free=[n for n in all_stock if clean_num(n) not in [clean_num(t) for t in taken]]
            if len(free)<3: await query.edit_message_text(f"⚠ Stock Low: {len(free)}", reply_markup=main_menu(uid)); cur.close(); conn.close(); return
            picked=random.sample(free,3)
            for n in picked: cur.execute("INSERT INTO user_numbers VALUES (%s,%s) ON CONFLICT DO NOTHING",(uid,n))
            conn.commit(); cur.close(); conn.close()
            await query.edit_message_text(f"✅ **3 Fresh Numbers Assigned**\n\n" + "\n".join([f"`{n}`" for n in picked]), reply_markup=main_menu(uid), parse_mode='Markdown')
        elif query.data=="my_numbers":
            conn=get_db(); cur=conn.cursor(); cur.execute("SELECT number FROM user_numbers WHERE user_id=%s",(uid,)); nums=[r[0] for r in cur.fetchall()]; cur.execute("SELECT count FROM otp_stats WHERE user_id=%s",(uid,)); cnt=cur.fetchone(); otp_c=cnt[0] if cnt else 0; cur.close(); conn.close()
            txt=f"📞 **Your Numbers ({len(nums)})**\n📩 OTPs Received: {otp_c}\n\n" + "\n".join([f"`{n}`" for n in nums]) if nums else "📭 No numbers yet."
            await query.edit_message_text(txt, reply_markup=main_menu(uid), parse_mode='Markdown')
        elif query.data=="manage_stock":
            conn=get_db(); cur=conn.cursor(); cur.execute("SELECT COUNT(*) FROM stock"); t=cur.fetchone()[0]; cur.execute("SELECT COUNT(*) FROM user_numbers"); a=cur.fetchone()[0]; cur.close(); conn.close()
            await query.edit_message_text(f"📦 **STOCK MANAGEMENT**\nTotal: {t} | Assigned: {a} | Free: {t-a}\n\n/addstock /removestock /stock /clearstock /add /remove", reply_markup=main_menu(uid))
        elif query.data=="admin_stats":
            conn=get_db(); cur=conn.cursor(); cur.execute("SELECT user_id FROM users"); users=cur.fetchall()
            msg="📈 **ADMIN STATS**\n\n"
            for (u_id,) in users:
                cur.execute("SELECT COUNT(*) FROM user_numbers WHERE user_id=%s",(u_id,)); num_cnt=cur.fetchone()[0]
                cur.execute("SELECT count FROM otp_stats WHERE user_id=%s",(u_id,)); r=cur.fetchone(); otp_cnt=r[0] if r else 0
                msg+=f"👤 `{u_id}` | Nums: {num_cnt} | OTPs: {otp_cnt}\n"
            cur.execute("SELECT COUNT(*) FROM stock"); msg+=f"\n📦 Stock Total: {cur.fetchone()[0]}"
            cur.close(); conn.close()
            await query.edit_message_text(msg, reply_markup=main_menu(uid), parse_mode='Markdown')
    except BadRequest: pass

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    conn=get_db(); cur=conn.cursor(); added=0
    for a in context.args:
        n=re.sub(r'\D','',a)
        if len(n)>=8: cur.execute("INSERT INTO stock VALUES (%s) ON CONFLICT DO NOTHING",(n,)); added+=cur.rowcount
    conn.commit(); cur.close(); conn.close(); await update.message.reply_text(f"✅ Added {added}")

async def remove_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    conn=get_db(); cur=conn.cursor()
    for a in context.args:
        n=re.sub(r'\D','',a); cur.execute("DELETE FROM stock WHERE number=%s",(n,)); cur.execute("DELETE FROM user_numbers WHERE number=%s",(n,))
    conn.commit(); cur.close(); conn.close(); await update.message.reply_text("Removed from stock")

async def stock_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    conn=get_db(); cur=conn.cursor(); cur.execute("SELECT number FROM stock"); rows=cur.fetchall(); cur.close(); conn.close()
    await update.message.reply_text(f"📦 {len(rows)}:\n" + "\n".join([r[0] for r in rows[:100]]) or "Empty")

async def clear_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    conn=get_db(); cur=conn.cursor(); cur.execute("DELETE FROM stock"); cur.execute("DELETE FROM user_numbers"); cur.execute("DELETE FROM seen"); cur.execute("DELETE FROM otp_stats"); conn.commit(); cur.close(); conn.close()
    await update.message.reply_text("Cleared All")

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    conn=get_db(); cur=conn.cursor()
    for a in context.args:
        try: cur.execute("INSERT INTO users VALUES (%s) ON CONFLICT DO NOTHING",(int(re.sub(r'\D','',a)),))
        except: pass
    conn.commit(); cur.close(); conn.close(); await update.message.reply_text("User Added")

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    conn=get_db(); cur=conn.cursor()
    for a in context.args:
        try:
            uid=int(re.sub(r'\D','',a))
            cur.execute("DELETE FROM users WHERE user_id=%s",(uid,)); cur.execute("DELETE FROM user_numbers WHERE user_id=%s",(uid,)); cur.execute("DELETE FROM otp_stats WHERE user_id=%s",(uid,))
        except: pass
    conn.commit(); cur.close(); conn.close(); await update.message.reply_text("User Removed")

async def post_init(app): init_db(); asyncio.create_task(auto_forwarder(app))

def main():
    app=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_user))
    app.add_handler(CommandHandler("remove", remove_user))
    app.add_handler(CommandHandler("addstock", add_stock))
    app.add_handler(CommandHandler("removestock", remove_stock))
    app.add_handler(CommandHandler("stock", stock_list))
    app.add_handler(CommandHandler("clearstock", clear_stock))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()
if __name__=="__main__": main()
