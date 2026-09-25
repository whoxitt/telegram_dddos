"""
Упрощенный Telegram Bot для авторизации (версия для сервера)
"""

import os
import json
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Константы
API_ID = 94575
API_HASH = 'a3406de8d171bb422bb6ddf3bbd800e2'
ACCOUNTS_FILE = 'accounts.json'

user_sessions = {}

class AccountManager:
    @staticmethod
    def load_accounts(user_id: int) -> list:
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get(str(user_id), [])
            except:
                return []
        return []
    
    @staticmethod
    def save_account(user_id: int, phone: str, label: str = None):
        data = {}
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except:
                pass
        
        user_key = str(user_id)
        if user_key not in data:
            data[user_key] = []
        
        existing = next((acc for acc in data[user_key] if acc['phone'] == phone), None)
        
        if existing:
            existing['label'] = label or phone
            existing['updated'] = datetime.now().isoformat()
        else:
            data[user_key].append({
                'phone': phone,
                'label': label or phone,
                'created': datetime.now().isoformat()
            })
        
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    @staticmethod
    def remove_account(user_id: int, phone: str):
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                user_key = str(user_id)
                if user_key in data:
                    data[user_key] = [acc for acc in data[user_key] if acc['phone'] != phone]
                    
                    session_file = f'session_{phone.replace("+", "")}.session'
                    for ext in ['', '-journal']:
                        try:
                            if os.path.exists(session_file + ext):
                                os.remove(session_file + ext)
                        except:
                            pass
                    
                    with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    return True
            except:
                pass
        return False

def get_session(user_id: int) -> dict:
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            'state': 'main',
            'phone': None,
            'client': None,
            'label': None
        }
    return user_sessions[user_id]

def delete_session_file(phone: str):
    session_name = f'session_{phone.replace("+", "")}'
    for ext in ['.session', '.session-journal']:
        if os.path.exists(session_name + ext):
            try:
                os.remove(session_name + ext)
            except:
                pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    accounts = AccountManager.load_accounts(user.id)
    
    keyboard = []
    if accounts:
        keyboard.append([InlineKeyboardButton("📱 Мои аккаунты", callback_data="list")])
    keyboard.append([InlineKeyboardButton("➕ Добавить аккаунт", callback_data="add")])
    
    text = f"🔐 <b>Telegram Auth Manager</b>\n\nПривет, {user.first_name}!\n\nСохранено аккаунтов: <b>{len(accounts)}</b>"
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def list_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    accounts = AccountManager.load_accounts(update.effective_user.id)
    
    if not accounts:
        await query.message.edit_text("❌ Нет аккаунтов", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Добавить", callback_data="add")],
                                               [InlineKeyboardButton("◀️ Назад", callback_data="start")]]))
        return
    
    text = "<b>📱 Твои аккаунты</b>\n\n"
    keyboard = []
    
    for i, acc in enumerate(accounts, 1):
        label = acc.get('label', acc['phone'])
        text += f"{i}. <b>{label}</b> ({acc['phone']})\n"
        keyboard.append([InlineKeyboardButton(f"🔐 {label}", callback_data=f"login:{acc['phone']}")])
    
    keyboard.append([InlineKeyboardButton("🗑 Удалить", callback_data="del_menu")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="start")])
    
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def add_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    session = get_session(update.effective_user.id)
    session['state'] = 'phone'
    
    await query.message.edit_text(
        "<b>➕ Добавление аккаунта</b>\n\nВведи номер телефона:\n<code>+79123456789</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="start")]]),
        parse_mode='HTML'
    )

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    
    if session['state'] != 'phone':
        return
    
    phone = update.message.text.strip()
    
    if not phone.startswith('+'):
        await update.message.reply_text("❌ Номер должен начинаться с +")
        return
    
    session['phone'] = phone
    session['state'] = 'code'
    delete_session_file(phone)
    
    await update.message.reply_text("⏳ Подключаюсь...")
    
    try:
        # БЕЗ прокси - используется глобальный VPN
        client = TelegramClient(f'session_{phone.replace("+", "")}', API_ID, API_HASH)
        
        await client.connect()
        await client.send_code_request(phone)
        session['client'] = client
        
        await update.message.reply_text(
            f"✅ Код отправлен на <code>{phone}</code>\n\nВведи код:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Заново", callback_data="resend")],
                                               [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]]),
            parse_mode='HTML'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        session['state'] = 'main'

