import os
import logging
import time
import asyncio
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired, ChallengeRequired, LoginRequired

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = '8297692816:AAE9-ELN52UJ_uA9WM1L_yOH-n4t0I9kfKI'
DELAY_BETWEEN_ACTIONS = 4

USERNAME, PASSWORD, TWO_FACTOR_CODE, CHALLENGE_CODE, WAITING_ACTION, TARGET_USERNAME = range(6)

user_sessions = {}
instagram_clients = {}
active_processes = {}

def get_client(user_id):
    if user_id not in instagram_clients:
        instagram_clients[user_id] = Client()
    return instagram_clients[user_id]

def show_main_menu():
    keyboard = [
        ['➖ Unfollow Someone', '🚫 Remove Follower'],
        ['🔥 Remove ALL Followers', '🔥 Unfollow ALL'],
        ['📊 Account Info', '❌ Logout']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def show_stop_menu():
    keyboard = [['⛔ STOP PROCESS'], ['📊 Check Progress']]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def stop_active_process(user_id):
    if user_id in active_processes:
        active_processes[user_id]['should_stop'] = True
        return True
    return False

def mass_remove_followers_sync(user_id, bot_token, chat_id):
    asyncio.run(mass_remove_followers(user_id, bot_token, chat_id))

async def mass_remove_followers(user_id, bot_token, chat_id):
    from telegram import Bot
    bot = Bot(token=bot_token)
    cl = get_client(user_id)
    
    try:
        active_processes[user_id] = {'should_stop': False, 'action': 'remove_followers', 'count': 0, 'total': 0, 'failed': 0}
        
        await bot.send_message(chat_id=chat_id, text="🔄 *Fetching followers...*", parse_mode='Markdown')
        
        followers = cl.user_followers(cl.user_id)
        total_followers = len(followers)
        active_processes[user_id]['total'] = total_followers
        
        if total_followers == 0:
            await bot.send_message(chat_id=chat_id, text="ℹ️ No followers to remove.", reply_markup=show_main_menu())
            del active_processes[user_id]
            return
        
        await bot.send_message(
            chat_id=chat_id,
            text=f"🔥 *Starting Mass Removal*\n\n📊 Total: *{total_followers}*\n⏱️ ETA: *{(total_followers * DELAY_BETWEEN_ACTIONS) / 60:.1f} min*",
            parse_mode='Markdown',
            reply_markup=show_stop_menu()
        )
        
        count = 0
        failed = 0
        
        for uid, user_info in followers.items():
            if active_processes[user_id].get('should_stop', False):
                await bot.send_message(chat_id=chat_id, text=f"⛔ *STOPPED*\n\n✅ Removed: *{count}*\n❌ Failed: *{failed}*", parse_mode='Markdown', reply_markup=show_main_menu())
                del active_processes[user_id]
                return
            
            try:
                cl.user_remove_follower(uid)
                count += 1
                active_processes[user_id]['count'] = count
                
                if count % 5 == 0:
                    await bot.send_message(chat_id=chat_id, text=f"⚙️ Progress: *{count}/{total_followers}* ({(count/total_followers)*100:.1f}%)", parse_mode='Markdown')
                
                time.sleep(DELAY_BETWEEN_ACTIONS)
            except Exception as e:
                failed += 1
                active_processes[user_id]['failed'] = failed
                time.sleep(2)
        
        await bot.send_message(chat_id=chat_id, text=f"✅ *COMPLETE!*\n\n✅ Removed: *{count}*\n❌ Failed: *{failed}*", parse_mode='Markdown', reply_markup=show_main_menu())
        del active_processes[user_id]
        
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"❌ Error: `{str(e)}`", parse_mode='Markdown', reply_markup=show_main_menu())
        if user_id in active_processes:
            del active_processes[user_id]

def mass_unfollow_all_sync(user_id, bot_token, chat_id):
    asyncio.run(mass_unfollow_all(user_id, bot_token, chat_id))

