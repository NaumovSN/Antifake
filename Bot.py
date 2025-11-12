import logging
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, \
    CallbackQuery
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, CallbackContext
from telegram.error import TelegramError
import sqlite3

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- БЛОК КОНФИГУРАЦИИ ---

# Загружаем переменные окружения из .env файла
load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Статический ID супер администраторов
SUPER_ADMIN_IDS = [693462962, 296649668]  # Список супер администраторов

# --- Валидация переменных ---

if not BOT_TOKEN:
    logger.critical("Переменная окружения BOT_TOKEN не установлена!")
    raise ValueError("Необходима переменная окружения BOT_TOKEN")


# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message_text TEXT,
            message_id INTEGER,
            admin_message_id TEXT,
            status TEXT DEFAULT 'pending',
            response TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_by_admin_id INTEGER, 
            FOREIGN KEY(processed_by_admin_id) REFERENCES users(user_id)
        )
    ''')

    # Обновленная таблица users с полем is_super_admin
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_admin BOOLEAN DEFAULT FALSE,
            is_super_admin BOOLEAN DEFAULT FALSE,  -- Новое поле
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Добавляем/обновляем супер администраторов
    for super_admin_id in SUPER_ADMIN_IDS:
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, is_admin, is_super_admin) 
            VALUES (?, TRUE, TRUE)
        ''', (super_admin_id,))

        # Обновляем, если пользователь уже был в базе, но без прав
        cursor.execute('''
            UPDATE users SET is_admin = TRUE, is_super_admin = TRUE WHERE user_id = ?
        ''', (super_admin_id,))

    conn.commit()
    conn.close()


