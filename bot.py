"""
Telegram Auth Manager Bot v2
Множественные входы + улучшенный интерфейс
"""

import os
import json
import asyncio
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

# Хранилище в памяти (т.к. файловая система Render readonly)
user_sessions = {}
saved_accounts = {}

def get_session(user_id: int) -> dict:
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            'state': 'main',
            'phone': None,
            'client': None,
            'label': None,
            'multi_count': 0,
            'multi_total': 0,
            'multi_codes': []
        }
    return user_sessions[user_id]

def save_account(user_id: int, phone: str, label: str = None):
    """Сохранить аккаунт в памяти"""
    if user_id not in saved_accounts:
        saved_accounts[user_id] = []
    
    # Проверяем есть ли уже
    existing = next((acc for acc in saved_accounts[user_id] if acc['phone'] == phone), None)
    
    if existing:
        existing['label'] = label or phone
        existing['updated'] = datetime.now().isoformat()
    else:
        saved_accounts[user_id].append({
            'phone': phone,
            'label': label or phone,
            'created': datetime.now().isoformat()
        })

def get_accounts(user_id: int) -> list:
    """Получить аккаунты пользователя"""
    return saved_accounts.get(user_id, [])

def remove_account(user_id: int, phone: str):
    """Удалить аккаунт"""
    if user_id in saved_accounts:
        saved_accounts[user_id] = [acc for acc in saved_accounts[user_id] if acc['phone'] != phone]
        return True
    return False

def delete_session_file(phone: str):
    """Удалить сессию"""
    try:
        session_name = f'session_{phone.replace("+", "")}'
        for ext in ['.session', '.session-journal']:
            if os.path.exists(session_name + ext):
                os.remove(session_name + ext)
    except:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню"""
    user = update.effective_user
    accounts = get_accounts(user.id)
    
    keyboard = []
    
    if accounts:
        keyboard.append([InlineKeyboardButton("📱 Мои аккаунты", callback_data="list")])
    
    keyboard.append([InlineKeyboardButton("➕ Добавить аккаунт", callback_data="add")])
    keyboard.append([InlineKeyboardButton("🔄 Множественный вход", callback_data="multi")])
    keyboard.append([InlineKeyboardButton("ℹ️ Инструкция", callback_data="help")])
    keyboard.append([InlineKeyboardButton("📊 Статистика", callback_data="stats")])
    
    text = f"""
🔐 <b>Telegram Auth Manager v2</b>

Привет, {user.first_name}!

<b>Возможности:</b>
✅ Вход с новым кодом каждый раз
✅ Сохранение аккаунтов
✅ Множественные входы (до 10 раз)
✅ Поддержка 2FA

<b>Сохранено аккаунтов:</b> {len(accounts)}
"""
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def list_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список аккаунтов"""
    query = update.callback_query
    await query.answer()
    
    accounts = get_accounts(update.effective_user.id)
    
    if not accounts:
        await query.message.edit_text(
            "❌ Нет сохраненных аккаунтов",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Добавить", callback_data="add")],
                                               [InlineKeyboardButton("◀️ Назад", callback_data="start")]])
        )
        return
    
    text = "<b>📱 Твои аккаунты</b>\n\n"
    keyboard = []
    
    for i, acc in enumerate(accounts, 1):
        label = acc.get('label', acc['phone'])
        text += f"{i}. <b>{label}</b>\n   📞 {acc['phone']}\n\n"
        keyboard.append([InlineKeyboardButton(f"🔐 {label}", callback_data=f"login:{acc['phone']}")])
    
    keyboard.append([InlineKeyboardButton("🗑 Удалить аккаунт", callback_data="del_menu")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="start")])
    
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def add_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить аккаунт"""
    query = update.callback_query
    await query.answer()
    
    session = get_session(update.effective_user.id)
    session['state'] = 'phone'
    session['multi_count'] = 0
    session['multi_total'] = 0
    
    await query.message.edit_text(
        "<b>➕ Добавление аккаунта</b>\n\nВведи номер телефона:\n<code>+79123456789</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="start")]]),
        parse_mode='HTML'
    )

async def multi_login_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню множественного входа"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("2️⃣ 2 входа", callback_data="multi_set:2"),
         InlineKeyboardButton("3️⃣ 3 входа", callback_data="multi_set:3")],
        [InlineKeyboardButton("5️⃣ 5 входов", callback_data="multi_set:5"),
         InlineKeyboardButton("🔟 10 входов", callback_data="multi_set:10")],
        [InlineKeyboardButton("✏️ Свое число", callback_data="multi_custom")],
        [InlineKeyboardButton("◀️ Назад", callback_data="start")]
    ]
    
    text = """
