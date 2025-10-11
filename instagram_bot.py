from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackContext
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired, ChallengeRequired, LoginRequired
import logging
import time
import threading

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
# ⚠️ CHANGE THIS VALUE ⚠️
TELEGRAM_BOT_TOKEN = "8297692816:AAE9-ELN52UJ_uA9WM1L_yOH-n4t0I9kfKI"  # Replace with your bot token

# Safety settings
DELAY_BETWEEN_ACTIONS = 2  # Seconds between each unfollow/remove (increase if getting rate limited)
MAX_ACTIONS_PER_HOUR = 60  # Maximum actions per hour (Instagram limit protection)

# ==================== CONVERSATION STATES ====================
USERNAME, PASSWORD, TWO_FACTOR_CODE, CHALLENGE_CODE, WAITING_ACTION, TARGET_USERNAME = range(6)

# ==================== GLOBAL VARIABLES ====================
user_sessions = {}
instagram_clients = {}
active_processes = {}  # Track running mass removal processes

# ==================== HELPER FUNCTIONS ====================

def get_client(user_id):
    """Get or create Instagram client for user"""
    if user_id not in instagram_clients:
        instagram_clients[user_id] = Client()
    return instagram_clients[user_id]

def show_main_menu(update: Update):
    """Display main menu keyboard"""
    keyboard = [
        ['➖ Unfollow Someone', '🚫 Remove Follower'],
        ['🔥 Remove ALL Followers', '🔥 Unfollow ALL'],
        ['📊 Account Info', '❌ Logout']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    return reply_markup

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

def mass_remove_followers(user_id, bot, chat_id):
    """Remove all followers automatically"""
    cl = get_client(user_id)
    
    try:
        # Initialize process tracking
        active_processes[user_id] = {
            'should_stop': False,
            'action': 'remove_followers',
            'count': 0,
            'total': 0,
            'failed': 0
        }
        
        bot.send_message(
            chat_id=chat_id,
            text="🔄 *Fetching your followers list...*\n\nPlease wait...",
            parse_mode='Markdown'
        )
        
        # Get all followers
        followers = cl.user_followers(cl.user_id)
        total_followers = len(followers)
        
        active_processes[user_id]['total'] = total_followers
        
        if total_followers == 0:
            bot.send_message(
                chat_id=chat_id,
                text="ℹ️ You have no followers to remove.",
                parse_mode='Markdown',
                reply_markup=show_main_menu(None)
            )
            del active_processes[user_id]
            return
        
        bot.send_message(
            chat_id=chat_id,
            text=f"🔥 *Starting Mass Removal*\n\n"
                 f"📊 Total followers: *{total_followers}*\n"
                 f"⏱️ Delay between actions: *{DELAY_BETWEEN_ACTIONS} seconds*\n"
                 f"⚠️ Estimated time: *{(total_followers * DELAY_BETWEEN_ACTIONS) / 60:.1f} minutes*\n\n"
                 f"_Click ⛔ STOP PROCESS to cancel anytime_",
            parse_mode='Markdown',
            reply_markup=show_stop_menu()
        )
        
        # Remove each follower
        count = 0
        failed = 0
        
        for user_id_to_remove, user_info in followers.items():
            # Check if user requested stop
            if active_processes[user_id].get('should_stop', False):
                bot.send_message(
                    chat_id=chat_id,
                    text=f"⛔ *Process STOPPED by user*\n\n"
                         f"✅ Removed: *{count}* followers\n"
                         f"❌ Failed: *{failed}*\n"
                         f"⏭️ Remaining: *{total_followers - count - failed}*",
                    parse_mode='Markdown',
                    reply_markup=show_main_menu(None)
                )
                del active_processes[user_id]
                return
            
            try:
                username = user_info.username
                cl.user_remove_follower(user_id_to_remove)
                count += 1
                active_processes[user_id]['count'] = count
                
                # Send progress update every 5 removals
                if count % 5 == 0:
                    bot.send_message(
                        chat_id=chat_id,
                        text=f"⚙️ *Progress Update*\n\n"
                             f"✅ Removed: *{count}/{total_followers}*\n"
                             f"❌ Failed: *{failed}*\n"
                             f"📊 Progress: *{(count/total_followers)*100:.1f}%*\n"
                             f"🕐 Last removed: @{username}",
                        parse_mode='Markdown'
                    )
                
                # Safety delay
                time.sleep(DELAY_BETWEEN_ACTIONS)
                
            except Exception as e:
                failed += 1
                active_processes[user_id]['failed'] = failed
                logger.error(f"Failed to remove {user_info.username}: {e}")
                time.sleep(2)
        
        # Process complete
        bot.send_message(
            chat_id=chat_id,
            text=f"✅ *MASS REMOVAL COMPLETE!*\n\n"
                 f"✅ Successfully removed: *{count}* followers\n"
                 f"❌ Failed: *{failed}*\n"
                 f"📊 Total processed: *{total_followers}*\n\n"
                 f"🎉 All done!",
            parse_mode='Markdown',
            reply_markup=show_main_menu(None)
        )
        
        del active_processes[user_id]
        
    except Exception as e:
        bot.send_message(
            chat_id=chat_id,
            text=f"❌ *Error during mass removal:*\n\n`{str(e)}`",
            parse_mode='Markdown',
            reply_markup=show_main_menu(None)
        )
        if user_id in active_processes:
            del active_processes[user_id]

def mass_unfollow_all(user_id, bot, chat_id):
    """Unfollow everyone automatically"""
    cl = get_client(user_id)
    
    try:
        # Initialize process tracking
        active_processes[user_id] = {
            'should_stop': False,
            'action': 'unfollow_all',
            'count': 0,
            'total': 0,
            'failed': 0
        }
        
        bot.send_message(
            chat_id=chat_id,
            text="🔄 *Fetching your following list...*\n\nPlease wait...",
            parse_mode='Markdown'
        )
        
        # Get all following
        following = cl.user_following(cl.user_id)
        total_following = len(following)
        
        active_processes[user_id]['total'] = total_following
        
        if total_following == 0:
            bot.send_message(
                chat_id=chat_id,
                text="ℹ️ You are not following anyone.",
                parse_mode='Markdown',
                reply_markup=show_main_menu(None)
            )
            del active_processes[user_id]
            return
        
        bot.send_message(
            chat_id=chat_id,
            text=f"🔥 *Starting Mass Unfollow*\n\n"
                 f"📊 Total following: *{total_following}*\n"
                 f"⏱️ Delay between actions: *{DELAY_BETWEEN_ACTIONS} seconds*\n"
                 f"⚠️ Estimated time: *{(total_following * DELAY_BETWEEN_ACTIONS) / 60:.1f} minutes*\n\n"
                 f"_Click ⛔ STOP PROCESS to cancel anytime_",
            parse_mode='Markdown',
            reply_markup=show_stop_menu()
        )
        
        # Unfollow each user
        count = 0
        failed = 0
        
        for user_id_to_unfollow, user_info in following.items():
            # Check if user requested stop
            if active_processes[user_id].get('should_stop', False):
                bot.send_message(
                    chat_id=chat_id,
                    text=f"⛔ *Process STOPPED by user*\n\n"
                         f"✅ Unfollowed: *{count}*\n"
                         f"❌ Failed: *{failed}*\n"
                         f"⏭️ Remaining: *{total_following - count - failed}*",
                    parse_mode='Markdown',
                    reply_markup=show_main_menu(None)
                )
                del active_processes[user_id]
                return
            
            try:
                username = user_info.username
                cl.user_unfollow(user_id_to_unfollow)
                count += 1
                active_processes[user_id]['count'] = count
                
                # Send progress update every 5 unfollows
                if count % 5 == 0:
                    bot.send_message(
                        chat_id=chat_id,
                        text=f"⚙️ *Progress Update*\n\n"
                             f"✅ Unfollowed: *{count}/{total_following}*\n"
                             f"❌ Failed: *{failed}*\n"
                             f"📊 Progress: *{(count/total_following)*100:.1f}%*\n"
                             f"🕐 Last unfollowed: @{username}",
                        parse_mode='Markdown'
                    )
                
                # Safety delay
                time.sleep(DELAY_BETWEEN_ACTIONS)
                
            except Exception as e:
                failed += 1
                active_processes[user_id]['failed'] = failed
                logger.error(f"Failed to unfollow {user_info.username}: {e}")
                time.sleep(2)
        
        # Process complete
        bot.send_message(
            chat_id=chat_id,
            text=f"✅ *MASS UNFOLLOW COMPLETE!*\n\n"
                 f"✅ Successfully unfollowed: *{count}*\n"
                 f"❌ Failed: *{failed}*\n"
                 f"📊 Total processed: *{total_following}*\n\n"
                 f"🎉 All done!",
            parse_mode='Markdown',
            reply_markup=show_main_menu(None)
        )
        
        del active_processes[user_id]
        
    except Exception as e:
        bot.send_message(
            chat_id=chat_id,
            text=f"❌ *Error during mass unfollow:*\n\n`{str(e)}`",
            parse_mode='Markdown',
            reply_markup=show_main_menu(None)
        )
        if user_id in active_processes:
            del active_processes[user_id]

# ==================== BOT COMMAND HANDLERS ====================

def start(update: Update, context: CallbackContext):
    """Start command - Entry point"""
    user_id = update.effective_user.id
    telegram_username = update.effective_user.username or "Unknown"
    
    # Log who is using the bot
    logger.info(f"User started bot: ID={user_id}, Username=@{telegram_username}")
    
    update.message.reply_text(
        "🔐 *Instagram Account Manager Bot*\n\n"
        "⚠️ *SECURITY WARNING:*\n"
        "• Only use YOUR OWN Instagram account\n"
        "• Your password is NOT stored\n"
        "• This is a private team bot\n\n"
        "👤 *Your Telegram Info:*\n"
        f"ID: `{user_id}`\n"
        f"Username: @{telegram_username}\n\n"
        "📱 Please enter your *Instagram username*:",
        parse_mode='Markdown'
    )
    
    # Initialize session
    user_sessions[user_id] = {'telegram_user': telegram_username}
    
    return USERNAME

def receive_username(update: Update, context: CallbackContext):
    """Receive Instagram username"""
    user_id = update.effective_user.id
    username = update.message.text.strip()
    
    # Save username
    user_sessions[user_id]['username'] = username
    
    update.message.reply_text(
        f"✅ Username: *{username}*\n\n"
        f"🔑 Now enter your *Instagram password*:\n\n"
        f"_⚠️ Your password message will be automatically deleted for security_",
        parse_mode='Markdown'
    )
    
    return PASSWORD

def receive_password(update: Update, context: CallbackContext):
    """Receive password and attempt login"""
    user_id = update.effective_user.id
    password = update.message.text.strip()
    username = user_sessions[user_id]['username']
    
    # Delete password message for security
    try:
        context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id
        )
    except:
        pass
    
    # Show loading message
    loading_msg = update.message.reply_text("🔄 *Logging in to Instagram...*\n\nPlease wait...", parse_mode='Markdown')
    
    # Get Instagram client
    cl = get_client(user_id)
    
    try:
        # Attempt login
        cl.login(username, password)
        
        # Delete loading message
        try:
            loading_msg.delete()
        except:
            pass
        
        # Login successful
        account = cl.account_info()
        
        # Log successful login
        logger.info(f"Successful login: Telegram ID={user_id}, Instagram=@{account.username}")
        
        update.message.reply_text(
            f"✅ *Successfully logged in!*\n\n"
            f"👤 *Account:* @{account.username}\n"
            f"👥 *Followers:* {account.follower_count:,}\n"
            f"➡️ *Following:* {account.following_count:,}\n"
            f"📝 *Posts:* {account.media_count:,}\n\n"
            f"Choose an action below:",
            parse_mode='Markdown',
            reply_markup=show_main_menu(update)
        )
        
        return WAITING_ACTION
        
    except TwoFactorRequired:
        # 2FA is enabled - ask for code
        try:
            loading_msg.delete()
        except:
            pass
        
        update.message.reply_text(
            "🔐 *Two-Factor Authentication Required*\n\n"
            "Please enter the *6-digit code* from your authenticator app:",
            parse_mode='Markdown'
        )
        
        # Save password for retry with 2FA
        user_sessions[user_id]['password'] = password
        
        return TWO_FACTOR_CODE
        
    except ChallengeRequired:
        # Instagram security challenge
        try:
            loading_msg.delete()
        except:
            pass
        
        update.message.reply_text(
            "⚠️ *Instagram Security Challenge*\n\n"
            "Instagram has sent a verification code to your email/phone.\n\n"
            "Please enter the code:",
            parse_mode='Markdown'
        )
        
        # Save password for retry
        user_sessions[user_id]['password'] = password
        
        return CHALLENGE_CODE
        
    except Exception as e:
        try:
            loading_msg.delete()
        except:
            pass
        
        error_message = str(e)
        logger.error(f"Login failed for user {user_id}: {error_message}")
        
        update.message.reply_text(
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

def receive_2fa_code(update: Update, context: CallbackContext):
    """Handle 2FA code"""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    username = user_sessions[user_id]['username']
    password = user_sessions[user_id]['password']
    
    # Delete code message
    try:
        update.message.delete()
    except:
        pass
    
    loading_msg = update.message.reply_text("🔄 *Verifying code...*", parse_mode='Markdown')
    
    cl = get_client(user_id)
    
    try:
        # Login with 2FA code
        cl.login(username, password, verification_code=code)
        
        try:
            loading_msg.delete()
        except:
            pass
        
        # Clear password from session
        user_sessions[user_id].pop('password', None)
        
        account = cl.account_info()
        
        logger.info(f"Successful 2FA login: Telegram ID={user_id}, Instagram=@{account.username}")
        
        update.message.reply_text(
            f"✅ *Successfully logged in with 2FA!*\n\n"
            f"👤 *Account:* @{account.username}\n"
            f"👥 *Followers:* {account.follower_count:,}\n"
            f"➡️ *Following:* {account.following_count:,}\n"
            f"📝 *Posts:* {account.media_count:,}\n\n"
            f"Choose an action below:",
            parse_mode='Markdown',
            reply_markup=show_main_menu(update)
        )
        
        return WAITING_ACTION
        
    except Exception as e:
        try:
            loading_msg.delete()
        except:
            pass
        
        update.message.reply_text(
            f"❌ *2FA Verification Failed!*\n\n"
            f"Error: `{str(e)}`\n\n"
            f"Please use /start to try again.",
            parse_mode='Markdown'
        )
        
        return ConversationHandler.END

def receive_challenge_code(update: Update, context: CallbackContext):
    """Handle Instagram challenge code"""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    
    # Delete code message
    try:
        update.message.delete()
    except:
        pass
    
    loading_msg = update.message.reply_text("🔄 *Verifying challenge code...*", parse_mode='Markdown')
    
    cl = get_client(user_id)
    
    try:
        # Complete the challenge
        cl.challenge_code_handler(code)
        
        try:
            loading_msg.delete()
        except:
            pass
        
        # Clear password
        user_sessions[user_id].pop('password', None)
        
        account = cl.account_info()
        
        logger.info(f"Successful challenge login: Telegram ID={user_id}, Instagram=@{account.username}")
        
        update.message.reply_text(
            f"✅ *Challenge completed! Logged in successfully!*\n\n"
            f"👤 *Account:* @{account.username}\n"
            f"👥 *Followers:* {account.follower_count:,}\n"
            f"➡️ *Following:* {account.following_count:,}\n\n"
            f"Choose an action below:",
            parse_mode='Markdown',
            reply_markup=show_main_menu(update)
        )
        
        return WAITING_ACTION
        
    except Exception as e:
        try:
            loading_msg.delete()
        except:
            pass
        
        update.message.reply_text(
            f"❌ *Challenge Failed!*\n\n"
            f"Error: `{str(e)}`\n\n"
            f"Use /start to try again.",
            parse_mode='Markdown'
        )
        
        return ConversationHandler.END

def handle_menu_action(update: Update, context: CallbackContext):
    """Handle main menu button clicks"""
    user_id = update.effective_user.id
    choice = update.message.text
    cl = get_client(user_id)
    
    try:
        # Check if STOP button was pressed
        if choice == '⛔ STOP PROCESS':
            if user_id in active_processes:
                stop_active_process(user_id)
                update.message.reply_text(
                    "⏸️ *Stopping process...*\n\nPlease wait for current action to complete.",
                    parse_mode='Markdown'
                )
            else:
                update.message.reply_text(
                    "ℹ️ No active process to stop.",
                    parse_mode='Markdown',
                    reply_markup=show_main_menu(update)
                )
            return WAITING_ACTION
        
        # Check progress
        if choice == '📊 Check Progress':
            if user_id in active_processes:
                proc = active_processes[user_id]
                update.message.reply_text(
                    f"📊 *Current Progress*\n\n"
                    f"Action: *{proc['action']}*\n"
                    f"✅ Completed: *{proc['count']}/{proc['total']}*\n"
                    f"❌ Failed: *{proc['failed']}*\n"
                    f"📈 Progress: *{(proc['count']/proc['total']*100) if proc['total'] > 0 else 0:.1f}%*",
                    parse_mode='Markdown'
                )
            else:
                update.message.reply_text("ℹ️ No active process running.")
            return WAITING_ACTION
        
        if choice == '➖ Unfollow Someone':
            context.user_data['action'] = 'unfollow'
            update.message.reply_text(
                "👤 *Unfollow User*\n\n"
                "Enter the Instagram username to *unfollow*:\n"
                "_(without @ symbol)_",
                parse_mode='Markdown'
            )
            return TARGET_USERNAME
            
        elif choice == '🚫 Remove Follower':
            context.user_data['action'] = 'remove'
            update.message.reply_text(
                "🚫 *Remove Follower*\n\n"
                "Enter the username to *remove* from your followers:\n"
                "_(without @ symbol)_",
                parse_mode='Markdown'
            )
            return TARGET_USERNAME
        
        elif choice == '🔥 Remove ALL Followers':
            # Confirmation
            keyboard = [
                ['✅ YES, Remove ALL Followers', '❌ Cancel']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            account = cl.account_info()
            update.message.reply_text(
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
            # Confirmation
            keyboard = [
                ['✅ YES, Unfollow Everyone', '❌ Cancel']
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            account = cl.account_info()
            update.message.reply_text(
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
            update.message.reply_text(
                "🚀 *Starting mass follower removal...*",
                parse_mode='Markdown'
            )
            # Start in separate thread
            thread = threading.Thread(
                target=mass_remove_followers,
                args=(user_id, context.bot, update.effective_chat.id)
            )
            thread.start()
            context.user_data.pop('awaiting_confirmation', None)
            return WAITING_ACTION
        
        elif choice == '✅ YES, Unfollow Everyone':
            update.message.reply_text(
                "🚀 *Starting mass unfollow...*",
                parse_mode='Markdown'
            )
            # Start in separate thread
            thread = threading.Thread(
                target=mass_unfollow_all,
                args=(user_id, context.bot, update.effective_chat.id)
            )
            thread.start()
            context.user_data.pop('awaiting_confirmation', None)
            return WAITING_ACTION
        
        elif choice == '❌ Cancel':
            context.user_data.pop('awaiting_confirmation', None)
            update.message.reply_text(
                "✅ Cancelled. Choose another action:",
                reply_markup=show_main_menu(update)
            )
            return WAITING_ACTION
            
        elif choice == '📊 Account Info':
            account = cl.account_info()
            update.message.reply_text(
                f"📊 *Account Information*\n\n"
                f"👤 *Username:* @{account.username}\n"
                f"📝 *Full Name:* {account.full_name}\n"
                f"👥 *Followers:* {account.follower_count:,}\n"
                f"➡️ *Following:* {account.following_count:,}\n"
                f"📷 *Posts:* {account.media_count:,}\n"
                f"📖 *Biography:* {account.biography[:100] if account.biography else 'N/A'}",
                parse_mode='Markdown'
            )
            return WAITING_ACTION
            
        elif choice == '❌ Logout':
            # Stop any active process
            stop_active_process(user_id)
            
            # Get username before clearing
            instagram_username = "Unknown"
            if user_id in user_sessions:
                instagram_username = user_sessions[user_id].get('username', 'Unknown')
            
            # Log logout
            logger.info(f"User logged out: Telegram ID={user_id}, Instagram=@{instagram_username}")
            
            # Clear session
            if user_id in instagram_clients:
                del instagram_clients[user_id]
            if user_id in user_sessions:
                del user_sessions[user_id]
            
            update.message.reply_text(
                "👋 *Logged out successfully!*\n\n"
                "Use /start to login again.",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
            
    except LoginRequired:
        update.message.reply_text(
            "⚠️ *Session expired!*\n\n"
            "Please use /start to login again.",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
        
    except Exception as e:
        update.message.reply_text(
            f"❌ *Error:* `{str(e)}`",
            parse_mode='Markdown'
        )
        return WAITING_ACTION

def execute_target_action(update: Update, context: CallbackContext):
    """Execute unfollow or remove follower action"""
    user_id = update.effective_user.id
    target_username = update.message.text.strip().replace('@', '')
    action = context.user_data.get('action')
    cl = get_client(user_id)
    
    loading_msg = update.message.reply_text(f"🔄 *Processing...*", parse_mode='Markdown')
    
    try:
        # Get user ID from username
        user_id_to_action = cl.user_id_from_username(target_username)
        
        if action == 'unfollow':
            cl.user_unfollow(user_id_to_action)
            try:
                loading_msg.delete()
            except:
                pass
            update.message.reply_text(
                f"✅ *Successfully unfollowed* @{target_username}",
                parse_mode='Markdown',
                reply_markup=show_main_menu(update)
            )
            
        elif action == 'remove':
            cl.user_remove_follower(user_id_to_action)
            try:
                loading_msg.delete()
            except:
                pass
            update.message.reply_text(
                f"✅ *Successfully removed* @{target_username} *from followers*",
                parse_mode='Markdown',
                reply_markup=show_main_menu(update)
            )
    
    except Exception as e:
        try:
            loading_msg.delete()
        except:
            pass
        
        error_msg = str(e)
        update.message.reply_text(
            f"❌ *Action failed!*\n\n"
            f"Error: `{error_msg}`\n\n"
            f"Possible reasons:\n"
            f"• Username doesn't exist\n"
            f"• You don't follow this user\n"
            f"• Instagram rate limit\n\n"
            f"Try again or choose another action.",
            parse_mode='Markdown',
            reply_markup=show_main_menu(update)
        )
    
    return WAITING_ACTION

def cancel(update: Update, context: CallbackContext):
    """Cancel and exit conversation"""
    user_id = update.effective_user.id
    stop_active_process(user_id)
    
    update.message.reply_text(
        "❌ *Cancelled*\n\n"
        "Use /start to begin again.",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def error_handler(update: Update, context: CallbackContext):
    """Log errors"""
    logger.warning(f'Update "{update}" caused error "{context.error}"')

# ==================== ADMIN COMMANDS ====================

def stats(update: Update, context: CallbackContext):
    """Show bot statistics (anyone can use)"""
    active_users = len(instagram_clients)
    active_tasks = len(active_processes)
    
    update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"👥 Active users: *{active_users}*\n"
        f"⚙️ Active processes: *{active_tasks}*\n"
        f"🔄 Delay setting: *{DELAY_BETWEEN_ACTIONS}s*",
        parse_mode='Markdown'
    )

# ==================== MAIN FUNCTION ====================

def main():
    """Start the bot"""
    
    # Validate configuration
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: Please set TELEGRAM_BOT_TOKEN in the code!")
        return
    
    # Create updater
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Conversation handler with all states
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            USERNAME: [MessageHandler(Filters.text & ~Filters.command, receive_username)],
            PASSWORD: [MessageHandler(Filters.text & ~Filters.command, receive_password)],
            TWO_FACTOR_CODE: [MessageHandler(Filters.text & ~Filters.command, receive_2fa_code)],
            CHALLENGE_CODE: [MessageHandler(Filters.text & ~Filters.command, receive_challenge_code)],
            WAITING_ACTION: [MessageHandler(Filters.text & ~Filters.command, handle_menu_action)],
            TARGET_USERNAME: [MessageHandler(Filters.text & ~Filters.command, execute_target_action)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )
    
    dp.add_handler(conv_handler)
    dp.add_handler(CommandHandler('stats', stats))
    dp.add_error_handler(error_handler)
    
    # Start bot
    print("=" * 60)
    print("🤖 Instagram Multi-User Manager Bot Started!")
    print("=" * 60)
    print(f"✅ Authorization: DISABLED (Team Mode)")
    print(f"⚠️  ANYONE with bot link can use it!")
    print(f"⏱️  Delay between actions: {DELAY_BETWEEN_ACTIONS} seconds")
    print(f"✅ Bot is running and waiting for commands...")
    print(f"⚠️  Press Ctrl+C to stop the bot")
    print("=" * 60)
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
