import pymongo
import re
import aiohttp
import asyncio
import logging
import datetime 
from functools import lru_cache
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- ⚙️ CONFIGURATION ---
BOT_TOKEN = "8493774369:AAFFquaaAtX3FXbsgjNnDLXRogt60GroDyU"
MONGO_DB_URL = "mongodb+srv://irexanon:xUf7PCf9cvMHy8g6@rexdb.d9rwo.mongodb.net/?retryWrites=true&w=majority&appName=RexDB"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"

# 🔑 AUTHENTICATION CONFIGURATION
BOT_PASSWORD = "11223344" 

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 🚀 GLOBAL INSTANCES FOR PERFORMANCE ---
_mongo_client = None
_aiohttp_session = None

def get_mongo_client():
    """Reuse single MongoDB client instance."""
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = pymongo.MongoClient(
            MONGO_DB_URL,
            maxPoolSize=50,
            minPoolSize=10,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=10000
        )
    return _mongo_client

async def get_aiohttp_session():
    """Reuse single aiohttp session for all HTTP requests."""
    global _aiohttp_session
    if _aiohttp_session is None or _aiohttp_session.closed:
        timeout = aiohttp.ClientTimeout(total=10, connect=5)
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
        _aiohttp_session = aiohttp.ClientSession(timeout=timeout, connector=connector)
    return _aiohttp_session

# --- 📦 OPTIMIZED DATABASE FUNCTIONS ---
def get_api_keys_db():
    """Get database with persistent connection."""
    client = get_mongo_client()
    return client["ApiKeys"]

# --- API KEY MANAGEMENT ---

@lru_cache(maxsize=1)
def _get_gemini_collection():
    """Cache collection reference using original name."""
    return get_api_keys_db()["gemini_keys"]

def save_gemini_keys(keys: list):
    """Saves a list of key objects."""
    try:
        collection = _get_gemini_collection()
        collection.update_one({"type": "keys"}, {"$set": {"keys": keys}}, upsert=True)
    except Exception as e:
        logger.error(f"Error saving Gemini keys: {e}")

def get_gemini_keys():
    """Retrieves keys and handles migration."""
    try:
        collection = _get_gemini_collection()
        result_doc = collection.find_one({"type": "keys"}, {"keys": 1, "_id": 0})
        if not result_doc:
            return []

        keys_data = result_doc.get("keys", [])
        if not keys_data:
            return []

        # Check the format for migration
        if isinstance(keys_data[0], str):
            logger.info("Old key format detected. Migrating to new object format.")
            migrated_keys = [{"key": key_str, "name": None} for key_str in keys_data]
            save_gemini_keys(migrated_keys)
            return migrated_keys
            
        return keys_data # Already in the new format
            
    except Exception as e:
        logger.error(f"Error getting Gemini keys: {e}")
        return []

# --- AUTHORIZATION MANAGEMENT (NEW) ---

@lru_cache(maxsize=1)
def _get_auth_collection():
    """Cache collection reference for authorized users."""
    return get_api_keys_db()["authorized_users"]

def add_authorized_user(user_id: int):
    """Adds a user's ID to the authorized users collection."""
    try:
        collection = _get_auth_collection()
        # Use _id as the user_id for fast lookup
        collection.update_one(
            {"_id": user_id},
            {"$set": {"authorized": True, "timestamp": datetime.datetime.now()}},
            upsert=True
        )
        # Clear cache to ensure immediate recognition
        is_authorized_user.cache_clear() 
        logger.info(f"User {user_id} authorized.")
    except Exception as e:
        logger.error(f"Error authorizing user {user_id}: {e}")

@lru_cache(maxsize=None) # Cache is cleared on modification
def is_authorized_user(user_id: int) -> bool:
    """Checks if a user's ID is in the authorized users collection."""
    try:
        collection = _get_auth_collection()
        return collection.find_one({"_id": user_id, "authorized": True}) is not None
    except Exception as e:
        logger.error(f"Error checking authorization for user {user_id}: {e}")
        return False

# --- 🔧 ASYNC API KEY TESTING ---
async def test_gemini_key(api_key: str) -> tuple[str, str]:
    """Async API key testing."""
    try:
        session = await get_aiohttp_session()
        params = {"key": api_key}
        data = {"contents": [{"parts": [{"text": "Hi"}]}]}
        async with session.post(GEMINI_API_URL, params=params, json=data) as response:
            if response.status == 200: return "valid", "✅ Valid"
            elif response.status == 429: return "rate_limited", "⚠️ Rate Limited"
            elif response.status in (400, 401, 403): return "invalid", "❌ Invalid"
            else: return "error", f"❓ Error {response.status}"
    except Exception as e:
        return "error", f"❓ Error: {str(e)[:20]}"

async def test_keys_batch(keys: list[str]) -> list:
    """Test multiple key strings concurrently."""
    tasks = [test_gemini_key(key) for key in keys]
    return await asyncio.gather(*tasks)

