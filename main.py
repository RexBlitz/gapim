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
            save_gemini_keys(migrated_keys)
            return migrated_keys
        
        return keys_data
        
    except Exception as e:
        logger.error(f"Error getting Gemini keys: {e}")
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

def parse_batch_keys(text: str) -> list[str]:
    """Parse keys separated by comma, space, or newline."""
    # Split by comma, space, or newline
    keys = re.split(r'[,\s\n]+', text.strip())
    # Filter valid API keys
    valid_keys = [k for k in keys if re.match(r'^AIza[A-Za-z0-9_-]{35}$', k)]
    return valid_keys

# --- 🤖 BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    total_keys = len(get_gemini_keys())
    help_text = (
        f"👋 **Gemini API Key Manager**\n"
        f"📊 Keys: **{total_keys}**\n\n"
        f"**Single Key Operations:**\n"
        f"• Send: `AIza...key... Optional Name`\n"
        f"• `/list` \\- See all keys\n"
        f"• `/test [key|index]` \\- Test keys\n"
        f"• `/del <index>` \\- Delete by index\n\n"
        f"**Batch Operations:**\n"
        f"• `/add batch <name> <key1>,<key2>,...`\n"
        f"  _Keys named: name1, name2, etc\\._\n"
        f"• `/del batch <name>` \\- Delete all keys with that batch name"
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')

async def list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keys = get_gemini_keys()
    if not keys:
        await update.message.reply_text("No keys stored\\.", parse_mode='MarkdownV2')
        return
    
    key_lines = []
    for i, entry in enumerate(keys):
        line = f"**{i + 1}\\.** `{escape_markdown_v2(entry['key'][:25])}\\.\\.\\.`"
        if entry.get('name'):
            line += f" \\- _{escape_markdown_v2(entry['name'])}_"
        key_lines.append(line)

    response = "🔑 **Stored Keys:**\n\n" + "\n".join(key_lines)
    await update.message.reply_text(response, parse_mode='MarkdownV2')

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add command for both single and batch operations."""
    if not context.args:
        await update.message.reply_text(
            "**Usage:**\n"
            "• `/add <key> [name]` \\- Add single key\n"
            "• `/add batch <batch_name> <key1>,<key2>,...` \\- Add multiple keys",
            parse_mode='MarkdownV2'
        )
        return
    
    # Check if it's a batch operation
    if context.args[0].lower() == "batch":
        if len(context.args) < 3:
            await update.message.reply_text(
                "⚠️ Usage: `/add batch <batch_name> <key1>,<key2>,...`",
                parse_mode='MarkdownV2'
            )
            return
        
        batch_name = context.args[1]
        keys_text = " ".join(context.args[2:])
        keys_to_add = parse_batch_keys(keys_text)
        
        if not keys_to_add:
            await update.message.reply_text("⚠️ No valid keys found\\.", parse_mode='MarkdownV2')
            return
        
        current_keys = get_gemini_keys()
        added_count = 0
        duplicate_count = 0
        
        for idx, key in enumerate(keys_to_add, 1):
            if any(entry['key'] == key for entry in current_keys):
                duplicate_count += 1
                continue
            
            new_entry = {"key": key, "name": f"{batch_name}{idx}"}
            current_keys.append(new_entry)
            added_count += 1
        
        save_gemini_keys(current_keys)
        
        response = f"✅ Batch **{escape_markdown_v2(batch_name)}**: Added **{added_count}** keys"
        if duplicate_count > 0:
            response += f" \\({duplicate_count} duplicates skipped\\)"
        response += "\\."
        await update.message.reply_text(response, parse_mode='MarkdownV2')
    
    else:
        # Single key addition
        key_text = " ".join(context.args)
        key, name = parse_key_input(key_text)
        
        if not key:
            await update.message.reply_text("⚠️ Invalid key format\\.", parse_mode='MarkdownV2')
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

    argument = args[0]
    
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
        if re.match(r'^AIza[A-Za-z0-9_-]{35}$', argument):
            key_to_test = argument
            msg = await update.message.reply_text(f"🔄 Testing provided key `{escape_markdown_v2(key_to_test[:15])}...`", parse_mode='MarkdownV2')
            status, result_text = await test_gemini_key(key_to_test)
            
            response = f"🔑 **Ad\\-hoc Test Result:**\n`{escape_markdown_v2(key_to_test)}`\nStatus: {escape_markdown_v2(result_text)}"
            await msg.edit_text(response, parse_mode='MarkdownV2')
        else:
            await update.message.reply_text("⚠️ Invalid argument\\. Provide a key index, a full API key, or no argument to test all keys\\.", parse_mode='MarkdownV2')

async def del_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a single key by index or all keys in a batch by name."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "**Usage:**\n"
            "• `/del <index>` \\- Delete by index\n"
            "• `/del batch <batch_name>` \\- Delete all keys with batch name",
            parse_mode='MarkdownV2'
        )
        return
    
    # Check if it's a batch deletion
    if args[0].lower() == "batch":
        if len(args) < 2:
            await update.message.reply_text(
                "⚠️ Usage: `/del batch <batch_name>`",
                parse_mode='MarkdownV2'
            )
            return
        
        batch_name = args[1]
        keys = get_gemini_keys()
        
        # Find all keys that start with the batch name followed by a number
        keys_to_delete = []
        remaining_keys = []
        
        for entry in keys:
            if entry.get('name') and entry['name'].startswith(batch_name):
                # Check if the remaining part after batch_name is a number
                suffix = entry['name'][len(batch_name):]
                if suffix.isdigit():
                    keys_to_delete.append(entry)
                else:
                    remaining_keys.append(entry)
            else:
                remaining_keys.append(entry)
        
        if not keys_to_delete:
            await update.message.reply_text(
                f"⚠️ No keys found with batch name **{escape_markdown_v2(batch_name)}**\\.",
                parse_mode='MarkdownV2'
            )
            return
        
        save_gemini_keys(remaining_keys)
        
        await update.message.reply_text(
            f"🗑️ Deleted **{len(keys_to_delete)}** keys from batch **{escape_markdown_v2(batch_name)}**\\.",
            parse_mode='MarkdownV2'
        )
    
    else:
        # Single key deletion by index
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
            await update.message.reply_text("⚠️ Invalid argument\\. Use an index number\\.", parse_mode='MarkdownV2')

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
        BotCommand("start", "Start bot and see help"),
        BotCommand("add", "Add key(s) - single or batch"),
        BotCommand("list", "List all keys"),
        BotCommand("test", "Test keys by index or all"),
        BotCommand("del", "Delete by index or batch"),
    ])

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("list", list_keys))
    application.add_handler(CommandHandler("test", test_key))
    application.add_handler(CommandHandler("del", del_key))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_potential_key))

    logger.info("🚀 Gemini Key Manager Bot is running!")
    application.run_polling()

if __name__ == '__main__':
    main()
