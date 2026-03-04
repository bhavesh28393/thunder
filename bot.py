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
playwright, browser = None, None
accounts, target, messages = {}, None, []
speed, pair_mode, pair_accounts = "medium", False, []
stop_spam, spam_task = asyncio.Event(), None

# Health server for Render
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
    def log_message(self, *args): pass

threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthHandler).serve_forever(), daemon=True).start()

async def get_browser():
    global playwright, browser
    if not browser:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True, args=['--no-sandbox'])
    return browser

# Commands
async def start(update, ctx):
    if update.effective_user.id != OWNER_ID: return await update.message.reply_text("❌ Access Denied")
    await update.message.reply_text("/login <name> <sessionid>\n/accounts\n/target <user>\n/msgs <msg1&msg2>\n/speed low|medium|high\n/pair name1-name2\n/spam\n/stop")

async def login(update, ctx):
    if update.effective_user.id != OWNER_ID or len(ctx.args) < 2: return
    name, sessionid = ctx.args[0], ctx.args[1]
    b, c, p = await get_browser(), await (await get_browser()).new_context(), None
    try:
        await c.add_cookies([{"name": "sessionid", "value": sessionid, "domain": ".instagram.com", "path": "/"}])
        p = await c.new_page()
        await p.goto("https://www.instagram.com/")
        await p.wait_for_selector("svg[aria-label='Profile']", timeout=15000)
        accounts[name] = {"ctx": c, "page": p}
        await update.message.reply_text(f"✅ Added {name}")
    except Exception as e: await c.close(); await update.message.reply_text(f"❌ {str(e)}")

async def show_accounts(update, ctx):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text("Accounts:\n" + "\n".join(accounts.keys()) if accounts else "No accounts")

async def set_target(update, ctx):
    global target
    if update.effective_user.id == OWNER_ID and ctx.args:
        target = ctx.args[0].lstrip('@')
        await update.message.reply_text(f"Target: @{target}")

async def set_messages(update, ctx):
    global messages
    if update.effective_user.id == OWNER_ID and ctx.args:
        messages = [m.strip() for m in " ".join(ctx.args).split("&") if m.strip()]
        await update.message.reply_text(f"Messages: {messages}")

async def set_speed(update, ctx):
    global speed
    if update.effective_user.id == OWNER_ID and ctx.args and ctx.args[0].lower() in SPEEDS:
        speed = ctx.args[0].lower()
        await update.message.reply_text(f"Speed: {speed}")

async def pair(update, ctx):
    global pair_mode, pair_accounts
    if update.effective_user.id != OWNER_ID or not ctx.args: return
    arg = ctx.args[0].lower()
    if arg in ["on", "off"]:
        pair_mode = (arg == "on")
        await update.message.reply_text(f"Pair mode: {pair_mode}")
    elif "-" in arg:
        n1, n2 = arg.split("-")
        if n1 in accounts and n2 in accounts:
            pair_accounts, pair_mode = [n1, n2], True
            await update.message.reply_text(f"Pair set: {n1} & {n2}")
        else: await update.message.reply_text("Account not found")

async def spam(update, ctx):
    global spam_task, stop_spam
    if update.effective_user.id != OWNER_ID or not messages or not target or not accounts: return
    acc_list = pair_accounts if (pair_mode and pair_accounts) else [list(accounts.keys())[0]]
    stop_spam.clear()
    spam_task = asyncio.create_task(spam_loop(acc_list))
    await update.message.reply_text(f"Spamming with {acc_list}")

async def stop(update, ctx):
    if update.effective_user.id == OWNER_ID and spam_task and not spam_task.done():
        stop_spam.set()
        await update.message.reply_text("Stopping...")

async def spam_loop(acc_names):
    delay, msg_idx, acc_idx = SPEEDS[speed], 0, 0
    pages = []
    for name in acc_names:
        try:
            p = accounts[name]["page"]
            await p.goto(f"https://www.instagram.com/{target}/")
            await asyncio.sleep(2)
            await p.click("button[type='button']", has_text="Message")
            await p.wait_for_selector("textarea", timeout=10000)
            pages.append(p)
        except: return
    while not stop_spam.is_set():
        try:
            await pages[acc_idx].fill("textarea", messages[msg_idx])
            await asyncio.sleep(0.5)
            await pages[acc_idx].press("textarea", "Enter")
            msg_idx, acc_idx = (msg_idx + 1) % len(messages), (acc_idx + 1) % len(acc_names)
            await asyncio.sleep(delay * random.uniform(0.8, 1.2))
        except: break

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
