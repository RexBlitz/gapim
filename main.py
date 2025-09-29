import pymongo
import re
import asyncio
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.generativeai.errors import APIError

# --- ⚙️ CONFIGURATION ---
# NOTE: Using placeholder values for security.
# Replace with your actual BOT_TOKEN and MONGO_DB_URL.
BOT_TOKEN = "8493774369:AAFFquaaAtX3FXbsgjNnDLXRogt60GroDyU" 
MONGO_DB_URL = "mongodb-for-security-not-used-here" # Placeholder URL
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

# --- 🔑 GEMINI KEY VALIDATION ---

async def test_key_validity(key: str) -> str:
    """
    Tests a single Gemini API key by making a lightweight API call.
    Returns a status string.
    """
    try:
        client = genai.Client(api_key=key)
        # The list_models() call is a lightweight way to check the key's validity.
        await asyncio.to_thread(client.list_models)
        return "✅ Valid"
    except APIError as e:
        error_message = str(e)
        if "API key not valid" in error_message or "API_KEY_INVALID" in error_message:
            return "❌ Invalid Key"
        elif "quota" in error_message.lower() or "limit" in error_message.lower():
            # Catches quota/rate limit errors
            return "⚠️ Limit Exceeded/Quota Error"
        else:
            # Other API-related errors
            return f"❓ Other API Error: {error_message.splitlines()[0]}"
    except Exception as e:
        # Catch network or other unexpected errors
        return f"🚨 Unknown Error: {e}"

# --- 🤖 BOT COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the welcome message with the total key count."""
    total_keys = len(get_gemini_keys())
    help_text = f"""
👋 **Gemini API Key Storage**
📊 Currently storing: **{total_keys}** keys

- Send a message with a key to save it.
- Use `/list` to see all stored keys.
- Use `/test` to check the validity of all stored keys.
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists all stored keys."""
    keys = get_gemini_keys()
    if not keys:
        await update.message.reply_text("No keys are stored.")
        return
        
    key_lines = [f"**{i + 1}.** `{key}`" for i, key in enumerate(keys)]
        
    response = "🔑 **Stored Keys:**\n\n" + "\n".join(key_lines)
    await update.message.reply_text(response, parse_mode='Markdown')

async def test_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tests all stored keys for validity."""
    keys = get_gemini_keys()
    if not keys:
        await update.message.reply_text("No keys to test.")
        return

    await update.message.reply_text("⏳ **Testing all stored keys...** This might take a moment.")
    
    # Create concurrent tasks to test all keys
    tasks = [test_key_validity(key) for key in keys]
    results = await asyncio.gather(*tasks)

    # Compile the final report
    report_lines = []
    for i, (key, status) in enumerate(zip(keys, results)):
        # Shorten the key for display
        short_key = f"{key[:4]}...{key[-4:]}"
        report_lines.append(f"**{i + 1}.** `{short_key}`: {status}")
        
    response = "🔬 **Key Test Results**\n\n" + "\n".join(report_lines)
    await update.message.reply_text(response, parse_mode='Markdown')

async def handle_potential_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles raw text messages to save keys without validation."""
    message_text = update.message.text.strip()
    
    # Checks for format only (starts with AIza, correct length)
    # NOTE: The pattern for a Google/Gemini API key is usually not 'AIza...'
    # but I'm keeping your original regex: ^AIza[A-Za-z0-9_-]{35}$
    if re.match(r'^AIza[A-Za-z0-9_-]{35}$', message_text):
        key = message_text
        current_keys = get_gemini_keys()

        if key in current_keys:
            await update.message.reply_text("⚠️ That key is already saved.")
            return

        # No validation, just add and save
        current_keys.append(key)
        save_gemini_keys(current_keys)
        await update.message.reply_text("✅ Key saved.")

async def post_init(application: Application) -> None:
    """Sets the bot's command menu after initialization."""
    commands = [
        BotCommand("start", " Start the bot"),
        BotCommand("list", " List all keys"),
        BotCommand("test", " Test validity of all keys"),
    ]
    await application.bot.set_my_commands(commands)

def main() -> None:
    """Sets up and runs the bot."""
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("list", list_keys))
    # ADDED THE NEW COMMAND HANDLER
    application.add_handler(CommandHandler("test", test_keys))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_potential_key))

    print("Gemini Key storage bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
        current_keys = get_gemini_keys()

        if key in current_keys:
            await update.message.reply_text("⚠️ That key is already saved.")
            return

        # No validation, just add and save
        current_keys.append(key)
        save_gemini_keys(current_keys)
        await update.message.reply_text("✅ Key saved.")

async def post_init(application: Application) -> None:
    """Sets the bot's command menu after initialization."""
    commands = [
        BotCommand("start", " Start the bot"),
        BotCommand("list", " List all keys"),
    ]
    await application.bot.set_my_commands(commands)

def main() -> None:
    """Sets up and runs the bot."""
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("list", list_keys))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_potential_key))

    print("Gemini Key storage bot  is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