# --- 🛠️ UTILITY FUNCTIONS ---
def escape_markdown_v2(text: str) -> str:
    """Escapes text for Telegram MarkdownV2."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def parse_key_input(text: str) -> tuple[str | None, str | None]:
    """Parses 'key name' format."""
    # Matches the key format and optionally captures the rest as the name
    match = re.match(r'^\s*(AIza[A-Za-z0-9_-]{35})(?:\s+(.*))?\s*$', text)
    if match:
        key = match.group(1)
        # Only take a name if it's not empty/just whitespace
        name = match.group(2).strip() if match.group(2) else None
        return key, name
    return None, None

def restricted(func):
    """Decorator that checks if the user is authorized."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if is_authorized_user(user_id):
            return await func(update, context)
        else:
            await update.message.reply_text(
                "🚫 **Access Denied**\\. Please use `/start` to authenticate\\.",
                parse_mode='MarkdownV2'
            )
    return wrapper

# --- 🤖 BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    
    if is_authorized_user(user_id):
        total_keys = len(get_gemini_keys())
        help_text = (
            f"👋 **Gemini API Key Manager**\n"
            f"📊 Keys: **{total_keys}**\n\n"
            f"• **To Add:** Send a key in the format:\n`AIza...key... Optional Name`\n"
            f"• `/list` \\- See all keys and their names\n"
            f"• `/test [key|index]` \\- Test all keys, a specific key, or by index\n"
            f"• `/del <index>` \\- Delete a key by index"
        )
        await update.message.reply_text(help_text, parse_mode='MarkdownV2')
    else:
        # Set state for password check
        context.user_data['awaiting_password'] = True
        await update.message.reply_text("🔐 Welcome\\. Please send the **bot password** to gain access\\.", parse_mode='MarkdownV2')


async def authenticate_and_handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles password authentication or, if authorized, processes potential key input."""
    user_id = update.effective_user.id
    text_input = update.message.text.strip()

    # Case 1: Awaiting Password
    if context.user_data.get('awaiting_password'):
        if text_input == BOT_PASSWORD:
            add_authorized_user(user_id)
            del context.user_data['awaiting_password']
            
            await update.message.reply_text("🎉 **Access Granted!** You are now authorized\\. Use `/start` to see the commands\\.", parse_mode='MarkdownV2')
            # Fall through to the start command to show the menu immediately
            await start(update, context) 
        else:
            await update.message.reply_text("❌ Incorrect password\\. Please try again\\.", parse_mode='MarkdownV2')
    
    # Case 2: Already Authorized - treat as potential key input
    elif is_authorized_user(user_id):
        await handle_potential_key(update, context)


@restricted
async def list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keys = get_gemini_keys()
    if not keys:
        await update.message.reply_text("No keys stored\\.", parse_mode='MarkdownV2')
        return
    
    key_lines = []
    for i, entry in enumerate(keys):
        # Apply escape only to the key and name values, not the Markdown syntax
        key_part = escape_markdown_v2(entry['key'])
        name_part = f" \\({escape_markdown_v2(entry['name'])}\\)" if entry.get('name') else ""
        line = f"**{i + 1}\\.** `{key_part}`{name_part}"
        key_lines.append(line)

    response = "🔑 **Stored Keys:**\n\n" + "\n".join(key_lines)
    await update.message.reply_text(response, parse_mode='MarkdownV2')

# This is NOT restricted because it's called by authenticate_and_handle_text, which has auth logic
async def handle_potential_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text_to_parse = update.message.text.strip()
    key, name = parse_key_input(text_to_parse)

    if not key:
        # Do not reply if it's not a key (avoids spamming for every message)
        return

    current_keys = get_gemini_keys()
    if any(entry['key'] == key for entry in current_keys):
        await update.message.reply_text("⚠️ Key already saved\\.", parse_mode='MarkdownV2')
        return

    new_entry = {"key": key, "name": name}
    current_keys.append(new_entry)
    save_gemini_keys(current_keys)

    response = f"✅ Key saved"
    if name:
        response += f" with name **{escape_markdown_v2(name)}**"
    response += "\\."
    await update.message.reply_text(response, parse_mode='MarkdownV2')

@restricted
async def test_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tests all keys, a specific key by index, or a raw key string."""
    args = context.args
    
    # Case 1: No arguments -> Test all keys in the database
    if not args:
        keys = get_gemini_keys()
        if not keys:
            await update.message.reply_text("No keys in DB to test\\. Use `/test <key>` to test one\\.", parse_mode='MarkdownV2')
            return

        msg = await update.message.reply_text("🔄 Testing all stored keys\\.\\.\\.", parse_mode='MarkdownV2')
        
        key_strings_to_test = [entry['key'] for entry in keys]
        results = await test_keys_batch(key_strings_to_test)
        
        response_lines = []
        for i, (entry, (status, result)) in enumerate(zip(keys, results)):
            # Escape parts for MarkdownV2
            key_part = escape_markdown_v2(entry['key'][:20])
            name_part = f" \\({escape_markdown_v2(entry['name'])}\\)" if entry.get('name') else ""
            result_part = escape_markdown_v2(result)
            
            line = f"**{i + 1}\\.** `{key_part}\\.\\.\\.`{name_part}: {result_part}"
            response_lines.append(line)
            
        response = "🔑 **Stored Keys Test Results:**\n\n" + "\n".join(response_lines)
        await msg.edit_text(response, parse_mode='MarkdownV2')
        return

    # Case 2: Argument provided -> could be index or raw key
    argument = args[0]
    
    # Try to interpret as an index first
    try:
        index = int(argument) - 1
        keys = get_gemini_keys()
        if 0 <= index < len(keys):
            entry_to_test = keys[index]
            key_to_test = entry_to_test['key']
            name = entry_to_test.get('name')
            
            msg = await update.message.reply_text(f"🔄 Testing key at index {index + 1}\\.\\.\\.", parse_mode='MarkdownV2')
            status, result_text = await test_gemini_key(key_to_test)
            
            # Escape parts for MarkdownV2
            key_part = escape_markdown_v2(key_to_test)
            name_part = f" \\({escape_markdown_v2(name)}\\)" if name else ""
            result_part = escape_markdown_v2(result_text)

            response = f"🔑 **Test Result \\(Index {index + 1}\\):**\n`{key_part}`{name_part}"
            response += f"\nStatus: {result_part}"
            await msg.edit_text(response, parse_mode='MarkdownV2')
            return
        else:
            await update.message.reply_text(f"⚠️ Index out of range\\. Please use a number from 1 to {len(keys)}\\.", parse_mode='MarkdownV2')
            return
    except ValueError:
        # Not a number, so check if it's a raw API key
        if re.match(r'^AIza[A-Za-z0-9_-]{35}$', argument):
            key_to_test = argument
            
            # Escape parts for MarkdownV2
            key_part_short = escape_markdown_v2(key_to_test[:15])

            msg = await update.message.reply_text(f"🔄 Testing provided key `{key_part_short}...`", parse_mode='MarkdownV2')
            status, result_text = await test_gemini_key(key_to_test)
            
            # Escape parts for MarkdownV2
            key_part_full = escape_markdown_v2(key_to_test)
            result_part = escape_markdown_v2(result_text)

            response = f"🔑 **Ad\\-hoc Test Result:**\n`{key_part_full}`\nStatus: {result_part}"
            await msg.edit_text(response, parse_mode='MarkdownV2')
        else:
            await update.message.reply_text("⚠️ Invalid argument\\. Provide a key index, a full API key, or no argument to test all keys\\.", parse_mode='MarkdownV2')

