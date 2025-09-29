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
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

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
    """Cache collection reference."""
    return get_api_keys_db()["gemini_keys"]

@lru_cache(maxsize=1)
def _get_trash_collection():
    """Cache collection reference."""
    return get_api_keys_db()["trash_keys"]

def get_gemini_keys():
    """Optimized key retrieval with caching."""
    try:
        collection = _get_gemini_collection()
        result = collection.find_one({"type": "keys"}, {"keys": 1, "_id": 0})
        return result.get("keys", []) if result else []
    except Exception as e:
        logger.error(f"Error getting Gemini keys: {e}")
        return []

def save_gemini_keys(keys: list):
    """Optimized bulk save operation."""
    try:
        collection = _get_gemini_collection()
        collection.update_one(
            {"type": "keys"}, 
            {"$set": {"keys": keys}}, 
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving Gemini keys: {e}")

def get_trash_keys():
    """Optimized trash key retrieval."""
    try:
        collection = _get_trash_collection()
        result = collection.find_one({"type": "trashed"}, {"keys": 1, "_id": 0})
        return result.get("keys", []) if result else []
    except Exception as e:
        logger.error(f"Error getting trash keys: {e}")
        return []

def save_trash_keys(trash_list: list):
    """Optimized trash save operation."""
    try:
        collection = _get_trash_collection()
        collection.update_one(
            {"type": "trashed"}, 
            {"$set": {"keys": trash_list}}, 
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving trash keys: {e}")

# --- 🔧 ASYNC API KEY TESTING ---
async def test_gemini_key(api_key: str) -> tuple[str, str]:
    """Async API key testing - MUCH FASTER!"""
    try:
        session = await get_aiohttp_session()
        params = {"key": api_key}
        data = {"contents": [{"parts": [{"text": "Hi"}]}]}
        
        async with session.post(GEMINI_API_URL, params=params, json=data) as response:
            status_code = response.status
            
            if status_code == 200:
                return "valid", "✅ Valid"
            elif status_code == 429:
                return "rate_limited", "⚠️ Rate Limited"
            elif status_code in (400, 401, 403):
                return "invalid", "❌ Invalid"
            else:
                return "error", f"❓ Error {status_code}"
    except asyncio.TimeoutError:
        return "error", "❓ Timeout"
    except Exception as e:
        return "error", f"❓ Error: {str(e)[:20]}"

async def test_keys_batch(keys: list) -> list:
    """Test multiple keys concurrently - ULTRA FAST!"""
    tasks = [test_gemini_key(key) for key in keys]
    return await asyncio.gather(*tasks)

# --- 🛠️ OPTIMIZED MARKDOWN ESCAPE ---
_ESCAPE_CHARS = str.maketrans({
    '_': r'\_', '*': r'\*', '[': r'\[', ']': r'\]', '(': r'\(', ')': r'\)',
    '~': r'\~', '`': r'\`', '>': r'\>', '#': r'\#', '+': r'\+', '-': r'\-',
    '=': r'\=', '|': r'\|', '{': r'\{', '}': r'\}', '.': r'\.', '!': r'\!'
})

def escape_markdown_v2(text: str) -> str:
    """Ultra-fast markdown escaping using str.translate."""
    return text.translate(_ESCAPE_CHARS)

# --- 🤖 OPTIMIZED BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lightning-fast start command."""
    total_keys = len(get_gemini_keys())
    trash_count = len(get_trash_keys())
    help_text = (
        f"👋 **Gemini API Key Storage**\n"
        f"📊 Keys: **{total_keys}** \\| Trash: **{trash_count}**\n\n"
        f"• Send a key to save it\n"
        f"• `/list` \\- see all keys\n"
        f"• `/test [index]` \\- test keys\n"
        f"• `/del <index|trash>` \\- delete key or clear trash\n"
        f"• `/trash` \\- trash management"
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')

async def list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Optimized key listing."""
    keys = get_gemini_keys()
    if not keys:
        await update.message.reply_text("No keys stored\\.", parse_mode='MarkdownV2')
        return
    
    # Build response in one go
    key_lines = [f"**{i + 1}\\.** `{escape_markdown_v2(key)}`" for i, key in enumerate(keys)]
    response = "🔑 **Stored Keys:**\n\n" + "\n".join(key_lines)
    await update.message.reply_text(response, parse_mode='MarkdownV2')

async def handle_potential_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ultra-fast key saving without validation."""
    message_text = update.message.text.strip()
    
    if re.match(r'^AIza[A-Za-z0-9_-]{35}$', message_text):
        current_keys = get_gemini_keys()

        if message_text in current_keys:
            await update.message.reply_text("⚠️ Key already saved\\.", parse_mode='MarkdownV2')
            return

        current_keys.append(message_text)
        save_gemini_keys(current_keys)
        await update.message.reply_text("✅ Key saved\\.", parse_mode='MarkdownV2')

async def test_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ULTRA-FAST concurrent key testing!"""
    keys = get_gemini_keys()
    if not keys:
        await update.message.reply_text("No keys to test\\.", parse_mode='MarkdownV2')
        return

    args = context.args
    if args:
        try:
            index = int(args[0]) - 1
            if 0 <= index < len(keys):
                key = keys[index]
                status, result = await test_gemini_key(key)
                await update.message.reply_text(
                    f"🔑 Key {index + 1}: `{escape_markdown_v2(key)}`\n{escape_markdown_v2(result)}",
                    parse_mode='MarkdownV2'
                )
            else:
                await update.message.reply_text(
                    f"⚠️ Index must be 1\\-{len(keys)}\\.",
                    parse_mode='MarkdownV2'
                )
        except ValueError:
            await update.message.reply_text("⚠️ Invalid index\\.", parse_mode='MarkdownV2')
    else:
        # Send "testing..." message
        msg = await update.message.reply_text("🔄 Testing all keys\\.\\.\\.", parse_mode='MarkdownV2')
        
        # Test ALL keys concurrently - BLAZING FAST!
        results = await test_keys_batch(keys)
        
        # Build response
        response_lines = [
            f"**{i + 1}\\.** `{escape_markdown_v2(key[:20])}\\.\\.\\.`: {escape_markdown_v2(result)}"
            for i, (key, (status, result)) in enumerate(zip(keys, results))
        ]
        
        response = "🔑 **Test Results:**\n\n" + "\n".join(response_lines)
        await msg.edit_text(response, parse_mode='MarkdownV2')

async def del_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deletes a key by index or clears the entire trash."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ **Usage:**\n`/del <index>` \\- Deletes one key\n`/del trash` \\- Clears all trash",
            parse_mode='MarkdownV2'
        )
        return

    # Check if the command is to clear the trash
    if args[0].lower() == 'trash':
        if not get_trash_keys():
            await update.message.reply_text("📭 Trash is already empty\\.", parse_mode='MarkdownV2')
            return

        keyboard = [
            [
                InlineKeyboardButton("💥 Yes, Delete All Permanently", callback_data="confirm_clear_trash"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚠️ **ARE YOU SURE?**\n\nThis will permanently delete all keys currently in the trash\\. This action cannot be undone\\.",
            reply_markup=reply_markup,
            parse_mode='MarkdownV2'
        )
        return

    # If not 'trash', proceed with the original logic to delete by index
    try:
        keys = get_gemini_keys()
        if not keys:
            await update.message.reply_text("No keys to delete\\.", parse_mode='MarkdownV2')
            return

        index = int(args[0]) - 1
        if 0 <= index < len(keys):
            deleted_key = keys.pop(index)
            save_gemini_keys(keys)
            await update.message.reply_text(
                f"🗑️ Deleted key {index + 1}:\n`{escape_markdown_v2(deleted_key[:30])}\\.\\.\\.`",
                parse_mode='MarkdownV2'
            )
        else:
            await update.message.reply_text(
                f"⚠️ Invalid index\\. Must be 1\\-{len(keys)}\\.",
                parse_mode='MarkdownV2'
            )
    except ValueError:
        await update.message.reply_text("⚠️ Invalid argument\\. Use an index number or the word `trash`\\.", parse_mode='MarkdownV2')

async def trash_menu(update_or_query: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles displaying the trash menu from either a command or a callback query."""
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
        await update_or_query.edit_message_text(
            text=menu_text,
            reply_markup=reply_markup,
            parse_mode='MarkdownV2'
        )
    else:
        await update_or_query.message.reply_text(
            text=menu_text,
            reply_markup=reply_markup,
            parse_mode='MarkdownV2'
        )

async def execute_clear_trash(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Permanently clears all keys from the trash collection."""
    await query.edit_message_text("🗑️ Clearing trash\\.\\.\\.", parse_mode='MarkdownV2')
    save_trash_keys([]) 
    await query.edit_message_text("✅ Trash has been permanently cleared\\.", parse_mode='MarkdownV2')


# --- 🗑️ OPTIMIZED TRASH HANDLERS ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all button callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "confirm_clear_trash":
        await execute_clear_trash(query, context)
        return
    elif data == "cancel_action":
        await query.edit_message_text("❌ Action cancelled\\.", parse_mode='MarkdownV2')
        return

    handlers_with_context = {
        "trash_rate": handle_trash_rate,
        "trash_invalid": handle_trash_invalid,
        "restore": handle_restore_confirm,
        "confirm_trash_rate": confirm_trash_rate,
        "confirm_trash_invalid": confirm_trash_invalid,
        "confirm_restore": confirm_restore,
    }
    
    handlers_no_context = {
        "test_trash": handle_test_trash,
        "view_trash": handle_view_trash,
    }
    
    if data in handlers_with_context:
        await handlers_with_context[data](query, context)
    elif data in handlers_no_context:
        await handlers_no_context[data](query)
    elif data.startswith("cancel_"):
        await query.edit_message_text("❌ Cancelled\\.", parse_mode='MarkdownV2')
        await trash_menu(query, context)

async def handle_trash_rate(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show confirmation for rate-limited keys."""
    await query.edit_message_text(
        "⚠️ **Confirm?**\n\nTrash rate\\-limited keys\\. Can restore later\\.",
        parse_mode='MarkdownV2',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes", callback_data="confirm_trash_rate")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_trash_rate")]
        ])
    )

