#!/usr/bin/env python3
import os, asyncio, logging, random, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from playwright.async_api import async_playwright

TOKEN = "8544832540:AAENbTXnZ6dl-yBmlP01nI-kwvjHLPcPcZY"
OWNER_ID = 8336576838
SPEEDS = {"low": 30, "medium": 15, "high": 5}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
playwright = None
browser = None
accounts = {}
target = None
messages = []
speed = "medium"
pair_mode = False
pair_accounts = []
stop_spam = asyncio.Event()
spam_task = None

# Health server
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, *args): pass

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(('0.0.0.0', port), HealthHandler).serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()
logger.info("Health server started")

# Browser
async def get_browser():
    global playwright, browser
    if browser is None:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True, args=['--no-sandbox'])
    return browser

# Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Access denied")
        return
    await update.message.reply_text(
        "Instagram Spam Bot\n\n"
        "/login <name> <sessionid>\n"
        "/accounts\n/target <user>\n/msgs <msg1&msg2>\n"
        "/speed low|medium|high\n/pair name1-name2\n/spam\n/stop"
    )

async def login(update, context):
    if update.effective_user.id != OWNER_ID: return
    if len(context.args) < 2: return
    name, sessionid = context.args[0], context.args[1]
    b = await get_browser()
    ctx = await b.new_context()
    page = await ctx.new_page()
    try:
        await ctx.add_cookies([{
            "name": "sessionid", "value": sessionid,
            "domain": ".instagram.com", "path": "/"
        }])
        await page.goto("https://www.instagram.com/")
        await page.wait_for_selector("svg[aria-label='Profile']", timeout=15000)
        accounts[name] = {"ctx": ctx, "page": page}
        await update.message.reply_text(f"✅ Added {name}")
    except Exception as e:
        await ctx.close()
        await update.message.reply_text(f"❌ {str(e)}")

async def show_accounts(update, context):
    if update.effective_user.id != OWNER_ID: return
    if not accounts: await update.message.reply_text("No accounts")
    else: await update.message.reply_text("Accounts:\n" + "\n".join(accounts.keys()))

async def set_target(update, context):
    if update.effective_user.id != OWNER_ID: return
    global target
    if context.args: target = context.args[0].lstrip('@')
    await update.message.reply_text(f"Target: @{target}")

async def set_messages(update, context):
    if update.effective_user.id != OWNER_ID: return
    global messages
    if context.args:
        text = " ".join(context.args)
        messages = [m.strip() for m in text.split("&") if m.strip()]
    await update.message.reply_text(f"Messages: {messages}")

async def set_speed(update, context):
    if update.effective_user.id != OWNER_ID: return
    global speed
    if context.args and context.args[0].lower() in SPEEDS:
        speed = context.args[0].lower()
    await update.message.reply_text(f"Speed: {speed}")

async def pair(update, context):
    if update.effective_user.id != OWNER_ID: return
    global pair_mode, pair_accounts
    if not context.args: return
    arg = context.args[0].lower()
    if arg in ["on","off"]:
        pair_mode = (arg=="on")
        await update.message.reply_text(f"Pair mode: {pair_mode}")
    elif "-" in arg:
        n1,n2 = arg.split("-")
        if n1 in accounts and n2 in accounts:
            pair_accounts = [n1,n2]
            pair_mode = True
            await update.message.reply_text(f"Pair set: {n1} & {n2}")
        else:
            await update.message.reply_text("Account missing")

async def spam(update, context):
    global spam_task, stop_spam
    if update.effective_user.id != OWNER_ID: return
    if not messages or not target or not accounts:
        await update.message.reply_text("Missing messages/target/accounts")
        return
    acc_list = pair_accounts if (pair_mode and pair_accounts) else [list(accounts.keys())[0]]
    stop_spam.clear()
    spam_task = asyncio.create_task(spam_loop(acc_list))
    await update.message.reply_text(f"Spamming with {acc_list}")

async def stop(update, context):
    if update.effective_user.id != OWNER_ID: return
    if spam_task:
        stop_spam.set()
        await update.message.reply_text("Stopping...")

async def spam_loop(acc_names):
    delay = SPEEDS[speed]
    msg_idx = 0
    acc_idx = 0
    pages = []
    for name in acc_names:
        page = accounts[name]["page"]
        try:
            await page.goto(f"https://www.instagram.com/{target}/")
            await asyncio.sleep(2)
            await page.click("button[type='button']", has_text="Message")
            await page.wait_for_selector("textarea", timeout=10000)
            pages.append(page)
        except:
            return
    while not stop_spam.is_set():
        try:
            await pages[acc_idx].fill("textarea", messages[msg_idx])
            await asyncio.sleep(0.5)
            await pages[acc_idx].press("textarea", "Enter")
            logger.info(f"Sent: {messages[msg_idx]}")
            msg_idx = (msg_idx + 1) % len(messages)
            acc_idx = (acc_idx + 1) % len(acc_names)
            await asyncio.sleep(delay * random.uniform(0.8,1.2))
        except:
            break

async def post_init(app):
    await get_browser()

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("accounts", show_accounts))
    app.add_handler(CommandHandler("target", set_target))
    app.add_handler(CommandHandler("msgs", set_messages))
    app.add_handler(CommandHandler("speed", set_speed))
    app.add_handler(CommandHandler("pair", pair))
    app.add_handler(CommandHandler("spam", spam))
    app.add_handler(CommandHandler("stop", stop))
    app.run_polling()

if __name__ == "__main__":
    main()
