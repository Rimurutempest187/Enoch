# main.py  (updated — allows plain-text triggers + scheduled auto-post)
import os
import json
import random
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Set

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from dotenv import load_dotenv
import config

# -------------------------
# Load .env
# -------------------------
load_dotenv()

# -------------------------
# Logging
# -------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("ChurchBot")

# -------------------------
# Files / paths
# -------------------------
DATA_DIR = getattr(config, "DATA_DIR", "data")
USERS_FILE = getattr(config, "USERS_FILE", f"{DATA_DIR}/users.json")
QUIZZES_FILE = getattr(config, "QUIZZES_FILE", f"{DATA_DIR}/quizzes.json")
EVENTS_FILE = getattr(config, "EVENTS_FILE", f"{DATA_DIR}/events.json")
VERSES_FILE = getattr(config, "VERSES_FILE", f"{DATA_DIR}/verses.json")
ADMIN_FILE = f"{DATA_DIR}/admins.json"
GROUPS_FILE = f"{DATA_DIR}/groups.json"  # optional if you want to persist group IDs

# -------------------------
# Ensure folders & files
# -------------------------
def ensure_paths():
    Path(DATA_DIR).mkdir(exist_ok=True)
    Path(getattr(config, "MEDIA_PDFS", f"{DATA_DIR}/pdfs")).mkdir(parents=True, exist_ok=True)
    Path(getattr(config, "MEDIA_AUDIO", f"{DATA_DIR}/audio")).mkdir(parents=True, exist_ok=True)
    Path(getattr(config, "MEDIA_IMAGES", f"{DATA_DIR}/images")).mkdir(parents=True, exist_ok=True)

    def create_file(path, default):
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)

    create_file(USERS_FILE, {})
    create_file(QUIZZES_FILE, [])
    create_file(EVENTS_FILE, [])
    create_file(VERSES_FILE, [])
    create_file(ADMIN_FILE, [])        # list of extra admins
    create_file(GROUPS_FILE, [])       # optional persistent group list

ensure_paths()

# -------------------------
# JSON helpers
# -------------------------
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Load failed (%s): %s", path, e)
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# -------------------------
# Admin management (in-memory + persistent)
# -------------------------
def load_admins() -> Set[int]:
    base = getattr(config, "ADMIN_IDS", [])
    extra = load_json(ADMIN_FILE, [])
    try:
        extra_ints = [int(x) for x in extra]
    except Exception:
        extra_ints = []
    return set([int(x) for x in base] + extra_ints)

ADMINS: Set[int] = load_admins()

def persist_admins():
    base = set(getattr(config, "ADMIN_IDS", []))
    extras = list(sorted(ADMINS - base))
    save_json(ADMIN_FILE, extras)

def is_admin(uid: int) -> bool:
    return int(uid) in ADMINS

# -------------------------
# User system
# -------------------------
def add_user(uid: int, username: str = None, name: str = None):
    users = load_json(USERS_FILE, {})
    uid_s = str(uid)
    if uid_s not in users:
        users[uid_s] = {
            "username": username,
            "full_name": name,
            "quiz_score": 0,
            "prayer_requests": [],
            "first_seen": datetime.utcnow().isoformat(),
        }
    else:
        users[uid_s]["username"] = username
        users[uid_s]["full_name"] = name
    save_json(USERS_FILE, users)

def get_users_list() -> List[int]:
    users = load_json(USERS_FILE, {})
    return [int(k) for k in users.keys()]

# -------------------------
# Optional: persist group ids (if you want)
# -------------------------
def load_saved_groups() -> List[int]:
    groups = load_json(GROUPS_FILE, [])
    try:
        return [int(x) for x in groups]
    except Exception:
        return []

def save_group(gid: int):
    groups = load_saved_groups()
    if gid not in groups:
        groups.append(gid)
        save_json(GROUPS_FILE, groups)

