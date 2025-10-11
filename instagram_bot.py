import os
import logging
import time
import asyncio
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired, ChallengeRequired, LoginRequired

# --- Configuration ---
# It's recommended to use environment variables for sensitive data like bot tokens.
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8297692816:AAE9-ELN52UJ_uA9WM1L_yOH-n4t0I9kfKI')
DELAY_BETWEEN_ACTIONS = 4

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Conversation States ---
USERNAME, PASSWORD, TWO_FACTOR_CODE, CHALLENGE_CODE, WAITING_ACTION, TARGET_USERNAME = range(6)

# --- In-memory Storage (for simplicity) ---
# In a larger application, consider using a database.
user_sessions = {}
instagram_clients = {}
active_processes = {}

# --- Helper Functions ---
def get_client(user_id):
    """Retrieves or creates an Instagram client instance for a user."""
    if user_id not in instagram_clients:
        instagram_clients[user_id] = Client()
    return instagram_clients[user_id]

def show_main_menu():
    """Returns the main menu keyboard."""
    keyboard = [
        ['➖ Unfollow Someone', '🚫 Remove Follower'],
        ['🔥 Remove ALL Followers', '🔥 Unfollow ALL'],
        ['📊 Account Info', '❌ Logout']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def show_stop_menu():
    """Returns the menu for stopping a running process."""
    keyboard = [['⛔ STOP PROCESS'], ['📊 Check Progress']]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def stop_active_process(user_id):
    """Flags the active process for a user to stop."""
    if user_id in active_processes:
        active_processes[user_id]['should_stop'] = True
        return True
    return False

# --- Asynchronous Background Tasks ---
# These functions run in separate threads to avoid blocking the bot.

def mass_remove_followers_sync(user_id, bot_token, chat_id):
    """Synchronous wrapper to run the async mass remove function."""
    asyncio.run(mass_remove_followers(user_id, bot_token, chat_id))

async def mass_remove_followers(user_id, bot_token, chat_id):
    """Handles the logic for removing all followers."""
    from telegram import Bot
    bot = Bot(token=bot_token)
    cl = get_client(user_id)
    
    try:
        active_processes[user_id] = {'should_stop': False, 'action': 'remove_followers', 'count': 0, 'total': 0, 'failed': 0}
        
        await bot.send_message(chat_id=chat_id, text="🔄 *Fetching followers... this might take a moment.*", parse_mode='Markdown')
        
        followers = cl.user_followers(cl.user_id)
        total_followers = len(followers)
        active_processes[user_id]['total'] = total_followers
        
        if total_followers == 0:
            await bot.send_message(chat_id=chat_id, text="ℹ️ You have no followers to remove.", reply_markup=show_main_menu())
            del active_processes[user_id]
            return
        
        await bot.send_message(
            chat_id=chat_id,
            text=f"🔥 *Starting Mass Follower Removal*\n\n📊 Total: *{total_followers}*\n⏱️ Estimated Time: *{(total_followers * DELAY_BETWEEN_ACTIONS) / 60:.1f} minutes*",
            parse_mode='Markdown',
            reply_markup=show_stop_menu()
        )
        
        count = 0
        failed = 0
        
        for uid, user_info in followers.items():
            if active_processes.get(user_id, {}).get('should_stop', False):
                await bot.send_message(chat_id=chat_id, text=f"⛔ *Process Stopped*\n\n✅ Removed: *{count}*\n❌ Failed: *{failed}*", parse_mode='Markdown', reply_markup=show_main_menu())
                del active_processes[user_id]
                return
            
            try:
                if cl.user_remove_follower(uid):
                    count += 1
                    active_processes[user_id]['count'] = count
                    logger.info(f"User {user_id} removed follower {user_info.username} ({count}/{total_followers})")
                    time.sleep(DELAY_BETWEEN_ACTIONS)
                else:
                    raise Exception(f"Failed to remove {user_info.username}")
            except Exception as e:
                logger.error(f"Failed to remove follower for user {user_id}: {e}")
                failed += 1
                active_processes[user_id]['failed'] = failed
                time.sleep(2) # Shorter delay on failure
        
        await bot.send_message(chat_id=chat_id, text=f"✅ *Mass Removal Complete!*\n\n✅ Removed: *{count}*\n❌ Failed: *{failed}*", parse_mode='Markdown', reply_markup=show_main_menu())
        del active_processes[user_id]
        
    except Exception as e:
        logger.error(f"Error in mass_remove_followers for user {user_id}: {e}")
        await bot.send_message(chat_id=chat_id, text=f"❌ An unexpected error occurred: `{str(e)}`", parse_mode='Markdown', reply_markup=show_main_menu())
        if user_id in active_processes:
            del active_processes[user_id]


def mass_unfollow_all_sync(user_id, bot_token, chat_id):
    """Synchronous wrapper to run the async mass unfollow function."""
    asyncio.run(mass_unfollow_all(user_id, bot_token, chat_id))

async def mass_unfollow_all(user_id, bot_token, chat_id):
    """Handles the logic for unfollowing all users."""
    from telegram import Bot
    bot = Bot(token=bot_token)
    cl = get_client(user_id)
    
    try:
        active_processes[user_id] = {'should_stop': False, 'action': 'unfollow_all', 'count': 0, 'total': 0, 'failed': 0}
        
        await bot.send_message(chat_id=chat_id, text="🔄 *Fetching your following list...*", parse_mode='Markdown')
        
        following = cl.user_following(cl.user_id)
        total_following = len(following)
        active_processes[user_id]['total'] = total_following
        
        if total_following == 0:
            await bot.send_message(chat_id=chat_id, text="ℹ️ You are not following anyone.", reply_markup=show_main_menu())
            del active_processes[user_id]
            return
        
        await bot.send_message(
            chat_id=chat_id,
            text=f"🔥 *Starting Mass Unfollow*\n\n📊 Total: *{total_following}*\n⏱️ Estimated Time: *{(total_following * DELAY_BETWEEN_ACTIONS) / 60:.1f} minutes*",
            parse_mode='Markdown',
            reply_markup=show_stop_menu()
        )
        
        count = 0
        failed = 0
        
        for uid, user_info in following.items():
            if active_processes.get(user_id, {}).get('should_stop', False):
                await bot.send_message(chat_id=chat_id, text=f"⛔ *Process Stopped*\n\n✅ Unfollowed: *{count}*\n❌ Failed: *{failed}*", parse_mode='Markdown', reply_markup=show_main_menu())
                del active_processes[user_id]
                return
            
            try:
                if cl.user_unfollow(uid):
                    count += 1
                    active_processes[user_id]['count'] = count
                    logger.info(f"User {user_id} unfollowed {user_info.username} ({count}/{total_following})")
                    time.sleep(DELAY_BETWEEN_ACTIONS)
                else:
                    raise Exception(f"Failed to unfollow {user_info.username}")
            except Exception as e:
                logger.error(f"Failed to unfollow for user {user_id}: {e}")
                failed += 1
                active_processes[user_id]['failed'] = failed
                time.sleep(2)
        
        await bot.send_message(chat_id=chat_id, text=f"✅ *Mass Unfollow Complete!*\n\n✅ Unfollowed: *{count}*\n❌ Failed: *{failed}*", parse_mode='Markdown', reply_markup=show_main_menu())
        del active_processes[user_id]
        
    except Exception as e:
        logger.error(f"Error in mass_unfollow_all for user {user_id}: {e}")
        await bot.send_message(chat_id=chat_id, text=f"❌ An unexpected error occurred: `{str(e)}`", parse_mode='Markdown', reply_markup=show_main_menu())
        if user_id in active_processes:
            del active_processes[user_id]

# --- Conversation Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the conversation and asks for the Instagram username."""
    user_id = update.effective_user.id
    if user_id in instagram_clients and instagram_clients[user_id].user_id:
        await update.message.reply_text(
            "ℹ️ You are already logged in.",
            reply_markup=show_main_menu()
        )
        return WAITING_ACTION
    
    await update.message.reply_text(
        "🔐 *Welcome to the Instagram Manager Bot*\n\nPlease enter your Instagram username:",
        parse_mode='Markdown'
    )
    user_sessions[user_id] = {}
    return USERNAME

async def receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stores the username and asks for the password."""
    user_id = update.effective_user.id
    username = update.message.text.strip()
    user_sessions[user_id]['username'] = username
    await update.message.reply_text(
        f"✅ Username: *{username}*\n\nNow, please enter your password:",
        parse_mode='Markdown'
    )
    return PASSWORD

async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attempts to log in with the provided credentials."""
    user_id = update.effective_user.id
    password = update.message.text.strip()
    username = user_sessions[user_id]['username']
    
    # Delete the password message for security
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception as e:
        logger.warning(f"Could not delete password message: {e}")
    
    msg = await update.message.reply_text("🔄 *Logging in, please wait...*", parse_mode='Markdown')
    cl = get_client(user_id)
    
    try:
        cl.login(username, password)
        await msg.delete()
        
        account = cl.account_info()
        await update.message.reply_text(
            f"✅ *Login Successful!*\n\n👤 Welcome, @{account.username}\n👥 Followers: {account.follower_count:,}\n➡️ Following: {account.following_count:,}",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        return WAITING_ACTION
        
    except TwoFactorRequired:
        await msg.delete()
        await update.message.reply_text("🔐 *Two-Factor Authentication Required*\n\nPlease enter the 6-digit code from your authenticator app:", parse_mode='Markdown')
        user_sessions[user_id]['password'] = password
        return TWO_FACTOR_CODE
        
    except ChallengeRequired:
        await msg.delete()
        # Storing challenge details to re-login after code verification
        user_sessions[user_id]['password'] = password
        await update.message.reply_text("⚠️ *Verification Required*\n\nInstagram has sent a verification code to your email or phone. Please enter it here:", parse_mode='Markdown')
        return CHALLENGE_CODE
        
    except Exception as e:
        await msg.delete()
        await update.message.reply_text(f"❌ Login failed: `{str(e)}`\n\nPlease try again by using /start.", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

async def receive_2fa_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles 2FA code submission."""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    username = user_sessions[user_id]['username']
    password = user_sessions[user_id]['password']
    
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete 2FA code message: {e}")
    
    msg = await update.message.reply_text("🔄 *Verifying 2FA code...*", parse_mode='Markdown')
    cl = get_client(user_id)
    
    try:
        cl.login(username, password, verification_code=code)
        user_sessions[user_id].pop('password', None) # Clear password after use
        await msg.delete()
        
        account = cl.account_info()
        await update.message.reply_text(f"✅ *Login Successful!*\n\nWelcome, @{account.username}", parse_mode='Markdown', reply_markup=show_main_menu())
        return WAITING_ACTION
    except Exception as e:
        await msg.delete()
        await update.message.reply_text(f"❌ 2FA Verification Failed: `{str(e)}`\nPlease use /start to try again.", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

async def receive_challenge_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles challenge code submission."""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    username = user_sessions[user_id]['username']
    password = user_sessions[user_id]['password']

    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete challenge code message: {e}")

    msg = await update.message.reply_text("🔄 *Verifying challenge code...*", parse_mode='Markdown')
    cl = get_client(user_id)
    
    try:
        # After a challenge, you must re-login with the original credentials
        # The instagrapi client handles the challenge state internally.
        cl.login(username, password)
        user_sessions[user_id].pop('password', None) # Clear password after use
        await msg.delete()
        
        account = cl.account_info()
        await update.message.reply_text(f"✅ *Verification Successful!*\n\nWelcome back, @{account.username}", parse_mode='Markdown', reply_markup=show_main_menu())
        return WAITING_ACTION
    except Exception as e:
        await msg.delete()
        await update.message.reply_text(f"❌ Challenge Verification Failed: `{str(e)}`\nPlease use /start to try again.", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END


async def handle_menu_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all actions from the main menu."""
    user_id = update.effective_user.id
    choice = update.message.text
    cl = get_client(user_id)
    
    try:
        if choice == '⛔ STOP PROCESS':
            if user_id in active_processes:
                stop_active_process(user_id)
                await update.message.reply_text("⏸️ *Sending stop signal...* The process will halt after its current action.", parse_mode='Markdown')
            else:
                await update.message.reply_text("ℹ️ You have no processes running.", reply_markup=show_main_menu())
            return WAITING_ACTION
        
        if choice == '📊 Check Progress':
            if user_id in active_processes:
                proc = active_processes[user_id]
                action_text = "Removing followers" if proc['action'] == 'remove_followers' else "Unfollowing users"
                progress_percent = (proc['count'] / proc['total'] * 100) if proc['total'] > 0 else 0
                await update.message.reply_text(
                    f"📊 *Current Task: {action_text}*\n\nProgress: *{proc['count']}/{proc['total']}* ({progress_percent:.1f}%)\nFailed: *{proc['failed']}*",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text("ℹ️ You have no processes running.", reply_markup=show_main_menu())
            return WAITING_ACTION
        
        if choice == '➖ Unfollow Someone':
            context.user_data['action'] = 'unfollow'
            await update.message.reply_text("Please enter the Instagram username you want to unfollow (e.g., `instagram`):", parse_mode='Markdown')
            return TARGET_USERNAME
            
        elif choice == '🚫 Remove Follower':
            context.user_data['action'] = 'remove'
            await update.message.reply_text("Please enter the Instagram username of the follower you want to remove (e.g., `instagram`):", parse_mode='Markdown')
            return TARGET_USERNAME
        
        elif choice == '🔥 Remove ALL Followers':
            keyboard = [['✅ Yes, REMOVE ALL', '❌ No, Cancel']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            account = cl.account_info()
            await update.message.reply_text(f"⚠️ *ARE YOU SURE?*\n\nThis will permanently remove all *{account.follower_count:,}* of your followers. This action cannot be undone.", reply_markup=reply_markup, parse_mode='Markdown')
            return WAITING_ACTION
        
        elif choice == '🔥 Unfollow ALL':
            keyboard = [['✅ Yes, UNFOLLOW ALL', '❌ No, Cancel']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            account = cl.account_info()
            await update.message.reply_text(f"⚠️ *ARE YOU SURE?*\n\nThis will unfollow all *{account.following_count:,}* users. This action cannot be undone.", reply_markup=reply_markup, parse_mode='Markdown')
            return WAITING_ACTION
        
        elif choice == '✅ Yes, REMOVE ALL':
            await update.message.reply_text("🚀 *Initializing mass follower removal...*", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
            # Run the blocking operation in a separate thread
            thread = Thread(target=mass_remove_followers_sync, args=(user_id, TELEGRAM_BOT_TOKEN, update.effective_chat.id))
            thread.daemon = True
            thread.start()
            return WAITING_ACTION
        
        elif choice == '✅ Yes, UNFOLLOW ALL':
            await update.message.reply_text("🚀 *Initializing mass unfollow...*", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
            thread = Thread(target=mass_unfollow_all_sync, args=(user_id, TELEGRAM_BOT_TOKEN, update.effective_chat.id))
            thread.daemon = True
            thread.start()
            return WAITING_ACTION
        
        elif choice in ['❌ No, Cancel', '❌ Cancel']:
            await update.message.reply_text("✅ Action cancelled.", reply_markup=show_main_menu())
            return WAITING_ACTION
            
        elif choice == '📊 Account Info':
            account = cl.account_info()
            await update.message.reply_text(
                f"📊 *Account Info*\n\n👤 Username: @{account.username}\n"
                f"📝 Full Name: {account.full_name}\n"
                f"👥 Followers: {account.follower_count:,}\n"
                f"➡️ Following: {account.following_count:,}\n"
                f"📷 Posts: {account.media_count:,}",
                parse_mode='Markdown'
            )
            return WAITING_ACTION
            
        elif choice == '❌ Logout':
            stop_active_process(user_id)
            if user_id in instagram_clients:
                del instagram_clients[user_id]
            if user_id in user_sessions:
                del user_sessions[user_id]
            await update.message.reply_text("👋 *You have been successfully logged out!* \n\nUse /start to log in again.", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
            
    except LoginRequired:
        await update.message.reply_text("⚠️ *Your session has expired.* Please log in again using /start.", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in handle_menu_action for user {user_id}: {e}")
        await update.message.reply_text(f"❌ An error occurred: `{str(e)}`", parse_mode='Markdown', reply_markup=show_main_menu())
        return WAITING_ACTION

async def execute_target_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executes a single-user action (unfollow or remove)."""
    user_id = update.effective_user.id
    target_username = update.message.text.strip().replace('@', '')
    action = context.user_data.pop('action', None)
    cl = get_client(user_id)
    
    if not action:
        await update.message.reply_text("❓ Something went wrong. Please select an action from the menu.", reply_markup=show_main_menu())
        return WAITING_ACTION
    
    msg = await update.message.reply_text(f"🔄 Processing request for @{target_username}...", reply_markup=ReplyKeyboardRemove())
    
    try:
        target_id = cl.user_id_from_username(target_username)
        
        if action == 'unfollow':
            if cl.user_unfollow(target_id):
                await msg.edit_text(f"✅ Successfully unfollowed @{target_username}.", reply_markup=show_main_menu())
            else:
                await msg.edit_text(f"⚠️ Could not unfollow @{target_username}. You might not be following them.", reply_markup=show_main_menu())
        elif action == 'remove':
            if cl.user_remove_follower(target_id):
                 await msg.edit_text(f"✅ Successfully removed @{target_username} as a follower.", reply_markup=show_main_menu())
            else:
                 await msg.edit_text(f"⚠️ Could not remove @{target_username}. They might not be following you.", reply_markup=show_main_menu())

    except Exception as e:
        await msg.edit_text(f"❌ Action failed: `{str(e)}`", parse_mode='Markdown', reply_markup=show_main_menu())
    
    return WAITING_ACTION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the current conversation."""
    user_id = update.effective_user.id
    stop_active_process(user_id)
    await update.message.reply_text("❌ Operation cancelled.", reply_markup=ReplyKeyboardRemove())
    # Clean up user session data
    if user_id in user_sessions:
        del user_sessions[user_id]
    if 'action' in context.user_data:
        del context.user_data['action']
    return ConversationHandler.END

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to check bot stats."""
    # Add a check for authorized admin user ID if needed
    # admin_user_id = 12345678
    # if update.effective_user.id != admin_user_id:
    #     return
    await update.message.reply_text(f"📊 Active Users (logged in): {len(instagram_clients)}\n⚙️ Active Processes: {len(active_processes)}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors caused by updates."""
    logger.error(f"Update {update} caused error {context.error}")

# --- Main Bot Execution ---
def main():
    """Sets up and runs the Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == 'YOUR_TELEGRAM_BOT_TOKEN':
        logger.critical("TELEGRAM_BOT_TOKEN is not set. Please set it as an environment variable or in the script.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_username)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
            TWO_FACTOR_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_2fa_code)],
            CHALLENGE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_challenge_code)],
            WAITING_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_action)],
            TARGET_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, execute_target_action)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('stats', stats))
    application.add_error_handler(error_handler)
    
    print("=" * 60)
    print("🤖 Instagram Bot has started successfully!")
    print(f"✅ Bot running with python-telegram-bot")
    print("=" * 60)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
