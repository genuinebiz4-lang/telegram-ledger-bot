from telegram import Update, InputFile
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, filters
)
from datetime import datetime, date, time
import sqlite3, os, re
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ================= CONFIG =================
import os
BOT_TOKEN = os.getenv("BOT_TOKEN")

OWNER_USERNAMES = ["philip_007"]
BACKEND_ADMIN_IDS = [1074526287,]
ACCESS_DENIED = "🚫 Access denied."

# ================= DATABASE =================
db = sqlite3.connect("hybrid_ledger.db"), check_same_thread=False)
cur = db.cursor()

cur.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT
);
CREATE TABLE IF NOT EXISTS owners (
    username TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS admins (
    chat_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY(chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS owner_last_group (
    owner TEXT PRIMARY KEY,
    chat_id INTEGER
);
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    day TEXT,
    type TEXT,
    amount REAL,
    note TEXT,
    time TEXT,
    datetime TEXT
);
CREATE TABLE IF NOT EXISTS rates (
    chat_id INTEGER,
    day TEXT,
    rate REAL,
    PRIMARY KEY(chat_id, day)
);
""")

for o in OWNER_USERNAMES:
    cur.execute("INSERT OR IGNORE INTO owners VALUES(?)", (o.lower(),))
db.commit()

# ================= HELPERS =================
def uname(update): return (update.effective_user.username or "").lower()
def uid(update): return update.effective_user.id
def cid(update): return update.effective_chat.id
def today(): return date.today().isoformat()
def now(): return datetime.now().strftime("%H:%M")
def now_full(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ================= PERMISSIONS =================
def is_owner(update):
    cur.execute("SELECT 1 FROM owners WHERE username=?", (uname(update),))
    return cur.fetchone() is not None

def is_admin(update):
    if uid(update) in BACKEND_ADMIN_IDS:
        return True
    if is_owner(update):
        return True
    cur.execute("SELECT 1 FROM admins WHERE chat_id=? AND user_id=?", (cid(update), uid(update)))
    return cur.fetchone() is not None

def save_last_group(update):
    if update.effective_chat.type in ("group", "supergroup"):
        if is_owner(update):
            cur.execute(
                "INSERT OR REPLACE INTO owner_last_group VALUES (?,?)",
                (uname(update), cid(update))
            )
            db.commit()

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (uid(update), uname(update))
    )
    db.commit()

    await update.message.reply_text(
        "👋 Hi Greetings!\n\n"
        "Welcome to Ledger BoT.\n\n"
        "If you're interested in accessing the bot with full rights, "
        "please type /myid, copy your Chat ID, and send it to @Goldensparrow0.\n\n"
        "Thank you 🙏"
    )
# ================= RATE / IN / OUT =================
async def rate_cmd(update, context):
    save_last_group(update)
    if not is_admin(update):
        return await update.message.reply_text(ACCESS_DENIED)
    rate = float(context.args[0])
    cur.execute("INSERT OR REPLACE INTO rates VALUES (?,?,?)", (cid(update), today(), rate))
    db.commit()
    await update.message.reply_text(f"✅ Rate set: {rate}")

async def in_cmd(update, context):
    save_last_group(update)
    if not is_admin(update):
        return await update.message.reply_text(ACCESS_DENIED)
    amt = float(context.args[0])
    note = " ".join(context.args[1:]) or "-"
    cur.execute(
        "INSERT INTO ledger VALUES(NULL,?,?,?,?,?,?,?)",
        (cid(update), today(), "IN", amt, note, now(), now_full())
    )
    db.commit()
    await statement(update, context)

async def out_cmd(update, context):
    save_last_group(update)
    if not is_admin(update):
        return await update.message.reply_text(ACCESS_DENIED)
    amt = float(context.args[0])
    note = " ".join(context.args[1:]) or "-"
    cur.execute(
        "INSERT INTO ledger VALUES(NULL,?,?,?,?,?,?,?)",
        (cid(update), today(), "OUT", amt, note, now(), now_full())
    )
    db.commit()
    await statement(update, context)

# ================= STATEMENT (POST-RESET ONLY) =================
async def statement(update, context):
    save_last_group(update)
    if not is_admin(update):
        return await update.message.reply_text(ACCESS_DENIED)

    chat = cid(update)
    day = today()

    cur.execute("SELECT rate FROM rates WHERE chat_id=? AND day=?", (chat, day))
    rate = cur.fetchone()
    rate = rate[0] if rate else 0

    cur.execute("""
        SELECT time, type, amount, note
        FROM ledger
        WHERE chat_id=? AND day=?
          AND datetime >= (
            SELECT COALESCE(MAX(datetime),'0000')
            FROM ledger
            WHERE chat_id=? AND day=? AND type='RESET'
          )
        ORDER BY datetime
    """, (chat, day, chat, day))

    total_in = total_out = 0
    usdt, inr = [], []

    for tm, t, a, n in cur.fetchall():
        if t == "IN":
            total_in += a
            usdt.append(f"{tm} {a} U - {n}")
        elif t == "OUT":
            total_out += a
            inr.append(f"{tm} ₹{a} - {n}")

    converted = total_in * rate
    bal_inr = converted - total_out
    bal_usdt = bal_inr / rate if rate else 0

    msg = (
        "📊 LIVE LEDGER (POST RESET)\n\n"
        "USDT IN:\n" + ("\n".join(usdt) if usdt else "—") +
        "\n\nINR OUT:\n" + ("\n".join(inr) if inr else "—") +
        f"\n\nRate: {rate}\n"
        f"Balance INR: ₹{bal_inr}\n"
        f"Balance USDT: {round(bal_usdt,2)}"
    )
    await update.message.reply_text(msg)

# ================= RESET =================
async def reset_cmd(update, context):
    save_last_group(update)
    if not is_admin(update):
        return await update.message.reply_text(ACCESS_DENIED)

    cur.execute(
        "INSERT INTO ledger VALUES(NULL,?,?,?,?,?,?,?)",
        (cid(update), today(), "RESET", 0, "Ledger reset", now(), now_full())
    )
    db.commit()
    await update.message.reply_text("♻ Ledger reset recorded")

# ================= PDF (FIXED – FULL 24 HRS MASTER) =================
async def generate_pdf(chat_id, send_func):
    filename = f"ledger_{chat_id}_{today()}.pdf"
    c = canvas.Canvas(filename, pagesize=A4)
    y = 800

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "FULL DAY MASTER LEDGER (24 HOURS)")
    y -= 25
    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Date: {today()}")
    y -= 30

    cur.execute("""
        SELECT day, time, type, amount, note
        FROM ledger
        WHERE chat_id=? AND day=?
        ORDER BY datetime
    """, (chat_id, today()))

    for d, tm, t, a, n in cur.fetchall():
        if t == "RESET":
            c.setFont("Helvetica-Bold", 10)
            line = f"{d} {tm} === RESET ==="
        else:
            c.setFont("Helvetica", 10)
            line = f"{d} {tm} {t} {a} | {n}"

        c.drawString(50, y, line)
        y -= 14

        if y < 60:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = 800

    c.save()

    # 🔥 FORCE REAL PDF DELIVERY (FIX WORD ISSUE)
    with open(filename, "rb") as f:
        await send_func(
            document=f,
            filename=os.path.basename(filename)
        )

    os.remove(filename)

async def pdf_cmd(update, context):
    if not is_admin(update):
        return await update.message.reply_text(ACCESS_DENIED)
    await generate_pdf(cid(update), update.message.reply_document)

# ================= AUTO DAILY PDF (23:59) =================
async def daily_pdf_job(context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT DISTINCT chat_id FROM admins")
    chats = [r[0] for r in cur.fetchall()]
    for chat_id in chats:
        await generate_pdf(
            chat_id,
            lambda document, cid=chat_id: context.bot.send_document(
                chat_id=cid,
                document=document
            )
        )

# ================= CALCULATOR =================
async def calculator(update, context):
    text = update.message.text.strip()
    if text.startswith("/") or not re.fullmatch(r"[0-9\.\+\-\*\/\(\)\^ ]+", text):
        return
    await update.message.reply_text(str(eval(text.replace("^", "**"))))

# ================= MAIN =================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rate", rate_cmd))
    app.add_handler(CommandHandler("in", in_cmd))
    app.add_handler(CommandHandler("out", out_cmd))
    app.add_handler(CommandHandler("statement", statement))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("pdf", pdf_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, calculator))

    app.job_queue.run_daily(
        daily_pdf_job,
        time=time(hour=23, minute=59)
    )

    print("✅ Ledger bot running")
    app.run_polling()

if __name__ == "__main__":
    main()