# -------------------------
# Broadcast helpers
# -------------------------
async def broadcast_to_groups(bot, message: str, groups: List[int] = None):
    if groups is None:
        groups = getattr(config, "GROUP_IDS", []) or []
        groups = list(dict.fromkeys(groups + load_saved_groups()))
    success = 0
    failed = 0
    for gid in groups:
        try:
            await bot.send_message(chat_id=gid, text=message)
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logger.warning("Broadcast failed to %s: %s", gid, e)
    return success, failed

async def broadcast_to_users(bot, message: str):
    user_ids = get_users_list()
    success = 0
    failed = 0
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=message)
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logger.warning("Failed to send DM to %s: %s", uid, e)
    return success, failed

# -------------------------
# COMMANDS (same as before)
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    name = f"{u.first_name or ''} {u.last_name or ''}".strip()
    add_user(u.id, u.username, name)

    # if in a group, save group id optionally
    if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
        save_group(update.effective_chat.id)

    msg = (
        "🙌 Welcome!\n\n"
        "This is Church Community Bot.\n"
        "Type /cmd to see commands."
    )
    await update.message.reply_text(msg)

async def cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
"/start - Register\n"
"/cmd - All commands\n"
"/verse - Random verse\n"
"/prayer <text> - Prayer\n"
"/events - Events\n"
"/quiz - Quiz\n"
"/answer <A/B/C/D> - Answer\n"
"/tops - Ranking\n"
"/daily_inspiration - Daily Word\n"
"/myid - Show your Telegram ID\n"
"/chatid - Show current chat ID\n"
"/broadcast <message> - Send to configured groups (Admin)\n"
"/broadcast_users <message> - Send DM to all saved users (Admin)\n"
"/addadmin <user_id> - Add admin (Admin)\n"
"/listadmins - Show admin list (Admin)\n"
"/deladmin <user_id> - Remove admin (Admin)\n"
    )
    await update.message.reply_text(text)

async def verse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_json(VERSES_FILE, [])
    if not data:
        await update.message.reply_text("No verses yet.")
        return
    await update.message.reply_text("📖 " + random.choice(data))

async def prayer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Use: /prayer <text>")
        return
    u = update.effective_user
    add_user(u.id, u.username, u.first_name)
    users = load_json(USERS_FILE, {})
    uid = str(u.id)
    text = " ".join(context.args)
    users[uid]["prayer_requests"].append({
        "text": text,
        "time": datetime.utcnow().isoformat()
    })
    save_json(USERS_FILE, users)
    await update.message.reply_text("🙏 Prayer saved.")

async def events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_json(EVENTS_FILE, [])
    if not data:
        await update.message.reply_text("No events.")
        return
    msg = "🗓 EVENTS\n\n"
    for e in data:
        msg += f"{e.get('name')} - {e.get('time')}\n"
    await update.message.reply_text(msg)

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_json(QUIZZES_FILE, [])
    if not data:
        await update.message.reply_text("No quiz.")
        return
    q = random.choice(data)
    context.user_data["answer"] = q["answer"]
    msg = f"❓ {q['question']}\n\n"
    for c in q["choices"]:
        msg += c + "\n"
    msg += "\nReply: /answer A/B/C/D"
    await update.message.reply_text(msg)

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "answer" not in context.user_data:
        await update.message.reply_text("Start quiz first.")
        return
    if not context.args:
        await update.message.reply_text("Use: /answer A")
        return
    user_ans = context.args[0].upper()
    correct = context.user_data["answer"].upper()
    u = update.effective_user
    users = load_json(USERS_FILE, {})
    uid = str(u.id)
    if user_ans == correct:
        users[uid]["quiz_score"] += 1
        save_json(USERS_FILE, users)
        await update.message.reply_text(
            f"✅ Correct! Score: {users[uid]['quiz_score']}"
        )
    else:
        await update.message.reply_text(
            f"❌ Wrong. Correct: {correct}"
        )