async def mass_unfollow_all(user_id, bot_token, chat_id):
    from telegram import Bot
    bot = Bot(token=bot_token)
    cl = get_client(user_id)
    
    try:
        active_processes[user_id] = {'should_stop': False, 'action': 'unfollow_all', 'count': 0, 'total': 0, 'failed': 0}
        
        await bot.send_message(chat_id=chat_id, text="🔄 *Fetching following...*", parse_mode='Markdown')
        
        following = cl.user_following(cl.user_id)
        total_following = len(following)
        active_processes[user_id]['total'] = total_following
        
        if total_following == 0:
            await bot.send_message(chat_id=chat_id, text="ℹ️ Not following anyone.", reply_markup=show_main_menu())
            del active_processes[user_id]
            return
        
        await bot.send_message(
            chat_id=chat_id,
            text=f"🔥 *Starting Mass Unfollow*\n\n📊 Total: *{total_following}*\n⏱️ ETA: *{(total_following * DELAY_BETWEEN_ACTIONS) / 60:.1f} min*",
            parse_mode='Markdown',
            reply_markup=show_stop_menu()
        )
        
        count = 0
        failed = 0
        
        for uid, user_info in following.items():
            if active_processes[user_id].get('should_stop', False):
                await bot.send_message(chat_id=chat_id, text=f"⛔ *STOPPED*\n\n✅ Unfollowed: *{count}*\n❌ Failed: *{failed}*", parse_mode='Markdown', reply_markup=show_main_menu())
                del active_processes[user_id]
                return
            
            try:
                cl.user_unfollow(uid)
                count += 1
                active_processes[user_id]['count'] = count
                
                if count % 5 == 0:
                    await bot.send_message(chat_id=chat_id, text=f"⚙️ Progress: *{count}/{total_following}* ({(count/total_following)*100:.1f}%)", parse_mode='Markdown')
                
                time.sleep(DELAY_BETWEEN_ACTIONS)
            except Exception as e:
                failed += 1
                active_processes[user_id]['failed'] = failed
                time.sleep(2)
        
        await bot.send_message(chat_id=chat_id, text=f"✅ *COMPLETE!*\n\n✅ Unfollowed: *{count}*\n❌ Failed: *{failed}*", parse_mode='Markdown', reply_markup=show_main_menu())
        del active_processes[user_id]
        
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"❌ Error: `{str(e)}`", parse_mode='Markdown', reply_markup=show_main_menu())
        if user_id in active_processes:
            del active_processes[user_id]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("🔐 *Instagram Bot*\n\nEnter your Instagram username:", parse_mode='Markdown')
    user_sessions[user_id] = {}
    return USERNAME

async def receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.message.text.strip()
    user_sessions[user_id]['username'] = username
    await update.message.reply_text(f"✅ Username: *{username}*\n\nNow enter password:", parse_mode='Markdown')
    return PASSWORD

async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    password = update.message.text.strip()
    username = user_sessions[user_id]['username']
    
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except:
        pass
    
    msg = await update.message.reply_text("🔄 *Logging in...*", parse_mode='Markdown')
    cl = get_client(user_id)
    
    try:
        cl.login(username, password)
        await msg.delete()
        
        account = cl.account_info()
        await update.message.reply_text(
            f"✅ *Logged in!*\n\n👤 @{account.username}\n👥 Followers: {account.follower_count:,}\n➡️ Following: {account.following_count:,}",
            parse_mode='Markdown',
            reply_markup=show_main_menu()
        )
        return WAITING_ACTION
        
    except TwoFactorRequired:
        await msg.delete()
        await update.message.reply_text("🔐 *2FA Required*\n\nEnter 6-digit code:", parse_mode='Markdown')
        user_sessions[user_id]['password'] = password
        return TWO_FACTOR_CODE
        
    except ChallengeRequired:
        await msg.delete()
        await update.message.reply_text("⚠️ *Challenge Required*\n\nEnter verification code:", parse_mode='Markdown')
        user_sessions[user_id]['password'] = password
        return CHALLENGE_CODE
        
    except Exception as e:
        await msg.delete()
        await update.message.reply_text(f"❌ Login failed: {str(e)}\n\nUse /start to retry", parse_mode='Markdown')
        return ConversationHandler.END

async def receive_2fa_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text(f"✅ *Logged in!*\n\n👤 @{account.username}", parse_mode='Markdown', reply_markup=show_main_menu())
        return WAITING_ACTION
    except Exception as e:
        await update.message.reply_text(f"❌ 2FA Failed: {str(e)}", parse_mode='Markdown')
        return ConversationHandler.END

async def receive_challenge_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text(f"✅ *Challenge completed!*\n\n👤 @{account.username}", parse_mode='Markdown', reply_markup=show_main_menu())
        return WAITING_ACTION
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {str(e)}", parse_mode='Markdown')
        return ConversationHandler.END

