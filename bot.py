import os
import json
import asyncio
import logging
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from playwright.async_api import async_playwright

# ==================== CONFIGURATION ====================
TOKEN = "8544832540:AAENbTXnZ6dl-yBmlP01nI-kwvjHLPcPcZY"
OWNER_ID = 8336576838
SPEEDS = {"hard": 0.1, "medium": 0.5, "slow": 1.0}

# File paths
GROUPS_FILE = "groups.json"
ACCOUNTS_FILE = "accounts.json"

# Global state
playwright = None
browser = None
accounts = {}  # nickname -> {"context": ctx, "page": page, "username": str}
groups = {}    # name -> {"id": str, "link": str, "added_date": str}
selected_groups = []  # List of selected group names
messages = []
speed = "medium"
pair_mode = False
pair_accounts = []
spam_task = None
stop_spam = asyncio.Event()
ua_list = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

# ==================== LOGGING SETUP ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== HEALTH SERVER (FOR RENDER) ====================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, *args): pass

port = int(os.environ.get("PORT", 10000))
threading.Thread(target=lambda: HTTPServer(('0.0.0.0', port), HealthHandler).serve_forever(), daemon=True).start()
logger.info(f"✅ Health server started on port {port}")

# ==================== DATA PERSISTENCE ====================
def load_groups():
    global groups
    try:
        if os.path.exists(GROUPS_FILE):
            with open(GROUPS_FILE, 'r') as f:
                groups = json.load(f)
            logger.info(f"✅ Loaded {len(groups)} groups from {GROUPS_FILE}")
    except Exception as e:
        logger.error(f"Failed to load groups: {e}")
        groups = {}

def save_groups():
    try:
        with open(GROUPS_FILE, 'w') as f:
            json.dump(groups, f, indent=2)
        logger.info(f"✅ Saved {len(groups)} groups to {GROUPS_FILE}")
    except Exception as e:
        logger.error(f"Failed to save groups: {e}")

def load_accounts():
    global accounts
    try:
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, 'r') as f:
                saved = json.load(f)
                # We only load metadata, browser contexts will be recreated
                accounts = {name: {"username": data.get("username", "unknown")} 
                           for name, data in saved.items()}
            logger.info(f"✅ Loaded {len(accounts)} accounts from {ACCOUNTS_FILE}")
    except Exception as e:
        logger.error(f"Failed to load accounts: {e}")
        accounts = {}

def save_accounts():
    try:
        accounts_data = {}
        for name, acc in accounts.items():
            accounts_data[name] = {
                "username": acc.get("username", "unknown"),
                "added_date": datetime.now().isoformat()
            }
        with open(ACCOUNTS_FILE, 'w') as f:
            json.dump(accounts_data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save accounts: {e}")

# Load data on startup
load_groups()
load_accounts()

# ==================== PLAYW RIGHT SETUP ====================
async def get_browser():
    global playwright, browser
    if not browser:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process'
            ]
        )
        logger.info("✅ Browser launched")
    return browser

async def create_context():
    browser = await get_browser()
    user_agent = random.choice(ua_list)
    context = await browser.new_context(
        user_agent=user_agent,
        viewport={'width': random.randint(1024, 1920), 'height': random.randint(768, 1080)}
    )
    return context

# ==================== AUTHORIZATION CHECK ====================
def is_owner(update):
    return update.effective_user.id == OWNER_ID