<b>🔄 Множественный вход</b>

Бот зайдет несколько раз подряд и тебе придет много кодов в Telegram!

<b>Как работает:</b>
1. Выбери количество входов
2. Введи номер телефона
3. Бот будет заходить N раз подряд
4. Каждый раз придет новый код

<b>Зачем это нужно:</b>
• Быстрая регистрация нескольких аккаунтов
• Тестирование
• Получение кодов заранее

Выбери количество входов:
"""
    
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def set_multi_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить количество входов"""
    query = update.callback_query
    await query.answer()
    
    count = int(query.data.split(':')[1])
    session = get_session(update.effective_user.id)
    session['state'] = 'phone'
    session['multi_total'] = count
    session['multi_count'] = 0
    session['multi_codes'] = []
    
    await query.message.edit_text(
        f"<b>🔄 Множественный вход ({count}x)</b>\n\nВведи номер телефона:\n<code>+79123456789</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="start")]]),
        parse_mode='HTML'
    )

async def multi_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод своего количества"""
    query = update.callback_query
    await query.answer()
    
    session = get_session(update.effective_user.id)
    session['state'] = 'multi_custom'
    
    await query.message.edit_text(
        "<b>✏️ Свое количество</b>\n\nВведи число от 1 до 20:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="start")]]),
        parse_mode='HTML'
    )

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка номера"""
    session = get_session(update.effective_user.id)
    
    if session['state'] == 'multi_custom':
        try:
            count = int(update.message.text.strip())
            if 1 <= count <= 20:
                session['state'] = 'phone'
                session['multi_total'] = count
                session['multi_count'] = 0
                session['multi_codes'] = []
                await update.message.reply_text(
                    f"✅ Установлено: {count} входов\n\nВведи номер телефона:",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text("❌ Число должно быть от 1 до 20")
        except:
            await update.message.reply_text("❌ Введи число!")
        return
    
    if session['state'] != 'phone':
        return
    
    phone = update.message.text.strip()
    
    if not phone.startswith('+'):
        await update.message.reply_text("❌ Номер должен начинаться с +")
        return
    
    session['phone'] = phone
    session['state'] = 'code'
    
    # Удаляем старую сессию
    delete_session_file(phone)
    
    await update.message.reply_text("⏳ Подключаюсь...")
    
    try:
        client = TelegramClient(f'session_{phone.replace("+", "")}', API_ID, API_HASH)
        await client.connect()
        await client.send_code_request(phone)
        session['client'] = client
        
        if session['multi_total'] > 0:
            session['multi_count'] = 1
            text = f"✅ Код #{session['multi_count']}/{session['multi_total']} отправлен на <code>{phone}</code>\n\n📱 Введи код или пропусти:"
        else:
            text = f"✅ Код отправлен на <code>{phone}</code>\n\n📱 Введи код:"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Заново", callback_data="resend")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
        ]
        
        if session['multi_total'] > 0 and session['multi_count'] < session['multi_total']:
            keyboard.insert(1, [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_code")])
        
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        session['state'] = 'main'

async def resend_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повторная отправка кода"""
    query = update.callback_query
    await query.answer("Отправляю новый код...")
    
    session = get_session(update.effective_user.id)
    
    if session['state'] != 'code' or not session['client']:
        await query.message.reply_text("❌ Нет активной сессии")
        return
    
    try:
        # Удаляем сессию
        delete_session_file(session['phone'])
        await session['client'].disconnect()
        
        # Новое подключение
        client = TelegramClient(f'session_{session["phone"].replace("+", "")}', API_ID, API_HASH)
        await client.connect()
        await client.send_code_request(session['phone'])
        session['client'] = client
        
        await query.message.reply_text(
            f"✅ Новый код отправлен на <code>{session['phone']}</code>",
            parse_mode='HTML'
        )
    except Exception as e:
        await query.message.reply_text(f"❌ Ошибка: {e}")

async def skip_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропустить ввод кода и запросить следующий"""
    query = update.callback_query
    await query.answer()
    
    session = get_session(update.effective_user.id)
    
    if session['multi_count'] >= session['multi_total']:
        await query.message.reply_text("❌ Лимит достигнут")
        return
    
    try:
        # Отключаемся
        if session['client']:
            await session['client'].disconnect()
        
        # Удаляем сессию
        delete_session_file(session['phone'])
        
        # Запрашиваем новый код
        session['multi_count'] += 1
        
        client = TelegramClient(f'session_{session["phone"].replace("+", "")}', API_ID, API_HASH)
        await client.connect()
        await client.send_code_request(session['phone'])
        session['client'] = client
        
        text = f"✅ Код #{session['multi_count']}/{session['multi_total']} отправлен на <code>{session['phone']}</code>\n\n📱 Введи код или пропусти:"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Заново", callback_data="resend")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
        ]
        
        if session['multi_count'] < session['multi_total']:
            keyboard.insert(1, [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_code")])
        
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        
    except Exception as e:
        await query.message.reply_text(f"❌ Ошибка: {e}")

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кода"""
    session = get_session(update.effective_user.id)
    
    if session['state'] != 'code':
        return
    
    code = update.message.text.strip()
    
    try:
        await session['client'].sign_in(session['phone'], code)
        
        # Добавляем в список кодов
        session['multi_codes'].append(code)
        
        # Если множественный вход и еще не все
        if session['multi_total'] > 0 and session['multi_count'] < session['multi_total']:
            await update.message.reply_text(f"✅ Код #{session['multi_count']} принят!")
            
            # Отключаемся
            await session['client'].disconnect()
            delete_session_file(session['phone'])
            
            # Запрашиваем следующий
            await asyncio.sleep(2)
            session['multi_count'] += 1
            
            client = TelegramClient(f'session_{session["phone"].replace("+", "")}', API_ID, API_HASH)
            await client.connect()
            await client.send_code_request(session['phone'])
            session['client'] = client
            
            text = f"✅ Код #{session['multi_count']}/{session['multi_total']} отправлен!\n\n📱 Введи код или пропусти:"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Заново", callback_data="resend")],
                [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
            ]
            
            if session['multi_count'] < session['multi_total']:
                keyboard.insert(1, [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_code")])
            
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
            return
        
        # Завершено - спрашиваем подпись
        session['state'] = 'label'
        
        stats_text = ""
        if session['multi_total'] > 0:
            stats_text = f"\n\n📊 Получено кодов: {len(session['multi_codes'])}/{session['multi_total']}"
        
        await update.message.reply_text(
            f"✅ <b>Успешно авторизован!</b>{stats_text}\n\nДобавь подпись для аккаунта:",
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
    """Обработка 2FA"""
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
    """Обработка подписи"""
    session = get_session(update.effective_user.id)
    
    if session['state'] != 'label':
        return
    
    label = update.message.text.strip()
    save_account(update.effective_user.id, session['phone'], label)
    
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
    """Пропустить подпись"""
    query = update.callback_query
    await query.answer()
    
    session = get_session(update.effective_user.id)
    save_account(update.effective_user.id, session['phone'], session['phone'])
    
    if session['client']:
        try:
            await session['client'].disconnect()
        except:
            pass
    
    session['state'] = 'main'
    
    await query.message.edit_text(
        "✅ Аккаунт сохранен!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📱 Мои аккаунты", callback_data="list")]])
    )

async def login_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в сохраненный аккаунт"""
    query = update.callback_query
    await query.answer()
    
    phone = query.data.split(':')[1]
    session = get_session(update.effective_user.id)
    
    session['phone'] = phone
    session['state'] = 'code'
    session['multi_count'] = 0
    session['multi_total'] = 0
    
    delete_session_file(phone)
    
    await query.message.edit_text("⏳ Подключаюсь...")
    
    try:
        client = TelegramClient(f'session_{phone.replace("+", "")}', API_ID, API_HASH)
        await client.connect()
        await client.send_code_request(phone)
        session['client'] = client
        
        await query.message.edit_text(
            f"✅ Код отправлен на <code>{phone}</code>\n\n📱 Введи код:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Заново", callback_data="resend")],
                [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
            ]),
            parse_mode='HTML'
        )
    except Exception as e:
        await query.message.edit_text(f"❌ Ошибка: {e}")

