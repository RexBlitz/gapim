import pymongo
import re
import requests
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- ⚙️ CONFIGURATION ---
BOT_TOKEN = "8493774369:AAFFquaaAtX3FXbsgjNnDLXRogt60GroDyU"
MONGO_DB_URL = "mongodb+srv://irexanon:xUf7PCf9cvMHy8g6@rexdb.d9rwo.mongodb.net/?retryWrites=true&w=majority&appName=RexDB"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
# -------------------------------------------------------------------------

# --- 📦 DATABASE HELPER FUNCTIONS ---
def get_api_keys_db():
    client = pymongo.MongoClient(MONGO_DB_URL)
    return client["ApiKeys"]

def get_gemini_keys():
    try:
        api_db = get_api_keys_db()
        result = api_db["gemini_keys"].find_one({"type": "keys"})
        if result is None:
            api_db["gemini_keys"].insert_one({"type": "keys", "keys": []})
            return []
        return result.get("keys", [])
    except Exception as e:
        print(f"Error getting Gemini keys: {e}")
        return []

def save_gemini_keys(keys: list):
    try:
        api_db = get_api_keys_db()
        api_db["gemini_keys"].update_one(
            {"type": "keys"}, {"$set": {"keys": keys}}, upsert=True
        )
        print(f"Successfully saved {len(keys)} keys.")
    except Exception as e:
        print(f"Error saving Gemini keys: {e}")

def get_trash_keys():
    try:
        api_db = get_api_keys_db()
        result = api_db["trash_keys"].find_one({"type": "trashed"})
        if result is None:
            api_db["trash_keys"].insert_one({"type": "trashed", "keys": []})
            return []
        return result.get("keys", [])
    except Exception as e:
        print(f"Error getting trash keys: {e}")
        return []

def save_trash_keys(trash_list: list):
    try:
        api_db = get_api_keys_db()
        api_db["trash_keys"].update_one(
            {"type": "trashed"}, {"$set": {"keys": trash_list}}, upsert=True
        )
        print(f"Successfully saved {len(trash_list)} trash keys.")
    except Exception as e:
        print(f"Error saving trash keys: {e}")

# --- 🔧 API KEY TESTING FUNCTION ---
def test_gemini_key(api_key: str) -> tuple[str, str]:
    """Tests a Gemini API key and returns status and message."""
    try:
        headers = {"Content-Type": "application/json"}
        params = {"key": api_key}
        data = {
            "contents": [{"parts": [{"text": "Test"}]}]
        }
        response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=data)
        
        if response.status_code == 200:
            return "valid", "✅ Valid key"
        elif response.status_code == 429:
            return "rate_limited", "⚠️ Rate limit exceeded"
        elif response.status_code == 400 or response.status_code == 401:
            return "invalid", "❌ Invalid key"
        else:
            return "error", f"❓ Error: {response.status_code}"
    except Exception as e:
        return "error", f"❓ Error testing key: {str(e)[:50]}"

# --- 🛠️ MARKDOWN ESCAPING FUNCTION ---
def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram's MarkdownV2 parsing."""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

