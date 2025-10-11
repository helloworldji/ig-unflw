from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired, ChallengeRequired, LoginRequired
import logging
import time
import threading
import asyncio

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Replace with your bot token

# Safety settings
DELAY_BETWEEN_ACTIONS = 4
MAX_ACTIONS_PER_HOUR = 60

# ==================== CONVERSATION STATES ====================
USERNAME, PASSWORD, TWO_FACTOR_CODE, CHALLENGE_CODE, WAITING_ACTION, TARGET_USERNAME = range(6)

# ==================== GLOBAL VARIABLES ====================
user_sessions = {}
instagram_clients = {}
active_processes = {}

# ==================== HELPER FUNCTIONS ====================

def get_client(user_id):
    """Get or create Instagram client for user"""
    if user_id not in instagram_clients:
        instagram_clients[user_id] = Client()
    return instagram_clients[user_id]

def show_main_menu():
    """Display main menu keyboard"""
    keyboard = [
        ['➖ Unfollow Someone', '🚫 Remove Follower'],
        ['🔥 Remove ALL Followers', '🔥 Unfollow ALL'],
        ['📊 Account Info', '❌ Logout']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def show_stop_menu():
    """Display menu with STOP button"""
    keyboard = [
        ['⛔ STOP PROCESS'],
        ['📊 Check Progress']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def stop_active_process(user_id):
    """Stop any running process for user"""
    if user_id in active_processes:
        active_processes[user_id]['should_stop'] = True
        return True
    return False

# ==================== MASS REMOVAL FUNCTIONS ====================

async def mass_remove_followers(user_id, bot, chat_id):
    """Remove all followers automatically"""
    cl = get_client(user_id)
    
    try:
        active_processes[user_id] = {
            'should_stop': False,
            'action': 'remove_followers',
            'count': 0,
            'total': 0,
            'failed': 0
        }
        
        await bot.send_message(
            chat_id=chat_id,
            text="🔄 *Fetching your followers list...*\n\nPlease wait...",
            parse_mode='Markdown'
        )
        
        followers = cl.user_followers(cl.user_id)
        total_followers = len(followers)
        
        active_processes[user_id]['total'] = total_followers
        
        if total_followers == 0:
            await bot.send_message(
                chat_id=chat_id,
                text="ℹ️ You have no followers to remove.",
                parse_mode='Markdown',
                reply_markup=show_main_menu()
            )
            del active_processes[user_id]
            return
        
        await bot.send_message(
            chat_id=chat_id,
            text=f"🔥 *Starting Mass Removal*\n\n"
                 f"📊 Total followers: *{total_followers}*\n"
                 f"⏱️ Delay between actions: *{DELAY_BETWEEN_ACTIONS} seconds*\n"
                 f"⚠️ Estimated time: *{(total_followers * DELAY_BETWEEN_ACTIONS) / 60:.1f} minutes*\n\n"
                 f"_Click ⛔ STOP PROCESS to cancel anytime_",
            parse_mode='Markdown',
            reply_markup=show_stop_menu()
        )
        
        count = 0
        failed = 0
        
        for user_id_to_remove, user_info in followers.items():
            if active_processes[user_id].get('should_stop', False):
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"⛔ *Process STOPPED by user*\n\n"
                         f"✅ Removed: *{count}* followers\n"
                         f"❌ Failed: *{failed}*\n"
                         f"⏭️ Remaining: *{total_followers - count - failed}*",
                    parse_mode='Markdown',
                    reply_markup=show_main_menu()
                )
                del active_processes[user_id]
                return
            
            try:
                username = user_info.username
                cl.user_remove_follower(user_id_to_remove)
                count += 1
                active_processes[user_id]['count'] = count
                
                if count % 5 == 0:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"⚙️ *Progress Update*\n\n"
                             f"✅ Removed: *{count}/{total_followers}*\n"
                             f"❌ Failed: *{failed}*\n"
                             f"📊 Progress: *{(count/total_followers)*100:.1f}%*\n"
                             f"🕐 Last removed: @{username}",
                        parse_mode='Markdown'
                    )
                
                time.sleep(DELAY_BETWEEN_ACTIONS)
                
            except Exception as e:
                failed += 1
                active_processes[user_id]['failed'] = failed
                logger.error(f"Failed to remove {user_info.username}: {e}")
                time.sleep(2)
        
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ *MASS REMOVAL COMPLETE!*\n\n"
                 f"✅ Successfully removed: *{count}* followers\n"
                 f"❌ Failed: *{failed}*\n"
                 f"📊 Total processed: *{total_followers}*\n\n"
                 f"🎉 All done!",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        
        del active_processes[user_id]
        
    except Exception as e:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ *Error during mass removal:*\n\n`{str(e)}`",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        if user_id in active_processes:
            del active_processes[user_id]