async def resend_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Отправляю новый код...")
    
    session = get_session(update.effective_user.id)
    
    if session['state'] != 'code' or not session['client']:
        return
    
    try:
        delete_session_file(session['phone'])
        await session['client'].disconnect()
        
        # БЕЗ прокси
        client = TelegramClient(f'session_{session["phone"].replace("+", "")}', API_ID, API_HASH)
        
        await client.connect()
        await client.send_code_request(session['phone'])
        session['client'] = client
        
        await query.message.reply_text(f"✅ Новый код отправлен на <code>{session['phone']}</code>", parse_mode='HTML')
    except Exception as e:
        await query.message.reply_text(f"❌ Ошибка: {e}")

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    
    if session['state'] != 'code':
        return
    
    code = update.message.text.strip()
    
    try:
        await session['client'].sign_in(session['phone'], code)
        session['state'] = 'label'
        
        await update.message.reply_text(
            "✅ <b>Успешно!</b>\n\nДобавь подпись для аккаунта:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Пропустить", callback_data="skip")]]),
            parse_mode='HTML'
        )
    except SessionPasswordNeededError:
        session['state'] = '2fa'
        await update.message.reply_text("🔐 Введи пароль 2FA:")
    except PhoneCodeInvalidError:
        await update.message.reply_text("❌ Неверный код! Попробуй еще раз:")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def handle_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    
    if session['state'] != '2fa':
        return
    
    try:
        await session['client'].sign_in(password=update.message.text.strip())
        session['state'] = 'label'
        
        await update.message.reply_text(
            "✅ <b>Успешно!</b>\n\nДобавь подпись:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Пропустить", callback_data="skip")]]),
            parse_mode='HTML'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Неверный пароль: {e}")

async def handle_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    
    if session['state'] != 'label':
        return
    
    label = update.message.text.strip()
    AccountManager.save_account(update.effective_user.id, session['phone'], label)
    
    if session['client']:
        try:
            await session['client'].disconnect()
        except:
            pass
    
    session['state'] = 'main'
    session['client'] = None
    
    await update.message.reply_text(
        f"🎉 Аккаунт <b>{label}</b> сохранен!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 Мои аккаунты", callback_data="list")]]),
        parse_mode='HTML'
    )

async def skip_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    session = get_session(update.effective_user.id)
    AccountManager.save_account(update.effective_user.id, session['phone'], session['phone'])
    
    if session['client']:
        try:
            await session['client'].disconnect()
        except:
            pass
    
    session['state'] = 'main'
    
    await query.message.edit_text(
        f"✅ Аккаунт сохранен!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 Мои аккаунты", callback_data="list")]]))

async def login_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    phone = query.data.split(':')[1]
    session = get_session(update.effective_user.id)
    
    session['phone'] = phone
    session['state'] = 'code'
    delete_session_file(phone)
    
    await query.message.edit_text("⏳ Подключаюсь...")
    
    try:
        # БЕЗ прокси
        client = TelegramClient(f'session_{phone.replace("+", "")}', API_ID, API_HASH)
        await client.connect()
        await client.send_code_request(phone)
        session['client'] = client
        
        await query.message.edit_text(
            f"✅ Код отправлен на <code>{phone}</code>\n\nВведи код:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Заново", callback_data="resend")],
                                               [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]]),
            parse_mode='HTML'
        )
    except Exception as e:
        await query.message.edit_text(f"❌ Ошибка: {e}")

async def delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    accounts = AccountManager.load_accounts(update.effective_user.id)
    
    keyboard = []
    for acc in accounts:
        label = acc.get('label', acc['phone'])
        keyboard.append([InlineKeyboardButton(f"❌ {label}", callback_data=f"delete:{acc['phone']}")])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="list")])
    
    await query.message.edit_text("🗑 Выбери аккаунт для удаления:", reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    phone = query.data.split(':')[1]
    
    if AccountManager.remove_account(update.effective_user.id, phone):
        await query.answer("✅ Удалено!")
        await list_accounts(update, context)
    else:
        await query.answer("❌ Ошибка")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    session = get_session(update.effective_user.id)
    
    if session['client']:
        try:
            await session['client'].disconnect()
        except:
            pass
    
    session['state'] = 'main'
    session['client'] = None
    
    await query.message.reply_text("❌ Отменено")
    await start(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    
    if data == "start":
        await start(update, context)
    elif data == "list":
        await list_accounts(update, context)
    elif data == "add":
        await add_account(update, context)
    elif data.startswith("login:"):
        await login_account(update, context)
    elif data == "del_menu":
        await delete_menu(update, context)
    elif data.startswith("delete:"):
        await delete_account(update, context)
    elif data == "resend":
        await resend_code(update, context)
    elif data == "cancel":
        await cancel(update, context)
    elif data == "skip":
        await skip_label(update, context)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    state = session.get('state', 'main')
    
    if state == 'phone':
        await handle_phone(update, context)
    elif state == 'code':
        await handle_code(update, context)
    elif state == '2fa':
        await handle_2fa(update, context)
    elif state == 'label':
        await handle_label(update, context)

def main():
    # Читаем токен из файла или переменной окружения
    BOT_TOKEN = os.environ.get('BOT_TOKEN')
    
    if not BOT_TOKEN and os.path.exists('bot_token.txt'):
        with open('bot_token.txt', 'r') as f:
            BOT_TOKEN = f.read().strip()
    
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не найден!")
        return
    
    print("✅ Токен загружен")
    print("💡 Убедись что VPN включен!")
    print("")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    print("✅ Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
