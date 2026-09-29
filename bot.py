import os
import re
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.request import HTTPXRequest

# ──────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "8701108813:AAEO2ghZYnUxSPzSpIQ6LxBdC04N5ptFqk8")
ACCOUNTS_DIR = Path(__file__).parent / "accounts"   # accounts/ subfolder

PROXY_URL = os.environ.get("PROXY_URL", "")  # Railway: empty = no proxy

# ── Branding ───────────────────────────────────
DEVELOPER    = "Abubakar"
BOT_NAME     = "🎬 Netflix VIP Bot"
VIP_TAG      = "⭐ VIP ⭐"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  STATE
# ──────────────────────────────────────────────
user_state: dict[int, dict] = {}


# ──────────────────────────────────────────────
#  ANIMATION  (typing-style "dots" effect)
# ──────────────────────────────────────────────
async def animate_generating(chat_id: int, bot) -> int:
    """
    Send a 'Generating...' animation message (3 steps) and return its message_id.
    Simulates a typing / loading effect.
    """
    frames = [
        "⚙️ *Generating*`  .`",
        "⚙️ *Generating*`  ..`",
        "⚙️ *Generating*`  ...`",
        f"✨ *{VIP_TAG}  Account Ready!*",
    ]
    msg = await bot.send_message(
        chat_id=chat_id,
        text=frames[0],
        parse_mode="Markdown",
    )
    for frame in frames[1:]:
        await asyncio.sleep(0.55)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg.message_id,
                text=frame,
                parse_mode="Markdown",
            )
        except Exception:
            pass
    await asyncio.sleep(0.4)
    return msg.message_id


def dev_footer() -> str:
    """VIP footer shown on every message."""
    return (
        "\n\n"
        "─────────────────────\n"
        f"🛡 {BOT_NAME}\n"
        f"👨‍💻 *Developed by* `{DEVELOPER}`"
    )


# ──────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────
def load_accounts() -> list[Path]:
    files = sorted(ACCOUNTS_DIR.glob("*.txt"))
    return files