# Клавиатура для гостей
def get_guest_keyboard():
    keyboard = [
        [KeyboardButton("📋 Справка")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# Клавиатура для администраторов
def get_admin_keyboard():
    keyboard = [
        [KeyboardButton("📊 Статистика"), KeyboardButton("🗑️ Сброс")],
        [KeyboardButton("📋 Справка")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# Клавиатура для СУПЕР администраторов
def get_super_admin_keyboard():
    keyboard = [
        [KeyboardButton("📊 Статистика"), KeyboardButton("🗑️ Сброс")],
        [KeyboardButton("➕/➖ Админы"), KeyboardButton("📋 Справка")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# Клавиатура для кнопок администратора в сообщениях
def get_admin_inline_keyboard(report_id):
    keyboard = [
        [
            InlineKeyboardButton("✅ Фейк", callback_data=f"fake_{report_id}"),
            InlineKeyboardButton("❌ Не фейк", callback_data=f"not_{report_id}")
        ],
        [
            InlineKeyboardButton("⏸️ Без ответа", callback_data=f"no_{report_id}"),
            InlineKeyboardButton("🚫 Игнор", callback_data=f"ignore_{report_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


# Клавиатура для управления админами
def get_super_admin_inline_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ Добавить админа", callback_data="add_admin_start")],
        [InlineKeyboardButton("➖ Удалить админа", callback_data="remove_admin_start")],
        [InlineKeyboardButton("📜 Список админов", callback_data="list_admins")]
    ]
    return InlineKeyboardMarkup(keyboard)


# Проверка прав администратора (получает список из БД)
def is_admin(user_id):
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == 1


# Проверка прав супер администратора (получает список из БД)
def is_super_admin(user_id):
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT is_super_admin FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == 1


# Команда /start
async def start(update: Update, _context: CallbackContext):
    user = update.effective_user
    user_id = user.id
    username = user.username
    first_name = user.first_name

    # Сохраняем/обновляем информацию о пользователе
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, username, first_name) 
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
        username = excluded.username,
        first_name = excluded.first_name
    ''', (user_id, username, first_name))

    # Обновляем права для SUPER_ADMIN_IDS, если они вдруг сбросились
    if user_id in SUPER_ADMIN_IDS:
        cursor.execute('''
            UPDATE users SET is_admin = TRUE, is_super_admin = TRUE WHERE user_id = ?
        ''', (user_id,))

    conn.commit()
    conn.close()

    is_sup_admin = is_super_admin(user_id)
    is_adm = is_admin(user_id)

    if is_sup_admin:
        await update.message.reply_text(
            "👑 Добро пожаловать, *Супер Администратор*!\n\n"
            "Используйте кнопки ниже для навигации. Вы можете управлять списком администраторов.",
            reply_markup=get_super_admin_keyboard(),
            parse_mode='Markdown'
        )
    elif is_adm:
        await update.message.reply_text(
            "👋 Добро пожаловать, Администратор!\n\n"
            "Используйте кнопки ниже для навигации.",
            reply_markup=get_admin_keyboard()
        )
    else:
        await update.message.reply_text(
            "Добро пожаловать в бот *Антифейк | Орловская область* \n\n"
            "🔍 Здесь вы можете проверить, является ли информация фейковой. Опишите ситуацию в сообщении для бота и прикрепите скриншот, фотографию или видеозапись. Если информация уже где-то опубликована, обязательно добавьте ссылку. \n\n"
            "📋 Справка - получите информацию о работе бота\n\n"
            "_Проект «Антифейк» реализуется Центром управления региона Орловской области и Департаментом информационно-аналитической работы Орловской области_",
            reply_markup=get_guest_keyboard(),
            parse_mode='Markdown'
        )


# Обработка текстовых сообщений
async def handle_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    message_text = update.message.text
    is_sup_admin = is_super_admin(user_id)
    is_adm = is_admin(user_id)

    # Обработка состояний (для добавления/удаления админа)
    if context.user_data.get('state') == 'awaiting_admin_id' and is_sup_admin:
        await add_admin(update, context)
        return
    elif context.user_data.get('state') == 'awaiting_remove_id' and is_sup_admin:
        await remove_admin(update, context)
        return

    if is_adm:
        # Администраторы/Супер администраторы
        if message_text == "📋 Справка":
            await show_admin_help(update)
        elif message_text == "📊 Статистика":
            await show_statistics(update)
        elif message_text == "🗑️ Сброс":
            await ask_for_reset_confirmation(update)
        elif message_text == "➕/➖ Админы" and is_sup_admin:
            await update.message.reply_text(
                "👑 **Управление администраторами**\nВыберите действие:",
                reply_markup=get_super_admin_inline_keyboard(),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("ℹ️ Используйте кнопки меню для навигации.")
    else:
        # Обработка сообщений от гостей
        if message_text == "📋 Справка":
            await show_guest_help(update)
        else:
            await process_guest_report(update, context)


# Обработка медиа-сообщений от гостей
async def handle_media(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await process_guest_report(update, context)


# Обработка жалобы от гостя
async def process_guest_report(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id
    message = update.message

    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()

    # 1. Получаем список всех текущих администраторов из БД
    cursor.execute('SELECT user_id FROM users WHERE is_admin = TRUE')
    admin_ids = [row[0] for row in cursor.fetchall()]

    # Сохраняем/обновляем информацию о пользователе
    cursor.execute('''
        INSERT INTO users (user_id, username, first_name) 
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
        username = excluded.username,
        first_name = excluded.first_name
    ''', (user_id, user.username, user.first_name))

    # Получаем текст сообщения или описание для медиа
    if message.text:
        message_content = message.text
    elif message.caption:
        message_content = message.caption
    else:
        message_content = "Медиа-сообщение без текста"

    cursor.execute('''
        INSERT INTO reports (user_id, message_text, message_id)
        VALUES (?, ?, ?)
    ''', (user_id, message_content, message.message_id))

    report_id = cursor.lastrowid
    conn.commit()

    # Отправляем отбивку сообщение гостю
    await message.reply_text(
        "✅ Ваше сообщение получено! Спасибо за сигнал.\n"
        "В ближайшее время мы дадим вам ответ."
    )

    # Формируем сообщение для администраторов
    username_display = f"@{user.username}" if user.username else user.first_name
    user_info = f"👤 Пользователь: {username_display} (ID: {user_id})"
    report_info = f"📄 Жалоба #{report_id}\n\n{user_info}"

    admin_message_ids = []

    # Отправляем сообщение всем администраторам
    for admin_id in admin_ids:  # Используем список из БД
        try:
            # 1. Пересылаем ОРИГИНАЛЬНОЕ сообщение
            forwarded_msg = await context.bot.forward_message(
                chat_id=admin_id,
                from_chat_id=message.chat_id,
                message_id=message.message_id
            )

            # 2. Отправляем кнопки ОТВЕТОМ на пересланное сообщение
            admin_message = await context.bot.send_message(
                chat_id=admin_id,
                text=report_info,
                reply_to_message_id=forwarded_msg.message_id,
                reply_markup=get_admin_inline_keyboard(report_id)
            )

            # Сохраняем ID сообщения с кнопками
            admin_message_ids.append(str(admin_message.message_id))

        except Exception as e:
            logger.error(f"Ошибка отправки администратору {admin_id}: {e}")

    # Сохраняем ID сообщений администраторов
    cursor.execute('''
        UPDATE reports SET admin_message_id = ? WHERE id = ?
    ''', (','.join(admin_message_ids), report_id))

    conn.commit()
    conn.close()


# Обработка нажатий на кнопки администратора
async def handle_admin_button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    callback_data = query.data

    # 1. Проверка прав администратора
    if not is_admin(user_id):
        await query.edit_message_text("❌ У вас нет прав для этого действия!")
        return

    is_sup_admin = is_super_admin(user_id)

    # 2. Обработка кнопок сброса (доступно всем админам)
    if callback_data == "confirm_reset":
        await perform_reset(query)
        return
    if callback_data == "cancel_reset":
        await query.edit_message_text("✅ Сброс статистики отменен.")
        return

    # 3. Обработка кнопок управления админами (доступно только супер админам)
    if callback_data in ["add_admin_start", "remove_admin_start", "list_admins"]:
        if is_sup_admin:
            if callback_data == "add_admin_start":
                context.user_data['state'] = 'awaiting_admin_id'
                await query.edit_message_text(
                    "➕ **Добавление администратора**\n"
                    "Введите *ID* пользователя Telegram, которого хотите сделать администратором:",
                    parse_mode='Markdown'
                )
            elif callback_data == "remove_admin_start":
                context.user_data['state'] = 'awaiting_remove_id'
                await query.edit_message_text(
                    "➖ **Удаление администратора**\n"
                    "Введите *ID* пользователя Telegram, которого хотите удалить из администраторов.\n\n"
                    "⚠️ **ВНИМАНИЕ**: Вы не можете удалить себя.",
                    parse_mode='Markdown'
                )
            elif callback_data == "list_admins":
                await show_admin_list(query)
        else:
            await query.edit_message_text("❌ У вас нет прав *Супер Администратора* для этого действия!")
        return

    # 4. Обработка кнопок для отчета
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()

    # Парсинг callback_data для отчета
    try:
        action, report_id_str = callback_data.split('_', 1)
        report_id = int(report_id_str)
    except ValueError:
        await query.edit_message_text("❌ Ошибка обработки запроса!")
        conn.close()
        return

    # Получаем информацию о жалобе
    cursor.execute('''
        SELECT user_id, message_text, status, admin_message_id FROM reports WHERE id = ?
    ''', (report_id,))

    report = cursor.fetchone()

    if not report:
        await query.edit_message_text("❌ Жалоба не найдена!")
        conn.close()
        return

    user_id_guest, message_text_guest, status, admin_message_ids = report

    if status != 'pending':
        await query.edit_message_text(f"❌ На эту жалобу уже дан ответ (статус: {status})!")
        conn.close()
        return

    # 5. Получаем список всех текущих администраторов из БД для синхронизации
    cursor.execute('SELECT user_id FROM users WHERE is_admin = TRUE')
    all_current_admin_ids = [row[0] for row in cursor.fetchall()]

    # Обрабатываем выбор администратора
    if action == "fake":
        response_text = "⚠️ Администратор подтвердил, что это информация является фейком. Разъяснения будут опубликованы в канале *Антифейк | Орловская область* @antifake57"
        status_update = "fake"
        send_to_guest = True
    elif action == "not":
        response_text = "✅ Администратор подтвердил, что информация не является фейковой."
        status_update = "not_fake"
        send_to_guest = True
    elif action == "no":
        response_text = "ℹ️ Ваше сообщение нуждается в дополнительной проверке."
        status_update = "no_response"
        send_to_guest = True
    elif action == "ignore":
        response_text = "🚫 Администратор проигнорировал обращение."
        status_update = "ignored"
        send_to_guest = False  # Не отправляем сообщение гостю
    else:
        await query.edit_message_text("❌ Неизвестное действие!")
        conn.close()
        return

    # Обновляем статус жалобы и ID администратора
    cursor.execute('''
        UPDATE reports SET status = ?, response = ?, processed_by_admin_id = ? WHERE id = ?
    ''', (status_update, response_text, user_id, report_id))

    # Отправляем ответ гостю только если не выбран игнор
    if send_to_guest:
        try:
            await context.bot.send_message(
                chat_id=user_id_guest,
                text=f"📢 Ответ на ваше сообщение:\n\n{response_text}\n\nВаше сообщение: {message_text_guest}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки ответа гостю {user_id_guest}: {e}")

    # Получаем оригинальный текст из сообщения с кнопками
    original_admin_message_content = ""
    if query.message is not None and hasattr(query.message, 'text'):
        original_admin_message_content = query.message.text or ""

    # Ищем строку с информацией о пользователе
    user_info_line = ""
    if original_admin_message_content:
        for line in original_admin_message_content.split('\n'):
            if line.startswith("👤 Пользователь:"):
                user_info_line = line
                break

    if not user_info_line:
        user_info_line = f"Жалоба от пользователя (ID: {user_id_guest})"  # Fallback

    # Обновляем сообщения у всех администраторов
    admin_username = f"@{query.from_user.username}" if query.from_user.username else query.from_user.first_name
    new_text = f"✅ Обработано: {admin_username}\nСтатус: {response_text}\n\n{user_info_line}"

    if admin_message_ids:
        admin_message_id_list = admin_message_ids.split(',')

        # Получаем список ID админов, которым было отправлено сообщение
        # (в данном случае это те, кто были админами на момент отправки)
        # В идеале нужно хранить маппинг в БД, но для упрощения используем zip

        # Обновляем сообщение у админа, который нажал (это всегда текстовое сообщение с кнопками)
        try:
            await query.edit_message_text(text=new_text, reply_markup=None)
        except TelegramError as e:
            logger.warning(f"Не удалось обновить исходное сообщение: {e}")

        # Обновляем сообщения у ДРУГИХ администраторов
        # Важно: здесь мы используем *всех* текущих админов (all_current_admin_ids)
        # и сохраненные ID сообщений (admin_message_id_list).
        # Это может привести к ошибкам, если список админов изменился.
        # Для *корректной* синхронизации нужно хранить маппинг (report_id, admin_id, admin_message_id)
        # Но для простоты: сопоставим текущих админов с сохраненными message_id

        # ВНИМАНИЕ: Из-за упрощения логики, если список админов изменится между отправкой
        # жалобы и ее обработкой, синхронизация может сработать некорректно.
        # Для Production-кода требуется более надежная схема с маппинг-таблицей.

        # Просто пройдемся по сохраненным message_id и попробуем обновить их
        for admin_id_loop, msg_id_str in zip(all_current_admin_ids, admin_message_id_list):

            # Пропускаем админа, который нажал на кнопку (его сообщение уже было обновлено выше)
            if admin_id_loop == query.from_user.id:
                continue

            try:
                msg_id = int(msg_id_str)
            except (ValueError, TypeError):
                logger.error(f"Неверный msg_id {msg_id_str} для админа {admin_id_loop} (жалоба {report_id})")
                continue

            # Обновляем текстовое сообщение с кнопками у другого админа
            try:
                await context.bot.edit_message_text(
                    chat_id=admin_id_loop,
                    message_id=msg_id,
                    text=new_text,
                    reply_markup=None
                )
            except TelegramError as e:
                # Логи только значимые ошибки
                if "message to edit not found" not in str(e) and "message is not modified" not in str(e):
                    logger.error(f"Не удалось обновить сообщение {msg_id} у админа {admin_id_loop}: {e}")

    conn.commit()
    conn.close()


# --- ФУНКЦИИ УПРАВЛЕНИЯ АДМИНАМИ ---

async def add_admin(update: Update, context: CallbackContext):
    """Добавляет пользователя в администраторы по ID."""
    user_id = update.effective_user.id
    if not is_super_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав Супер Администратора.")
        return

    context.user_data['state'] = None  # Сброс состояния

    try:
        new_admin_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Пожалуйста, введите только числовой ID пользователя.")
        return

    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        # Проверяем, существует ли пользователь в базе (если он ранее взаимодействовал с ботом)
        cursor.execute('SELECT username, first_name, is_admin FROM users WHERE user_id = ?', (new_admin_id,))
        user_data = cursor.fetchone()

        if user_data and user_data[2] == 1:
            await update.message.reply_text(f"❌ Пользователь (ID: {new_admin_id}) уже является администратором.")
            return

        # Пытаемся получить информацию о пользователе из Telegram API
        try:
            user = await context.bot.get_chat(new_admin_id)
            username = user.username
            first_name = user.first_name
        except Exception as e:
            logger.warning(f"Не удалось получить информацию о пользователе {new_admin_id} из Telegram API: {e}")
            username = None
            first_name = None

        # Обновляем или вставляем нового админа с актуальной информацией
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, is_admin) 
            VALUES (?, ?, ?, TRUE)
            ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            is_admin = TRUE
        ''', (new_admin_id, username, first_name))

        conn.commit()

        # Формируем отображаемое имя
        display_name = f"@{username}" if username else first_name if first_name else f"ID: {new_admin_id}"

        await update.message.reply_text(
            f"✅ Пользователь *{display_name}* (ID: {new_admin_id}) успешно добавлен в администраторов.",
            parse_mode='Markdown')

        # Оповещение нового админа (если возможно)
        try:
            await context.bot.send_message(
                chat_id=new_admin_id,
                text="🎉 Поздравляем! Вы назначены администратором бота *Антифейк | Орловская область*.\n"
                     "Используйте команду /start для активации админ-клавиатуры.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить нового администратора {new_admin_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка при добавлении администратора: {e}")
        await update.message.reply_text("❌ Произошла ошибка при добавлении администратора.")
    finally:
        conn.close()


async def remove_admin(update: Update, context: CallbackContext):
    """Удаляет пользователя из администраторов по ID."""
    user_id = update.effective_user.id
    if not is_super_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав Супер Администратора.")
        return

    context.user_data['state'] = None  # Сброс состояния

    try:
        remove_admin_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Пожалуйста, введите только числовой ID пользователя.")
        return

    if remove_admin_id == user_id:
        await update.message.reply_text("❌ Вы не можете удалить *себя* из администраторов.", parse_mode='Markdown')
        return

    if remove_admin_id in SUPER_ADMIN_IDS:
        await update.message.reply_text("❌ Вы не можете удалить *статического Супер Администратора*.",
                                        parse_mode='Markdown')
        return

    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        # Проверяем, является ли пользователь админом
        cursor.execute('SELECT username, first_name, is_admin FROM users WHERE user_id = ?', (remove_admin_id,))
        user_data = cursor.fetchone()

        if not user_data or user_data[2] != 1:
            await update.message.reply_text(f"❌ Пользователь (ID: {remove_admin_id}) не является администратором.")
            return

        # Удаляем права администратора
        cursor.execute('''
            UPDATE users SET is_admin = FALSE, is_super_admin = FALSE WHERE user_id = ?
        ''', (remove_admin_id,))

        conn.commit()

        # Формируем отображаемое имя
        display_name = f"@{user_data[0]}" if user_data[0] else user_data[1] if user_data[1] else f"ID: {remove_admin_id}"

        await update.message.reply_text(
            f"✅ Пользователь *{display_name}* (ID: {remove_admin_id}) успешно удален из администраторов.",
            parse_mode='Markdown')

        # Оповещение бывшего админа
        try:
            await context.bot.send_message(
                chat_id=remove_admin_id,
                text="😢 Ваши права администратора бота *Антифейк | Орловская область* были отозваны. "
                     "Используйте команду /start для получения гостевой клавиатуры.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить бывшего администратора {remove_admin_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка при удалении администратора: {e}")
        await update.message.reply_text("❌ Произошла ошибка при удалении администратора.")
    finally:
        conn.close()


async def show_admin_list(query: CallbackQuery):
    """Показывает список всех администраторов и супер администраторов."""
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT user_id, username, first_name, is_super_admin FROM users WHERE is_admin = TRUE
            ORDER BY is_super_admin DESC, user_id ASC
        ''')
        admin_list = cursor.fetchall()

        list_text = "📜 Список Администраторов:\n\n"

        if not admin_list:
            list_text += "  (Нет администраторов, кроме, возможно, статического Супер Администратора)"
        else:
            for user_id, username, first_name, is_super in admin_list:
                display_name = f"@{username}" if username else first_name if first_name else "Имя не указано"
                role = "👑 Супер Админ" if is_super else "👤 Админ"

                list_text += f"• {role}: {display_name}\n"
                list_text += f"  ID: {user_id}\n\n"

        await query.edit_message_text(list_text, parse_mode=None)

    except Exception as e:
        logger.error(f"Ошибка при получении списка администраторов: {e}")
        await query.edit_message_text("❌ Произошла ошибка при получении списка администраторов.")
    finally:
        conn.close()


# --- СТАНДАРТНЫЕ ФУНКЦИИ АДМИНОВ ---

async def show_statistics(update: Update):
    """Отправляет администратору статистику по боту."""
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        # 1. Всего обращений
        cursor.execute("SELECT COUNT(*) FROM reports")
        total_reports = cursor.fetchone()[0]

        # 2. Всего фейков
        cursor.execute("SELECT COUNT(*) FROM reports WHERE status = 'fake'")
        total_fakes = cursor.fetchone()[0]

        # 3. Обработано по администраторам
        cursor.execute('''
            SELECT u.username, u.first_name, COUNT(r.id) 
            FROM reports r
            JOIN users u ON r.processed_by_admin_id = u.user_id
            WHERE r.status != 'pending'
            GROUP BY r.processed_by_admin_id
            ORDER BY COUNT(r.id) DESC
        ''')
        admin_stats = cursor.fetchall()

        stats_text = f"📊 **Статистика Бота**\n\n"
        stats_text += f"**Всего обращений:** {total_reports}\n"
        stats_text += f"**Из них фейков:** {total_fakes}\n\n"
        stats_text += "**Обработано по администраторам:**\n"

        if not admin_stats:
            stats_text += "  (пока нет обработанных обращений)"
        else:
            for username, first_name, count in admin_stats:
                display_name = f"@{username}" if username else first_name
                stats_text += f"  • {display_name}: {count}\n"

        await update.message.reply_text(stats_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        await update.message.reply_text("❌ Произошла ошибка при получении статистики.")
    finally:
        conn.close()


async def ask_for_reset_confirmation(update: Update):
    """Запрашивает подтверждение на сброс статистики."""
    keyboard = [
        [InlineKeyboardButton("⚠️ Да, сбросить статистику", callback_data="confirm_reset")],
        [InlineKeyboardButton("❌ Отменить сброс", callback_data="cancel_reset")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "**ВНИМАНИЕ!**\n\n"
        "Вы уверены, что хотите сбросить *всю статистику*?\n\n"
        "⚠⚠⚠\n"
        "Необработанные обращения *СТАНУТ НЕДОСТУПНЫ* для ответа пользователю.\n\n"
        "Это действие **необратимо**.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def perform_reset(query: CallbackQuery):
    """Выполняет сброс статистики и нумерации."""
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        # Удаляем все записи из reports
        cursor.execute("DELETE FROM reports")

        # Сбрасываем автоинкрементный счетчик
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='reports'")

        conn.commit()
        await query.edit_message_text("✅ Статистика и нумерация обращений сброшены.")
    except Exception as e:
        logger.error(f"Ошибка при сбросе статистики: {e}")
        await query.edit_message_text("❌ Произошла ошибка при сбросе.")
    finally:
        conn.close()


# Справка для гостей
async def show_guest_help(update: Update):
    help_text = (
        "📋 Справка по использованию бота:\n\n"
        "🤖 Этот бот помогает выявлять фейковую информацию\n\n"
        "💡 Как отправить сообщение на проверку:\n"
        "Просто опишите ситуацию в чате с ботом, приложите текст, фото, видео или документ, добавьте ссылку на публикацию сомнительного материала\n\n"
        "📝 Ваше сообщение автоматически будет отправлено администраторам\n"
        "⏱️ Администраторы проверят его и дадут ответ\n"
        "📢 Вы получите уведомление с результатом проверки\n\n"
        "🔍 Проверяемая информация:\n"
        "• подозрительные новости;\n"
        "• документы (приказы, распоряжения), оказавшиеся в открытом доступе;\n"
        "• фотографии и видео;\n"
        "• любая другая информация, вызывающая сомнения.\n\n"
        "_Проект «Антифейк» реализуется Центром управления региона Орловской области и Департаментом информационно-аналитической работы Орловской области_"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')


# Справка для администраторов
async def show_admin_help(update: Update):
    is_sup_admin = is_super_admin(update.effective_user.id)

    help_text = "📋 Справка для администратора:\n\n"
    if is_sup_admin:
        help_text += "👑 У вас есть права *Супер Администратора*.\n"
    else:
        help_text += "👥 У вас есть права администратора.\n"

    help_text += (
        "\n⌨️ Кнопки меню:\n"
        "• 📊 Статистика - показать статистику обращений.\n"
        "• 🗑 Сброс - Очистить базу обращений и сбросить статистику.\n"
    )

    if is_sup_admin:
        help_text += "• ➕/➖ Админы - Добавить/удалить администраторов и просмотреть список.\n"

    help_text += (
        "• 📋 Справка - текущее сообщение.\n\n"
        "🔍 Для обработки сообщений:\n"
        "1. Ожидайте сообщения от пользователей\n"
        "2. Используйте кнопки для оценки:\n"
        "  ✅ Фейк – подтвердить, что информация является фейковой (пользователь получит ответ)\n"
        "  ❌ Не фейк – подтвердить, что информация не является фейковой (пользователь получит ответ)\n"
        "   ⏸️ Без ответа – оставить без подтверждения (пользователь получит сообщение о более длительной проверке)\n"
        "   🚫 Игнор – отметить как обработанное (пользователь не получит никакой ответ)\n\n"
        "📢 Пользователь получит автоматический ответ (кроме случая Игнор)"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')


# Обработка ошибок
async def error_handler(_update: object, context: CallbackContext):
    logger.error(f"Exception while handling an update: {context.error}")


# Основная функция
def main():
    # Инициализация базы данных
    init_db()

    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))

    # Обработчики сообщений
    # Обработчики текстовых сообщений (включая команды супер админа)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Отдельные обработчики для разных типов медиа
    application.add_handler(MessageHandler(filters.PHOTO, handle_media))
    application.add_handler(MessageHandler(filters.VIDEO, handle_media))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_media))

    # Обработчики callback-кнопок
    application.add_handler(CallbackQueryHandler(handle_admin_button))

    # Обработчик ошибок
    application.add_error_handler(error_handler)

    # Запуск бота
    print("Бот запущен...")
    application.run_polling()


if __name__ == '__main__':
    main()