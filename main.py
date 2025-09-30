import pymongo
import re
import aiohttp
import asyncio
import logging
from functools import lru_cache
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- ⚙️ CONFIGURATION ---
BOT_TOKEN = "8493774369:AAFFquaaAtX3FXbsgjNnDLXRogt60GroDyU"
MONGO_DB_URL = "mongodb+srv://irexanon:xUf7PCf9cvMHy8g6@rexdb.d9rwo.mongodb.net/?retryWrites=true&w=majority&appName=RexDB"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

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

@lru_cache(maxsize=1)
def _get_gemini_collection():
    """Cache collection reference using original name."""
    return get_api_keys_db()["gemini_keys"]

@lru_cache(maxsize=1)
def _get_trash_collection():
    """Cache collection reference using original name."""
    return get_api_keys_db()["trash_keys"]

def save_gemini_keys(keys: list):
    """Saves a list of key objects."""
    try:
        collection = _get_gemini_collection()
        collection.update_one({"type": "keys"}, {"$set": {"keys": keys}}, upsert=True)
    except Exception as e:
        logger.error(f"Error saving Gemini keys: {e}")

def get_gemini_keys():
    """
    Retrieves keys and automatically migrates from old format (list of strings)
    to new format (list of objects) if needed.
    """
    try:
        collection = _get_gemini_collection()
        result_doc = collection.find_one({"type": "keys"}, {"keys": 1, "_id": 0})
        if not result_doc:
            return []

        keys_data = result_doc.get("keys", [])
        if not keys_data:
            return []

        # Check the format of the first item to determine if migration is needed
        if isinstance(keys_data[0], str):
            logger.info("Old key format detected. Migrating to new object format.")
            migrated_keys = [{"key": key_str, "name": None} for key_str in keys_data]
            save_gemini_keys(migrated_keys) # Save migrated data back to DB
            return migrated_keys
        
        return keys_data # Already in the new format
        
    except Exception as e:
        logger.error(f"Error getting Gemini keys: {e}")
        return []

def save_trash_keys(trash_list: list):
    """Saves a list of trashed key objects."""
    try:
        collection = _get_trash_collection()
        collection.update_one({"type": "trashed"}, {"$set": {"keys": trash_list}}, upsert=True)
    except Exception as e:
        logger.error(f"Error saving trash keys: {e}")

def get_trash_keys():
    """Retrieves trashed keys and handles backward compatibility."""
    try:
        collection = _get_trash_collection()
        result_doc = collection.find_one({"type": "trashed"}, {"keys": 1, "_id": 0})
        if not result_doc:
            return []

        keys_data = result_doc.get("keys", [])
        if not keys_data:
            return []

        # Check format and migrate if necessary
        if isinstance(keys_data[0], str):
            logger.info("Old trash key format detected. Migrating.")
            migrated_keys = [{"key": key_str, "name": None} for key_str in keys_data]
            save_trash_keys(migrated_keys)
            return migrated_keys
        
        if isinstance(keys_data[0], dict) and 'key' in keys_data[0]:
             return keys_data

        return []

    except Exception as e:
        logger.error(f"Error getting trash keys: {e}")
        return []

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
    match = re.match(r'^\s*(AIza[A-Za-z0-9_-]{35})(?:\s+(.*))?\s*$', text)
    if match:
        key = match.group(1)
        name = match.group(2).strip() if match.group(2) else None
        return key, name
    return None, None