async def confirm_trash_rate(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute trash rate-limited - WITH CONCURRENT TESTING!"""
    await query.edit_message_text("🔄 Processing\\.\\.\\.", parse_mode='MarkdownV2')
    
    keys = get_gemini_keys()
    trash_list = get_trash_keys()
    
    results = await test_keys_batch(keys)
    
    moved = 0
    new_keys = []
    for key, (status, _) in zip(keys, results):
        if status == "rate_limited":
            trash_list.append({"key": key, "status": "rate_limited"})
            moved += 1
        else:
            new_keys.append(key)
    
    save_gemini_keys(new_keys)
    save_trash_keys(trash_list)
    
    await query.edit_message_text(f"✅ Moved {moved} keys to trash\\.", parse_mode='MarkdownV2')
    await trash_menu(query, context)

async def handle_trash_invalid(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show confirmation for invalid keys."""
    await query.edit_message_text(
        "⚠️ **Permanent Delete?**\n\nInvalid keys gone forever\\!",
        parse_mode='MarkdownV2',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes", callback_data="confirm_trash_invalid")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_trash_invalid")]
        ])
    )

async def confirm_trash_invalid(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute trash invalid - PERMANENTLY DELETE, NOT SAVE!"""
    await query.edit_message_text("🔄 Processing\\.\\.\\.", parse_mode='MarkdownV2')
    
    keys = get_gemini_keys()
    results = await test_keys_batch(keys)
    
    deleted = 0
    new_keys = []
    for key, (status, _) in zip(keys, results):
        if status == "invalid":
            deleted += 1
        else:
            new_keys.append(key)
    
    save_gemini_keys(new_keys)
    
    await query.edit_message_text(f"🗑️ Permanently deleted {deleted} invalid keys\\!", parse_mode='MarkdownV2')
    await trash_menu(query, context)

async def handle_test_trash(query: CallbackQuery) -> None:
    """Test trash keys concurrently."""
    trash_list = get_trash_keys()
    if not trash_list:
        await query.edit_message_text("📭 Trash empty\\.", parse_mode='MarkdownV2')
        return
    
    await query.edit_message_text("🔄 Testing\\.\\.\\.", parse_mode='MarkdownV2')
    
    keys = [entry["key"] for entry in trash_list]
    results = await test_keys_batch(keys)
    
    response_lines = [
        f"**{i + 1}\\.** `{escape_markdown_v2(key[:20])}\\.\\.\\.`: {escape_markdown_v2(result)}"
        for i, (entry, (status, result)) in enumerate(zip(trash_list, results))
        for key in [entry["key"]]
    ]
    
    response = "🔍 **Trash Test:**\n\n" + "\n".join(response_lines)
    await query.edit_message_text(response, parse_mode='MarkdownV2')

async def handle_restore_confirm(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show restore confirmation."""
    await query.edit_message_text(
        "⚠️ **Confirm Restore?**\n\nTest and restore valid keys\\.",
        parse_mode='MarkdownV2',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes", callback_data="confirm_restore")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_restore")]
        ])
    )