# ==================== COMMAND HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ Access Denied")
    
    help_text = """
🤖 **Instagram Bot Commands**

**Account Management:**
/login <name> <sessionid> - Add Instagram account
/accounts - List all accounts

**Group Management:**
/addgc <name> <link/id> - Add single group
/bulkgc - Upload file with multiple groups
/listgc [page] - List all groups (paginated)
/searchgc <keyword> - Search groups
/removegc <name> - Remove a group
/clearallgc - Delete ALL groups

**Target Selection:**
/targetgc <name1> <name2> ... - Select groups to target
/targetgc all - Select ALL groups
/selectedgc - Show selected groups
/cleargc - Clear selection

**Message Settings:**
/msgs <msg1&msg2&msg3> - Set messages
/speed <hard|medium|slow> - Set speed

**Pair System:**
/pair <acc1>-<acc2> - Set paired accounts
/pair on|off - Toggle pair mode

**Control:**
/spam - Start spamming
/stop - Stop spamming
/stats - Show statistics
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /login <name> <sessionid>")
    
    name, sessionid = context.args[0], context.args[1]
    
    try:
        context_obj = await create_context()
        await context_obj.add_cookies([{
            "name": "sessionid",
            "value": sessionid,
            "domain": ".instagram.com",
            "path": "/"
        }])
        
        page = await context_obj.new_page()
        await page.goto("https://www.instagram.com/")
        await page.wait_for_selector("svg[aria-label='Profile']", timeout=15000)
        
        # Get username
        username_elem = await page.query_selector("span[class*='_ap3a']")
        username = await username_elem.inner_text() if username_elem else "unknown"
        
        accounts[name] = {
            "context": context_obj,
            "page": page,
            "username": username
        }
        save_accounts()
        await update.message.reply_text(f"✅ Added @{username} as '{name}'")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {str(e)}")

async def show_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    
    if not accounts:
        return await update.message.reply_text("No accounts added")
    
    text = "📱 **Accounts:**\n"
    for name, acc in accounts.items():
        username = acc.get("username", "unknown")
        text += f"• {name}: @{username}\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /addgc <name> <link_or_id>")
    
    name, identifier = context.args[0], " ".join(context.args[1:])
    
    if name in groups:
        return await update.message.reply_text(f"❌ Group '{name}' already exists")
    
    groups[name] = {
        "id": identifier,
        "link": identifier,
        "added_date": datetime.now().isoformat()
    }
    save_groups()
    await update.message.reply_text(f"✅ Added group: {name}")

async def bulk_add_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    
    if not update.message.document:
        return await update.message.reply_text("Please upload a .txt file")
    
    try:
        file = await context.bot.get_file(update.message.document.file_id)
        content = (await file.download_as_bytearray()).decode('utf-8')
        
        added = 0
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                continue
            
            name, identifier = parts[0], parts[1]
            if name not in groups:
                groups[name] = {
                    "id": identifier,
                    "link": identifier,
                    "added_date": datetime.now().isoformat()
                }
                added += 1
        
        save_groups()
        await update.message.reply_text(f"✅ Added {added} new groups")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {str(e)}")

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    
    if not groups:
        return await update.message.reply_text("No groups added")
    
    page = 1
    if context.args and context.args[0].isdigit():
        page = int(context.args[0])
    
    per_page = 10
    start = (page - 1) * per_page
    end = start + per_page
    items = list(groups.items())[start:end]
    
    if not items:
        return await update.message.reply_text(f"Page {page} has no groups")
    
    text = f"📋 **Groups (Page {page}/{ (len(groups)-1)//per_page + 1}):**\n"
    for name, data in items:
        selected = "✅" if name in selected_groups else "⬜"
        text += f"{selected} {name}: {data['id'][:30]}...\n"
    
    text += f"\nTotal: {len(groups)} groups"
    await update.message.reply_text(text, parse_mode='Markdown')

async def search_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if not context.args:
        return await update.message.reply_text("Usage: /searchgc <keyword>")
    
    keyword = " ".join(context.args).lower()
    matches = []
    
    for name, data in groups.items():
        if keyword in name.lower() or keyword in data['id'].lower():
            matches.append(name)
    
    if not matches:
        return await update.message.reply_text("No matches found")
    
    text = f"🔍 **Found {len(matches)} matches:**\n"
    text += "\n".join(f"• {name}" for name in matches[:20])
    if len(matches) > 20:
        text += f"\n... and {len(matches)-20} more"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def remove_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if not context.args:
        return await update.message.reply_text("Usage: /removegc <name>")
    
    name = context.args[0]
    if name not in groups:
        return await update.message.reply_text(f"Group '{name}' not found")
    
    del groups[name]
    if name in selected_groups:
        selected_groups.remove(name)
    
    save_groups()
    await update.message.reply_text(f"✅ Removed group: {name}")

async def clear_all_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    
    # Ask for confirmation
    if context.args and context.args[0] == "confirm":
        groups.clear()
        selected_groups.clear()
        save_groups()
        await update.message.reply_text("✅ All groups cleared")
    else:
        await update.message.reply_text("⚠️ This will delete ALL groups. Use /clearallgc confirm to proceed")

async def target_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if not context.args:
        return await update.message.reply_text("Usage: /targetgc <name1> <name2> ... or /targetgc all")
    
    global selected_groups
    
    if context.args[0] == "all":
        selected_groups = list(groups.keys())
        await update.message.reply_text(f"✅ Selected ALL {len(selected_groups)} groups")
        return
    
    new_selected = []
    not_found = []
    
    for name in context.args:
        if name in groups:
            new_selected.append(name)
        else:
            not_found.append(name)
    
    if new_selected:
        selected_groups = new_selected
        await update.message.reply_text(f"✅ Selected {len(new_selected)} groups")
    
    if not_found:
        await update.message.reply_text(f"❌ Not found: {', '.join(not_found)}")

async def show_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    
    if not selected_groups:
        return await update.message.reply_text("No groups selected")
    
    text = f"🎯 **Selected Groups ({len(selected_groups)}):**\n"
    for name in selected_groups[:20]:
        text += f"• {name}\n"
    
    if len(selected_groups) > 20:
        text += f"... and {len(selected_groups)-20} more"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def clear_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    
    selected_groups.clear()
    await update.message.reply_text("✅ Selection cleared")

async def set_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if not context.args:
        return await update.message.reply_text("Usage: /msgs <msg1&msg2&msg3>")
    
    global messages
    text = " ".join(context.args)
    messages = [m.strip() for m in text.split("&") if m.strip()]
    
    await update.message.reply_text(f"✅ {len(messages)} messages set")

async def set_speed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if not context.args or context.args[0].lower() not in SPEEDS:
        return await update.message.reply_text("Speed must be hard, medium, or slow")
    
    global speed
    speed = context.args[0].lower()
    await update.message.reply_text(f"✅ Speed set to {speed} ({SPEEDS[speed]}s)")

async def pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if not context.args:
        return await update.message.reply_text("Usage: /pair <acc1>-<acc2> or /pair on/off")
    
    global pair_mode, pair_accounts
    arg = context.args[0].lower()
    
    if arg in ["on", "off"]:
        pair_mode = (arg == "on")
        await update.message.reply_text(f"✅ Pair mode: {pair_mode}")
    
    elif "-" in arg:
        parts = arg.split("-")
        if len(parts) != 2:
            return await update.message.reply_text("Invalid format. Use: acc1-acc2")
        
        a1, a2 = parts[0], parts[1]
        if a1 not in accounts or a2 not in accounts:
            missing = []
            if a1 not in accounts: missing.append(a1)
            if a2 not in accounts: missing.append(a2)
            return await update.message.reply_text(f"❌ Accounts not found: {', '.join(missing)}")
        
        pair_accounts = [a1, a2]
        pair_mode = True
        await update.message.reply_text(f"✅ Paired: {a1} ↔ {a2}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    
    stats_text = f"""