# --- 🤖 BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    total_keys = len(get_gemini_keys())
    trash_count = len(get_trash_keys())
    help_text = (
        f"👋 **Gemini API Key Manager**\n"
        f"📊 Keys: **{total_keys}** \\| Trash: **{trash_count}**\n\n"
        f"• **To Add:** Send a key in the format:\n`AIza...key... Optional Name`\n"
        f"• `/list` \\- See all keys and their names\n"
        f"• `/test [key|index]` \\- Test all keys, a specific key, or by index\n"
        f"• `/del <index|trash>` \\- Delete a key or clear trash\n"
        f"• `/trash` \\- Trash management"
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')

async def list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keys = get_gemini_keys()
    if not keys:
        await update.message.reply_text("No keys stored\\.", parse_mode='MarkdownV2')
        return
    
    key_lines = []
    for i, entry in enumerate(keys):
        line = f"**{i + 1}\\.** `{escape_markdown_v2(entry['key'])}`"
        if entry.get('name'):
            line += f" \\({escape_markdown_v2(entry['name'])}\\)"
        key_lines.append(line)

    response = "🔑 **Stored Keys:**\n\n" + "\n".join(key_lines)
    await update.message.reply_text(response, parse_mode='MarkdownV2')

async def handle_potential_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text_to_parse = update.message.text.strip()
    key, name = parse_key_input(text_to_parse)

    if not key:
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
            line = f"**{i + 1}\\.** `{escape_markdown_v2(entry['key'][:20])}\\.\\.\\.`"
            if entry.get('name'):
                line += f" \\({escape_markdown_v2(entry['name'])}\\)"
            line += f": {escape_markdown_v2(result)}"
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
            
            response = f"🔑 **Test Result \\(Index {index + 1}\\):**\n`{escape_markdown_v2(key_to_test)}`"
            if name:
                response += f" \\({escape_markdown_v2(name)}\\)"
            response += f"\nStatus: {escape_markdown_v2(result_text)}"
            await msg.edit_text(response, parse_mode='MarkdownV2')
            return
        else:
            await update.message.reply_text(f"⚠️ Index out of range\\. Please use a number from 1 to {len(keys)}\\.", parse_mode='MarkdownV2')
            return
    except ValueError:
        # Not a number, so check if it's a raw API key
        if re.match(r'^AIza[A-Za-z0-9_-]{35}$', argument):
            key_to_test = argument
            msg = await update.message.reply_text(f"🔄 Testing provided key `{escape_markdown_v2(key_to_test[:15])}...`", parse_mode='MarkdownV2')
            status, result_text = await test_gemini_key(key_to_test)
            
            response = f"🔑 **Ad\\-hoc Test Result:**\n`{escape_markdown_v2(key_to_test)}`\nStatus: {escape_markdown_v2(result_text)}"
            await msg.edit_text(response, parse_mode='MarkdownV2')
        else:
            await update.message.reply_text("⚠️ Invalid argument\\. Provide a key index, a full API key, or no argument to test all keys\\.", parse_mode='MarkdownV2')


async def del_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Usage:\n`/del <index>`\n`/del trash`", parse_mode='MarkdownV2')
        return

    if args[0].lower() == 'trash':
        if not get_trash_keys():
            await update.message.reply_text("📭 Trash is already empty\\.", parse_mode='MarkdownV2')
            return
        keyboard = [[InlineKeyboardButton("💥 Yes, Delete All Permanently", callback_data="confirm_clear_trash"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]]
        await update.message.reply_text("⚠️ **ARE YOU SURE?**\nThis will permanently delete all keys in the trash\\.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='MarkdownV2')
        return

    try:
        keys = get_gemini_keys()
        index = int(args[0]) - 1
        if 0 <= index < len(keys):
            deleted_entry = keys.pop(index)
            save_gemini_keys(keys)
            
            key_part = escape_markdown_v2(deleted_entry['key'][:30])
            name_part = f" \\({escape_markdown_v2(deleted_entry['name'])}\\)" if deleted_entry.get('name') else ""
            await update.message.reply_text(f"🗑️ Deleted key {index + 1}:\n`{key_part}\\.\\.\\.`{name_part}", parse_mode='MarkdownV2')
        else:
            await update.message.reply_text(f"⚠️ Invalid index\\. Must be 1\\-{len(keys)}\\.", parse_mode='MarkdownV2')
    except (ValueError, IndexError):
        await update.message.reply_text("⚠️ Invalid argument\\. Use an index number or `trash`\\.", parse_mode='MarkdownV2')

async def trash_menu(update_or_query: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("🗑️ Trash Rate Limited", callback_data="trash_rate")],
        [InlineKeyboardButton("🗑️ Trash Invalid (Permanent)", callback_data="trash_invalid")],
        [InlineKeyboardButton("🔍 Test Trash", callback_data="test_trash")],
        [InlineKeyboardButton("🔄 Restore Keys", callback_data="restore")],
        [InlineKeyboardButton("📋 View Trash", callback_data="view_trash")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    menu_text = "🗑️ **Trash Management**\n\nChoose an action:"
    if isinstance(update_or_query, CallbackQuery):
        await update_or_query.edit_message_text(text=menu_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    else:
        await update_or_query.message.reply_text(text=menu_text, reply_markup=reply_markup, parse_mode='MarkdownV2')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    # Simplified router for different button presses
    if data == "trash_rate":
        await query.edit_message_text("Move rate-limited keys to trash?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data="confirm_trash_rate"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]]), parse_mode='MarkdownV2')
    elif data == "confirm_trash_rate":
        await execute_trash_operation(query, context, "rate_limited")
    elif data == "trash_invalid":
        await query.edit_message_text("Permanently delete invalid keys?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data="confirm_trash_invalid"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]]), parse_mode='MarkdownV2')
    elif data == "confirm_trash_invalid":
        await execute_trash_operation(query, context, "invalid")
    elif data == "restore":
        await execute_restore(query, context)
    elif data == "confirm_clear_trash":
        save_trash_keys([])
        await query.edit_message_text("✅ Trash cleared permanently.", parse_mode='MarkdownV2')
    elif data == "cancel_action":
        await query.edit_message_text("❌ Action cancelled.", parse_mode='MarkdownV2')
    else:
        await query.edit_message_text("This action is not yet implemented.", parse_mode='MarkdownV2')

async def execute_trash_operation(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, status_to_trash: str):
    await query.edit_message_text("🔄 Processing\\.\\.\\.", parse_mode='MarkdownV2')
    keys = get_gemini_keys()
    trash_list = get_trash_keys()
    results = await test_keys_batch([entry['key'] for entry in keys])
    
    new_keys, moved_count = [], 0
    for entry, (status, _) in zip(keys, results):
        if status == status_to_trash:
            if status_to_trash == "rate_limited":
                trash_list.append(entry)
            moved_count += 1
        else:
            new_keys.append(entry)
    
    if moved_count > 0:
        save_gemini_keys(new_keys)
        if status_to_trash == "rate_limited":
            save_trash_keys(trash_list)
        
    action_word = "Moved to trash" if status_to_trash == "rate_limited" else "Permanently deleted"
    await query.edit_message_text(f"✅ {action_word} {moved_count} key\\(s\\)\\.", parse_mode='MarkdownV2')
    await trash_menu(query, context)

async def execute_restore(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    await query.edit_message_text("🔄 Testing trash\\.\\.\\.", parse_mode='MarkdownV2')
    live_keys = get_gemini_keys()
    trash_list = get_trash_keys()
    if not trash_list:
        await query.edit_message_text("📭 Trash is empty.", parse_mode='MarkdownV2'); return

    results = await test_keys_batch([entry['key'] for entry in trash_list])
    
    new_trash, restored_count = [], 0
    for entry, (status, _) in zip(trash_list, results):
        if status == "valid":
            live_keys.append(entry)
            restored_count += 1
        else:
            new_trash.append(entry)
            
    if restored_count > 0:
        save_gemini_keys(live_keys)
        save_trash_keys(new_trash)
    
    await query.edit_message_text(f"🔄 Restored {restored_count} key\\(s\\)\\.", parse_mode='MarkdownV2')
    await trash_menu(query, context)

async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Start bot and see help"),
        BotCommand("add", "Add a key with an optional name"),
        BotCommand("list", "List keys and their names"),
        BotCommand("test", "Test by key, index, or all"),
        BotCommand("del", "Delete a key or clear trash"),
        BotCommand("trash", "Trash management"),
    ])

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", list_keys))
    application.add_handler(CommandHandler("test", test_key))
    application.add_handler(CommandHandler("del", del_key))
    application.add_handler(CommandHandler("trash", trash_menu))
    application.add_handler(CommandHandler("add", handle_potential_key))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_potential_key))

    logger.info("🚀 Gemini Key Manager Bot is running!")
    application.run_polling()

if __name__ == '__main__':
    main()

