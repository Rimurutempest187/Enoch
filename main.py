import os
import json
import random
import asyncio

import aiosqlite
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# =====================
# LOAD ENV
# =====================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = "database.db"

# =====================
# GAME CONFIG
# =====================

START_COINS = 1000
GACHA_COST = 100

RARITY_RATE = {
    "SSR": 2,
    "SR": 8,
    "R": 30,
    "N": 60
}

# =====================
# LOAD CHARACTERS
# =====================

with open("characters.json", "r", encoding="utf-8") as f:
    CHARACTERS = json.load(f)


# =====================
# DATABASE INIT
# =====================

async def init_db():

    async with aiosqlite.connect(DB_FILE) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            coins INTEGER
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS inventory(
            user_id INTEGER,
            char_id INTEGER,
            count INTEGER,
            PRIMARY KEY(user_id, char_id)
        )
        """)

        await db.commit()


# =====================
# USER SYSTEM
# =====================

async def get_user(uid):

    async with aiosqlite.connect(DB_FILE) as db:

        cur = await db.execute(
            "SELECT coins FROM users WHERE user_id=?",
            (uid,)
        )

        row = await cur.fetchone()

        if not row:

            await db.execute(
                "INSERT INTO users VALUES(?,?)",
                (uid, START_COINS)
            )

            await db.commit()

            return START_COINS

        return row[0]


async def change_coins(uid, amount):

    async with aiosqlite.connect(DB_FILE) as db:

        await db.execute(
            "UPDATE users SET coins = coins + ? WHERE user_id=?",
            (amount, uid)
        )

        await db.commit()


# =====================
# INVENTORY
# =====================

async def add_character(uid, cid):

    async with aiosqlite.connect(DB_FILE) as db:

        await db.execute("""
        INSERT INTO inventory(user_id,char_id,count)
        VALUES(?,?,1)
        ON CONFLICT(user_id,char_id)
        DO UPDATE SET count = count + 1
        """, (uid, cid))

        await db.commit()


async def get_inventory(uid):

    async with aiosqlite.connect(DB_FILE) as db:

        cur = await db.execute("""
        SELECT c.name, c.rarity, i.count
        FROM inventory i
        JOIN (
            SELECT id, name, rarity FROM json_each(?)
        ) AS c
        """, (json.dumps(CHARACTERS),))

        return await cur.fetchall()


# =====================
# GACHA SYSTEM
# =====================

def roll_rarity():

    pool = []

    for r, w in RARITY_RATE.items():
        pool += [r] * w

    return random.choice(pool)


def roll_character(rarity):

    pool = [c for c in CHARACTERS if c["rarity"] == rarity]

    return random.choice(pool)


async def summon(uid):

    await change_coins(uid, -GACHA_COST)

    rarity = roll_rarity()
    char = roll_character(rarity)

    await add_character(uid, char["id"])

    return char


# =====================
# COMMANDS
# =====================

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):

    coins = await get_user(update.effective_user.id)

    await update.message.reply_text(
        f"🎮 Welcome!\n💰 Coins: {coins}\n\n"
        "/summon - Gacha\n"
        "/bal - Balance\n"
        "/inv - Inventory\n"
        "/top - Ranking"
    )


async def summon_cmd(update, ctx):

    uid = update.effective_user.id

    coins = await get_user(uid)

    if coins < GACHA_COST:
        return await update.message.reply_text("❌ Not enough coins")

    char = await summon(uid)

    await update.message.reply_text(
        f"✨ You got:\n"
        f"{char['name']} ({char['rarity']})\n"
        f"{char['anime']}"
    )


async def balance(update, ctx):

    coins = await get_user(update.effective_user.id)

    await update.message.reply_text(f"💰 Coins: {coins}")


async def inventory_cmd(update, ctx):

    uid = update.effective_user.id

    async with aiosqlite.connect(DB_FILE) as db:

        cur = await db.execute("""
        SELECT i.char_id, i.count
        FROM inventory i
        WHERE i.user_id=?
        """, (uid,))

        rows = await cur.fetchall()

    if not rows:
        return await update.message.reply_text("📦 Inventory empty")

    text = "📦 Your Collection\n\n"

    for cid, count in rows:

        char = next(c for c in CHARACTERS if c["id"] == cid)

        text += f"{char['name']} ({char['rarity']}) x{count}\n"

    await update.message.reply_text(text)


async def ranking(update, ctx):

    async with aiosqlite.connect(DB_FILE) as db:

        cur = await db.execute("""
        SELECT user_id, SUM(count) total
        FROM inventory
        GROUP BY user_id
        ORDER BY total DESC
        LIMIT 10
        """)

        rows = await cur.fetchall()

    text = "🏆 Top Players\n\n"

    for i, r in enumerate(rows, 1):
        text += f"{i}. {r[0]} → {r[1]} chars\n"

    await update.message.reply_text(text)


# =====================
# MAIN
# =====================

async def main():

    await init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("summon", summon_cmd))
    app.add_handler(CommandHandler("bal", balance))
    app.add_handler(CommandHandler("inv", inventory_cmd))
    app.add_handler(CommandHandler("top", ranking))

    print("✅ Bot Running")

    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