async def handle_menu_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    choice = update.message.text
    cl = get_client(user_id)
    
    try:
        if choice == '⛔ STOP PROCESS':
            if user_id in active_processes:
                stop_active_process(user_id)
                await update.message.reply_text("⏸️ *Stopping...*", parse_mode='Markdown')
            else:
                await update.message.reply_text("ℹ️ No active process.", reply_markup=show_main_menu())
            return WAITING_ACTION
        
        if choice == '📊 Check Progress':
            if user_id in active_processes:
                proc = active_processes[user_id]
                await update.message.reply_text(
                    f"📊 Progress: *{proc['count']}/{proc['total']}* ({(proc['count']/proc['total']*100) if proc['total'] > 0 else 0:.1f}%)",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text("ℹ️ No active process.")
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
            await update.message.reply_text(f"⚠️ Remove ALL {account.follower_count:,} followers?\n\nAre you sure?", reply_markup=reply_markup)
            context.user_data['awaiting_confirmation'] = 'remove_all_followers'
            return WAITING_ACTION
        
        elif choice == '🔥 Unfollow ALL':
            keyboard = [['✅ YES, Unfollow ALL', '❌ Cancel']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            account = cl.account_info()
            await update.message.reply_text(f"⚠️ Unfollow ALL {account.following_count:,}?\n\nAre you sure?", reply_markup=reply_markup)
            context.user_data['awaiting_confirmation'] = 'unfollow_all'
            return WAITING_ACTION
        
        elif choice == '✅ YES, Remove ALL':
            await update.message.reply_text("🚀 *Starting...*", parse_mode='Markdown')
            thread = Thread(target=mass_remove_followers_sync, args=(user_id, TELEGRAM_BOT_TOKEN, update.effective_chat.id))
            thread.daemon = True
            thread.start()
            context.user_data.pop('awaiting_confirmation', None)
            return WAITING_ACTION
        
        elif choice == '✅ YES, Unfollow ALL':
            await update.message.reply_text("🚀 *Starting...*", parse_mode='Markdown')
            thread = Thread(target=mass_unfollow_all_sync, args=(user_id, TELEGRAM_BOT_TOKEN, update.effective_chat.id))
            thread.daemon = True
            thread.start()
            context.user_data.pop('awaiting_confirmation', None)
            return WAITING_ACTION
        
        elif choice == '❌ Cancel':
            context.user_data.pop('awaiting_confirmation', None)
            await update.message.reply_text("✅ Cancelled", reply_markup=show_main_menu())
            return WAITING_ACTION
            
        elif choice == '📊 Account Info':
            account = cl.account_info()
            await update.message.reply_text(
                f"📊 *Account Info*\n\n👤 @{account.username}\n👥 Followers: {account.follower_count:,}\n➡️ Following: {account.following_count:,}\n📷 Posts: {account.media_count:,}",
                parse_mode='Markdown'
            )
            return WAITING_ACTION
            
        elif choice == '❌ Logout':
            stop_active_process(user_id)
            if user_id in instagram_clients:
                del instagram_clients[user_id]
            if user_id in user_sessions:
                del user_sessions[user_id]
            await update.message.reply_text("👋 *Logged out!*", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
            
    except LoginRequired:
        await update.message.reply_text("⚠️ *Session expired!* Use /start", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ Error: `{str(e)}`", parse_mode='Markdown')
        return WAITING_ACTION

async def execute_target_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    target_username = update.message.text.strip().replace('@', '')
    action = context.user_data.get('action')
    cl = get_client(user_id)
    
    try:
        target_id = cl.user_id_from_username(target_username)
        
        if action == 'unfollow':
            cl.user_unfollow(target_id)
            await update.message.reply_text(f"✅ Unfollowed @{target_username}", reply_markup=show_main_menu())
        elif action == 'remove':
            cl.user_remove_follower(target_id)
            await update.message.reply_text(f"✅ Removed @{target_username}", reply_markup=show_main_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {str(e)}", reply_markup=show_main_menu())
    
    return WAITING_ACTION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stop_active_process(user_id)
    await update.message.reply_text("❌ Cancelled", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📊 Users: {len(instagram_clients)}\n⚙️ Processes: {len(active_processes)}")

def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

def main():
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
    print("🤖 Instagram Bot Started!")
    print("=" * 60)
    print(f"✅ Bot running on Python {os.sys.version}")
    print(f"✅ Multi-user mode enabled")
    print("=" * 60)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
