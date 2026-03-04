#!/usr/bin/env python3
"""
Instagram Spam Bot - Render Deployment Version
SIMPLIFIED - No FastAPI, just a simple HTTP server for port binding
"""

import os
import json
import asyncio
import logging
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional, List
from functools import wraps
from fake_useragent import UserAgent

from telegram import Update, Document
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from playwright.async_api import async_playwright, Browser

# ---------------------------- Configuration ----------------------------
TELEGRAM_BOT_TOKEN = "8544832540:AAENbTXnZ6dl-yBmlP01nI-kwvjHLPcPcZY"
AUTHORIZED_USERS = [8336576838]
ACCESS_DENIED_MESSAGE = "❌ YOU DON'T HAVE ACCESS TO USE THIS BOT. DM @pruvn TO GET ACCESS."

# Critical for Render: Set browser path to a writable location
PLAYWRIGHT_BROWSERS_PATH = os.environ.get(
    "PLAYWRIGHT_BROWSERS_PATH", "/opt/render/project/src/playwright_browsers"
)
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = PLAYWRIGHT_BROWSERS_PATH

INSTAGRAM_SESSION_DIR = "instagram_sessions"
SPEED_DELAYS = {"low": 30, "medium": 15, "high": 5}

# Create necessary directories
os.makedirs(INSTAGRAM_SESSION_DIR, exist_ok=True)
os.makedirs(PLAYWRIGHT_BROWSERS_PATH, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global Playwright objects
playwright: Optional[async_playwright] = None
browser: Optional[Browser] = None
ua = UserAgent()

# ---------------------------- Simple HTTP Health Server ----------------------------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    
    def log_message(self, format, *args):
        # Suppress log messages
        pass

def run_health_server():
    """Run a simple HTTP server on the required port"""
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    logger.info(f"Health server listening on port {port}")
    server.serve_forever()

# ---------------------------- Authorization Decorator ----------------------------
def authorized_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in AUTHORIZED_USERS:
            await update.message.reply_text(ACCESS_DENIED_MESSAGE)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ---------------------------- User Data Storage ----------------------------
class UserData:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.instagram_accounts: Dict[str, dict] = {}
        self.target_instagram: Optional[str] = None
        self.messages: list = []
        self.speed = "medium"
        self.pair_mode = False
        self.pair_accounts: List[str] = []
        self.spam_task: Optional[asyncio.Task] = None
        self.stop_spam = asyncio.Event()

    def set_messages_from_text(self, text: str):
        self.messages = [m.strip() for m in text.split("&") if m.strip()]

    def set_messages_from_file(self, file_content: str):
        lines = file_content.splitlines()
        self.messages = [line.replace("{name}", "H8R") for line in lines if line.strip()]

user_data: Dict[int, UserData] = {}

def get_user_data(user_id: int) -> UserData:
    if user_id not in user_data:
        user_data[user_id] = UserData(user_id)
    return user_data[user_id]

# ---------------------------- Playwright Management ----------------------------
async def ensure_browser():
    global playwright, browser
    if playwright is None:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage'
            ]
        )
        logger.info("Browser launched successfully")

async def close_browser():
    global playwright, browser
    if browser:
        await browser.close()
        browser = None
    if playwright:
        await playwright.stop()
        playwright = None

async def create_instagram_context():
    await ensure_browser()
    user_agent = ua.random
    context = await browser.new_context(
        user_agent=user_agent,
        viewport={'width': 1280, 'height': 800}
    )
    page = await context.new_page()
    return context, page

# ---------------------------- Instagram Login Helpers ----------------------------
async def login_with_password(nickname: str, username: str, password: str, user_id: int) -> str:
    data = get_user_data(user_id)
    context, page = await create_instagram_context()
    try:
        await page.goto("https://www.instagram.com/accounts/login/")
        await page.wait_for_selector("input[name='username']", timeout=30000)
        await page.fill("input[name='username']", username)
        await page.fill("input[name='password']", password)
        await page.click("button[type='submit']")
        await asyncio.sleep(random.uniform(3, 7))
        await page.wait_for_url("https://www.instagram.com/", timeout=30000)

        storage = await context.storage_state()
        with open(f"{INSTAGRAM_SESSION_DIR}/{user_id}_{nickname}.json", "w") as f:
            json.dump(storage, f)

        data.instagram_accounts[nickname] = {
            "context": context,
            "page": page,
            "username": username
        }
        return f"✅ Logged in as @{username} with nickname '{nickname}'."
    except Exception as e:
        await context.close()
        return f"❌ Login failed for '{nickname}': {str(e)}"

