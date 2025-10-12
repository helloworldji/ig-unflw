from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired, ChallengeRequired
import os
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8297692816:AAE9-ELN52UJ_uA9WM1L_yOH-n4t0I9kfKI')

# Simple in-memory storage (resets on each function call - limitation of serverless)
user_sessions = {}

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("➖ Unfollow Someone", callback_data="action_unfollow")],
        [InlineKeyboardButton("🚫 Remove Follower", callback_data="action_remove")],
        [InlineKeyboardButton("📊 Account Info", callback_data="action_info")],
        [InlineKeyboardButton("❌ Logout", callback_data="action_logout")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    await update.message.reply_text(
        "🔐 *Instagram Account Manager Bot*\n\n"
        "⚠️ *Note:* This is a serverless version. Mass actions are not available.\n\n"
        "📱 Send your Instagram username:",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    user_id = update.effective_user.id
    text = update.message.text
    
    # Check if waiting for username
    if user_id not in user_sessions:
        # Assume this is username
        user_sessions[user_id] = {'username': text, 'step': 'password'}
        await update.message.reply_text(
            f"✅ Username: *{text}*\n\n"
            "🔑 Now send your Instagram password:\n"
            "_⚠️ Password will be deleted immediately_",
            parse_mode='Markdown'
        )
        return
    
    session = user_sessions[user_id]
    
    # Check if waiting for password
    if session.get('step') == 'password':
        password = text
        username = session['username']
        
        # Delete password message
        try:
            await update.message.delete()
        except:
            pass
        
        msg = await update.message.reply_text("🔄 *Logging in...*", parse_mode='Markdown')
        
        try:
            cl = Client()
            cl.login(username, password)
            
            # Store client session
            session['logged_in'] = True
            session['client_settings'] = cl.get_settings()
            session['step'] = None
            
            account = cl.account_info()
            
            await msg.edit_text(
                f"✅ *Logged in successfully!*\n\n"
                f"👤 @{account.username}\n"
                f"👥 Followers: {account.follower_count:,}\n"
                f"➡️ Following: {account.following_count:,}\n\n"
                "Choose an action:",
                parse_mode='Markdown',
                reply_markup=get_main_menu()
            )
            
        except TwoFactorRequired:
            session['password'] = password
            session['step'] = '2fa'
            await msg.edit_text("🔐 *2FA Required*\n\nSend the 6-digit code:", parse_mode='Markdown')
            
        except ChallengeRequired:
            session['password'] = password
            session['step'] = 'challenge'
            await msg.edit_text("⚠️ *Challenge Required*\n\nSend the verification code:", parse_mode='Markdown')
            
        except Exception as e:
            await msg.edit_text(f"❌ Login failed: {str(e)}\n\nUse /start to retry", parse_mode='Markdown')
            del user_sessions[user_id]
        
        return
    
    # Handle 2FA code
    if session.get('step') == '2fa':
        code = text
        try:
            await update.message.delete()
        except:
            pass
        
        username = session['username']
        password = session['password']
        
        try:
            cl = Client()
            cl.login(username, password, verification_code=code)
            
            session['logged_in'] = True
            session['client_settings'] = cl.get_settings()
            session['step'] = None
            session.pop('password', None)
            
            account = cl.account_info()
            
            await update.message.reply_text(
                f"✅ *Logged in with 2FA!*\n\n👤 @{account.username}",
                parse_mode='Markdown',
                reply_markup=get_main_menu()
            )
        except Exception as e:
            await update.message.reply_text(f"❌ 2FA failed: {str(e)}", parse_mode='Markdown')
            del user_sessions[user_id]
        
        return
    
    # Handle challenge code
    if session.get('step') == 'challenge':
        code = text
        try:
            await update.message.delete()
        except:
            pass
        
        try:
            cl = Client()
            cl.set_settings(session.get('client_settings', {}))
            cl.challenge_code_handler(code)
            
            session['logged_in'] = True
            session['client_settings'] = cl.get_settings()
            session['step'] = None
            
            await update.message.reply_text(
                "✅ *Challenge completed!*",
                parse_mode='Markdown',
                reply_markup=get_main_menu()
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Challenge failed: {str(e)}", parse_mode='Markdown')
            del user_sessions[user_id]
        
        return
    
    # Handle target username for unfollow/remove
    if session.get('step') in ['unfollow_target', 'remove_target']:
        target = text.strip().replace('@', '')
        action = session['step']
        
        try:
            cl = Client()
            cl.set_settings(session['client_settings'])
            
            target_id = cl.user_id_from_username(target)
            
            if action == 'unfollow_target':
                cl.user_unfollow(target_id)
                await update.message.reply_text(
                    f"✅ *Successfully unfollowed* @{target}",
                    parse_mode='Markdown',
                    reply_markup=get_main_menu()
                )
            elif action == 'remove_target':
                cl.user_remove_follower(target_id)
                await update.message.reply_text(
                    f"✅ *Successfully removed* @{target}",
                    parse_mode='Markdown',
                    reply_markup=get_main_menu()
                )
            
            session['step'] = None
            
        except Exception as e:
            await update.message.reply_text(
                f"❌ Failed: {str(e)}",
                parse_mode='Markdown',
                reply_markup=get_main_menu()
            )
            session['step'] = None

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if user_id not in user_sessions:
        await query.edit_message_text("❌ Session expired. Use /start to login again.")
        return
    
    session = user_sessions[user_id]
    
    if not session.get('logged_in'):
        await query.edit_message_text("❌ Not logged in. Use /start")
        return
    
    try:
        cl = Client()
        cl.set_settings(session['client_settings'])
        
        if data == "action_unfollow":
            session['step'] = 'unfollow_target'
            await query.edit_message_text(
                "👤 *Unfollow User*\n\nSend the Instagram username to unfollow:\n_(without @ symbol)_",
                parse_mode='Markdown'
            )
        
        elif data == "action_remove":
            session['step'] = 'remove_target'
            await query.edit_message_text(
                "🚫 *Remove Follower*\n\nSend the username to remove:\n_(without @ symbol)_",
                parse_mode='Markdown'
            )
        
        elif data == "action_info":
            account = cl.account_info()
            await query.edit_message_text(
                f"📊 *Account Information*\n\n"
                f"👤 @{account.username}\n"
                f"👥 Followers: {account.follower_count:,}\n"
                f"➡️ Following: {account.following_count:,}\n"
                f"📷 Posts: {account.media_count:,}",
                parse_mode='Markdown',
                reply_markup=get_main_menu()
            )
        
        elif data == "action_logout":
            del user_sessions[user_id]
            await query.edit_message_text("👋 *Logged out!* Use /start to login again.", parse_mode='Markdown')
    
    except Exception as e:
        await query.edit_message_text(f"❌ Error: {str(e)}", parse_mode='Markdown')

# Vercel serverless function handler
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

application.add_handler(CommandHandler('start', start))
application.add_handler(CallbackQueryHandler(handle_callback))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

async def webhook(request):
    """Handle incoming webhook from Telegram"""
    if request.method == "POST":
        try:
            update = Update.de_json(json.loads(request.body.decode()), application.bot)
            await application.process_update(update)
            return {"statusCode": 200, "body": "OK"}
        except Exception as e:
            logger.error(f"Error: {e}")
            return {"statusCode": 500, "body": str(e)}
    
    return {"statusCode": 200, "body": "Telegram Bot Webhook"}

# For Vercel
def handler(request):
    """Vercel serverless function entry point"""
    import asyncio
    return asyncio.run(webhook(request))