📊 **Bot Statistics**

**Accounts:** {len(accounts)}
**Groups:** {len(groups)}
**Selected:** {len(selected_groups)}
**Messages:** {len(messages)}
**Speed:** {speed} ({SPEEDS[speed]}s)
**Pair Mode:** {pair_mode}
**Paired Accounts:** {pair_accounts if pair_accounts else 'None'}
    """
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    
    global spam_task, stop_spam
    
    # Validation
    if not messages:
        return await update.message.reply_text("❌ No messages set")
    if not accounts:
        return await update.message.reply_text("❌ No accounts added")
    if not selected_groups:
        return await update.message.reply_text("❌ No groups selected")
    
    if spam_task and not spam_task.done():
        return await update.message.reply_text("❌ Spam already running")
    
    stop_spam.clear()
    spam_task = asyncio.create_task(spam_loop())
    await update.message.reply_text(f"✅ Spamming started with {len(selected_groups)} groups")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    
    global stop_spam
    if spam_task and not spam_task.done():
        stop_spam.set()
        await update.message.reply_text("⏹️ Stopping spam...")
    else:
        await update.message.reply_text("❌ No spam running")

async def spam_loop():
    logger.info(f"🚀 Spam loop started with {len(selected_groups)} groups")
    
    delay = SPEEDS[speed]
    msg_idx = 0
    
    # Determine which accounts to use
    account_list = pair_accounts if (pair_mode and pair_accounts) else [list(accounts.keys())[0]]
    
    # Prepare pages for all accounts
    pages = []
    for name in account_list:
        if name in accounts and "page" in accounts[name]:
            pages.append(accounts[name]["page"])
        else:
            logger.error(f"Account {name} not ready")
            return
    
    if not pages:
        logger.error("No pages available")
        return
    
    group_list = selected_groups.copy()
    group_idx = 0
    account_idx = 0
    
    try:
        while not stop_spam.is_set():
            # Get current group and account
            current_group = group_list[group_idx % len(group_list)]
            current_page = pages[account_idx % len(pages)]
            current_message = messages[msg_idx]
            
            # Get group identifier
            group_id = groups[current_group]["id"]
            
            try:
                # Navigate to group (simulate sending - actual implementation depends on group type)
                # This is a placeholder - you'll need to implement actual group sending logic
                logger.info(f"[{account_list[account_idx]}] Sending to {current_group}: {current_message[:30]}...")
                
                # Here you would implement actual sending to group
                # For now, just log it
                
                # Add random human-like delay
                base_delay = delay * random.uniform(0.8, 1.2)
                await asyncio.sleep(base_delay)
                
            except Exception as e:
                logger.error(f"Failed to send to {current_group}: {e}")
                # Remove failed group?
            
            # Update indices
            msg_idx = (msg_idx + 1) % len(messages)
            group_idx += 1
            account_idx += 1
            
            # Small delay between groups
            await asyncio.sleep(0.1)
            
    except Exception as e:
        logger.error(f"Spam loop error: {e}")
    finally:
        logger.info("Spam loop ended")

async def post_init(app):
    await get_browser()
    logger.info("✅ Bot initialized")

# ==================== MAIN ====================
def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    
    # Account commands
  