async def mass_unfollow_all(user_id, bot, chat_id):
    """Unfollow everyone automatically"""
    cl = get_client(user_id)
    
    try:
        active_processes[user_id] = {
            'should_stop': False,
            'action': 'unfollow_all',
            'count': 0,
            'total': 0,
            'failed': 0
        }
        
        await bot.send_message(
            chat_id=chat_id,
            text="🔄 *Fetching your following list...*\n\nPlease wait...",
            parse_mode='Markdown'
        )
        
        following = cl.user_following(cl.user_id)
        total_following = len(following)
        
        active_processes[user_id]['total'] = total_following
        
        if total_following == 0:
            await bot.send_message(
                chat_id=chat_id,
                text="ℹ️ You are not following anyone.",
                parse_mode='Markdown',
                reply_markup=show_main_menu()
            )
            del active_processes[user_id]
            return
        
        await bot.send_message(
            chat_id=chat_id,
            text=f"🔥 *Starting Mass Unfollow*\n\n"
                 f"📊 Total following: *{total_following}*\n"
                 f"⏱️ Delay between actions: *{DELAY_BETWEEN_ACTIONS} seconds*\n"
                 f"⚠️ Estimated time: *{(total_following * DELAY_BETWEEN_ACTIONS) / 60:.1f} minutes*\n\n"
                 f"_Click ⛔ STOP PROCESS to cancel anytime_",
            parse_mode='Markdown',
            reply_markup=show_stop_menu()
        )
        
        count = 0
        failed = 0
        
        for user_id_to_unfollow, user_info in following.items():
            if active_processes[user_id].get('should_stop', False):
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"⛔ *Process STOPPED by user*\n\n"
                         f"✅ Unfollowed: *{count}*\n"
                         f"❌ Failed: *{failed}*\n"
                         f"⏭️ Remaining: *{total_following - count - failed}*",
                    parse_mode='Markdown',
                    reply_markup=show_main_menu()
                )
                del active_processes[user_id]
                return
            
            try:
                username = user_info.username
                cl.user_unfollow(user_id_to_unfollow)
                count += 1
                active_processes[user_id]['count'] = count
                
                if count % 5 == 0:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"⚙️ *Progress Update*\n\n"
                             f"✅ Unfollowed: *{count}/{total_following}*\n"
                             f"❌ Failed: *{failed}*\n"
                             f"📊 Progress: *{(count/total_following)*100:.1f}%*\n"
                             f"🕐 Last unfollowed: @{username}",
                        parse_mode='Markdown'
                    )
                
                time.sleep(DELAY_BETWEEN_ACTIONS)
                
            except Exception as e:
                failed += 1
                active_processes[user_id]['failed'] = failed
                logger.error(f"Failed to unfollow {user_info.username}: {e}")
                time.sleep(2)
        
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ *MASS UNFOLLOW COMPLETE!*\n\n"
                 f"✅ Successfully unfollowed: *{count}*\n"
                 f"❌ Failed: *{failed}*\n"
                 f"📊 Total processed: *{total_following}*\n\n"
                 f"🎉 All done!",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        
        del active_processes[user_id]
        
    except Exception as e:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ *Error during mass unfollow:*\n\n`{str(e)}`",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        if user_id in active_processes:
            del active_processes[user_id]

# ==================== BOT COMMAND HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user_id = update.effective_user.id
    telegram_username = update.effective_user.username or "Unknown"
    
    logger.info(f"User started bot: ID={user_id}, Username=@{telegram_username}")
    
    await update.message.reply_text(
        "🔐 *Instagram Account Manager Bot*\n\n"
        "⚠️ *SECURITY WARNING:*\n"
        "• Only use YOUR OWN Instagram account\n"
        "• Your password is NOT stored\n\n"
        "📱 Please enter your *Instagram username*:",
        parse_mode='Markdown'
    )
    
    user_sessions[user_id] = {'telegram_user': telegram_username}
    return USERNAME

