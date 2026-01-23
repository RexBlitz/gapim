import pymongo
import re
import aiohttp
import asyncio
import logging
import datetime 
from functools import lru_cache
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- CONFIGURATION ---
BOT_TOKEN = "8493774369:AAFFquaaAtX3FXbsgjNnDLXRogt60GroDyU"
MONGO_DB_URL = "mongodb+srv://irexanon:xUf7PCf9cvMHy8g6@rexdb.d9rwo.mongodb.net/?retryWrites=true&w=majority&appName=RexDB"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
BOT_PASSWORD = "11223344" 
KEYS_PER_PAGE = 50

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- DATABASE INSTANCES ---
_mongo_client = None
_aiohttp_session = None

def get_mongo_client():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = pymongo.MongoClient(MONGO_DB_URL, maxPoolSize=50, minPoolSize=10)
    return _mongo_client

async def get_aiohttp_session():
    global _aiohttp_session
    if _aiohttp_session is None or _aiohttp_session.closed:
        _aiohttp_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    return _aiohttp_session

def get_api_keys_db():
    return get_mongo_client()["ApiKeys"]

@lru_cache(maxsize=1)
def _get_gemini_collection():
    return get_api_keys_db()["gemini_keys"]

def save_gemini_keys(keys: list):
    _get_gemini_collection().update_one({"type": "keys"}, {"$set": {"keys": keys}}, upsert=True)

def get_gemini_keys():
    doc = _get_gemini_collection().find_one({"type": "keys"})
    if not doc: return []
    return doc.get("keys", [])

# --- AUTHENTICATION ---
@lru_cache(maxsize=1)
def _get_auth_collection():
    return get_api_keys_db()["authorized_users"]

def add_authorized_user(user_id: int):
    _get_auth_collection().update_one(
        {"_id": user_id},
        {"$set": {"authorized": True, "timestamp": datetime.datetime.now()}},
        upsert=True
    )
    is_authorized_user.cache_clear()

@lru_cache(maxsize=None)
def is_authorized_user(user_id: int) -> bool:
    return _get_auth_collection().find_one({"_id": user_id, "authorized": True}) is not None

# --- CORE UTILS ---
async def test_gemini_key(api_key: str) -> tuple[str, str]:
    try:
        session = await get_aiohttp_session()
        params = {"key": api_key}
        data = {"contents": [{"parts": [{"text": "Hi"}]}]}
        async with session.post(GEMINI_API_URL, params=params, json=data) as resp:
            if resp.status == 200: return "valid", "✅ Valid"
            elif resp.status == 429: return "rate_limited", "⚠️ Rate Limited"
            return "invalid", f"❌ Invalid ({resp.status})"
    except Exception as e:
        return "error", f"❓ Error: {str(e)[:15]}"

def escape_md(text: str) -> str:
    if not text: return ""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))

