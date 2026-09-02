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

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn=get_db(); cur=conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS stock (number TEXT PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS user_numbers (user_id BIGINT, number TEXT, PRIMARY KEY(user_id, number))")
    cur.execute("CREATE TABLE IF NOT EXISTS seen (sms_id TEXT PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS otp_stats (user_id BIGINT PRIMARY KEY, count INT DEFAULT 0)")
    cur.execute("INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (ADMIN_ID,))
    conn.commit(); cur.close(); conn.close()
    print("DB Init Done")

def clean_num(n):
    return re.sub(r'\D','', str(n))[-10:]

def api_get(e,p={}):
    try:
        r = requests.get(f"{BASE_URL}{e}", headers=HEADERS, params=p, timeout=15)
        # print(f"API {e} {p} -> {r.status_code}")
        return r.json()
    except Exception as ex:
        print(f"API Error {ex}")
        return {}

def extract_otp(t):
    m=re.search(r'\b\d{4,8}\b', str(t))
    return m.group(0) if m else None

async def auto_forwarder(app):
    print("✅ Forwarder FIXED - Day Filter Enabled")
    while True:
        await asyncio.sleep(4)
        try:
            day = datetime.now().strftime("%Y-%m-%d")
            all_api_sms = []
            # Day filter diye 2 page check
            for page in [1,2]:
                data = api_get("/api/stock/public/edr", {"page": page, "perPage": 100, "day": day})
                sms_list = data.get('data', [])
                if sms_list:
                    all_api_sms.extend(sms_list)
                # Day filter e na pele day chara try
                if not sms_list:
                    data2 = api_get("/api/stock/public/edr", {"page": page, "perPage": 100})
                    sms_list2 = data2.get('data', [])
                    if sms_list2:
                        all_api_sms.extend(sms_list2)

            if not all_api_sms:
                continue

            conn=get_db(); cur=conn.cursor()
            cur.execute("SELECT user_id, number FROM user_numbers")
            assigned_rows = cur.fetchall()
            if not assigned_rows:
                cur.close(); conn.close()
                continue

            # print(f"Checking {len(all_api_sms)} SMS for {len(assigned_rows)} numbers")

            for sms in all_api_sms:
                mid=str(sms.get('id'))
                cur.execute("SELECT 1 FROM seen WHERE sms_id=%s",(mid,))
                if cur.fetchone():
                    continue

                b_raw = str(sms.get('b_number',''))
                a_raw = str(sms.get('a_number',''))
                msg = str(sms.get('message',''))
                b_clean = clean_num(b_raw) if b_raw else ""
                a_clean = clean_num(a_raw) if a_raw else ""

                for uid, unum in assigned_rows:
                    stored_clean = clean_num(unum)
                    raw_match = (unum in b_raw) or (unum in a_raw) or (unum in msg)
                    clean_match = (stored_clean == b_clean) or (stored_clean == a_clean)

                    if clean_match or raw_match:
                        print(f"MATCH FOUND: User {uid} | Stock {unum} | API B {b_raw}")
                        cur.execute("INSERT INTO seen VALUES (%s) ON CONFLICT DO NOTHING",(mid,))
                        cur.execute("INSERT INTO otp_stats (user_id, count) VALUES (%s,1) ON CONFLICT (user_id) DO UPDATE SET count = otp_stats.count + 1", (uid,))
                        conn.commit()
                        otp=extract_otp(msg)
                        txt=f"🔔 **NEW OTP RECEIVED**\n\n📱 Your Number: `{unum}`\n📩 From: `{a_raw}`\n\n💬 {msg}"
                        if otp:
                            txt+=f"\n\n🔑 **CODE: `{otp}`**"
                        try:
                            await app.bot.send_message(chat_id=int(uid), text=txt, parse_mode='Markdown')
                            print(f"Sent OTP to {uid}")
                        except Exception as e:
                            print(f"Send fail {e}")
                        break

            cur.close(); conn.close()
        except Exception as e:
            print(f"Forwarder Loop Error: {e}")
            await asyncio.sleep(2)

def main_menu(uid):
    kb=[[InlineKeyboardButton("🎁 Get 3 Numbers", callback_data="get_3_numbers"), InlineKeyboardButton("📞 My Numbers", callback_data="my_numbers")]]
    if uid==ADMIN_ID:
        kb.append([InlineKeyboardButton("📦 Manage Stock", callback_data="manage_stock"), InlineKeyboardButton("📈 Admin Stats", callback_data="admin_stats")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE user_id=%s",(update.effective_user.id,))
    ok=cur.fetchone() or update.effective_user.id==ADMIN_ID
    cur.close(); conn.close()
    if not ok:
        await update.message.reply_text(f"⛔ Access Denied. ID: `{update.effective_user.id}`")
        return
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT COUNT(*) FROM stock"); c=cur.fetchone()[0]
    cur.close(); conn.close()
    await update.message.reply_text(f"👋 **Welcome**\n📦 Fresh Stock: {c}", reply_markup=main_menu(update.effective_user.id), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    uid=query.from_user.id
    try:
        if query.data=="get_3_numbers":
            conn=get_db(); cur=conn.cursor()
            cur.execute("SELECT number FROM stock"); all_stock=[r[0] for r in cur.fetchall()]
            cur.execute("SELECT number FROM user_numbers"); taken=[r[0] for r in cur.fetchall()]
            free=[n for n in all_stock if clean_num(n) not in [clean_num(t) for t in taken]]
            if len(free)<3:
                await query.edit_message_text(f"⚠ Stock Low: {len(free)}", reply_markup=main_menu(uid))
                cur.close(); conn.close()
                return
            picked=random.sample(free,3)
            for n in picked:
                cur.execute("INSERT INTO user_numbers VALUES (%s,%s) ON CONFLICT DO NOTHING",(uid,n))
            conn.commit(); cur.close(); conn.close()
            await query.edit_message_text("✅ Assigned:\n" + "\n".join([f"`{n}`" for n in picked]), reply_markup=main_menu(uid), parse_mode='Markdown')

        elif query.data=="my_numbers":
            conn=get_db(); cur=conn.cursor()
            cur.execute("SELECT number FROM user_numbers WHERE user_id=%s",(uid,))
            nums=[r[0] for r in cur.fetchall()]
            cur.execute("SELECT count FROM otp_stats WHERE user_id=%s",(uid,))
            r=cur.fetchone(); cnt=r[0] if r else 0
            cur.close(); conn.close()
            txt=f"📞 Yours ({len(nums)}) OTPs:{cnt}\n" + "\n".join([f"`{n}`" for n in nums]) if nums else "No numbers"
            await query.edit_message_text(txt, reply_markup=main_menu(uid), parse_mode='Markdown')

        elif query.data=="manage_stock":
            conn=get_db(); cur=conn.cursor()
            cur.execute("SELECT COUNT(*) FROM stock"); t=cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM user_numbers"); a=cur.fetchone()[0]
            cur.close(); conn.close()
            await query.edit_message_text(f"📦 Total:{t} Assigned:{a} Free:{t-a}\n/addstock /removestock /stock /clearstock /add /remove", reply_markup=main_menu(uid))

        elif query.data=="admin_stats":
            conn=get_db(); cur=conn.cursor()
            cur.execute("SELECT user_id FROM users"); users=cur.fetchall()
            msg="📈 **ADMIN STATS**\n\n"
            for (u_id,) in users:
                cur.execute("SELECT COUNT(*) FROM user_numbers WHERE user_id=%s",(u_id,)); num_cnt=cur.fetchone()[0]
                cur.execute("SELECT count FROM otp_stats WHERE user_id=%s",(u_id,)); r=cur.fetchone(); otp_cnt=r[0] if r else 0
                msg+=f"👤 `{u_id}` | Nums:{num_cnt} | OTPs:{otp_cnt}\n"
            cur.execute("SELECT COUNT(*) FROM stock"); msg+=f"\n📦 Stock: {cur.fetchone()[0]}"
            cur.close(); conn.close()
            await query.edit_message_text(msg, reply_markup=main_menu(uid), parse_mode='Markdown')
    except BadRequest:
        pass

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    conn=get_db(); cur=conn.cursor(); added=0
    for a in context.args:
        n=re.sub(r'\D','',a)
        if len(n)>=8:
            cur.execute("INSERT INTO stock VALUES (%s) ON CONFLICT DO NOTHING",(n,))
            added+=cur.rowcount
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text(f"Added {added}")

async def remove_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    conn=get_db(); cur=conn.cursor()
    for a in context.args:
        n=re.sub(r'\D','',a)
        cur.execute("DELETE FROM stock WHERE number=%s",(n,))
        cur.execute("DELETE FROM user_numbers WHERE number=%s",(n,))
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text("Removed")

async def stock_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT number FROM stock LIMIT 100"); rows=cur.fetchall()
    cur.close(); conn.close()
    await update.message.reply_text("\n".join([r[0] for r in rows]) or "Empty")

async def clear_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    conn=get_db(); cur=conn.cursor()
    cur.execute("DELETE FROM stock"); cur.execute("DELETE FROM user_numbers")
    cur.execute("DELETE FROM seen"); cur.execute("DELETE FROM otp_stats")
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text("Cleared All")

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    conn=get_db(); cur=conn.cursor()
    for a in context.args:
        try: cur.execute("INSERT INTO users VALUES (%s) ON CONFLICT DO NOTHING",(int(re.sub(r'\D','',a)),))
        except: pass
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text("User Added")

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    conn=get_db(); cur=conn.cursor()
    for a in context.args:
        try:
            uid=int(re.sub(r'\D','',a))
            cur.execute("DELETE FROM users WHERE user_id=%s",(uid,))
            cur.execute("DELETE FROM user_numbers WHERE user_id=%s",(uid,))
            cur.execute("DELETE FROM otp_stats WHERE user_id=%s",(uid,))
        except: pass
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text("User Removed")

async def post_init(app):
    init_db()
    asyncio.create_task(auto_forwarder(app))

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

if __name__=="__main__":
    main()
