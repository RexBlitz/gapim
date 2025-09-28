import pymongo
import re
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ⚙️ CONFIGURATION ---
BOT_TOKEN = "8493774369:AAFFquaaAtX3FXbsgjNnDLXRogt60GroDyU" 
MONGO_DB_URL = "mongodb+srv://irexanon:xUf7PCf9cvMHy8g6@rexdb.d9rwo.mongodb.net/?retryWrites=true&w=majority&appName=RexDB"
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

# --- 🤖 BOT COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the welcome message with the total key count."""
    total_keys = len(get_gemini_keys())
    help_text = f"""
👋 **Gemini API Key Storage**
📊 Currently storing: **{total_keys}** keys

- Send a message with a key to save it.
- Use `/list` to see all stored keys.
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