def parse_account(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8", errors="ignore")

    pc_url     = re.search(r"PC Login:\s*\n(https?://\S+)",     text)
    mobile_url = re.search(r"Mobile Login:\s*\n(https?://\S+)", text)
    tv_url     = re.search(r"TV Login:\s*\n(https?://\S+)",     text)

    if not any([pc_url, mobile_url, tv_url]):
        return None

    title_match = re.search(r"PREMIUM ACCOUNT #(\d+)", text)
    plan_match  = re.search(r"Plan:\s*(.+)",  text)
    email_match = re.search(r"Email:\s*(.+)", text)

    title = f"Account #{title_match.group(1)}" if title_match else path.stem

    return {
        "title":      title,
        "plan":       plan_match.group(1).strip()  if plan_match  else "Unknown",
        "email":      email_match.group(1).strip() if email_match else "Unknown",
        "pc_url":     pc_url.group(1).strip()      if pc_url      else None,
        "mobile_url": mobile_url.group(1).strip()  if mobile_url  else None,
        "tv_url":     tv_url.group(1).strip()      if tv_url      else None,
        "file":       path.name,
    }


def get_user_state(user_id: int) -> dict:
    if user_id not in user_state:
        user_state[user_id] = {
            "queue":          [],
            "index":          0,
            "waiting_status": False,  # True = status click ka intezaar
            "status_msg":     None,
        }
    return user_state[user_id]


# ──────────────────────────────────────────────
#  COMMAND HANDLERS
# ──────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    state = get_user_state(user.id)
    bot   = ctx.bot
    chat_id = update.effective_chat.id

    # ── 1. Animate intro ──────────────────────
    intro_frames = [
        f"💎 *{BOT_NAME}*\n\n`Loading`  .",
        f"💎 *{BOT_NAME}*\n\n`Loading`  ..",
        f"💎 *{BOT_NAME}*\n\n`Loading`  ...",
        (
            f"💎 *{BOT_NAME}*\n\n"
            f"✅ *System Ready!*\n\n"
            f"👨‍💻 *Developed by* `{DEVELOPER}`"
        ),
    ]
    intro_msg = await update.message.reply_text(
        intro_frames[0], parse_mode="Markdown"
    )
    for frame in intro_frames[1:]:
        await asyncio.sleep(0.6)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=intro_msg.message_id,
                text=frame,
                parse_mode="Markdown",
            )
        except Exception:
            pass

    await asyncio.sleep(0.8)

    # ── 2. Load queue ─────────────────────────
    files = load_accounts()
    if not files:
        await update.message.reply_text(
            "⚠️ *Koi account file nahi mili!*\n"
            "Bot folder mein `.txt` account files rakhein."
            + dev_footer(),
            parse_mode="Markdown",
        )
        return

    state["queue"]          = files
    state["index"]          = 0
    state["waiting_status"] = False
    state["status_msg"]     = None

    keyboard = [[InlineKeyboardButton("🎁 Generate VIP Account", callback_data="generate")]]
    await update.message.reply_text(
        f"👋 *Assalam-o-Alaikum {user.first_name}!*\n\n"
        f"🎬 {VIP_TAG} *Netflix Bot mein Khush Aamdeed!*\n\n"
        f"🗂 *{len(files)}* VIP account file(s) ready hain.\n\n"
        "⬇️ Neeche button dabayein aur apna Netflix account hasil karein!\n\n"
        "⏱ _Note: Har account ke baad 2 minute wait karna hoga._"
        + dev_footer(),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in user_state:
        del user_state[user.id]
    await update.message.reply_text(
        "🔄 *Queue reset ho gayi!*\n/start dabayein dobara shuru karne ke liye."
        + dev_footer(),
        parse_mode="Markdown",
    )


# ──────────────────────────────────────────────
#  CALLBACK HANDLERS
# ──────────────────────────────────────────────
async def cb_generate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user    = query.from_user
    state   = get_user_state(user.id)
    bot     = ctx.bot
    chat_id = query.message.chat_id

    # ── 1. Check: status feedback ka intezaar hai? ───────
    if state.get("waiting_status", False):
        await query.edit_message_text(
            "⚠️ *Pehle account ka status batayein!*\n\n"
            "Neeche wale message mein\n"
            "✅ *Working* ya ❌ *Not Working* click karein\n\n"
            "_Uske baad agla account generate ho ga._"
            + dev_footer(),
            parse_mode="Markdown",
        )
        return

    # ── 2. Queue check ────────────────────────
    if not state["queue"] or state["index"] >= len(state["queue"]):
        files = load_accounts()
        if not files:
            await query.edit_message_text(
                "😢 *Tamam VIP accounts khatam ho gaye!*\n\n"
                "Jaldi nayi files add ki jayengi."
                + dev_footer(),
                parse_mode="Markdown",
            )
            return
        state["queue"] = files
        state["index"] = 0

    # ── 3. Run animation ──────────────────────
    anim_id = await animate_generating(chat_id, bot)

    # ── 4. Parse account ──────────────────────
    idx  = state["index"]
    path = state["queue"][idx]
    acc  = parse_account(path)

    if acc is None:
        state["index"] += 1
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=anim_id,
                text=f"⚠️ File `{path.name}` parse nahi hui, skip..."
                + dev_footer(),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🎁 Try Again", callback_data="generate")]]
                ),
            )
        except Exception:
            pass
        return

    state["index"]          += 1
    state["waiting_status"]  = True   # status ka intezaar shuru
    state["status_msg"]      = None

    # ── 5. Build login buttons ─────────────────
    login_buttons = []
    if acc["pc_url"]:
        login_buttons.append(
            [InlineKeyboardButton("💻 PC Login", url=acc["pc_url"])]
        )
    if acc["tv_url"]:
        login_buttons.append(
            [InlineKeyboardButton("📺 TV Login", url=acc["tv_url"])]
        )
    if acc["mobile_url"]:
        login_buttons.append(
            [InlineKeyboardButton("📱 Mobile Login", url=acc["mobile_url"])]
        )

    # ── 6. Edit animation msg → account card ──
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=anim_id,
            text=(
                f"🎉 *{VIP_TAG}  {acc['title']} Generated!*\n\n"
                f"📋 *Plan:* `{acc['plan']}`\n"
                f"📧 *Email:* `{acc['email']}`\n\n"
                "🔗 *Login karne ke liye neeche click karein:*"
                + dev_footer()
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(login_buttons),
        )
    except Exception as e:
        log.warning(f"Account card edit error: {e}")

    # ── 7. Send status check message ──────────
    status_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Working",     callback_data=f"status_working_{user.id}"),
            InlineKeyboardButton("❌ Not Working", callback_data=f"status_notworking_{user.id}"),
        ]
    ])

    status_msg = await bot.send_message(
        chat_id=chat_id,
        text=(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📊 *Account Status Check*\n\n"
            "Kya yeh VIP account kaam kar raha hai?\n\n"
            "_Status click karne ke baad agla account generate kar sakte ho!_"
            + dev_footer()
        ),
        parse_mode="Markdown",
        reply_markup=status_keyboard,
    )
    state["status_msg"] = status_msg.message_id


# (countdown task hata diya — ab status click pe next account milega)


# ──────────────────────────────────────────────
#  STATUS CALLBACK
# ──────────────────────────────────────────────
async def cb_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts       = query.data.split("_")
    status_type = parts[1]   # "working" or "notworking"

    if status_type == "working":
        icon = "✅"
        text = "Working"
        msg  = "Badiya! VIP account theek se kaam kar raha hai. 🎉"
    else:
        icon = "❌"
        text = "Not Working"
        msg  = "Shukria feedback ke liye! Hum jald check karenge. 🔧"

    user  = query.from_user
    state = get_user_state(user.id)

    # ── Lock hatao — ab agla account generate ho sakta hai ──
    state["waiting_status"] = False

    left_q = len(state["queue"]) - state["index"]

    await query.edit_message_text(
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{icon} *Status: {text}*\n\n"
        f"{msg}\n\n"
        f"🟢 Ab agla VIP account generate kar sakte ho!\n"
        f"📦 Queue mein baaki: *{left_q}* account(s)"
        + dev_footer(),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🎁 Generate Next VIP Account", callback_data="generate")]]
        ),
    )


# ──────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────
async def async_main():
    builder = Application.builder().token(BOT_TOKEN)

    if PROXY_URL:
        log.info(f"Proxy use ho raha hai: {PROXY_URL}")
        request = HTTPXRequest(
            proxy=PROXY_URL,
            connect_timeout=20.0,
            read_timeout=20.0,
            write_timeout=20.0,
            pool_timeout=20.0,
        )
        builder = builder.request(request)
    else:
        log.info("Direct connection (no proxy)")

    app = builder.build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CallbackQueryHandler(cb_generate, pattern="^generate$"))
    app.add_handler(CallbackQueryHandler(cb_status,   pattern="^status_"))

    log.info(f"{BOT_NAME} — Developed by {DEVELOPER} — shuru ho gaya!")
    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        log.info("Polling shuru... (Ctrl+C se band karein)")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(async_main())