# --- 🤖 BOT COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the welcome message with the total key count."""
    total_keys = len(get_gemini_keys())
    trash_count = len(get_trash_keys())
    help_text = escape_markdown_v2(
        f"""
👋 **Gemini API Key Storage**
📊 Currently storing: **{total_keys}** keys | Trash: **{trash_count}** keys

- Send a message with a key to save it.
- Use /list to see all stored keys.
- Use /test [index] to test a specific key or all keys.
- Use /trash for trash management.
"""
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')

async def list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists all stored keys."""
    keys = get_gemini_keys()
    if not keys:
        await update.message.reply_text(escape_markdown_v2("No keys are stored."), parse_mode='MarkdownV2')
        return
        
    key_lines = [f"**{i + 1}\\.** `{escape_markdown_v2(key)}`" for i, key in enumerate(keys)]
    response = escape_markdown_v2("🔑 **Stored Keys:**\n\n") + "\n".join(key_lines)
    await update.message.reply_text(response, parse_mode='MarkdownV2')

async def handle_potential_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles raw text messages to save keys without validation."""
    message_text = update.message.text.strip()
    
    # Checks for format only (starts with AIza, correct length)
    if re.match(r'^AIza[A-Za-z0-9_-]{35}$', message_text):
        key = message_text
        current_keys = get_gemini_keys()

        if key in current_keys:
            await update.message.reply_text(escape_markdown_v2("⚠️ That key is already saved."), parse_mode='MarkdownV2')
            return

        # No validation, just add and save
        current_keys.append(key)
        save_gemini_keys(current_keys)
        await update.message.reply_text(escape_markdown_v2("✅ Key saved."), parse_mode='MarkdownV2')

async def test_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tests one or all stored Gemini API keys."""
    keys = get_gemini_keys()
    if not keys:
        await update.message.reply_text(escape_markdown_v2("No keys are stored to test."), parse_mode='MarkdownV2')
        return

    # Check if an index is provided
    args = context.args
    if args:
        try:
            index = int(args[0]) - 1  # Convert to 0-based index
            if 0 <= index < len(keys):
                key = keys[index]
                status, result = test_gemini_key(key)
                trash_keys = get_trash_keys()
                if key in [tk['key'] for tk in trash_keys]:
                    result += " (in trash)"
                await update.message.reply_text(
                    escape_markdown_v2(f"🔑 Testing key {index + 1}: ") + f"`{escape_markdown_v2(key)}`\n{escape_markdown_v2(result)}",
                    parse_mode='MarkdownV2'
                )
            else:
                await update.message.reply_text(
                    escape_markdown_v2(f"⚠️ Invalid index. Please provide a number between 1 and {len(keys)}."),
                    parse_mode='MarkdownV2'
                )
        except ValueError:
            await update.message.reply_text(
                escape_markdown_v2("⚠️ Please provide a valid number for the key index."),
                parse_mode='MarkdownV2'
            )
    else:
        # Test all keys
        results = []
        trash_keys = {tk['key']: tk['status'] for tk in get_trash_keys()}
        for i, key in enumerate(keys):
            status, result = test_gemini_key(key)
            if key in trash_keys:
                result += f" (in trash: {trash_keys[key]})"
            results.append(f"**{i + 1}\\.** `{escape_markdown_v2(key)}`: {escape_markdown_v2(result)}")
        
        response = escape_markdown_v2("🔑 **Test Results for All Keys:**\n\n") + "\n".join(results)
        await update.message.reply_text(response, parse_mode='MarkdownV2')

async def trash_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the trash management menu with inline buttons."""
    keyboard = [
        [InlineKeyboardButton("🗑️ Trash Rate Limit Keys", callback_data="trash_rate")],
        [InlineKeyboardButton("🗑️ Trash Invalid Keys (Permanent)", callback_data="trash_invalid")],
        [InlineKeyboardButton("🔍 Test Trash Keys", callback_data="test_trash")],
        [InlineKeyboardButton("🔄 Restore Keys (If No Longer Limited)", callback_data="restore")],
        [InlineKeyboardButton("📋 View Trash Keys", callback_data="view_trash")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        escape_markdown_v2("🗑️ **Trash Management Menu**\n\nChoose an action below:"), 
        reply_markup=reply_markup, parse_mode='MarkdownV2'
    )

# --- 🗑️ TRASH CALLBACK HANDLERS ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button callbacks from the trash menu."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "trash_rate":
        await handle_trash_rate(query)
    elif data == "trash_invalid":
        await handle_trash_invalid(query)
    elif data == "test_trash":
        await handle_test_trash(query)
    elif data == "restore":
        await handle_restore_confirm(query)
    elif data == "view_trash":
        await handle_view_trash(query)
    elif data.startswith("confirm_"):
        action = data.split("_")[1]
        if action == "trash_rate":
            await confirm_trash_rate(query, True)
        elif action == "trash_invalid":
            await confirm_trash_invalid(query, True)
        elif action == "restore":
            await confirm_restore(query, True)
    elif data.startswith("cancel_"):
        await query.edit_message_text(escape_markdown_v2("❌ Action cancelled. Back to menu."))
        await trash_menu(query, context)

async def handle_trash_rate(query: CallbackQuery) -> None:
    """Handles request to trash rate-limited keys with confirmation."""
    await query.edit_message_text(escape_markdown_v2("⚠️ **Confirm Trash Rate Limit Keys?**\n\nThis will move all currently rate-limited keys to trash. They can be restored later if limits reset."))
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Trash Them!", callback_data="confirm_trash_rate")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_trash_rate")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_reply_markup(reply_markup=reply_markup)

async def confirm_trash_rate(query: CallbackQuery, confirmed: bool) -> None:
    """Confirms and executes trashing rate-limited keys."""
    if not confirmed:
        await query.answer("Cancelled.")
        return
    keys = get_gemini_keys()
    trash_list = get_trash_keys()
    moved = 0
    for key in keys[:]:  # Copy to avoid modification during iteration
        status, _ = test_gemini_key(key)
        if status == "rate_limited":
            keys.remove(key)
            trash_list.append({"key": key, "status": "rate_limited"})
            moved += 1
    save_gemini_keys(keys)
    save_trash_keys(trash_list)
    await query.edit_message_text(escape_markdown_v2(f"✅ Moved {moved} rate-limited keys to trash."))

async def handle_trash_invalid(query: CallbackQuery) -> None:
    """Handles request to trash invalid keys with confirmation."""
    await query.edit_message_text(escape_markdown_v2("⚠️ **Confirm Trash Invalid Keys (Permanent)?**\n\nThis will **permanently** remove invalid keys from storage. No restore!"))
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Permanent Trash!", callback_data="confirm_trash_invalid")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_trash_invalid")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_reply_markup(reply_markup=reply_markup)

