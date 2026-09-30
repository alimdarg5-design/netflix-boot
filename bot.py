import os
import re
import asyncio
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.request import HTTPXRequest

# ════════════════════════════════════════════════════════════════
#  CONFIG  —  Railway Variables se load hota hai
# ════════════════════════════════════════════════════════════════
BOT_TOKEN       = os.environ.get("BOT_TOKEN", "")
GITHUB_REPO     = os.environ.get("GITHUB_REPO", "alimdarg5-design/netflix-boot")
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
ACCOUNTS_FOLDER = os.environ.get("ACCOUNTS_FOLDER", "netflix_accounts")
PROXY_URL       = os.environ.get("PROXY_URL", "")

# ── Branding ─────────────────────────────────────────────────────
DEVELOPER = "Abubakar"
BOT_NAME  = "🎬 Netflix VIP Bot"
VIP_TAG   = "⭐ VIP"
DIVIDER   = "━━━━━━━━━━━━━━━━━━━━━━━"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════
#  IN-MEMORY STATE
# ════════════════════════════════════════════════════════════════
user_state:  dict[int, dict] = {}   # per-user session
used_files:  set[str]        = set() # files served this process run


# ════════════════════════════════════════════════════════════════
#  GITHUB API HELPERS
# ════════════════════════════════════════════════════════════════
def _gh_headers() -> dict:
    h = {
        "User-Agent": "NetflixVIPBot/2.0",
        "Accept":     "application/vnd.github.v3+json",
    }
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def fetch_accounts() -> list[dict]:
    """
    GitHub API se LIVE accounts list fetch karta hai.
    Sirf ACCOUNTS_FOLDER ko scan karta hai — container ke local files ignore.
    """
    if not GITHUB_REPO:
        return []

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{ACCOUNTS_FOLDER}"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=_gh_headers())
            if resp.status_code == 401:
                # Token invalid — try anonymous
                resp = client.get(url, headers={"User-Agent": "NetflixVIPBot/2.0"})

            if resp.status_code == 200:
                return [
                    {
                        "name":         item["name"],
                        "download_url": item["download_url"],
                        "sha":          item["sha"],
                    }
                    for item in resp.json()
                    if item.get("name", "").endswith(".txt")
                    and item["name"] not in used_files
                ]
            elif resp.status_code == 404:
                log.warning(f"Folder '{ACCOUNTS_FOLDER}' GitHub par nahi mila (empty or not created).")
            else:
                log.warning(f"GitHub API: {resp.status_code} — {resp.text[:120]}")
    except Exception as e:
        log.error(f"GitHub fetch error: {e}")
    return []


def download_file(url: str) -> str | None:
    """GitHub raw file text download karta hai."""
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers={"User-Agent": "NetflixVIPBot/2.0"})
            if resp.status_code == 200:
                return resp.text
    except Exception as e:
        log.error(f"Download error: {e}")
    return None