@restricted
async def del_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Usage:\n`/del <index>`", parse_mode='MarkdownV2')
        return

    try:
        keys = get_gemini_keys()
        index = int(args[0]) - 1
        if 0 <= index < len(keys):
            deleted_entry = keys.pop(index)
            save_gemini_keys(keys)
            
            # Escape parts for MarkdownV2
            key_part = escape_markdown_v2(deleted_entry['key'][:30])
            name_part = f" \\({escape_markdown_v2(deleted_entry['name'])}\\)" if deleted_entry.get('name') else ""
            
            await update.message.reply_text(f"🗑️ Deleted key {index + 1}:\n`{key_part}\\.\\.\\.`{name_part}", parse_mode='MarkdownV2')
        else:
            await update.message.reply_text(f"⚠️ Invalid index\\. Must be 1\\-{len(keys)}\\.", parse_mode='MarkdownV2')
    except (ValueError, IndexError):
        await update.message.reply_text("⚠️ Invalid argument\\. Use an index number\\.", parse_mode='MarkdownV2')

@restricted
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel_action":
        await query.edit_message_text("❌ Action cancelled.", parse_mode='MarkdownV2')
    else:
        await query.edit_message_text("❌ Action not supported or cancelled.", parse_mode='MarkdownV2')


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Start bot and see help (or authenticate)"),
        BotCommand("list", "List keys and their names"),
        BotCommand("test", "Test by key, index, or all"),
        BotCommand("del", "Delete a key by index"),
    ])

def main() -> None:
    # ⚠️ IMPORTANT: Clear the cache on startup to ensure we read the DB for authorized users
    is_authorized_user.cache_clear() 
    
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # --- Handlers for Authentication and Key Management ---
    
    # 1. Start Command (Handles unauthenticated users, prompts for password)
    application.add_handler(CommandHandler("start", start))
    
    # 2. General Text Handler (Handles password attempts AND key inputs from authorized users)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, authenticate_and_handle_text))

    # 3. Protected Command Handlers (Access controlled by @restricted decorator)
    application.add_handler(CommandHandler("list", list_keys))
    application.add_handler(CommandHandler("test", test_key))
    application.add_handler(CommandHandler("del", del_key))
    
    # NOTE: The implicit "add" action is handled by the MessageHandler above.
    
    # 4. Callback Query Handler (Protected)
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # --- End Handlers ---

    logger.info("🚀 Gemini Key Manager Bot is running!")
    application.run_polling()

if __name__ == '__main__':
    main()