async def confirm_restore(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute restore with concurrent testing."""
    await query.edit_message_text("🔄 Testing trash\\.\\.\\.", parse_mode='MarkdownV2')
    
    keys = get_gemini_keys()
    trash_list = get_trash_keys()
    
    if not trash_list:
        await query.edit_message_text("📭 Trash is empty\\!", parse_mode='MarkdownV2')
        await trash_menu(query, context)
        return
    
    trash_keys = [entry["key"] for entry in trash_list]
    results = await test_keys_batch(trash_keys)
    
    restored = 0
    new_trash = []
    for entry, (status, _) in zip(trash_list, results):
        if status == "valid":
            keys.append(entry["key"])
            restored += 1
        else:
            new_trash.append(entry)
    
    save_gemini_keys(keys)
    save_trash_keys(new_trash)
    
    await query.edit_message_text(f"🔄 Restored {restored} keys\\!", parse_mode='MarkdownV2')
    await trash_menu(query, context)

async def handle_view_trash(query: CallbackQuery) -> None:
    """View trash keys."""
    trash_list = get_trash_keys()
    if not trash_list:
        await query.edit_message_text("📭 Trash empty\\.", parse_mode='MarkdownV2')
        return
    
    lines = [
        f"**{i + 1}\\.** `{escape_markdown_v2(entry['key'][:25])}\\.\\.\\.` \\({escape_markdown_v2(entry['status'])}\\)"
        for i, entry in enumerate(trash_list)
    ]
    response = "📋 **Trash Keys:**\n\n" + "\n".join(lines)
    await query.edit_message_text(response, parse_mode='MarkdownV2')

async def post_init(application: Application) -> None:
    """Set bot commands."""
    commands = [
        BotCommand("start", "Start bot"),
        BotCommand("list", "List keys"),
        BotCommand("test", "Test keys"),
        BotCommand("del", "Delete key or clear trash"),
        BotCommand("trash", "Trash management"),
    ]
    await application.bot.set_my_commands(commands)

def main() -> None:
    """Run the bot."""
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("list", list_keys))
    application.add_handler(CommandHandler("test", test_key))
    application.add_handler(CommandHandler("del", del_key))
    application.add_handler(CommandHandler("trash", trash_menu))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_potential_key))

    logger.info("🚀 Gemini Api Key Manager bot running!")
    
    try:
        application.run_polling()
    finally:
        # Cleanup on exit
        if _aiohttp_session and not _aiohttp_session.closed:
            asyncio.run(_aiohttp_session.close())
        if _mongo_client:
            _mongo_client.close()

if __name__ == '__main__':
    main()