async def confirm_trash_invalid(query: CallbackQuery, confirmed: bool) -> None:
    """Confirms and executes permanent trashing of invalid keys."""
    if not confirmed:
        await query.answer("Cancelled.")
        return
    keys = get_gemini_keys()
    trash_list = get_trash_keys()
    moved = 0
    for key in keys[:]:
        status, _ = test_gemini_key(key)
        if status == "invalid":
            keys.remove(key)
            trash_list.append({"key": key, "status": "invalid_permanent"})
            moved += 1
    save_gemini_keys(keys)
    save_trash_keys(trash_list)
    await query.edit_message_text(escape_markdown_v2(f"🗑️ Permanently trashed {moved} invalid keys. Gone forever!"))

async def handle_test_trash(query: CallbackQuery) -> None:
    """Tests all trash keys."""
    trash_list = get_trash_keys()
    if not trash_list:
        await query.edit_message_text(escape_markdown_v2("📭 Trash is empty. Nothing to test!"))
        return
    results = []
    for i, entry in enumerate(trash_list):
        key = entry["key"]
        status, result = test_gemini_key(key)
        results.append(f"**{i + 1}\\.** `{escape_markdown_v2(key)}` \\(Original: {entry['status']}\\)\\: {escape_markdown_v2(result)}")
    response = escape_markdown_v2("🔍 **Trash Keys Test Results:**\n\n") + "\n".join(results)
    await query.edit_message_text(response, parse_mode='MarkdownV2')

async def handle_restore_confirm(query: CallbackQuery) -> None:
    """Handles restore request with confirmation."""
    await query.edit_message_text(escape_markdown_v2("⚠️ **Confirm Restore Keys?**\n\nThis will test trashed keys and restore only those no longer rate-limited. Invalid ones stay trashed."))
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Restore Eligible!", callback_data="confirm_restore")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_restore")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_reply_markup(reply_markup=reply_markup)

async def confirm_restore(query: CallbackQuery, confirmed: bool) -> None:
    """Confirms and executes restore of eligible trash keys."""
    if not confirmed:
        await query.answer("Cancelled.")
        return
    keys = get_gemini_keys()
    trash_list = get_trash_keys()
    restored = 0
    for entry in trash_list[:]:
        key = entry["key"]
        status, _ = test_gemini_key(key)
        if status == "valid" and entry["status"] != "invalid_permanent":
            keys.append(key)
            trash_list.remove(entry)
            restored += 1
    save_gemini_keys(keys)
    save_trash_keys(trash_list)
    await query.edit_message_text(escape_markdown_v2(f"🔄 Restored {restored} eligible keys from trash."))

async def handle_view_trash(query: CallbackQuery) -> None:
    """Views all trash keys."""
    trash_list = get_trash_keys()
    if not trash_list:
        await query.edit_message_text(escape_markdown_v2("📭 Trash is empty."))
        return
    lines = [f"**{i + 1}\\.** `{escape_markdown_v2(entry['key'])}` \\(Status: {entry['status']}\\")" for i, entry in enumerate(trash_list)]
    response = escape_markdown_v2("📋 **Trash Keys:**\n\n") + "\n".join(lines)
    await query.edit_message_text(response, parse_mode='MarkdownV2')

async def post_init(application: Application) -> None:
    """Sets the bot's command menu after initialization."""
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("list", "List all keys"),
        BotCommand("test", "Test a specific key or all keys"),
        BotCommand("trash", "Open trash management"),
    ]
    await application.bot.set_my_commands(commands)

def main() -> None:
    """Sets up and runs the bot."""
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("list", list_keys))
    application.add_handler(CommandHandler("test", test_key))
    application.add_handler(CommandHandler("trash", trash_menu))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_potential_key))

    print("Gemini Key storage bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