async def receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive Instagram username"""
    user_id = update.effective_user.id
    username = update.message.text.strip()
    
    user_sessions[user_id]['username'] = username
    
    await update.message.reply_text(
        f"✅ Username: *{username}*\n\n"
        f"🔑 Now enter your *Instagram password*:\n\n"
        f"_⚠️ Your password message will be automatically deleted_",
        parse_mode='Markdown'
    )
    
    return PASSWORD

async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive password and login"""
    user_id = update.effective_user.id
    password = update.message.text.strip()
    username = user_sessions[user_id]['username']
    
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id
        )
    except:
        pass
    
    loading_msg = await update.message.reply_text("🔄 *Logging in...*", parse_mode='Markdown')
    
    cl = get_client(user_id)
    
    try:
        cl.login(username, password)
        
        try:
            await loading_msg.delete()
        except:
            pass
        
        account = cl.account_info()
        
        logger.info(f"Login success: Telegram={user_id}, Instagram=@{account.username}")
        
        await update.message.reply_text(
            f"✅ *Successfully logged in!*\n\n"
            f"👤 *Account:* @{account.username}\n"
            f"👥 *Followers:* {account.follower_count:,}\n"
            f"➡️ *Following:* {account.following_count:,}\n\n"
            f"Choose an action:",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        
        return WAITING_ACTION
        
    except TwoFactorRequired:
        try:
            await loading_msg.delete()
        except:
            pass
        
        await update.message.reply_text(
            "🔐 *2FA Required*\n\nEnter the 6-digit code:",
            parse_mode='Markdown'
        )
        
        user_sessions[user_id]['password'] = password
        return TWO_FACTOR_CODE
        
    except ChallengeRequired:
        try:
            await loading_msg.delete()
        except:
            pass
        
        await update.message.reply_text(
            "⚠️ *Instagram Challenge*\n\nEnter the verification code:",
            parse_mode='Markdown'
        )
        
        user_sessions[user_id]['password'] = password
        return CHALLENGE_CODE
        
    except Exception as e:
        try:
            await loading_msg.delete()
        except:
            pass
        
        await update.message.reply_text(
            f"❌ *Login Failed!*\n\n`{str(e)}`\n\nUse /start to retry.",
            parse_mode='Markdown'
        )
        
        return ConversationHandler.END

async def receive_2fa_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 2FA"""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    username = user_sessions[user_id]['username']
    password = user_sessions[user_id]['password']
    
    try:
        await update.message.delete()
    except:
        pass
    
    cl = get_client(user_id)
    
    try:
        cl.login(username, password, verification_code=code)
        user_sessions[user_id].pop('password', None)
        
        account = cl.account_info()
        
        await update.message.reply_text(
            f"✅ *Logged in with 2FA!*\n\n"
            f"👤 @{account.username}\n"
            f"👥 Followers: {account.follower_count:,}\n",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        
        return WAITING_ACTION
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ 2FA Failed: `{str(e)}`",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

async def receive_challenge_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle challenge"""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    
    try:
        await update.message.delete()
    except:
        pass
    
    cl = get_client(user_id)
    
    try:
        cl.challenge_code_handler(code)
        user_sessions[user_id].pop('password', None)
        
        account = cl.account_info()
        
        await update.message.reply_text(
            f"✅ *Challenge completed!*\n\n@{account.username}",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        
        return WAITING_ACTION
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed: `{str(e)}`",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

async def handle_menu_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu"""
    user_id = update.effective_user.id
    choice = update.message.text
    cl = get_client(user_id)
    
    try:
        if choice == '⛔ STOP PROCESS':
            if user_id in active_processes:
                stop_active_process(user_id)
                await update.message.reply_text("⏸️ Stopping...", parse_mode='Markdown')
            return WAITING_ACTION
        
        if choice == '📊 Check Progress':
            if user_id in active_processes:
                proc = active_processes[user_id]
                await update.message.reply_text(
                    f"📊 Progress: {proc['count']}/{proc['total']}",
                    parse_mode='Markdown'
                )
            return WAITING_ACTION
        
        if choice == '➖ Unfollow Someone':
            context.user_data['action'] = 'unfollow'
            await update.message.reply_text("Enter username to unfollow:")
            return TARGET_USERNAME
            
        elif choice == '🚫 Remove Follower':
            context.user_data['action'] = 'remove'
            await update.message.reply_text("Enter username to remove:")
            return TARGET_USERNAME
        
        elif choice == '🔥 Remove ALL Followers':
            keyboard = [['✅ YES, Remove ALL', '❌ Cancel']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            account = cl.account_info()
            await update.message.reply_text(
                f"⚠️ Remove ALL {account.follower_count:,} followers?\n\nAre you sure?",
                reply_markup=reply_markup
            )
            context.user_data['awaiting_confirmation'] = 'remove_all_followers'
            return WAITING_ACTION
        
        elif choice == '🔥 Unfollow ALL':
            keyboard = [['✅ YES, Unfollow ALL', '❌ Cancel']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            account = cl.account_info()
            await update.message.reply_text(
                f"⚠️ Unfollow ALL {account.following_count:,} accounts?\n\nAre you sure?",
                reply_markup=reply_markup
            )
            context.user_data['awaiting_confirmation'] = 'unfollow_all'
            return WAITING_ACTION
        
        elif choice == '✅ YES, Remove ALL':
            await update.message.reply_text("🚀 Starting...")
            
            # Run in thread to avoid blocking
            def run_async(coro):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(coro)
            
            thread = threading.Thread(
                target=run_async,
                args=(mass_remove_followers(user_id, context.bot, update.effective_chat.id),)
            )
            thread.start()
            context.user_data.pop('awaiting_confirmation', None)
            return WAITING_ACTION
        
        elif choice == '✅ YES, Unfollow ALL':
            await update.message.reply_text("🚀 Starting...")
            
            def run_async(coro):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(coro)
            
            thread = threading.Thread(
                target=run_async,
                args=(mass_unfollow_all(user_id, context.bot, update.effective_chat.id),)
            )
            thread.start()
            context.user_data.pop('awaiting_confirmation', None)
            return WAITING_ACTION
        
        elif choice == '❌ Cancel':
            context.user_data.pop('awaiting_confirmation', None)
            await update.message.reply_text("Cancelled", reply_markup=show_main_menu())
            return WAITING_ACTION
            
        elif choice == '📊 Account Info':
            account = cl.account_info()
            await update.message.reply_text(
                f"📊 *Account*\n\n"
                f"👤 @{account.username}\n"
                f"👥 Followers: {account.follower_count:,}\n"
                f"➡️ Following: {account.following_count:,}",
                parse_mode='Markdown'
            )
            return WAITING_ACTION
            
        elif choice == '❌ Logout':
            stop_active_process(user_id)
            
            if user_id in instagram_clients:
                del instagram_clients[user_id]
            if user_id in user_sessions:
                del user_sessions[user_id]
            
            await update.message.reply_text(
                "👋 Logged out!",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error: `{str(e)}`", parse_mode='Markdown')
        return WAITING_ACTION

async def execute_target_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute action"""
    user_id = update.effective_user.id
    target_username = update.message.text.strip().replace('@', '')
    action = context.user_data.get('action')
    cl = get_client(user_id)
    
    try:
        user_id_to_action = cl.user_id_from_username(target_username)
        
        if action == 'unfollow':
            cl.user_unfollow(user_id_to_action)
            await update.message.reply_text(
                f"✅ Unfollowed @{target_username}",
                reply_markup=show_main_menu()
            )
            
        elif action == 'remove':
            cl.user_remove_follower(user_id_to_action)
            await update.message.reply_text(
                f"✅ Removed @{target_username}",
                reply_markup=show_main_menu()
            )
    
    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed: `{str(e)}`",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
    
    return WAITING_ACTION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel"""
    user_id = update.effective_user.id
    stop_active_process(user_id)
    
    await update.message.reply_text(
        "❌ Cancelled",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stats"""
    await update.message.reply_text(
        f"📊 Active users: {len(instagram_clients)}\n"
        f"⚙️ Active processes: {len(active_processes)}"
    )

# ==================== MAIN ====================

def main():
    """Start bot"""
    
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Set TELEGRAM_BOT_TOKEN!")
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
    
    print("=" * 60)
    print("🤖 Bot Started (python-telegram-bot 20.x)")
    print("=" * 60)
    
    application.run_polling()

if __name__ == '__main__':
    main()