async def tops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_json(USERS_FILE, {})
    if not users:
        await update.message.reply_text("No data.")
        return
    rank = []
    for u, d in users.items():
        name = d.get("username") or d.get("full_name") or "Unknown"
        rank.append((name, d.get("quiz_score", 0)))
    rank.sort(key=lambda x: x[1], reverse=True)
    msg = "🏆 TOP PLAYERS\n\n"
    for i, (n, s) in enumerate(rank[:10], 1):
        msg += f"{i}. {n} — {s}\n"
    await update.message.reply_text(msg)

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = [
        "Trust in the Lord. 🙏",
        "God is with you. ✨",
        "Keep praying. 💙",
        "Faith over fear. 🌟",
        "Jesus loves you. ❤️",
    ]
    await update.message.reply_text(random.choice(data))

# -------------------------
# ID & Admin commands
# -------------------------
async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username
    text = f"🆔 Your ID: {uid}\n👤 Username: @{uname}" if uname else f"🆔 Your ID: {uid}"
    await update.message.reply_text(text)

async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    ctype = update.effective_chat.type
    await update.message.reply_text(f"🆔 Chat ID: {cid}\n📌 Type: {ctype}")

async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized.")
        return

    target = None
    if context.args:
        try:
            target = int(context.args[0])
        except Exception:
            await update.message.reply_text("❌ Invalid ID format.")
            return
    elif update.message.reply_to_message:
        target = update.message.reply_to_message.from_user.id
    else:
        await update.message.reply_text("Usage: /addadmin <user_id>  OR reply to a user's message with /addadmin")
        return

    if target in ADMINS:
        await update.message.reply_text("⚠️ Already admin.")
        return

    ADMINS.add(int(target))
    persist_admins()
    await update.message.reply_text(f"✅ Added admin: {target}")

async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    txt = "Admins:\n" + "\n".join(str(x) for x in sorted(ADMINS))
    await update.message.reply_text(txt)

async def deladmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /deladmin <user_id>")
        return
    try:
        target = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ Invalid ID.")
        return

    base = set(getattr(config, "ADMIN_IDS", []))
    if target in base:
        await update.message.reply_text("❌ Cannot remove owner defined in config.py.")
        return

    if target not in ADMINS:
        await update.message.reply_text("⚠️ Not an admin.")
        return

    ADMINS.remove(target)
    persist_admins()
    await update.message.reply_text(f"✅ Removed admin: {target}")

# -------------------------
# Broadcast commands
# -------------------------
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    message = " ".join(context.args)
    ok, fail = await broadcast_to_groups(context.bot, message)
    await update.message.reply_text(f"✅ Broadcast to groups: Sent {ok}, Failed {fail}")

async def broadcast_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast_users <message>")
        return
    message = " ".join(context.args)
    ok, fail = await broadcast_to_users(context.bot, message)
    await update.message.reply_text(f"✅ Broadcast to users: Sent {ok}, Failed {fail}")

# -------------------------
# Error handler
# -------------------------
async def error_handler(update, context):
    logger.error("Exception while handling an update:", exc_info=context.error)