def github_delete(filename: str, sha: str) -> bool:
    """Account file ko GitHub se permanently delete karta hai (auto-cleanup)."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        log.warning("GITHUB_TOKEN nahi hai — auto-delete disabled.")
        return False

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{ACCOUNTS_FOLDER}/{filename}"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.request(
                "DELETE", url,
                headers=_gh_headers(),
                json={"message": f"🤖 Auto-removed used account: {filename}", "sha": sha},
            )
            if resp.status_code in (200, 204):
                log.info(f"✅ GitHub se delete: {filename}")
                return True
            log.error(f"Delete failed {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.error(f"Delete error: {e}")
    return False


# ════════════════════════════════════════════════════════════════
#  ACCOUNT PARSER
# ════════════════════════════════════════════════════════════════
def parse_account(text: str, filename: str) -> dict | None:
    """Account .txt se login URLs aur metadata extract karta hai."""
    pc_m  = re.search(r"(?:💻\s*)?PC\s*(?:Login|Link)?\s*[:=\-]?\s*(https?://\S+)",     text, re.I)
    mob_m = re.search(r"(?:📱\s*)?Mobile\s*(?:Login|Link)?\s*[:=\-]?\s*(https?://\S+)", text, re.I)
    tv_m  = re.search(r"(?:📺\s*)?TV\s*(?:Login|Link)?\s*[:=\-]?\s*(https?://\S+)",     text, re.I)

    pc_url  = pc_m.group(1).strip()  if pc_m  else None
    mob_url = mob_m.group(1).strip() if mob_m else None
    tv_url  = tv_m.group(1).strip()  if tv_m  else None

    # Fallback: any URLs in file
    if not any([pc_url, mob_url, tv_url]):
        all_urls = re.findall(r"(https?://\S+)", text)
        for u in all_urls:
            u = u.strip()
            if   ("tv8" in u or "/tv" in u)             and not tv_url:  tv_url  = u
            elif ("unsupported" in u or "mobile" in u)  and not mob_url: mob_url = u
            elif "browse" in u                           and not pc_url:  pc_url  = u
        if not any([pc_url, mob_url, tv_url]) and all_urls:
            pc_url  = all_urls[0]
            mob_url = all_urls[1] if len(all_urls) > 1 else None
            tv_url  = all_urls[2] if len(all_urls) > 2 else None

    if not any([pc_url, mob_url, tv_url]):
        return None

    title_m = re.search(r"PREMIUM ACCOUNT #(\d+)", text, re.I)
    plan_m  = re.search(r"Plan:\s*(.+)",            text, re.I)
    email_m = re.search(r"Email:\s*(.+)",           text, re.I)

    return {
        "title":   f"Account #{title_m.group(1)}" if title_m else filename.replace(".txt", "").replace("_", " "),
        "plan":    plan_m.group(1).strip()         if plan_m  else "Premium",
        "email":   email_m.group(1).strip()        if email_m else "Hidden",
        "pc_url":  pc_url,
        "mob_url": mob_url,
        "tv_url":  tv_url,
    }


# ════════════════════════════════════════════════════════════════
#  UI UTILITIES
# ════════════════════════════════════════════════════════════════
def footer() -> str:
    return f"\n\n{DIVIDER}\n🛡 *{BOT_NAME}*\n👨‍💻 *Dev:* `{DEVELOPER}`"


def get_state(user_id: int) -> dict:
    if user_id not in user_state:
        user_state[user_id] = {"waiting_status": False}
    return user_state[user_id]


async def animate(bot, chat_id: int, frames: list[str], delay: float = 0.45) -> int:
    """Typewriter-style animated message. Returns message_id."""
    msg = await bot.send_message(chat_id=chat_id, text=frames[0], parse_mode="Markdown")
    for frame in frames[1:]:
        await asyncio.sleep(delay)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg.message_id,
                text=frame, parse_mode="Markdown",
            )
        except Exception:
            pass
    return msg.message_id


# ════════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    chat_id = update.effective_chat.id
    state   = get_state(user.id)
    state["waiting_status"] = False

    # Startup animation
    await animate(ctx.bot, chat_id, [
        f"💎 *{BOT_NAME}*\n\n`⏳ Loading   .`",
        f"💎 *{BOT_NAME}*\n\n`⏳ Loading   ..`",
        f"💎 *{BOT_NAME}*\n\n`⏳ Loading   ...`",
        f"💎 *{BOT_NAME}*\n\n✅ *System Online!*\n👨‍💻 *Dev:* `{DEVELOPER}`",
    ])

    # Live stock check
    accounts = fetch_accounts()
    stock    = len(accounts)

    if stock == 0:
        await update.message.reply_text(
            f"😔 *Abhi koi account available nahi hai!*\n\n"
            f"📦 *Stock:* `0`\n\n"
            f"🔔 Jaldi nayi files add hongi — thoda sa intezaar karein."
            + footer(),
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        f"👋 *Salam {user.first_name}!*\n\n"
        f"🎬 *{VIP_TAG} Netflix Bot mein Khush Aamdeed!*\n\n"
        f"{DIVIDER}\n"
        f"📦 *Available Stock:* `{stock}` VIP account(s)\n"
        f"{DIVIDER}\n\n"
        f"⬇️ Neeche button dabao aur apna Netflix VIP account hasil karo!\n\n"
        f"💡 _Tip: Har account ke baad Working / Not Working zaroor batao_"
        + footer(),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🎁 Generate VIP Account", callback_data="generate")]]
        ),
    )


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in user_state:
        del user_state[user.id]
    stock = len(fetch_accounts())
    await update.message.reply_text(
        f"🔄 *Session reset ho gaya!*\n\n"
        f"📦 *Current Stock:* `{stock}` account(s)\n\n"
        f"/start dabao dobara shuru karne ke liye."
        + footer(),
        parse_mode="Markdown",
    )


async def cmd_debug(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    accounts = fetch_accounts()
    await update.message.reply_text(
        f"🛠 *Live Debug Report*\n\n"
        f"📁 *Source:* `GitHub API (Real-time)`\n"
        f"📦 *Repo:* `{GITHUB_REPO}`\n"
        f"📂 *Folder:* `{ACCOUNTS_FOLDER}`\n"
        f"🔑 *Token:* `{'✅ Configured' if GITHUB_TOKEN else '⚠️  Missing'}`\n"
        f"📊 *Live Stock:* `{len(accounts)}`\n"
        f"🚫 *Used (session):* `{len(used_files)}`"
        + footer(),
        parse_mode="Markdown",
    )


# ════════════════════════════════════════════════════════════════
#  CALLBACK: GENERATE
# ════════════════════════════════════════════════════════════════
async def cb_generate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()

    user    = query.from_user
    state   = get_state(user.id)
    bot     = ctx.bot
    chat_id = query.message.chat_id

    # Must give status before next account
    if state.get("waiting_status"):
        await query.edit_message_text(
            f"⏳ *Pehle pichle account ka status dein!*\n\n"
            f"Neeche wale buttons mein se ek dabao:\n"
            f"✅ *Working*  ya  ❌ *Not Working*\n\n"
            f"_Uske baad hi agla account generate hoga._"
            + footer(),
            parse_mode="Markdown",
        )
        return

    # Fetch live accounts
    accounts = fetch_accounts()
    if not accounts:
        await query.edit_message_text(
            f"😢 *Tamam VIP accounts khatam ho gaye!*\n\n"
            f"📦 *Stock:* `0`\n\n"
            f"🔔 Jaldi nayi files add hongi — thoda intezaar karein."
            + footer(),
            parse_mode="Markdown",
        )
        return

    # Generating animation
    anim_id = await animate(bot, chat_id, [
        "⚙️ *Generating*`   .`",
        "⚙️ *Checking Stock...*`   ..`",
        "⚙️ *Fetching VIP Account...*`   ...`",
        f"✨ *{VIP_TAG} Account Ready!*",
    ])

    # Find a valid parseable account
    acc_data  = None
    used_item = None

    for item in accounts:
        raw = download_file(item["download_url"])
        if not raw:
            used_files.add(item["name"])
            continue
        parsed = parse_account(raw, item["name"])
        if parsed:
            acc_data  = parsed
            used_item = item
            break
        else:
            # Corrupt / unreadable file → skip & delete
            used_files.add(item["name"])
            github_delete(item["name"], item["sha"])

    if not acc_data or not used_item:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=anim_id,
            text=(
                "😢 *Koi valid account nahi mila!*\n\n"
                "Files invalid lag rahi hain. Nayi files add hone par retry karein."
                + footer()
            ),
            parse_mode="Markdown",
        )
        return

    # Mark used + permanent GitHub delete
    used_files.add(used_item["name"])
    github_delete(used_item["name"], used_item["sha"])

    remaining = len(fetch_accounts())
    state["waiting_status"] = True

    # Build login buttons
    login_btns: list[list] = []
    if acc_data["pc_url"]:
        login_btns.append([InlineKeyboardButton("💻  PC Login",     url=acc_data["pc_url"])])
    if acc_data["tv_url"]:
        login_btns.append([InlineKeyboardButton("📺  TV Login",     url=acc_data["tv_url"])])
    if acc_data["mob_url"]:
        login_btns.append([InlineKeyboardButton("📱  Mobile Login", url=acc_data["mob_url"])])

    login_btns.append([
        InlineKeyboardButton("✅ Working",     callback_data="status_working"),
        InlineKeyboardButton("❌ Not Working", callback_data="status_notworking"),
    ])

    acc_text = (
        f"🎉 *Netflix VIP Account*\n"
        f"{DIVIDER}\n"
        f"🏷  *Title:* `{acc_data['title']}`\n"
        f"📋  *Plan:*  `{acc_data['plan']}`\n"
        f"📧  *Email:* `{acc_data['email']}`\n"
        f"{DIVIDER}\n\n"
        f"🔐 *Login ke liye neeche button dabao:*\n\n"
        f"📦 *Remaining Stock:* `{remaining}` account(s)"
        + footer()
    )

    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=anim_id,
            text=acc_text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(login_btns),
        )
    except Exception:
        await bot.send_message(
            chat_id=chat_id,
            text=acc_text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(login_btns),
        )


# ════════════════════════════════════════════════════════════════
#  CALLBACK: STATUS FEEDBACK
# ════════════════════════════════════════════════════════════════
async def cb_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user  = query.from_user
    state = get_state(user.id)
    state["waiting_status"] = False

    if query.data == "status_working":
        icon, label, msg = "✅", "Working", "Mubarak ho! Account kaam kar raha hai! 🎊"
    else:
        icon, label, msg = "❌", "Not Working", "Shukria feedback ke liye! Hum fix kar denge."

    remaining = len(fetch_accounts())

    await query.edit_message_text(
        f"{DIVIDER}\n"
        f"{icon} *Status: {label}*\n\n"
        f"💬 {msg}\n\n"
        f"🟢 Ab agla VIP account generate kar sakte ho!\n"
        f"📦 *Remaining Stock:* `{remaining}` account(s)"
        + footer(),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🎁 Generate Next VIP Account", callback_data="generate")]]
        ),
    )


# ════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════
async def main():
    if not BOT_TOKEN:
        log.critical("❌ BOT_TOKEN missing! Railway → Variables mein set karein.")
        return

    builder = Application.builder().token(BOT_TOKEN)

    if PROXY_URL:
        log.info(f"🌐 Proxy active: {PROXY_URL}")
        builder = builder.request(
            HTTPXRequest(
                proxy=PROXY_URL,
                connect_timeout=20.0,
                read_timeout=20.0,
                write_timeout=20.0,
                pool_timeout=20.0,
            )
        )

    app = builder.build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("reset",  cmd_reset))
    app.add_handler(CommandHandler("debug",  cmd_debug))
    app.add_handler(CallbackQueryHandler(cb_generate, pattern="^generate$"))
    app.add_handler(CallbackQueryHandler(cb_status,   pattern="^status_"))

    log.info(f"🚀 {BOT_NAME} — by {DEVELOPER} — ONLINE!")
    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        log.info("✅ Polling active. Press Ctrl+C to stop.")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