async def delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню удаления"""
    query = update.callback_query
    await query.answer()
    
    accounts = get_accounts(update.effective_user.id)
    
    keyboard = []
    for acc in accounts:
        label = acc.get('label', acc['phone'])
        keyboard.append([InlineKeyboardButton(f"❌ {label}", callback_data=f"delete:{acc['phone']}")])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="list")])
    
    await query.message.edit_text("🗑 Выбери аккаунт для удаления:", reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить аккаунт"""
    query = update.callback_query
    
    phone = query.data.split(':')[1]
    
    if remove_account(update.effective_user.id, phone):
        delete_session_file(phone)
        await query.answer("✅ Удалено!")
        await list_accounts(update, context)
    else:
        await query.answer("❌ Ошибка")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена"""
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

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Инструкция"""
    query = update.callback_query
    await query.answer()
    
    text = """
<b>ℹ️ Инструкция</b>

<b>🔐 Обычный вход:</b>
1. Нажми "➕ Добавить аккаунт"
2. Введи номер телефона
3. Введи код из Telegram
4. Готово!

<b>🔄 Множественный вход:</b>
1. Нажми "🔄 Множественный вход"
2. Выбери количество (или введи свое)
3. Введи номер телефона
4. Бот будет заходить N раз подряд
5. Каждый раз придет новый код
6. Можешь вводить коды или пропускать

<b>💡 Зачем множественный вход:</b>
• Быстрая регистрация сервисов
• Тестирование
• Получение кодов заранее

<b>🔄 Кнопка "Заново":</b>
Удаляет старую сессию и отправляет новый код

<b>⏭ Кнопка "Пропустить":</b>
Пропускает текущий код и запрашивает следующий

<b>⚠️ Важно:</b>
• Все данные хранятся в памяти
• При перезапуске бота данные сбросятся
• Сессии удаляются перед каждым входом
"""
    
    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="start")]]),
        parse_mode='HTML'
    )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика"""
    query = update.callback_query
    await query.answer()
    
    accounts = get_accounts(update.effective_user.id)
    
    text = f"""