# -------------------------
# Plain-text listener (handles messages without slash commands)
# -------------------------
async def text_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    lower = text.lower()

    # save user and optionally group
    u = update.effective_user
    add_user(u.id, u.username, u.first_name)
    if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
        save_group(update.effective_chat.id)

    # prayer: "prayer ..." or "pray ..."
    if lower.startswith("prayer ") or lower.startswith("pray "):
        # emulate /prayer <text>
        # set context.args and call the handler
        context.args = text.split()[1:]
        await prayer(update, context)
        return

    # verse: user types "verse"
    if lower == "verse" or lower == "v":
        await verse(update, context)
        return

    # events
    if lower == "events":
        await events(update, context)
        return

    # quiz
    if lower == "quiz":
        await quiz(update, context)
        return

    # answer (e.g. "answer A" or just "a")
    tokens = lower.split()
    if tokens and tokens[0] in ("a", "b", "c", "d", "answer"):
        if tokens[0] == "answer" and len(tokens) >= 2:
            context.args = [tokens[1]]
            await answer(update, context)
            return
        elif tokens[0] in ("a","b","c","d"):
            context.args = [tokens[0].upper()]
            await answer(update, context)
            return

    # tops / ranking
    if lower in ("tops", "ranking"):
        await tops(update, context)
        return

    # daily inspiration: "daily" or "inspire"
    if lower in ("daily", "daily inspiration", "inspire"):
        await daily(update, context)
        return

    # Admin quick broadcast using "broadcast: message" (must be admin)
    if lower.startswith("broadcast:") or lower.startswith("broadcast «") or lower.startswith("broadcast "):
        # only allow when admin
        if not is_admin(u.id):
            await update.message.reply_text("❌ Not authorized for quick broadcast.")
            return
        # extract content after colon or space
        parts = text.split(":", 1)
        if len(parts) == 2:
            msg = parts[1].strip()
        else:
            msg = text.split(None, 1)[1] if len(text.split(None,1))>1 else ""
        if not msg:
            await update.message.reply_text("Usage: broadcast: Your message here")
            return
        ok, fail = await broadcast_to_groups(context.bot, msg)
        await update.message.reply_text(f"✅ Broadcast to groups: Sent {ok}, Failed {fail}")
        return

    # otherwise: ignore / or you can add more triggers here

# -------------------------
# Scheduled jobs (auto send)
# -------------------------
async def scheduled_daily_inspiration(context: ContextTypes.DEFAULT_TYPE):
    """job callback for daily inspiration"""
    data = [
        "Trust in the Lord. 🙏",
        "God is with you. ✨",
        "Keep praying. 💙",
        "Faith over fear. 🌟",
        "Jesus loves you. ❤️",
    ]
    message = random.choice(data)
    await broadcast_to_groups(context.bot, "📬 Daily Inspiration:\n\n" + message)

async def scheduled_random_verse(context: ContextTypes.DEFAULT_TYPE):
    data = load_json(VERSES_FILE, [])
    if not data:
        logger.info("No verses to send for scheduled job.")
        return
    message = "📖 " + random.choice(data)
    await broadcast_to_groups(context.bot, message)

def seconds_until(hour: int, minute: int) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()

# -------------------------
# Main
# -------------------------
def main():
    if not getattr(config, "BOT_TOKEN", None):
        raise SystemExit("BOT_TOKEN missing in config.py")

    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # basic commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cmd", cmd))
    app.add_handler(CommandHandler("verse", verse))
    app.add_handler(CommandHandler("prayer", prayer))
    app.add_handler(CommandHandler("events", events))
    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(CommandHandler("answer", answer))
    app.add_handler(CommandHandler("tops", tops))
    app.add_handler(CommandHandler("daily_inspiration", daily))

    # id/admin/group utilities
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("chatid", chatid))

    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("listadmins", listadmins))
    app.add_handler(CommandHandler("deladmin", deladmin))

    # broadcast
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("broadcast_users", broadcast_users_cmd))

    # error handler
    app.add_error_handler(error_handler)

    # Plain-text trigger handler (messages without slash)
    if getattr(config, "AUTO_ENABLE_TEXT_TRIGGERS", True):
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_listener))

    # Scheduled jobs (if enabled in config)
    # DAILY
    if getattr(config, "AUTO_DAILY", False):
        dh = getattr(config, "DAILY_HOUR", 9)
        dm = getattr(config, "DAILY_MINUTE", 0)
        first_seconds = seconds_until(dh, dm)
        # schedule every 24h
        app.job_queue.run_repeating(scheduled_daily_inspiration, interval=24*3600, first=first_seconds)

    # RANDOM VERSE
    if getattr(config, "AUTO_VERSE", False):
        vh = getattr(config, "VERSE_HOUR", 12)
        vm = getattr(config, "VERSE_MINUTE", 0)
        first_seconds = seconds_until(vh, vm)
        app.job_queue.run_repeating(scheduled_random_verse, interval=24*3600, first=first_seconds)

    logger.info("✅ BOT STARTED (with text triggers=%s)", getattr(config, "AUTO_ENABLE_TEXT_TRIGGERS", True))
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
