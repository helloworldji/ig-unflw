import os
import logging
import time
import asyncio
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired, ChallengeRequired, LoginRequired

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
DELAY_BETWEEN_ACTIONS = 4  # seconds
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

def mass_remove_followers_sync(user_id, bot_token, chat_id):
    """Synchronous wrapper to run async function in thread"""
    asyncio.run(mass_remove_followers(user_id, bot_token, chat_id))

async def mass_remove_followers(user_id, bot_token, chat_id):
    """Remove all followers automatically"""
    from telegram import Bot
    bot = Bot(token=bot_token)
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
                 f"⏱️ Delay: *{DELAY_BETWEEN_ACTIONS}s per action*\n"
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
                    text=f"⛔ *Process STOPPED*\n\n"
                         f"✅ Removed: *{count}*\n"
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
                             f"🕐 Last: @{username}",
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
                 f"✅ Removed: *{count}*\n"
                 f"❌ Failed: *{failed}*\n"
                 f"📊 Total: *{total_followers}*\n\n"
                 f"🎉 All done!",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        
        del active_processes[user_id]
        
    except Exception as e:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ *Error:* `{str(e)}`",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        if user_id in active_processes:
            del active_processes[user_id]

def mass_unfollow_all_sync(user_id, bot_token, chat_id):
    """Synchronous wrapper to run async function in thread"""
    asyncio.run(mass_unfollow_all(user_id, bot_token, chat_id))

async def mass_unfollow_all(user_id, bot_token, chat_id):
    """Unfollow everyone automatically"""
    from telegram import Bot
    bot = Bot(token=bot_token)
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
                 f"⏱️ Delay: *{DELAY_BETWEEN_ACTIONS}s per action*\n"
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
                    text=f"⛔ *Process STOPPED*\n\n"
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
                             f"🕐 Last: @{username}",
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
                 f"✅ Unfollowed: *{count}*\n"
                 f"❌ Failed: *{failed}*\n"
                 f"📊 Total: *{total_following}*\n\n"
                 f"🎉 All done!",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        
        del active_processes[user_id]
        
    except Exception as e:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ *Error:* `{str(e)}`",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        if user_id in active_processes:
            del active_processes[user_id]

# ==================== BOT COMMAND HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - Entry point"""
    user_id = update.effective_user.id
    telegram_username = update.effective_user.username or "Unknown"
    
    logger.info(f"User started bot: ID={user_id}, Username=@{telegram_username}")
    
    await update.message.reply_text(
        "🔐 *Instagram Account Manager Bot*\n\n"
        "⚠️ *SECURITY WARNING:*\n"
        "• Only use YOUR OWN Instagram account\n"
        "• Your password is NOT stored\n"
        "• This is a private bot\n\n"
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
        f"_⚠️ Your password message will be deleted automatically_",
        parse_mode='Markdown'
    )
    
    return PASSWORD