async def login_with_session(nickname: str, sessionid: str, user_id: int) -> str:
    data = get_user_data(user_id)
    context, page = await create_instagram_context()
    try:
        await context.add_cookies([{
            "name": "sessionid",
            "value": sessionid,
            "domain": ".instagram.com",
            "path": "/",
            "httpOnly": True,
            "secure": True
        }])
        await page.goto("https://www.instagram.com/")
        await asyncio.sleep(random.uniform(3, 5))
        await page.wait_for_selector("svg[aria-label='Profile']", timeout=30000)

        username_elem = await page.query_selector("span[class*='_ap3a']")
        username = await username_elem.inner_text() if username_elem else "unknown"

        storage = await context.storage_state()
        with open(f"{INSTAGRAM_SESSION_DIR}/{user_id}_{nickname}.json", "w") as f:
            json.dump(storage, f)

        data.instagram_accounts[nickname] = {
            "context": context,
            "page": page,
            "username": username
        }
        return f"✅ Logged in with session as @{username} (nickname '{nickname}')."
    except Exception as e:
        await context.close()
        return f"❌ Session login failed for '{nickname}': {str(e)}"

# ---------------------------- Telegram Bot Handlers ----------------------------
@authorized_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **Instagram Spam Bot**\n\n"
        "**Commands:**\n"
        "/login_instagram <nickname> <username> <password>\n"
        "/login_session <nickname> <sessionid>\n"
        "/accounts - List accounts\n"
        "/set_target_instagram <username>\n"
        "/set_messages <msg1&msg2&msg3>\n"
        "/upload - Upload .txt file\n"
        "/set_speed <low|medium|high>\n"
        "/pair <nick1>-<nick2>\n"
        "/spam - Start\n"
        "/stop - Stop",
        parse_mode="Markdown",
    )

@authorized_only
async def login_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /login_instagram <nickname> <username> <password>")
        return
    nickname, username, password = context.args[0], context.args[1], context.args[2]
    user_id = update.effective_user.id
    await update.message.reply_text(f"Logging in as '{nickname}'...")
    result = await login_with_password(nickname, username, password, user_id)
    await update.message.reply_text(result)

@authorized_only
async def login_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /login_session <nickname> <sessionid>")
        return
    nickname, sessionid = context.args[0], context.args[1]
    user_id = update.effective_user.id
    await update.message.reply_text(f"Logging in with session as '{nickname}'...")
    result = await login_with_session(nickname, sessionid, user_id)
    await update.message.reply_text(result)

