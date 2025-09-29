import pymongo
import re
import requests  # Added for API testing
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ⚙️ CONFIGURATION ---
BOT_TOKEN = "8493774369:AAFFquaaAtX3FXbsgjNnDLXRogt60GroDyU"
MONGO_DB_URL = "mongodb+srv://irexanon:xUf7PCf9cvMHy8g6@rexdb.d9rwo.mongodb.net/?retryWrites=true&w=majority&appName=RexDB"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"  # Gemini API endpoint
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

# --- 🔧 API KEY TESTING FUNCTION ---
def test_gemini_key(api_key: str) -> str:
    """Tests a Gemini API key by making a simple request."""
    try:
        headers = {"Content-Type": "application/json"}
        params = {"key": api_key}
        data = {
            "contents": [{"parts": [{"text": "Test"}]}]
        }
        response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=data)
        
        if response.status_code == 200:
            return "✅ Valid key"
        elif response.status_code == 429:
            return "⚠️ Rate limit exceeded"
        elif response.status_code == 400 or response.status_code == 401:
            return "❌ Invalid key"
        else:
            return f"❓ Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"❓ Error testing key: {str(e)}"

# --- 🤖 BOT COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the welcome message with the total key count."""
    total_keys = len(get_gemini_keys())
    help_text = f"""
👋 **Gemini API Key Storage**
📊 Currently storing: **{total_keys}** keys

- Send a message with a key to save it.
- Use `/list` to see all stored keys.
- Use `/test [index]` to test a specific key or all keys.
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

async def handle_potential_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles raw text messages to save keys without validation."""
    message_text = update.message.text.strip()
    
    # Checks for format only (starts with AIza, correct length)
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

async def test_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tests one or all stored Gemini API keys."""
    keys = get_gemini_keys()
    if not keys:
        await update.message.reply_text("No keys are stored to test.")
        return

    # Check if an index is provided
    args = context.args
    if args:
        try:
            index = int(args[0]) - 1  # Convert to 0-based index
            if 0 <= index < len(keys):
                key = keys[index]
                result = test_gemini_key(key)
                await update.message.reply_text(
                    f"🔑 Testing key {index + 1}: `{key}`\n{result}",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    f"⚠️ Invalid index. Please provide a number between 1 and {len(keys)}."
                )
        except ValueError:
            await update.message.reply_text("⚠️ Please provide a valid number for the key index.")
    else:
        # Test all keys
        results = []
        for i, key in enumerate(keys):
            result = test_gemini_key(key)
            results.append(f"**{i + 1}.** `{key}`: {result}")
        
        response = "🔑 **Test Results for All Keys:**\n\n" + "\n".join(results)
        await update.message.reply_text(response, parse_mode='Markdown')

async def post_init(application: Application) -> None:
    """Sets the bot's command menu after initialization."""
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("list", "List all keys"),
        BotCommand("test", "Test a specific key or all keys"),  # Added test command
    ]
    await application.bot.set_my_commands(commands)

def main() -> None:
    """Sets up and runs the bot."""
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("list", list_keys))
    application.add_handler(CommandHandler("test", test_key))  # Added test command handler
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_potential_key))

    print("Gemini Key storage bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