async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive password and attempt login"""
    user_id = update.effective_user.id
    password = update.message.text.strip()
    username = user_sessions[user_id]['username']
    
    # Delete password message for security
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id
        )
    except:
        pass
    
    loading_msg = await update.message.reply_text("🔄 *Logging in to Instagram...*", parse_mode='Markdown')
    
    cl = get_client(user_id)
    
    try:
        cl.login(username, password)
        
        try:
            await loading_msg.delete()
        except:
            pass
        
        account = cl.account_info()
        
        logger.info(f"Successful login: Telegram ID={user_id}, Instagram=@{account.username}")
        
        await update.message.reply_text(
            f"✅ *Successfully logged in!*\n\n"
            f"👤 *Account:* @{account.username}\n"
            f"👥 *Followers:* {account.follower_count:,}\n"
            f"➡️ *Following:* {account.following_count:,}\n"
            f"📝 *Posts:* {account.media_count:,}\n\n"
            f"Choose an action below:",
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
            "🔐 *Two-Factor Authentication Required*\n\n"
            "Please enter the *6-digit code* from your authenticator app:",
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
            "⚠️ *Instagram Security Challenge*\n\n"
            "Instagram has sent a verification code to your email/phone.\n\n"
            "Please enter the code:",
            parse_mode='Markdown'
        )
        
        user_sessions[user_id]['password'] = password
        return CHALLENGE_CODE
        
    except Exception as e:
        try:
            await loading_msg.delete()
        except:
            pass
        
        error_message = str(e)
        logger.error(f"Login failed for user {user_id}: {error_message}")
        
        await update.message.reply_text(
            f"❌ *Login Failed!*\n\n"
            f"Error: `{error_message}`\n\n"
            f"Common issues:\n"
            f"• Wrong username or password\n"
            f"• Account has 2FA enabled\n"
            f"• Instagram security block\n\n"
            f"Use /start to try again.",
            parse_mode='Markdown'
        )
        
        return ConversationHandler.END

async def receive_2fa_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 2FA code"""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    username = user_sessions[user_id]['username']
    password = user_sessions[user_id]['password']
    
    try:
        await update.message.delete()
    except:
        pass
    
    loading_msg = await update.message.reply_text("🔄 *Verifying code...*", parse_mode='Markdown')
    
    cl = get_client(user_id)
    
    try:
        cl.login(username, password, verification_code=code)
        
        try:
            await loading_msg.delete()
        except:
            pass
        
        user_sessions[user_id].pop('password', None)
        
        account = cl.account_info()
        
        logger.info(f"Successful 2FA login: Telegram ID={user_id}, Instagram=@{account.username}")
        
        await update.message.reply_text(
            f"✅ *Successfully logged in with 2FA!*\n\n"
            f"👤 *Account:* @{account.username}\n"
            f"👥 *Followers:* {account.follower_count:,}\n"
            f"➡️ *Following:* {account.following_count:,}\n\n"
            f"Choose an action below:",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        
        return WAITING_ACTION
        
    except Exception as e:
        try:
            await loading_msg.delete()
        except:
            pass
        
        await update.message.reply_text(
            f"❌ *2FA Verification Failed!*\n\n"
            f"Error: `{str(e)}`\n\n"
            f"Please use /start to try again.",
            parse_mode='Markdown'
        )
        
        return ConversationHandler.END

async def receive_challenge_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Instagram challenge code"""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    
    try:
        await update.message.delete()
    except:
        pass
    
    loading_msg = await update.message.reply_text("🔄 *Verifying challenge code...*", parse_mode='Markdown')
    
    cl = get_client(user_id)
    
    try:
        cl.challenge_code_handler(code)
        
        try:
            await loading_msg.delete()
        except:
            pass
        
        user_sessions[user_id].pop('password', None)
        
        account = cl.account_info()
        
        logger.info(f"Successful challenge login: Telegram ID={user_id}, Instagram=@{account.username}")
        
        await update.message.reply_text(
            f"✅ *Challenge completed! Logged in successfully!*\n\n"
            f"👤 *Account:* @{account.username}\n"
            f"👥 *Followers:* {account.follower_count:,}\n"
            f"➡️ *Following:* {account.following_count:,}\n\n"
            f"Choose an action below:",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        
        return WAITING_ACTION
        
    except Exception as e:
        try:
            await loading_msg.delete()
        except:
            pass
        
        await update.message.reply_text(
            f"❌ *Challenge Failed!*\n\n"
            f"Error: `{str(e)}`\n\n"
            f"Use /start to try again.",
            parse_mode='Markdown'
        )
        
        return ConversationHandler.END

async def handle_menu_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu button clicks"""
    user_id = update.effective_user.id
    choice = update.message.text
    cl = get_client(user_id)
    
    try:
        # Handle STOP button
        if choice == '⛔ STOP PROCESS':
            if user_id in active_processes:
                stop_active_process(user_id)
                await update.message.reply_text(
                    "⏸️ *Stopping process...*\n\nPlease wait for current action to complete.",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    "ℹ️ No active process to stop.",
                    parse_mode='Markdown',
                    reply_markup=show_main_menu()
                )
            return WAITING_ACTION
        
        # Check progress
        if choice == '📊 Check Progress':
            if user_id in active_processes:
                proc = active_processes[user_id]
                await update.message.reply_text(
                    f"📊 *Current Progress*\n\n"
                    f"Action: *{proc['action']}*\n"
                    f"✅ Completed: *{proc['count']}/{proc['total']}*\n"
                    f"❌ Failed: *{proc['failed']}*\n"
                    f"📈 Progress: *{(proc['count']/proc['total']*100) if proc['total'] > 0 else 0:.1f}%*",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text("ℹ️ No active process running.")
            return WAITING_ACTION
        
        if choice == '➖ Unfollow Someone':
            context.user_data['action'] = 'unfollow'
            await update.message.reply_text(
                "👤 *Unfollow User*\n\n"
                "Enter the Instagram username to *unfollow*:\n"
                "_(without @ symbol)_",
                parse_mode='Markdown'
            )
            return TARGET_USERNAME
            
        elif choice == '🚫 Remove Follower':
            context.user_data['action'] = 'remove'
            await update.message.reply_text(
                "🚫 *Remove Follower*\n\n"
                "Enter the username to *remove* from your followers:\n"
                "_(without @ symbol)_",
                parse_mode='Markdown'
            )
            return TARGET_USERNAME
        
        elif choice == '🔥 Remove ALL Followers':
            keyboard = [['✅ YES, Remove ALL Followers', '❌ Cancel']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            account = cl.account_info()
            await update.message.reply_text(
                f"⚠️ *MASS REMOVAL WARNING*\n\n"
                f"You are about to remove *ALL {account.follower_count:,} followers*!\n\n"
                f"⏱️ This will take approximately *{(account.follower_count * DELAY_BETWEEN_ACTIONS) / 60:.0f} minutes*\n\n"
                f"Are you ABSOLUTELY sure?",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            context.user_data['awaiting_confirmation'] = 'remove_all_followers'
            return WAITING_ACTION
        
        elif choice == '🔥 Unfollow ALL':
            keyboard = [['✅ YES, Unfollow Everyone', '❌ Cancel']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            account = cl.account_info()
            await update.message.reply_text(
                f"⚠️ *MASS UNFOLLOW WARNING*\n\n"
                f"You are about to unfollow *ALL {account.following_count:,} accounts*!\n\n"
                f"⏱️ This will take approximately *{(account.following_count * DELAY_BETWEEN_ACTIONS) / 60:.0f} minutes*\n\n"
                f"Are you ABSOLUTELY sure?",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            context.user_data['awaiting_confirmation'] = 'unfollow_all'
            return WAITING_ACTION
        
        # Handle confirmations
        elif choice == '✅ YES, Remove ALL Followers':
            await update.message.reply_text(
                "🚀 *Starting mass follower removal...*\n\nThis will run in background.",
                parse_mode='Markdown'
            )
            
            thread = Thread(
                target=mass_remove_followers_sync,
                args=(user_id, TELEGRAM_BOT_TOKEN, update.effective_chat.id)
            )
            thread.daemon = True
            thread.start()
            
            context.user_data.pop('awaiting_confirmation', None)
            return WAITING_ACTION
        
        elif choice == '✅ YES, Unfollow Everyone':
            await update.message.reply_text(
                "🚀 *Starting mass unfollow...*\n\nThis will run in background.",
                parse_mode='Markdown'
            )
            
            thread = Thread(
                target=mass_unfollow_all_sync,
                args=(user_id, TELEGRAM_BOT_TOKEN, update.effective_chat.id)
            )
            thread.daemon = True
            thread.start()
            
            context.user_data.pop('awaiting_confirmation', None)
            return WAITING_ACTION
        
        elif choice == '❌ Cancel':
            context.user_data.pop('awaiting_confirmation', None)
            await update.message.reply_text(
                "✅ Cancelled. Choose another action:",
                reply_markup=show_main_menu()
            )
            return WAITING_ACTION
            
        elif choice == '📊 Account Info':
            account = cl.account_info()
            await update.message.reply_text(
                f"📊 *Account Information*\n\n"
                f"👤 *Username:* @{account.username}\n"
                f"📝 *Full Name:* {account.full_name}\n"
                f"👥 *Followers:* {account.follower_count:,}\n"
                f"➡️ *Following:* {account.following_count:,}\n"
                f"📷 *Posts:* {account.media_count:,}\n"
                f"📖 *Bio:* {account.biography[:100] if account.biography else 'N/A'}",
                parse_mode='Markdown'
            )
            return WAITING_ACTION
            
        elif choice == '❌ Logout':
            stop_active_process(user_id)
            
            instagram_username = "Unknown"
            if user_id in user_sessions:
                instagram_username = user_sessions[user_id].get('username', 'Unknown')
            
            logger.info(f"User logged out: Telegram ID={user_id}, Instagram=@{instagram_username}")
            
            if user_id in instagram_clients:
                del instagram_clients[user_id]
            if user_id in user_sessions:
                del user_sessions[user_id]
            
            await update.message.reply_text(
                "👋 *Logged out successfully!*\n\n"
                "Use /start to login again.",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
            
    except LoginRequired:
        await update.message.reply_text(
            "⚠️ *Session expired!*\n\n"
            "Please use /start to login again.",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ *Error:* `{str(e)}`",
            parse_mode='Markdown'
        )
        return WAITING_ACTION

async def execute_target_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute unfollow or remove follower action"""
    user_id = update.effective_user.id
    target_username = update.message.text.strip().replace('@', '')
    action = context.user_data.get('action')
    cl = get_client(user_id)
    
    loading_msg = await update.message.reply_text(f"🔄 *Processing...*", parse_mode='Markdown')
    
    try:
        user_id_to_action = cl.user_id_from_username(target_username)
        
        if action == 'unfollow':
            cl.user_unfollow(user_id_to_action)
            try:
                await loading_msg.delete()
            except:
                pass
            await update.message.reply_text(
                f"✅ *Successfully unfollowed* @{target_username}",
                parse_mode='Markdown',
                reply_markup=show_main_menu()
            )
            
        elif action == 'remove':
            cl.user_remove_follower(user_id_to_action)
            try:
                await loading_msg.delete()
            except:
                pass
            await update.message.reply_text(
                f"✅ *Successfully removed* @{target_username} *from followers*",
                parse_mode='Markdown',
                reply_markup=show_main_menu()
            )
    
    except Exception as e:
        try:
            await loading_msg.delete()
        except:
            pass
        
        error_msg = str(e)
        await update.message.reply_text(
            f"❌ *Action failed!*\n\n"
            f"Error: `{error_msg}`\n\n"
            f"Possible reasons:\n"
            f"• Username doesn't exist\n"
            f"• You don't follow this user\n"
            f"• Instagram rate limit\n\n"
            f"Try again or choose another action.",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
    
    return WAITING_ACTION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel and exit conversation"""
    user_id = update.effective_user.id
    stop_active_process(user_id)
    
    await update.message.reply_text(
        "❌ *Cancelled*\n\n"
        "Use /start to begin again.",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    active_users = len(instagram_clients)
    active_tasks = len(active_processes)
    
    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"👥 Active users: *{active_users}*\n"
        f"⚙️ Active processes: *{active_tasks}*\n"
        f"🔄 Delay setting: *{DELAY_BETWEEN_ACTIONS}s*",
        parse_mode='Markdown'
    )

def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Exception while handling an update: {context.error}")

# ==================== MAIN FUNCTION ====================

def main():
    """Start the bot"""
    
    if TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("=" * 60)
        print("❌ ERROR: TELEGRAM_BOT_TOKEN not set!")
        print("=" * 60)
        print("Please set your bot token in one of these ways:")
        print("1. Edit instagram_bot.py and replace 'YOUR_BOT_TOKEN_HERE'")
        print("2. Set environment variable: export TELEGRAM_BOT_TOKEN='your_token'")
        print("=" * 60)
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
    print("🤖 Instagram Multi-User Manager Bot Started!")
    print("=" * 60)
    print(f"✅ Authorization: DISABLED (Multi-User Mode)")
    print(f"⚠️  Anyone with bot link can use it")
    print(f"⏱️  Delay between actions: {DELAY_BETWEEN_ACTIONS} seconds")
    print(f"✅ Bot is running and waiting for commands...")
    print(f"⚠️  Press Ctrl+C to stop the bot")
    print("=" * 60)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