<b>📊 Статистика</b>

<b>Твои данные:</b>
• Сохранено аккаунтов: {len(accounts)}
• ID: <code>{update.effective_user.id}</code>

<b>О боте:</b>
• Версия: 2.0
• API: Telegram MTProto
• Хранилище: В памяти (временное)
"""
    
    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="start")]]),
        parse_mode='HTML'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок"""
    data = update.callback_query.data
    
    if data == "start":
        await start(update, context)
    elif data == "list":
        await list_accounts(update, context)
    elif data == "add":
        await add_account(update, context)
    elif data == "multi":
        await multi_login_menu(update, context)
    elif data.startswith("multi_set:"):
        await set_multi_count(update, context)
    elif data == "multi_custom":
        await multi_custom(update, context)
    elif data.startswith("login:"):
        await login_account(update, context)
    elif data == "del_menu":
        await delete_menu(update, context)
    elif data.startswith("delete:"):
        await delete_account(update, context)
    elif data == "resend":
        await resend_code(update, context)
    elif data == "skip_code":
        await skip_code(update, context)
    elif data == "cancel":
        await cancel(update, context)
    elif data == "skip":
        await skip_label(update, context)
    elif data == "help":
        await show_help(update, context)
    elif data == "stats":
        await show_stats(update, context)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик сообщений"""
    session = get_session(update.effective_user.id)
    state = session.get('state', 'main')
    
    if state in ['phone', 'multi_custom']:
        await handle_phone(update, context)
    elif state == 'code':
        await handle_code(update, context)
    elif state == '2fa':
        await handle_2fa(update, context)
    elif state == 'label':
        await handle_label(update, context)

def main():
    BOT_TOKEN = os.environ.get('BOT_TOKEN')
    
    if not BOT_TOKEN and os.path.exists('bot_token.txt'):
        with open('bot_token.txt', 'r') as f:
            BOT_TOKEN = f.read().strip()
    
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не найден!")
        return
    
    print("✅ Токен загружен")
    print("🚀 Запуск бота v2...")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    print("✅ Бот запущен!")
    
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
