import os
import json
import random
import asyncio
import datetime

import aiosqlite
from dotenv import load_dotenv

from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,      # <--- Add this
    ContextTypes,
    filters              # <--- Add this too
)

# ======================
# ENV
# ======================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

DB = "database.db"

# ======================
# CONFIG
# ======================

START_COINS = 1000
GACHA_COST = 100

DAILY_REWARD = 200
WEEKLY_REWARD = 1000

DROP_TIME = 60  # seconds

RARITY_RATE = {
    "SSR": 2,
    "SR": 8,
    "R": 30,
    "N": 60
}

# ======================
# LOAD CHARACTERS
# ======================

with open("characters.json", encoding="utf-8") as f:
    CHARS = json.load(f)

# ======================
# DB INIT
# ======================

async def init_db():

    async with aiosqlite.connect(DB) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            coins INTEGER,
            last_daily TEXT,
            last_weekly TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS inventory(
            user_id INTEGER,
            char_id INTEGER,
            count INTEGER,
            PRIMARY KEY(user_id,char_id)
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS admins(
            user_id INTEGER PRIMARY KEY
        )
        """)

        await db.execute("""
        INSERT OR IGNORE INTO admins VALUES(?)
        """,(ADMIN_ID,))

        await db.commit()

# ======================
# HELPERS
# ======================

def today():
    return datetime.date.today().isoformat()


def is_admin(uid):
    return uid == ADMIN_ID


async def get_user(uid):

    async with aiosqlite.connect(DB) as db:

        cur = await db.execute(
            "SELECT coins FROM users WHERE user_id=?",
            (uid,)
        )

        row = await cur.fetchone()

        if not row:

            await db.execute("""
            INSERT INTO users VALUES(?,?,?,?)
            """,(uid,START_COINS,None,None))

            await db.commit()

            return START_COINS

        return row[0]


async def add_coins(uid, amount):

    async with aiosqlite.connect(DB) as db:

        await db.execute(
            "UPDATE users SET coins=coins+? WHERE user_id=?",
            (amount,uid)
        )

        await db.commit()


# ======================
# INVENTORY
# ======================

async def add_char(uid, cid):

    async with aiosqlite.connect(DB) as db:

        await db.execute("""
        INSERT INTO inventory VALUES(?,?,1)
        ON CONFLICT(user_id,char_id)
        DO UPDATE SET count=count+1
        """,(uid,cid))

        await db.commit()


# ======================
# GACHA
# ======================

def roll_rarity():

    pool = []

    for r,w in RARITY_RATE.items():
        pool += [r]*w

    return random.choice(pool)


def roll_char(r):

    pool = [c for c in CHARS if c["rarity"]==r]

    return random.choice(pool)


async def summon(uid):

    await add_coins(uid,-GACHA_COST)

    r = roll_rarity()
    c = roll_char(r)

    await add_char(uid,c["id"])

    return c


# ======================
# IMAGE CARD
# ======================

async def send_card(update,char):

    await update.message.reply_photo(
        photo=char["image"],
        caption=
        f"✨ {char['name']} ({char['rarity']})\n"
        f"📺 {char['anime']}"
    )


# ======================
# COMMANDS
# ======================

async def start(update,ctx):

    coins = await get_user(update.effective_user.id)

    await update.message.reply_text(
        f"🎮 Welcome\n💰 {coins} Coins\n\n"
        "/summon\n/daily\n/weekly\n/bal\n/inv\n/top"
    )


# ======================
# GACHA
# ======================

async def summon_cmd(update,ctx):

    uid = update.effective_user.id

    coins = await get_user(uid)

    if coins < GACHA_COST:
        return await update.message.reply_text("❌ No coins")

    char = await summon(uid)

    await send_card(update,char)


# ======================
# DAILY / WEEKLY
# ======================

async def daily(update,ctx):

    uid = update.effective_user.id

    async with aiosqlite.connect(DB) as db:

        cur = await db.execute(
            "SELECT last_daily FROM users WHERE user_id=?",
            (uid,)
        )

        row = await cur.fetchone()

        if row and row[0]==today():
            return await update.message.reply_text("⏳ Already claimed")

        await db.execute("""
        UPDATE users SET last_daily=? WHERE user_id=?
        """,(today(),uid))

        await db.commit()

    await add_coins(uid,DAILY_REWARD)

    await update.message.reply_text(f"✅ +{DAILY_REWARD} Coins")


async def weekly(update,ctx):

    uid = update.effective_user.id

    async with aiosqlite.connect(DB) as db:

        cur = await db.execute(
            "SELECT last_weekly FROM users WHERE user_id=?",
            (uid,)
        )

        row = await cur.fetchone()

        if row and row[0]==today():
            return await update.message.reply_text("⏳ Already claimed")

        await db.execute("""
        UPDATE users SET last_weekly=? WHERE user_id=?
        """,(today(),uid))

        await db.commit()

    await add_coins(uid,WEEKLY_REWARD)

    await update.message.reply_text(f"✅ +{WEEKLY_REWARD} Coins")


# ======================
# ADMIN
# ======================

async def addcoins(update,ctx):

    uid = update.effective_user.id

    if not is_admin(uid):
        return

    user = int(ctx.args[0])
    amt = int(ctx.args[1])

    await add_coins(user,amt)

    await update.message.reply_text("✅ Coins added")


async def addadmin(update,ctx):

    if not is_admin(update.effective_user.id):
        return

    new = int(ctx.args[0])

    async with aiosqlite.connect(DB) as db:

        await db.execute(
            "INSERT OR IGNORE INTO admins VALUES(?)",
            (new,)
        )

        await db.commit()

    await update.message.reply_text("✅ Admin added")


async def setdrop(update,ctx):

    global DROP_TIME

    if not is_admin(update.effective_user.id):
        return

    DROP_TIME = int(ctx.args[0])

    await update.message.reply_text(f"✅ Drop Time = {DROP_TIME}")


async def store(update,ctx):

    if not is_admin(update.effective_user.id):
        return

    text="🏪 Store\n\n"

    for c in CHARS:
        text+=f"{c['name']} ({c['rarity']})\n"

    await update.message.reply_text(text)


# ======================
# INFO
# ======================

async def bal(update,ctx):

    coins = await get_user(update.effective_user.id)

    await update.message.reply_text(f"💰 {coins} Coins")


async def inv(update,ctx):

    uid = update.effective_user.id

    async with aiosqlite.connect(DB) as db:

        cur = await db.execute("""
        SELECT char_id,count FROM inventory WHERE user_id=?
        """,(uid,))

        rows = await cur.fetchall()

    if not rows:
        return await update.message.reply_text("Empty")

    text="📦 Inventory\n\n"

    for cid,c in rows:

        char = next(x for x in CHARS if x["id"]==cid)

        text+=f"{char['name']} x{c}\n"

    await update.message.reply_text(text)


async def top(update,ctx):

    async with aiosqlite.connect(DB) as db:

        cur = await db.execute("""
        SELECT user_id,SUM(count)
        FROM inventory
        GROUP BY user_id
        ORDER BY 2 DESC
        LIMIT 10
        """)

        rows = await cur.fetchall()

    text="🏆 Ranking\n\n"

    for i,r in enumerate(rows,1):
        text+=f"{i}. {r[0]} → {r[1]}\n"

    await update.message.reply_text(text)

# ======================
# UPLOAD COMMAND WITH TELEGRAM PHOTO
# ======================

UPLOAD_TMP = {}  # Temporarily store upload info until photo is received

async def upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ You are not admin")

    if len(ctx.args) < 4:
        return await update.message.reply_text(
            "Usage:\n/upload <id> <name> <anime> <rarity>\n"
            "Then reply with the character photo."
        )

    try:
        char_id = int(ctx.args[0])
        name = ctx.args[1]
        anime = ctx.args[2]
        rarity = ctx.args[3].upper()

        if rarity not in ["SSR", "SR", "R", "N"]:
            return await update.message.reply_text("❌ Invalid rarity: SSR/SR/R/N")

        # Check if ID already exists
        if any(c["id"] == char_id for c in CHARS):
            return await update.message.reply_text("❌ Character ID already exists")

        # Store temporarily until photo arrives
        UPLOAD_TMP[update.effective_user.id] = {
            "id": char_id,
            "name": name,
            "anime": anime,
            "rarity": rarity
        }

        await update.message.reply_text(
            "✅ Info saved. Now reply with the character photo."
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid not in UPLOAD_TMP:
        return  # Ignore photos not related to upload

    info = UPLOAD_TMP.pop(uid)

    # Save photo locally
    photo_file = await update.message.photo[-1].get_file()
    filename = f"images/{info['id']}.jpg"

    # Make sure images folder exists
    os.makedirs("images", exist_ok=True)

    await photo_file.download_to_drive(filename)

    # Add character to memory
    new_char = {
        "id": info["id"],
        "name": info["name"],
        "anime": info["anime"],
        "rarity": info["rarity"],
        "image": filename
    }
    CHARS.append(new_char)

    # Save to JSON
    with open("characters.json", "w", encoding="utf-8") as f:
        json.dump(CHARS, f, ensure_ascii=False, indent=4)

    # Reply with card
    await update.message.reply_photo(
        photo=filename,
        caption=(
            f"✅ Character Uploaded!\n\n"
            f"ID: {info['id']}\n"
            f"Name: {info['name']}\n"
            f"Anime: {info['anime']}\n"
            f"Rarity: {info['rarity']}"
        )
    )


# ======================
# MAIN
# ======================

async def main():

    await init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("summon",summon_cmd))

    app.add_handler(CommandHandler("daily",daily))
    app.add_handler(CommandHandler("weekly",weekly))

    app.add_handler(CommandHandler("addcoins",addcoins))
    app.add_handler(CommandHandler("addadmin",addadmin))
    app.add_handler(CommandHandler("setdroptime",setdrop))
    app.add_handler(CommandHandler("store",store))

    app.add_handler(CommandHandler("bal",bal))
    app.add_handler(CommandHandler("inv",inv))
    app.add_handler(CommandHandler("top",top))
    app.add_handler(CommandHandler("upload", upload))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    print("✅ Bot Online")

    await app.run_polling()


if __name__=="__main__":
    asyncio.run(main())