def restricted(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if is_authorized_user(update.effective_user.id):
            return await func(update, context)
        await update.effective_message.reply_text("🚫 **Access Denied**\\. Please use `/start` to authenticate\\.", parse_mode='MarkdownV2')
    return wrapper

# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if is_authorized_user(user_id):
        total = len(get_gemini_keys())
        msg = (f"👋 **Gemini Key Manager**\nTotal Keys: **{total}**\n\n"
               f"• To add: Send `AIza... Name`\n"
               f"• `/list` \\- View all keys\n"
               f"• `/test <index>` \\- Manual index test\n"
               f"• `/del <index>` \\- Delete key")
        await update.message.reply_text(msg, parse_mode='MarkdownV2')
    else:
        context.user_data['awaiting_password'] = True
        await update.message.reply_text("🔐 Welcome! Please send the **Password** to gain access\\.", parse_mode='MarkdownV2')

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if context.user_data.get('awaiting_password'):
        if text == BOT_PASSWORD:
            add_authorized_user(user_id)
            del context.user_data['awaiting_password']
            await update.message.reply_text("🎉 **Access Granted!** Use `/start` to see the menu\\.", parse_mode='MarkdownV2')
            await start(update, context)
        else:
            await update.message.reply_text("❌ Incorrect password! Please try again\\.")
        return

    if is_authorized_user(user_id):
        match = re.match(r'^\s*(AIza[A-Za-z0-9_-]{35})(?:\s+(.*))?\s*$', text)
        if match:
            key, name = match.groups()
            keys = get_gemini_keys()
            if any(k['key'] == key for k in keys):
                await update.message.reply_text("⚠️ This key is already saved\\.")
                return
            keys.append({"key": key, "name": name.strip() if name else None})
            save_gemini_keys(keys)
            name_str = escape_md(name) if name else "None"
            await update.message.reply_text(f"✅ Key saved successfully\\.\nName: **{name_str}**", parse_mode='MarkdownV2')

@restricted
async def list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE, page=0) -> None:
    keys = get_gemini_keys()
    if not keys:
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_text("No keys found in database\\.")
        return

    total_keys = len(keys)
    total_pages = (total_keys - 1) // KEYS_PER_PAGE + 1
    start_idx = page * KEYS_PER_PAGE
    end_idx = min(start_idx + KEYS_PER_PAGE, total_keys)
    current_batch = keys[start_idx:end_idx]

    lines = [f"🔑 **Stored Keys (Page {page+1}/{total_pages})**\n"]
    for i, entry in enumerate(current_batch):
        idx = start_idx + i + 1
        k_val = escape_md(entry['key'][:20])
        n_val = f" \\({escape_md(entry['name'])}\\)" if entry.get('name') else ""
        lines.append(f"**{idx}\\.** `{k_val}\\.\\.\\.`{n_val}")

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Back", callback_data=f"p_{page-1}"))
    if end_idx < total_keys:
        buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"p_{page+1}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None
    text = "\n".join(lines)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode='MarkdownV2')

@restricted
async def test_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("⚠️ Usage:\n`/test <index>` (e.g. `/test 1`)\n`/test <full_key>`", parse_mode='MarkdownV2')
        return

    arg = context.args[0]
    if arg.isdigit():
        keys = get_gemini_keys()
        idx = int(arg) - 1
        if 0 <= idx < len(keys):
            entry = keys[idx]
            m = await update.message.reply_text(f"🔄 Testing key at index {arg}\\.\\.\\.", parse_mode='MarkdownV2')
            _, res = await test_gemini_key(entry['key'])
            await m.edit_text(f"Index {arg} Result: {escape_md(res)}", parse_mode='MarkdownV2')
        else:
            await update.message.reply_text(f"⚠️ Invalid index! Total keys: {len(keys)}")
    elif re.match(r'^AIza[A-Za-z0-9_-]{35}$', arg):
        m = await update.message.reply_text("🔄 Testing raw key\\.\\.\\.", parse_mode='MarkdownV2')
        _, res = await test_gemini_key(arg)
        await m.edit_text(f"Key Result: {escape_md(res)}", parse_mode='MarkdownV2')
    else:
        await update.message.reply_text("⚠️ Invalid index or key format\\.")

@restricted
async def del_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: `/del <index>`")
        return
    idx = int(context.args[0]) - 1
    keys = get_gemini_keys()
    if 0 <= idx < len(keys):
        removed = keys.pop(idx)
        save_gemini_keys(keys)
        await update.message.reply_text(f"🗑 Deleted Index {idx+1}:\n`{escape_md(removed['key'][:20])}...`", parse_mode='MarkdownV2')
    else:
        await update.message.reply_text("Invalid index\\.")

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data.startswith("p_"):
        page = int(query.data.split("_")[1])
        await list_keys(update, context, page=page)

async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "Start bot and see help (or authenticate)"),
        BotCommand("list", "List keys and their names),
        BotCommand("test", "Test  they by (index or key)"),
        BotCommand("del", "Delete a key by index")
    ])

def main():
    is_authorized_user.cache_clear()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_keys))
    app.add_handler(CommandHandler("test", test_key))
    app.add_handler(CommandHandler("del", del_key))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(cb_handler))
    
    print("🚀 Bot is live (English UI)")
    app.run_polling()

if __name__ == '__main__':
    main()