@authorized_only
async def list_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = get_user_data(user_id)
    if not data.instagram_accounts:
        await update.message.reply_text("No Instagram accounts logged in.")
        return
    lines = ["**Logged-in accounts:**"]
    for nick, acc in data.instagram_accounts.items():
        lines.append(f"• `{nick}`: @{acc['username']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

@authorized_only
async def set_target_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = get_user_data(user_id)
    if not context.args:
        await update.message.reply_text("Please provide an Instagram username.")
        return
    target = context.args[0].strip().lstrip('@')
    data.target_instagram = target
    await update.message.reply_text(f"Instagram target set to: @{target}")

@authorized_only
async def set_speed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = get_user_data(user_id)
    if not context.args or context.args[0].lower() not in SPEED_DELAYS:
        await update.message.reply_text("Speed must be low, medium, or high.")
        return
    data.speed = context.args[0].lower()
    await update.message.reply_text(f"Speed set to {data.speed}.")

@authorized_only
async def set_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = get_user_data(user_id)
    if not context.args:
        await update.message.reply_text("Usage: /set_messages msg1&msg2&msg3")
        return
    text = " ".join(context.args)
    data.set_messages_from_text(text)
    await update.message.reply_text(f"Messages set: {data.messages}")

@authorized_only
async def upload_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = get_user_data(user_id)
    document = update.message.document
    if not document.file_name.endswith(".txt"):
        await update.message.reply_text("Please upload a .txt file.")
        return
    file = await context.bot.get_file(document.file_id)
    file_content = (await file.download_as_bytearray()).decode("utf-8")
    data.set_messages_from_file(file_content)
    await update.message.reply_text(f"Messages loaded. {len(data.messages)} messages.")

@authorized_only
async def pair_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = get_user_data(user_id)
    if not context.args:
        await update.message.reply_text("Usage: /pair nick1-nick2 or /pair on/off")
        return
    arg = context.args[0].lower()
    if arg in ["on", "off"]:
        data.pair_mode = (arg == "on")
        await update.message.reply_text(f"Pair mode {'enabled' if data.pair_mode else 'disabled'}.")
    elif "-" in arg:
        parts = arg.split("-")
        if len(parts) != 2:
            await update.message.reply_text("Invalid format. Use: /pair nick1-nick2")
            return
        nick1, nick2 = parts[0].strip(), parts[1].strip()
        if nick1 not in data.instagram_accounts or nick2 not in data.instagram_accounts:
            missing = []
            if nick1 not in data.instagram_accounts:
                missing.append(nick1)
            if nick2 not in data.instagram_accounts:
                missing.append(nick2)
            await update.message.reply_text(f"Account(s) not logged in: {', '.join(missing)}")
            return
        data.pair_accounts = [nick1, nick2]
        data.pair_mode = True
        await update.message.reply_text(f"Pair set: {nick1} and {nick2}")
    else:
        await update.message.reply_text("Invalid command")

@authorized_only
async def spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = get_user_data(user_id)
    if data.spam_task and not data.spam_task.done():
        await update.message.reply_text("Spam already running. Use /stop first.")
        return

    if not data.messages:
        await update.message.reply_text("No messages set.")
        return
    if not data.target_instagram:
        await update.message.reply_text("No target set.")
        return
    if not data.instagram_accounts:
        await update.message.reply_text("No Instagram accounts logged in.")
        return

    if data.pair_mode and len(data.pair_accounts) == 2:
        accounts = data.pair_accounts
    else:
        accounts = [list(data.instagram_accounts.keys())[0]]

    data.stop_spam.clear()
    data.spam_task = asyncio.create_task(spam_loop(user_id, accounts))
    await update.message.reply_text(f"Spamming started with accounts: {accounts}")

@authorized_only
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = get_user_data(user_id)
    if data.spam_task and not data.spam_task.done():
        data.stop_spam.set()
        await update.message.reply_text("Stopping spam...")
    else:
        await update.message.reply_text("No spam task running.")

# ---------------------------- Spam Loop ----------------------------
async def spam_loop(user_id: int, account_nicknames: List[str]):
    data = user_data.get(user_id)
    if not data:
        return

    base_delay = SPEED_DELAYS[data.speed]
    messages = data.messages
    msg_idx = 0
    account_idx = 0
    target = data.target_instagram

    pages = []
    for nick in account_nicknames:
        acc = data.instagram_accounts.get(nick)
        if not acc:
            return
        page = acc["page"]
        try:
            await page.goto(f"https://www.instagram.com/{target}/")
            await asyncio.sleep(random.uniform(2, 4))
            await page.click("button[type='button']", has_text="Message")
            await page.wait_for_selector("textarea", timeout=30000)
            pages.append(page)
        except Exception as e:
            logger.error(f"Failed to open DM: {e}")
            return

    while not data.stop_spam.is_set():
        try:
            current_page = pages[account_idx]
            message = messages[msg_idx]
            await current_page.type("textarea", message, delay=random.randint(50, 150))
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await current_page.press("textarea", "Enter")
            logger.info(f"Sent: {message}")

            msg_idx = (msg_idx + 1) % len(messages)
            account_idx = (account_idx + 1) % len(account_nicknames)
            await asyncio.sleep(base_delay * random.uniform(0.8, 1.5))
        except Exception as e:
            logger.error(f"Error: {e}")
            break

# ---------------------------- Main ----------------------------
async def post_init(application: Application):
    await ensure_browser()
    logger.info("Browser initialized")

async def post_shutdown(application: Application):
    await close_browser()
    logger.info("Browser closed")

def main():
    # Start health server in a separate thread
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    app = Application.builder()\
        .token(TELEGRAM_BOT_TOKEN)\
        .post_init(post_init)\
        .post_shutdown(post_shutdown)\
        .build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login_instagram", login_instagram))
    app.add_handler(CommandHandler("login_session", login_session))
    app.add_handler(CommandHandler("accounts", list_accounts))
    app.add_handler(CommandHandler("set_target_instagram", set_target_instagram))
    app.add_handler(CommandHandler("set_speed", set_speed))
    app.add_handler(CommandHandler("set_messages", set_messages))
    app.add_handler(CommandHandler("upload", upload_file))
    app.add_handler(CommandHandler("pair", pair_command))
    app.add_handler(CommandHandler("spam", spam))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), upload_file))

    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
