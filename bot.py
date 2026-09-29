import os
import re
import asyncio
import logging
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
BASE_DIR     = Path(__file__).parent
ACCOUNTS_DIR = BASE_DIR / "accounts"
USED_DIR     = BASE_DIR / "used_accounts"

GITHUB_REPO  = os.environ.get("GITHUB_REPO", "alimdarg5-design/netflix-boot")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "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")

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
#  STATE & CACHE
# ──────────────────────────────────────────────
# user_state[user_id] = {"waiting_status": bool}
user_state: dict[int, dict] = {}
# Session-level tracking: Jo accounts use ho chuke hain unka record
used_accounts_cache: set[str] = set()


# ──────────────────────────────────────────────
#  ANIMATION (typing-style loading effect)
# ──────────────────────────────────────────────
async def animate_generating(chat_id: int, bot) -> int:
    frames = [
        "⚙️ *Generating*`  .`",
        "⚙️ *Checking Stock...*`  ..`",
        "⚙️ *Fetching VIP Account...*`  ...`",
        f"✨ *{VIP_TAG}  Account Ready!*",
    ]
    msg = await bot.send_message(
        chat_id=chat_id,
        text=frames[0],
        parse_mode="Markdown",
    )
    for frame in frames[1:]:
        await asyncio.sleep(0.5)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg.message_id,
                text=frame,
                parse_mode="Markdown",
            )
        except Exception:
            pass
    await asyncio.sleep(0.3)
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
#  HELPERS (HYBRID: LOCAL + GITHUB LIVE SCAN)
# ──────────────────────────────────────────────
def fetch_github_accounts_list() -> list[dict]:
    """
    GitHub API se real-time accounts scan karta hai.
    Railway rebuild ka wait kiye baghair live stock mil jata hai.
    """
    if not GITHUB_REPO:
        return []
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/accounts"
    headers = {"User-Agent": "NetflixBot/1.0"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                items = resp.json()
                results = []
                for it in items:
                    name = it.get("name", "")
                    if name.endswith(".txt") and name not in used_accounts_cache:
                        results.append({
                            "source": "github",
                            "name": name,
                            "download_url": it.get("download_url"),
                            "sha": it.get("sha"),
                        })
                return results
            else:
                log.warning(f"GitHub contents fetch response {resp.status_code}")
    except Exception as e:
        log.error(f"GitHub API fetch error: {e}")
    return []


def load_accounts() -> list[dict]:
    """
    Real-time check:
    1. Local container ke accounts/ aur root directory scan karta hai.
    2. GitHub API se bhi scan karta hai (taake agar Railway pe deploy late ho to direct GitHub se mil jaye).
    """
    seen_names = set()
    all_accounts: list[dict] = []

    # 1. Local subfolder check
    if ACCOUNTS_DIR.exists():
        for f in sorted(ACCOUNTS_DIR.glob("*.txt")):
            if f.name not in used_accounts_cache and "used_accounts" not in str(f).lower():
                seen_names.add(f.name)
                all_accounts.append({
                    "source": "local",
                    "path": f,
                    "name": f.name,
                })

    # 2. Local root folder check
    for f in sorted(BASE_DIR.glob("*.txt")):
        if f.name.lower() not in ["requirements.txt", "license.txt", "readme.txt"]:
            if f.name not in used_accounts_cache and f.name not in seen_names:
                seen_names.add(f.name)
                all_accounts.append({
                    "source": "local",
                    "path": f,
                    "name": f.name,
                })

    # 3. GitHub API Live Check (Backup/Direct sync)
    gh_files = fetch_github_accounts_list()
    for gh in gh_files:
        if gh["name"] not in seen_names and gh["name"] not in used_accounts_cache:
            seen_names.add(gh["name"])
            all_accounts.append(gh)

    return all_accounts


def parse_account_text(text: str, filename: str) -> dict | None:
    """Account file ke text se login links aur info extract karta hai."""
    # Matches: PC Login, PC Link, 💻 PC Login, Mobile Login, Mobile Link, TV Login, TV Link
    pc_url     = re.search(r"(?:💻\s*)?PC\s*(?:Login|Link)?\s*[:=\-]?\s*(https?://\S+)", text, re.IGNORECASE)
    mobile_url = re.search(r"(?:📱\s*)?Mobile\s*(?:Login|Link)?\s*[:=\-]?\s*(https?://\S+)", text, re.IGNORECASE)
    tv_url     = re.search(r"(?:📺\s*)?TV\s*(?:Login|Link)?\s*[:=\-]?\s*(https?://\S+)", text, re.IGNORECASE)

    pc_link     = pc_url.group(1).strip()     if pc_url     else None
    mobile_link = mobile_url.group(1).strip() if mobile_url else None
    tv_link     = tv_url.group(1).strip()     if tv_url     else None

    # Fallback: agar specific labels na hon lekin Netflix links hon
    if not any([pc_link, mobile_link, tv_link]):
        urls = re.findall(r"(https?://\S+netflix\.com/\S+)", text, re.IGNORECASE)
        if not urls:
            urls = re.findall(r"(https?://\S+)", text)
        for u in urls:
            u_clean = u.strip()
            if "tv8" in u_clean or "/tv" in u_clean:
                if not tv_link:
                    tv_link = u_clean
            elif "unsupported" in u_clean or "mobile" in u_clean:
                if not mobile_link:
                    mobile_link = u_clean
            elif "browse" in u_clean:
                if not pc_link:
                    pc_link = u_clean

        if not any([pc_link, mobile_link, tv_link]) and urls:
            pc_link     = urls[0]
            mobile_link = urls[1] if len(urls) > 1 else None
            tv_link     = urls[2] if len(urls) > 2 else None

    if not any([pc_link, mobile_link, tv_link]):
        return None

    title_match = re.search(r"PREMIUM ACCOUNT #(\d+)", text, re.IGNORECASE)
    plan_match  = re.search(r"Plan:\s*(.+)",  text, re.IGNORECASE)
    email_match = re.search(r"Email:\s*(.+)", text, re.IGNORECASE)

    title = f"Account #{title_match.group(1)}" if title_match else filename.replace(".txt", "").replace("_", " ")

    return {
        "title":      title,
        "plan":       plan_match.group(1).strip()  if plan_match  else "Standard",
        "email":      email_match.group(1).strip() if email_match else "Unknown",
        "pc_url":     pc_link,
        "mobile_url": mobile_link,
        "tv_url":     tv_link,
        "file":       filename,
    }


def delete_from_github(filename: str, sha: str | None = None) -> bool:
    """GitHub repository se file delete karta hai."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "NetflixBot/1.0",
    }

    candidates = [f"accounts/{filename}", filename]
    for rel_path in candidates:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{rel_path}"
        try:
            with httpx.Client(timeout=10.0) as client:
                target_sha = sha
                if not target_sha:
                    res = client.get(url, headers=headers)
                    if res.status_code == 200:
                        target_sha = res.json().get("sha")

                if target_sha:
                    del_res = client.request(
                        "DELETE",
                        url,
                        headers=headers,
                        json={
                            "message": f"🤖 Auto-delete used account: {filename}",
                            "sha": target_sha,
                        },
                    )
                    if del_res.status_code in [200, 204]:
                        log.info(f"✅ GitHub se file auto-delete ho gayi: {rel_path}")
                        return True
        except Exception as e:
            log.error(f"GitHub delete error: {e}")
    return False


def delete_account_file(item: dict):
    """File generate hone ke baad local aur GitHub dono se remove karta hai."""
    name = item["name"]
    used_accounts_cache.add(name)

    # 1. Delete from GitHub
    delete_from_github(name, item.get("sha"))

    # 2. Agar local file hai to used_accounts/ mein move karein
    if item.get("source") == "local":
        path: Path = item["path"]
        try:
            import shutil
            USED_DIR.mkdir(parents=True, exist_ok=True)
            dest = USED_DIR / path.name
            if path.exists():
                shutil.move(str(path), str(dest))
                log.info(f"✅ File moved to used_accounts: {path.name}")
        except Exception as e:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass


def get_user_state(user_id: int) -> dict:
    if user_id not in user_state:
        user_state[user_id] = {
            "waiting_status": False,
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
        await asyncio.sleep(0.5)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=intro_msg.message_id,
                text=frame,
                parse_mode="Markdown",
            )
        except Exception:
            pass

    await asyncio.sleep(0.5)

    # ── 2. Real-time file count ───────────────
    files = load_accounts()
    stock = len(files)
    state["waiting_status"] = False

    if stock == 0:
        await update.message.reply_text(
            "⚠️ *Filhal koi account available nahi hai!*\n\n"
            "📦 *Available Stock:* `0`\n"
            "Jald nayi accounts upload kiye jayenge."
            + dev_footer(),
            parse_mode="Markdown",
        )
        return

    keyboard = [[InlineKeyboardButton("🎁 Generate VIP Account", callback_data="generate")]]
    await update.message.reply_text(
        f"👋 *Assalam-o-Alaikum {user.first_name}!*\n\n"
        f"🎬 {VIP_TAG} *Netflix Bot mein Khush Aamdeed!*\n\n"
        f"📦 *Total Stock:* *{stock}* VIP account file(s) available hain.\n\n"
        "⬇️ Neeche button dabayein aur apna Netflix account hasil karein!\n\n"
        "💡 _Note: Har account ke baad Working / Not Working status batana zaroori hai agla account lene ke liye._"
        + dev_footer(),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in user_state:
        del user_state[user.id]
    stock = len(load_accounts())
    await update.message.reply_text(
        f"🔄 *System reset ho gaya!*\n\n"
        f"📦 *Current Stock:* *{stock}* file(s)\n"
        "/start dabayein dobara shuru karne ke liye."
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

    # ── 1. Check: Pehle status feedback ka intezaar hai? ──
    if state.get("waiting_status", False):
        await query.edit_message_text(
            "⚠️ *Pehle pichlay account ka status batayein!*\n\n"
            "Neeche wale message mein\n"
            "✅ *Working* ya ❌ *Not Working* click karein.\n\n"
            "_Uske baad agla VIP account generate ho sakega._"
            + dev_footer(),
            parse_mode="Markdown",
        )
        return

    # ── 2. Real-time file check ────────────────────────
    files = load_accounts()
    if not files:
        await query.edit_message_text(
            "😢 *Tamam VIP accounts khatam ho gaye!*\n\n"
            "📦 *Available Stock:* `0`\n\n"
            "Jaldi nayi files add ki jayengi, thora intezaar karein."
            + dev_footer(),
            parse_mode="Markdown",
        )
        return

    # ── 3. Run animation ──────────────────────────────
    anim_id = await animate_generating(chat_id, bot)

    # ── 4. Find valid account & Auto-delete ─────────────
    acc = None
    target_item = None

    while files:
        candidate = files.pop(0)
        # Fetch file text (local ya github)
        text_content = ""
        if candidate.get("source") == "local":
            try:
                text_content = candidate["path"].read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                log.error(f"Local read error: {e}")
        elif candidate.get("source") == "github":
            try:
                dl_url = candidate.get("download_url")
                if dl_url:
                    with httpx.Client(timeout=10.0) as client:
                        resp = client.get(dl_url)
                        if resp.status_code == 200:
                            text_content = resp.text
            except Exception as e:
                log.error(f"GitHub fetch error: {e}")

        if text_content:
            parsed = parse_account_text(text_content, candidate["name"])
            if parsed:
                acc = parsed
                target_item = candidate
                break

        # Agar corrupt/invalid hai to remove karein
        delete_account_file(candidate)

    if not acc or not target_item:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=anim_id,
            text=(
                "😢 *Tamam accounts khatam ya invalid niklay!*\n\n"
                "Nayi files add hote hi dobara try karein."
                + dev_footer()
            ),
            parse_mode="Markdown",
        )
        return

    # Delete the used file immediately so it NEVER repeats!
    delete_account_file(target_item)

    # Real-time stock count remaining after this generation
    remaining_stock = len(load_accounts())

    # Set waiting status for this user
    state["waiting_status"] = True

    # ── 5. Build login buttons ─────────────────────────
    login_buttons = []
    if acc["pc_url"]:
        login_buttons.append([InlineKeyboardButton("💻 PC Login", url=acc["pc_url"])])
    if acc["tv_url"]:
        login_buttons.append([InlineKeyboardButton("📺 TV Login", url=acc["tv_url"])])
    if acc["mobile_url"]:
        login_buttons.append([InlineKeyboardButton("📱 Mobile Login", url=acc["mobile_url"])])

    # ── 6. Send Account Card with Stock Info ───────────
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=anim_id,
            text=(
                f"🎉 *{VIP_TAG}  {acc['title']} Generated!*\n\n"
                f"📦 *Peche Baaki Files (Stock):* `{remaining_stock}` file(s)\n"
                f"📁 *Processed File:* `{acc['file']}`\n\n"
                f"📋 *Plan:* `{acc['plan']}`\n"
                f"📧 *Email:* `{acc['email']}`\n\n"
                "🔗 *Login karne ke liye neeche button per click karein:*\n\n"
                "🌐 _Tip: Agar link Telegram ke andar open ho, to upar 3 dots dabakar 'Open in Chrome' karein ya Telegram Settings se In-App Browser OFF kar dein._"
                + dev_footer()
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(login_buttons),
        )
    except Exception as e:
        log.warning(f"Account card edit error: {e}")

    # ── 7. Send Status Check Message ───────────────────
    status_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Working",     callback_data=f"status_working_{user.id}"),
            InlineKeyboardButton("❌ Not Working", callback_data=f"status_notworking_{user.id}"),
        ]
    ])

    await bot.send_message(
        chat_id=chat_id,
        text=(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📊 *Account Status Check*\n\n"
            f"📦 Baaki Stock: *{remaining_stock}* accounts\n"
            "Kya yeh VIP account kaam kar raha hai?\n\n"
            "_Status click karne ke foran baad agla account generate kar sakte ho!_"
            + dev_footer()
        ),
        parse_mode="Markdown",
        reply_markup=status_keyboard,
    )


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
        msg  = "Shukria feedback ke liye! Next account try karein. 🔧"

    user  = query.from_user
    state = get_user_state(user.id)

    # ── Lock hatao — ab agla account generate ho sakta hai ──
    state["waiting_status"] = False

    # Real time stock count
    remaining_stock = len(load_accounts())

    await query.edit_message_text(
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{icon} *Status: {text}*\n\n"
        f"{msg}\n\n"
        f"🟢 Ab agla VIP account generate kar sakte ho!\n"
        f"📦 *Peche Baaki Stock:* `{remaining_stock}` file(s)"
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
