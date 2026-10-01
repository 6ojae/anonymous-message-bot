import asyncio
import os
import re
import sqlite3
import secrets
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.filters import Command, CommandObject
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from dotenv import load_dotenv


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

BOT_USERNAME = os.getenv("BOT_USERNAME", "your_bot_username")
MAJID_API_TOKEN = os.getenv("MAJID_API_TOKEN", "")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")

DB_PATH = os.getenv("DB_PATH", "hidden_sender.db")


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not configured.")


bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()


# =========================================================
# MEMORY
# =========================================================

states = {}

# آخرین صفحه‌ای که ربات برای هر کاربر نمایش داده
screen_messages = {}

# پیام‌هایی که ربات برای هر کاربر ارسال کرده
bot_messages = {}


# =========================================================
# DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn, table, column):
    rows = conn.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    return any(row["name"] == column for row in rows)


def add_column_if_missing(conn, table, column, definition):
    if not column_exists(conn, table, column):
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():

    conn = db()

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            alias TEXT,
            link_token TEXT UNIQUE,
            anonymous_link TEXT,
            link_active INTEGER DEFAULT 1,
            banned_until TEXT,
            created_at TEXT
        )
    """)

    add_column_if_missing(conn, "users", "username", "TEXT")
    add_column_if_missing(conn, "users", "first_name", "TEXT")
    add_column_if_missing(conn, "users", "last_name", "TEXT")
    add_column_if_missing(conn, "users", "alias", "TEXT")
    add_column_if_missing(conn, "users", "link_token", "TEXT")
    add_column_if_missing(conn, "users", "anonymous_link", "TEXT")
    add_column_if_missing(conn, "users", "link_active", "INTEGER DEFAULT 1")
    add_column_if_missing(conn, "users", "banned_until", "TEXT")
    add_column_if_missing(conn, "users", "created_at", "TEXT")


    # -----------------------------------------------------
    # NUMBER CHECKS
    # -----------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS number_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            phone TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # -----------------------------------------------------
    # MESSAGES
    # -----------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            message_type TEXT,
            message_text TEXT,
            telegram_message_id INTEGER,
            is_read INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0,
            parent_id INTEGER,
            media_file_id TEXT,
            created_at TEXT
        )
    """)

    add_column_if_missing(
        conn, "messages", "sender_id", "INTEGER"
    )
    add_column_if_missing(
        conn, "messages", "receiver_id", "INTEGER"
    )
    add_column_if_missing(
        conn, "messages", "message_type", "TEXT"
    )
    add_column_if_missing(
        conn, "messages", "message_text", "TEXT"
    )
    add_column_if_missing(
        conn, "messages", "telegram_message_id", "INTEGER"
    )
    add_column_if_missing(
        conn, "messages", "is_read", "INTEGER DEFAULT 0"
    )
    add_column_if_missing(
        conn, "messages", "is_deleted", "INTEGER DEFAULT 0"
    )
    add_column_if_missing(
        conn, "messages", "parent_id", "INTEGER"
    )
    add_column_if_missing(
        conn, "messages", "media_file_id", "TEXT"
    )
    add_column_if_missing(
        conn, "messages", "created_at", "TEXT"
    )


    # -----------------------------------------------------
    # BLOCKED USERS
    # -----------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS blocked_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            blocked_id INTEGER,
            created_at TEXT,
            UNIQUE(owner_id, blocked_id)
        )
    """)


    # -----------------------------------------------------
    # REPORTS
    # -----------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            reporter_id INTEGER,
            reported_user_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)


    # -----------------------------------------------------
    # LINK EVENTS
    # -----------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS link_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            visitor_id INTEGER,
            event_type TEXT,
            created_at TEXT
        )
    """)


    # -----------------------------------------------------
    # PENDING
    # -----------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            telegram_message_id INTEGER,
            message_type TEXT,
            message_text TEXT,
            parent_id INTEGER,
            media_file_id TEXT,
            created_at TEXT
        )
    """)

    add_column_if_missing(
        conn, "pending_messages",
        "media_file_id", "TEXT"
    )


    # -----------------------------------------------------
    # SETTINGS
    # -----------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            notifications_enabled INTEGER DEFAULT 1
        )
    """)

    conn.commit()
    conn.close()

    print("Database initialized successfully.")


# =========================================================
# USERS
# =========================================================

def create_user(message: Message):

    uid = message.from_user.id

    conn = db()

    row = conn.execute(
        "SELECT telegram_id FROM users WHERE telegram_id=?",
        (uid,)
    ).fetchone()

    if not row:

        token = secrets.token_urlsafe(10)

        conn.execute("""
            INSERT INTO users (
                telegram_id,
                username,
                first_name,
                last_name,
                alias,
                link_token,
                anonymous_link,
                link_active,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            uid,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
            None,
            token,
            f"https://t.me/{BOT_USERNAME}?start={token}",
            datetime.now().isoformat()
        ))

    else:

        conn.execute("""
            UPDATE users
            SET username=?,
                first_name=?,
                last_name=?
            WHERE telegram_id=?
        """, (
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
            uid
        ))

    conn.commit()
    conn.close()


def ensure_user(message):
    create_user(message)


def get_user(uid):

    conn = db()

    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (uid,)
    ).fetchone()

    conn.close()

    return row


def get_user_by_token(token):

    conn = db()

    row = conn.execute(
        "SELECT * FROM users WHERE link_token=?",
        (token,)
    ).fetchone()

    conn.close()

    return row


def display_name(uid):

    user = get_user(uid)

    if not user:
        return "کاربر"

    if user["alias"]:
        return user["alias"]

    if user["first_name"]:
        return user["first_name"]

    if user["username"]:
        return "@" + user["username"]

    return "کاربر"


def set_alias(uid, alias):

    conn = db()

    conn.execute(
        "UPDATE users SET alias=? WHERE telegram_id=?",
        (alias, uid)
    )

    conn.commit()
    conn.close()


def set_link_active(uid, active):

    conn = db()

    conn.execute(
        "UPDATE users SET link_active=? WHERE telegram_id=?",
        (1 if active else 0, uid)
    )

    conn.commit()
    conn.close()


def reset_link(uid):

    token = secrets.token_urlsafe(10)

    conn = db()

    conn.execute("""
        UPDATE users
        SET link_token=?,
            anonymous_link=?
        WHERE telegram_id=?
    """, (
        token,
        f"https://t.me/{BOT_USERNAME}?start={token}",
        uid
    ))

    conn.commit()
    conn.close()

    return f"https://t.me/{BOT_USERNAME}?start={token}"


# =========================================================
# BAN
# =========================================================

def ban_user(uid, minutes=None):

    conn = db()

    if minutes is None or minutes == 0:

        conn.execute(
            "UPDATE users SET banned_until=? WHERE telegram_id=?",
            ("PERMANENT", uid)
        )

    else:

        until = datetime.now() + timedelta(
            minutes=minutes
        )

        conn.execute(
            "UPDATE users SET banned_until=? WHERE telegram_id=?",
            (until.isoformat(), uid)
        )

    conn.commit()
    conn.close()


def is_banned(uid):

    user = get_user(uid)

    if not user:
        return False

    value = user["banned_until"]

    if not value:
        return False

    if value == "PERMANENT":
        return True

    try:
        until = datetime.fromisoformat(value)

        if datetime.now() < until:
            return True

        conn = db()

        conn.execute(
            "UPDATE users SET banned_until=NULL WHERE telegram_id=?",
            (uid,)
        )

        conn.commit()
        conn.close()

        return False

    except Exception:
        return False


# =========================================================
# BLOCK
# =========================================================

def block_user(owner_id, blocked_id):

    conn = db()

    conn.execute("""
        INSERT OR IGNORE INTO blocked_users
        (owner_id, blocked_id, created_at)
        VALUES (?, ?, ?)
    """, (
        owner_id,
        blocked_id,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


def unblock_user(owner_id, blocked_id):

    conn = db()

    conn.execute("""
        DELETE FROM blocked_users
        WHERE owner_id=? AND blocked_id=?
    """, (
        owner_id,
        blocked_id
    ))

    conn.commit()
    conn.close()


def is_blocked(owner_id, blocked_id):

    conn = db()

    row = conn.execute("""
        SELECT 1 FROM blocked_users
        WHERE owner_id=? AND blocked_id=?
    """, (
        owner_id,
        blocked_id
    )).fetchone()

    conn.close()

    return bool(row)


def get_blocked_users(owner_id):

    conn = db()

    rows = conn.execute("""
        SELECT blocked_id
        FROM blocked_users
        WHERE owner_id=?
        ORDER BY id DESC
    """, (owner_id,)).fetchall()

    conn.close()

    return rows


# =========================================================
# MESSAGES
# =========================================================

def save_message(
    sender_id,
    receiver_id,
    message_type,
    message_text,
    telegram_message_id,
    parent_id=None,
    media_file_id=None
):

    conn = db()

    cur = conn.execute("""
        INSERT INTO messages (
            sender_id,
            receiver_id,
            message_type,
            message_text,
            telegram_message_id,
            is_read,
            is_deleted,
            parent_id,
            media_file_id,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
    """, (
        sender_id,
        receiver_id,
        message_type,
        message_text,
        telegram_message_id,
        parent_id,
        media_file_id,
        datetime.now().isoformat()
    ))

    message_id = cur.lastrowid

    conn.commit()
    conn.close()

    return message_id


def get_message(message_id):

    conn = db()

    row = conn.execute(
        "SELECT * FROM messages WHERE id=?",
        (message_id,)
    ).fetchone()

    conn.close()

    return row


def mark_read(message_id):

    conn = db()

    conn.execute(
        "UPDATE messages SET is_read=1 WHERE id=?",
        (message_id,)
    )

    conn.commit()
    conn.close()


def count_messages(uid):

    conn = db()

    count = conn.execute("""
        SELECT COUNT(*)
        FROM messages
        WHERE receiver_id=?
          AND is_deleted=0
    """, (uid,)).fetchone()[0]

    conn.close()

    return count


# =========================================================
# REPORTS
# =========================================================

def create_report(
    message_id,
    reporter_id,
    reported_user_id
):

    conn = db()

    cur = conn.execute("""
        INSERT INTO reports (
            message_id,
            reporter_id,
            reported_user_id,
            status,
            created_at
        )
        VALUES (?, ?, ?, 'pending', ?)
    """, (
        message_id,
        reporter_id,
        reported_user_id,
        datetime.now().isoformat()
    ))

    report_id = cur.lastrowid

    conn.commit()
    conn.close()

    return report_id


def get_pending_reports():

    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM reports
        WHERE status='pending'
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return rows


def close_report(report_id):

    conn = db()

    conn.execute(
        "UPDATE reports SET status='closed' WHERE id=?",
        (report_id,)
    )

    conn.commit()
    conn.close()


# =========================================================
# LINK STATS
# =========================================================

def add_link_event(owner_id, visitor_id):

    conn = db()

    conn.execute("""
        INSERT INTO link_events (
            user_id,
            event_type,
            created_at
        )
        VALUES (?, 'click', ?)
    """, (
        owner_id,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


def get_link_stats(uid):

    conn = db()

    total = conn.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE user_id=?
    """, (uid,)).fetchone()[0]

    today = conn.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE user_id=?
        AND date(created_at)=date('now','localtime')
    """, (uid,)).fetchone()[0]

    week = conn.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE user_id=?
        AND datetime(created_at)
        >= datetime('now','-7 day','localtime')
    """, (uid,)).fetchone()[0]

    month = conn.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE user_id=?
        AND datetime(created_at)
        >= datetime('now','-30 day','localtime')
    """, (uid,)).fetchone()[0]

    conn.close()

    return total, today, week, month


# =========================================================
# PENDING
# =========================================================

def save_pending(
    sender_id,
    receiver_id,
    telegram_message_id,
    message_type,
    message_text,
    parent_id,
    media_file_id
):

    conn = db()

    cur = conn.execute("""
        INSERT INTO pending_messages (
            sender_id,
            receiver_id,
            telegram_message_id,
            message_type,
            message_text,
            parent_id,
            media_file_id,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sender_id,
        receiver_id,
        telegram_message_id,
        message_type,
        message_text,
        parent_id,
        media_file_id,
        datetime.now().isoformat()
    ))

    pending_id = cur.lastrowid

    conn.commit()
    conn.close()

    return pending_id


def get_pending(pending_id):

    conn = db()

    row = conn.execute(
        "SELECT * FROM pending_messages WHERE id=?",
        (pending_id,)
    ).fetchone()

    conn.close()

    return row


def delete_pending(pending_id):

    conn = db()

    conn.execute(
        "DELETE FROM pending_messages WHERE id=?",
        (pending_id,)
    )

    conn.commit()
    conn.close()


# =========================================================
# MESSAGE HELPERS
# =========================================================

def get_message_type(message):

    if message.text:
        return "text"

    if message.voice:
        return "voice"

    if message.photo:
        return "photo"

    if message.video:
        return "video"

    if message.audio:
        return "audio"

    if message.document:
        return "document"

    if message.animation:
        return "animation"

    if message.sticker:
        return "sticker"

    return "other"


def get_message_text(message):

    if message.text:
        return message.text

    if message.caption:
        return message.caption

    return None


def get_media_file_id(message):

    if message.voice:
        return message.voice.file_id

    if message.photo:
        return message.photo[-1].file_id

    if message.video:
        return message.video.file_id

    if message.audio:
        return message.audio.file_id

    if message.document:
        return message.document.file_id

    if message.animation:
        return message.animation.file_id

    if message.sticker:
        return message.sticker.file_id

    return None


def valid_text(text):

    text = text.strip()

    if not text:
        return False

    # حذف ایموجی و کاراکترهای رایج ایموجی
    cleaned = re.sub(
        r'[\U0001F000-\U0001FAFF'
        r'\U00002700-\U000027BF'
        r'\U0001F1E6-\U0001F1FF'
        r'\u2600-\u26FF'
        r'\uFE0F]+',
        '',
        text
    )

    return bool(cleaned.strip())


# =========================================================
# DELETE / SCREEN
# =========================================================

async def safe_delete(message):

    try:
        await message.delete()
    except Exception:
        pass


def ensure_chat_messages_table():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                created_at INTEGER DEFAULT (strftime('%s','now')),
                UNIQUE(chat_id, message_id)
            )
        """)
        con.commit()


def remember_user_message(message):
    if not message:
        return

    try:
        ensure_chat_messages_table()

        chat_id = message.chat.id
        message_id = message.message_id

        with db() as con:
            con.execute("""
                INSERT OR IGNORE INTO chat_messages
                (chat_id, message_id, direction)
                VALUES (?, ?, 'user')
            """, (chat_id, message_id))
            con.commit()
    except Exception as e:
        print(f"[CHAT TRACK USER ERROR] {e}")


async def remember_bot_message(user_id, message):
    if not message:
        return

    try:
        ensure_chat_messages_table()

        message_id = message.message_id

        with db() as con:
            con.execute("""
                INSERT OR IGNORE INTO chat_messages
                (chat_id, message_id, direction)
                VALUES (?, ?, 'bot')
            """, (user_id, message_id))
            con.commit()
    except Exception as e:
        print(f"[CHAT TRACK BOT ERROR] {e}")

    bot_messages.setdefault(user_id, [])
    bot_messages[user_id].append(message_id)

    # فقط 100 پیام آخر در حافظه
    bot_messages[user_id] = bot_messages[user_id][-100:]

    screen_messages[user_id] = message_id

async def delete_screen(user_id):

    message_id = screen_messages.pop(user_id, None)

    if message_id:

        try:
            await bot.delete_message(
                chat_id=user_id,
                message_id=message_id
            )
        except Exception:
            pass


async def clean_chat(user_id):
    """
    پاکسازی واقعی چت:
    علاوه بر پیام‌هایی که قبلاً ثبت شده‌اند،
    message_id های اخیر چت را هم مستقیماً امتحان می‌کند.
    """

    ids = set()

    # پیام‌های ثبت‌شده در حافظه
    for mid in bot_messages.get(user_id, []):
        try:
            ids.add(int(mid))
        except Exception:
            pass

    # پیام‌های ثبت‌شده در دیتابیس
    try:
        ensure_chat_messages_table()

        with db() as con:
            rows = con.execute("""
                SELECT message_id
                FROM chat_messages
                WHERE chat_id=?
            """, (user_id,)).fetchall()

            for row in rows:
                try:
                    ids.add(int(row["message_id"]))
                except Exception:
                    pass
    except Exception:
        pass

    # پیام‌های ثبت‌شده در جدول messages
    try:
        with db() as con:
            rows = con.execute("""
                SELECT telegram_message_id
                FROM messages
                WHERE sender_id=? OR receiver_id=?
            """, (user_id, user_id)).fetchall()

            for row in rows:
                try:
                    if row["telegram_message_id"]:
                        ids.add(int(row["telegram_message_id"]))
                except Exception:
                    pass
    except Exception:
        pass

    # --------------------------------------------------
    # پیدا کردن پیام‌های اخیر بدون نیاز به ذخیره قبلی
    # --------------------------------------------------
    #
    # در چت خصوصی Telegram message_id ها ترتیبی هستند.
    # از آخرین پیام شناخته‌شده به عقب می‌رویم.
    #
    max_id = 0

    for mid in ids:
        if mid > max_id:
            max_id = mid

    screen_id = screen_messages.get(user_id)
    if screen_id:
        try:
            max_id = max(max_id, int(screen_id))
        except Exception:
            pass

    # اگر هیچ شناسه‌ای نداریم، از محدوده اخیر شروع کن
    if max_id < 1:
        max_id = 300

    # حداکثر 500 پیام اخیر را بررسی می‌کنیم
    first_id = max(1, max_id - 500)

    for message_id in range(first_id, max_id + 1):
        ids.add(message_id)

    deleted = 0

    # حذف پیام‌ها
    for message_id in sorted(ids, reverse=True):
        try:
            await bot.delete_message(
                chat_id=user_id,
                message_id=message_id
            )
            deleted += 1
        except Exception:
            pass

    # پاک کردن اطلاعات موقت
    bot_messages[user_id] = []
    screen_messages.pop(user_id, None)

    # پاک کردن ثبت دائمی پیام‌های این چت
    try:
        with db() as con:
            con.execute(
                "DELETE FROM chat_messages WHERE chat_id=?",
                (user_id,)
            )
            con.commit()
    except Exception:
        pass

    print(f"[CLEAN] user={user_id} deleted={deleted}")

    return deleted

def main_keyboard(user_id):

    rows = [
        [
            KeyboardButton(text="📊 آمار لینک"),
            KeyboardButton(text="🔗 لینک ناشناس من")
        ],
        [
            KeyboardButton(text="💡 راهنما"),
            KeyboardButton(text="⚙️ تنظیمات")
        ],
        [
            KeyboardButton(text="📥 پیام‌های من")
        ],
        [
            KeyboardButton(text="🧹 تمیز کردن صفحه")
        ]
    ]

    if user_id == ADMIN_ID:
        rows.append([
            KeyboardButton(text="👑 پنل مدیریت")
        ])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True
    )


# =========================================================
# HOME
# =========================================================

WELCOME_TEXT = """سلام 👋
به ربات «پیام ناشناس» خوش‌اومدی.

اینجا میتونی از خدمات ما بصورت کاملا رایگان استفاده کنی و با استفاده از لینک ناشناس من، لینک رو برای دوستات بفرستی تا برات پیام ناشناس بفرستند.

{BOT_USERNAME} | ربات پیام ناشناس"""


async def send_home(user_id, delete_old=True, extra_text=None):

    if delete_old:
        await delete_screen(user_id)

    if extra_text and extra_text.startswith(("✅", "❌")):
        text = extra_text
    else:
        text = WELCOME_TEXT

        if extra_text:
            text += "\n\n" + extra_text

    message = await bot.send_message(
        chat_id=user_id,
        text=text,
        reply_markup=(
            delete_notice_keyboard()
            if extra_text and extra_text.startswith("✅")
            else main_keyboard(user_id)
        )
    )

    await remember_bot_message(user_id, message)

    return message


# =========================================================
# NOTIFICATION KEYBOARD
# =========================================================

def notification_keyboard(message_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👁 نمایش پیام",
                    callback_data=f"show:{message_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 حذف اعلان",
                    callback_data="delete_notice"
                )
            ]
        ]
    )

def delete_notice_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 حذف اعلان",
                    callback_data="delete_notice"
                )
            ]
        ]
    )

# =========================================================
# START
# =========================================================

@dp.message(Command("start"))
async def start(message: Message, command: CommandObject):

    ensure_user(message)

    uid = message.from_user.id

    # پیام /start کاربر حذف شود
    await safe_delete(message)

    if is_banned(uid):

        sent = await bot.send_message(
            uid,
            "🚫 حساب شما توسط مدیریت مسدود شده است."
        )

        await remember_bot_message(uid, sent)

        return

    token = command.args

    # -----------------------------------------
    # ورود از لینک ناشناس
    # -----------------------------------------

    if token:

        owner = get_user_by_token(token)

        if owner:

            owner_id = owner["telegram_id"]

            if owner_id != uid:

                add_link_event(
                    owner_id,
                    uid
                )

                if not owner["link_active"]:

                    await delete_screen(uid)

                    sent = await bot.send_message(
                        uid,
                        """🚫 <b>این لینک موقتاً غیرفعال شده است.</b>

صاحب لینک فعلاً امکان دریافت پیام ناشناس را غیرفعال کرده است.""",
                        reply_markup=InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text="🔙 بازگشت",
                                        callback_data="home"
                                    )
                                ]
                            ]
                        )
                    )

                    await remember_bot_message(uid, sent)

                    return

                states[uid] = {
                    "mode": "anonymous",
                    "target_id": owner_id
                }

                await delete_screen(uid)

                sent = await bot.send_message(
                    uid,
                    f"""💌 <b>ارسال پیام ناشناس</b>

الان میتونی هر پیام، عکس یا ویسی که داری رو به صورت ناشناس برای <b>{display_name(owner_id)}</b> بفرستی.

پیامت بدون نمایش هویتت برای این کاربر ارسال میشه.""",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="🔙 بازگشت",
                                    callback_data="home"
                                )
                            ]
                        ]
                    )
                )

                await remember_bot_message(uid, sent)

                return

    await send_home(uid)


# =========================================================
# LINK
# =========================================================

@dp.message(F.text == "🔗 لینک ناشناس من")
async def my_link(message: Message):

    ensure_user(message)

    uid = message.from_user.id

    await safe_delete(message)

    user = get_user(uid)

    active = bool(user["link_active"])

    status = "🟢 فعال" if active else "🔴 غیرفعال"

    text = f"""🔗 <b>لینک ناشناس شما</b>

<code>{user["anonymous_link"]}</code>

وضعیت لینک: {status}

هرکس از طریق این لینک وارد شود می‌تواند برای شما پیام ناشناس ارسال کند."""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 ساخت لینک جدید",
                    callback_data="reset_link"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🟢 غیرفعال کردن لینک"
                    if active
                    else "🔴 فعال کردن لینک",
                    callback_data="toggle_link"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data="home"
                )
            ]
        ]
    )

    await delete_screen(uid)

    sent = await bot.send_message(
        uid,
        text,
        reply_markup=keyboard
    )

    await remember_bot_message(uid, sent)


# =========================================================
# RESET LINK
# =========================================================

@dp.callback_query(F.data == "reset_link")
async def reset_link_callback(callback: CallbackQuery):

    uid = callback.from_user.id

    link = reset_link(uid)

    await callback.message.edit_text(
        f"""✅ <b>لینک جدید ساخته شد.</b>

<code>{link}</code>

لینک قبلی دیگر قابل استفاده نیست.""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 لینک من",
                        callback_data="my_link"
                    )
                ]
            ]
        )
    )

    await callback.answer("لینک جدید ساخته شد")


@dp.callback_query(F.data == "my_link")
async def my_link_callback(callback: CallbackQuery):

    uid = callback.from_user.id

    user = get_user(uid)

    active = bool(user["link_active"])

    await callback.message.edit_text(
        f"""🔗 <b>لینک ناشناس شما</b>

<code>{user["anonymous_link"]}</code>

وضعیت: {"🟢 فعال" if active else "🔴 غیرفعال"}""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔄 ساخت لینک جدید",
                        callback_data="reset_link"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🟢 غیرفعال کردن لینک"
                        if active
                        else "🔴 فعال کردن لینک",
                        callback_data="toggle_link"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data="home"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# TOGGLE LINK
# =========================================================

@dp.callback_query(F.data == "toggle_link")
async def toggle_link(callback: CallbackQuery):

    uid = callback.from_user.id

    user = get_user(uid)

    new_status = not bool(user["link_active"])

    set_link_active(
        uid,
        new_status
    )

    await callback.answer(
        "لینک فعال شد." if new_status else "لینک غیرفعال شد."
    )

    await my_link_callback(callback)


# =========================================================
# STATS
# =========================================================

@dp.message(F.text == "📊 آمار لینک")
async def my_stats(message: Message):

    ensure_user(message)

    uid = message.from_user.id

    await safe_delete(message)

    total, today, week, month = get_link_stats(uid)

    text = f"""📊 <b>آمار لینک ناشناس</b>

👆 کل ورود از لینک: <b>{total}</b>
📅 امروز: <b>{today}</b>
🗓 ۷ روز اخیر: <b>{week}</b>
📆 ۳۰ روز اخیر: <b>{month}</b>

💌 تعداد پیام‌های دریافتی: <b>{count_messages(uid)}</b>"""

    await delete_screen(uid)

    sent = await bot.send_message(
        uid,
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data="home"
                    )
                ]
            ]
        )
    )

    await remember_bot_message(uid, sent)


# =========================================================
# HELP
# =========================================================

@dp.message(F.text == "💡 راهنما")
async def help_menu(message: Message):

    ensure_user(message)

    uid = message.from_user.id

    await safe_delete(message)

    await delete_screen(uid)

    sent = await bot.send_message(
        uid,
        """💡 <b>راهنمای پیام ناشناس</b>

🔗 از بخش «لینک ناشناس من» لینک شخصی خودت رو بگیر.

📤 لینک رو برای دوستات بفرست.

💌 هرکس وارد لینک بشه میتونه متن، عکس یا ویس ناشناس برات ارسال کنه.

👁 برای دیدن پیام‌های دریافتی روی «نمایش پیام» بزن.

💬 میتونی به پیام‌ها پاسخ بدی.

🚫 در صورت نیاز میتونی فرستنده رو مسدود یا گزارش کنی.""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data="home"
                    )
                ]
            ]
        )
    )

    await remember_bot_message(uid, sent)


# =========================================================
# SETTINGS
# =========================================================

@dp.message(F.text == "⚙️ تنظیمات")
async def settings_menu(message: Message):

    ensure_user(message)

    uid = message.from_user.id

    await safe_delete(message)
    await delete_screen(uid)

    user = get_user(uid)

    active = bool(user["link_active"])

    sent = await bot.send_message(
        uid,
        f"""⚙️ <b>تنظیمات</b>

👤 اسم مستعار:
<b>{user["alias"] or "تنظیم نشده"}</b>

🔗 وضعیت لینک:
{"🟢 فعال" if active else "🔴 غیرفعال"}""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ تغییر اسم مستعار",
                        callback_data="change_alias"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🟢 غیرفعال کردن لینک"
                        if active
                        else "🔴 فعال کردن لینک",
                        callback_data="toggle_link_settings"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🚫 کاربران مسدودشده",
                        callback_data="blocked_list"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data="home"
                    )
                ]
            ]
        )
    )

    await remember_bot_message(uid, sent)


@dp.callback_query(F.data == "toggle_link_settings")
async def toggle_link_settings(callback: CallbackQuery):

    uid = callback.from_user.id

    user = get_user(uid)

    new_status = not bool(user["link_active"])

    set_link_active(
        uid,
        new_status
    )

    await callback.answer(
        "وضعیت لینک تغییر کرد."
    )

    user = get_user(uid)

    await callback.message.edit_text(
        f"""⚙️ <b>تنظیمات</b>

👤 اسم مستعار:
<b>{user["alias"] or "تنظیم نشده"}</b>

🔗 وضعیت لینک:
{"🟢 فعال" if user["link_active"] else "🔴 غیرفعال"}""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ تغییر اسم مستعار",
                        callback_data="change_alias"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🟢 غیرفعال کردن لینک"
                        if user["link_active"]
                        else "🔴 فعال کردن لینک",
                        callback_data="toggle_link_settings"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🚫 کاربران مسدودشده",
                        callback_data="blocked_list"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data="home"
                    )
                ]
            ]
        )
    )


# =========================================================
# ALIAS
# =========================================================

@dp.callback_query(F.data == "change_alias")
async def change_alias(callback: CallbackQuery):

    uid = callback.from_user.id

    states[uid] = {
        "mode": "alias"
    }

    await callback.message.edit_text(
        """✏️ <b>اسم مستعار جدید</b>

اسم جدیدت رو ارسال کن:

حداکثر ۴۰ کاراکتر.""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data="settings_back"
                    )
                ]
            ]
        )
    )

    await callback.answer()


@dp.callback_query(F.data == "settings_back")
async def settings_back(callback: CallbackQuery):

    uid = callback.from_user.id

    states.pop(uid, None)

    await safe_delete(callback.message)

    user = get_user(uid)

    active = bool(user["link_active"])

    sent = await bot.send_message(
        uid,
        f"""⚙️ <b>تنظیمات</b>

👤 اسم مستعار:
<b>{user["alias"] or "تنظیم نشده"}</b>

🔗 وضعیت لینک:
{"🟢 فعال" if active else "🔴 غیرفعال"}""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ تغییر اسم مستعار",
                        callback_data="change_alias"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🟢 غیرفعال کردن لینک"
                        if active
                        else "🔴 فعال کردن لینک",
                        callback_data="toggle_link_settings"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🚫 کاربران مسدودشده",
                        callback_data="blocked_list"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data="home"
                    )
                ]
            ]
        )
    )

    await remember_bot_message(
        uid,
        sent
    )

    await callback.answer()


# =========================================================
# BLOCKED LIST
# =========================================================

@dp.callback_query(F.data == "blocked_list")
async def blocked_list(callback: CallbackQuery):

    uid = callback.from_user.id

    rows = get_blocked_users(uid)

    if not rows:

        text = "🚫 <b>لیست مسدودشده‌ها خالی است.</b>"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 تنظیمات",
                        callback_data="settings_back"
                    )
                ]
            ]
        )

    else:

        text = "🚫 <b>کاربران مسدودشده</b>\n\n"

        buttons = []

        for row in rows:

            blocked_id = row["blocked_id"]

            text += (
                f"👤 {display_name(blocked_id)}\n"
                f"🆔 <code>{blocked_id}</code>\n\n"
            )

            buttons.append([
                InlineKeyboardButton(
                    text=f"🔓 رفع مسدودیت {display_name(blocked_id)}",
                    callback_data=f"unblock:{blocked_id}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                text="🔙 تنظیمات",
                callback_data="settings_back"
            )
        ])

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=buttons
        )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("unblock:"))
async def unblock_callback(callback: CallbackQuery):

    uid = callback.from_user.id

    blocked_id = int(
        callback.data.split(":")[1]
    )

    unblock_user(uid, blocked_id)

    try:
        await bot.send_message(
            blocked_id,
            "🔓 <b>رفع مسدودیت شد.</b>\n\nشما توسط این کاربر از حالت مسدود خارج شدید."
        )
    except Exception:
        pass

    await callback.answer("رفع مسدودیت شد.")

    await blocked_list(callback)


# =========================================================
# INBOX
# =========================================================

async def build_inbox(uid, page=1):

    per_page = 5

    conn = db()

    total = conn.execute("""
        SELECT COUNT(*)
        FROM messages
        WHERE receiver_id=?
        AND is_deleted=0
    """, (uid,)).fetchone()[0]

    unread = conn.execute("""
        SELECT COUNT(*)
        FROM messages
        WHERE receiver_id=?
        AND is_deleted=0
        AND is_read=0
    """, (uid,)).fetchone()[0]

    total_pages = max(
        1,
        (total + per_page - 1) // per_page
    )

    page = max(
        1,
        min(page, total_pages)
    )

    offset = (page - 1) * per_page

    rows = conn.execute("""
        SELECT *
        FROM messages
        WHERE receiver_id=?
        AND is_deleted=0
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """, (uid, per_page, offset)).fetchall()

    conn.close()

    text = f"""📥 <b>پیام‌های من</b>

💌 پیام‌های دریافت‌شده: <b>{total}</b>
👁 خوانده‌نشده: <b>{unread}</b>

📄 صفحه <b>{page}</b> از <b>{total_pages}</b>
برای مشاهده پیام روی آن بزن."""

    buttons = []

    for row in rows:

        icon = "🔵" if not row["is_read"] else "⚪"

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{icon} پیام #{row['id']}",
                    callback_data=f"show:{row['id']}"
                )
            ]
        )

    navigation = []

    if page > 1:

        navigation.append(
            InlineKeyboardButton(
                text="⬅️ قبلی",
                callback_data=f"inbox_page:{page - 1}"
            )
        )

    navigation.append(
        InlineKeyboardButton(
            text=f"📄 {page}/{total_pages}",
            callback_data="inbox_noop"
        )
    )

    if page < total_pages:

        navigation.append(
            InlineKeyboardButton(
                text="بعدی ➡️",
                callback_data=f"inbox_page:{page + 1}"
            )
        )

    buttons.append(navigation)

    buttons.append(
        [
            InlineKeyboardButton(
                text="🔙 بازگشت",
                callback_data="home"
            )
        ]
    )

    return text, InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


@dp.message(F.text == "📥 پیام‌های من")
async def inbox(message: Message):

    ensure_user(message)

    uid = message.from_user.id

    await safe_delete(message)

    await delete_screen(uid)

    text, keyboard = await build_inbox(
        uid,
        1
    )

    sent = await bot.send_message(
        uid,
        text,
        reply_markup=keyboard
    )

    await remember_bot_message(
        uid,
        sent
    )


# =========================================================
# SHOW MESSAGE
# =========================================================

async def send_stored_message(user_id, row):

    mtype = row["message_type"]
    text = row["message_text"] or ""
    media_id = row["media_file_id"]

    try:

        if mtype == "text":

            return await bot.send_message(
                user_id,
                f"💌 <b>پیام:</b>\n\n{text}"
            )

        if mtype == "photo" and media_id:

            return await bot.send_photo(
                user_id,
                photo=media_id,
                caption=text or None
            )

        if mtype == "voice" and media_id:

            return await bot.send_voice(
                user_id,
                voice=media_id
            )

        if mtype == "video" and media_id:

            return await bot.send_video(
                user_id,
                video=media_id,
                caption=text or None
            )

        if mtype == "audio" and media_id:

            return await bot.send_audio(
                user_id,
                audio=media_id,
                caption=text or None
            )

        if mtype == "document" and media_id:

            return await bot.send_document(
                user_id,
                document=media_id,
                caption=text or None
            )

        if mtype == "animation" and media_id:

            return await bot.send_animation(
                user_id,
                animation=media_id,
                caption=text or None
            )

        if mtype == "sticker" and media_id:

            return await bot.send_sticker(
                user_id,
                sticker=media_id
            )

    except Exception as e:

        print(
            f"[MEDIA SEND ERROR] "
            f"user={user_id} "
            f"message={row['id']} "
            f"error={e}"
        )

        raise

    return None


@dp.callback_query(F.data == "delete_notice")
async def delete_notice(callback: CallbackQuery):
    try:
        await callback.answer("🗑 اعلان حذف شد.")
    except Exception:
        pass

    try:
        await callback.message.delete()
    except Exception:
        pass

    return


@dp.callback_query(F.data.startswith("show:"))
async def show_message(callback: CallbackQuery):

    uid = callback.from_user.id

    message_id = int(
        callback.data.split(":")[1]
    )

    row = get_message(message_id)

    if not row or row["receiver_id"] != uid:

        await callback.answer(
            "پیام پیدا نشد.",
            show_alert=True
        )

        return

    # فقط اولین بار مشاهده به فرستنده اطلاع داده شود
    if not row["is_read"]:

        mark_read(message_id)

        try:

            notice = await bot.send_message(
                row["sender_id"],
                "👁 <b>پیامت توسط گیرنده مشاهده شد.</b>",
                reply_markup=delete_notice_keyboard()
            )

            await remember_bot_message(
                row["sender_id"],
                notice
            )

        except Exception:
            pass

    await safe_delete(callback.message)

    try:

        sent = await send_stored_message(
            uid,
            row
        )

        if sent:

            # ذخیره شناسه پیام نمایش‌داده‌شده برای حذف هنگام پاسخ
            states.setdefault(uid, {})
            states[uid]["viewed_message_id"] = sent.message_id

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💬 جواب دادن",
                            callback_data=f"reply:{message_id}"
                        ),
                        InlineKeyboardButton(
                            text="🚫 مسدود کردن",
                            callback_data=f"block:{message_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⚠️ گزارش",
                            callback_data=f"report:{message_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🔙 پیام‌ها",
                            callback_data="inbox"
                        )
                    ]
                ]
            )

            sent2 = await bot.send_message(
                uid,
                f"""👇 <b>عملیات پیام</b>

🕐 <b>تاریخ و ساعت:</b>
<code>{row["created_at"]}</code>""",
                reply_markup=keyboard
            )

            await remember_bot_message(
                uid,
                sent2
            )

        await callback.answer()

    except Exception:

        await callback.answer(
            "❌ نمایش پیام با مشکل مواجه شد.",
            show_alert=True
        )


# =========================================================
# INBOX CALLBACK
# =========================================================

@dp.callback_query(F.data == "inbox")
async def inbox_callback(callback: CallbackQuery):

    uid = callback.from_user.id

    text, keyboard = await build_inbox(
        uid,
        1
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("inbox_page:"))
async def inbox_page(callback: CallbackQuery):

    uid = callback.from_user.id

    page = int(
        callback.data.split(":")[1]
    )

    text, keyboard = await build_inbox(
        uid,
        page
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(F.data == "inbox_noop")
async def inbox_noop(callback: CallbackQuery):

    await callback.answer()


# =========================================================
# BLOCK FROM MESSAGE
# =========================================================

@dp.callback_query(F.data.startswith("block:"))
async def block_callback(callback: CallbackQuery):

    uid = callback.from_user.id

    message_id = int(
        callback.data.split(":")[1]
    )

    row = get_message(message_id)

    if not row or row["receiver_id"] != uid:

        await callback.answer(
            "پیام پیدا نشد.",
            show_alert=True
        )

        return

    sender_id = row["sender_id"]

    block_user(
        uid,
        sender_id
    )

    await callback.message.edit_text(
        "🚫 <b>این کاربر مسدود شد.</b>\n\n"
        "دیگر نمی‌تواند از طریق لینک ناشناس برای شما پیام ارسال کند.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 پیام‌ها",
                        callback_data="inbox"
                    )
                ]
            ]
        )
    )

    await callback.answer("کاربر مسدود شد.")


# =========================================================
# REPORT
# =========================================================

@dp.callback_query(F.data.startswith("report:"))
async def report_callback(callback: CallbackQuery):

    uid = callback.from_user.id

    message_id = int(
        callback.data.split(":")[1]
    )

    row = get_message(message_id)

    if not row or row["receiver_id"] != uid:

        await callback.answer(
            "پیام پیدا نشد.",
            show_alert=True
        )

        return

    report_id = create_report(
        message_id,
        uid,
        row["sender_id"]
    )

    try:

        report_text = f"""⚠️ <b>گزارش جدید</b>

📄 گزارش: <code>#{report_id}</code>

👤 گزارش‌دهنده:
<code>{uid}</code>

👤 فرستنده پیام:
<code>{row["sender_id"]}</code>

👤 دریافت‌کننده:
<code>{row["receiver_id"]}</code>

📌 نوع:
<b>{row["message_type"]}</b>

📝 متن:
{row["message_text"] or "رسانه‌ای"}

🕐 زمان:
{row["created_at"]}"""

        await bot.send_message(
            ADMIN_ID,
            report_text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🚫 مسدود دائمی",
                            callback_data=f"aban:{row['sender_id']}:0:{report_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⏱ 24 ساعت",
                            callback_data=f"aban:{row['sender_id']}:1440:{report_id}"
                        ),
                        InlineKeyboardButton(
                            text="⏱ 7 روز",
                            callback_data=f"aban:{row['sender_id']}:10080:{report_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="✅ بستن گزارش",
                            callback_data=f"close_report:{report_id}"
                        )
                    ]
                ]
            )
        )

        if row["message_type"] != "text":

            await send_stored_message(
                ADMIN_ID,
                row
            )

    except Exception as e:

        print(
            f"[REPORT ERROR] {e}"
        )

    await callback.message.edit_text(
        "✅ <b>گزارش شما ثبت شد.</b>\n\n"
        "گزارش توسط مدیریت بررسی خواهد شد.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 پیام‌ها",
                        callback_data="inbox"
                    )
                ]
            ]
        )
    )

    await callback.answer("گزارش ثبت شد.")


# =========================================================
# REPLY
# =========================================================

@dp.callback_query(F.data.startswith("reply:"))
async def reply_start(callback: CallbackQuery):

    uid = callback.from_user.id

    message_id = int(
        callback.data.split(":")[1]
    )

    row = get_message(message_id)

    if not row or row["receiver_id"] != uid:

        await callback.answer(
            "پیام پیدا نشد.",
            show_alert=True
        )

        return

    # اگر پیام اصلی در صفحه نمایش داده شده، قبل از ورود به پاسخ حذفش کن
    viewed_message_id = None

    if uid in states:
        viewed_message_id = states[uid].get("viewed_message_id")

    if viewed_message_id:

        try:
            await bot.delete_message(
                chat_id=uid,
                message_id=viewed_message_id
            )
        except Exception:
            pass

    states[uid] = {
        "mode": "reply",
        "target_id": row["sender_id"],
        "parent_id": message_id
    }

    await callback.message.edit_text(
        """💬 <b>پاسخ به پیام</b>

پاسخت رو ارسال کن.

متن، عکس یا ویس قابل ارسال است.""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ بیخیال",
                        callback_data="home"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# CLEAN PAGE
# =========================================================

@dp.message(F.text == "🧹 تمیز کردن صفحه")
async def clean_page(message: Message):

    ensure_user(message)

    uid = message.from_user.id

    await safe_delete(message)

    await delete_screen(uid)

    sent = await bot.send_message(
        uid,
        """🧹 <b>تمیز کردن صفحه</b>

می‌خوای این صفحه رو کامل پاک کنیم تا چت شلوغ نشه؟

با تأیید، پیام‌های مربوط به صفحه‌های ربات که قابل حذف باشند پاک می‌شوند.""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ تأیید و پاک‌سازی",
                        callback_data="clean_confirm"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="↩️ برگشت",
                        callback_data="home"
                    )
                ]
            ]
        )
    )

    await remember_bot_message(uid, sent)


@dp.callback_query(F.data == "clean_confirm")
async def clean_confirm(callback: CallbackQuery):

    uid = callback.from_user.id

    states.pop(uid, None)

    await callback.answer(
        "در حال پاک‌سازی..."
    )

    # پیام تأیید فعلی را هم پاک می‌کنیم
    await safe_delete(callback.message)

    await clean_chat(uid)

    await send_home(
        uid,
        delete_old=False
    )


# =========================================================
# MEMBERSHIP
# =========================================================

def membership_keyboard(pending_id):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 عضویت در کانال",
                    url="https://t.me/{BOT_USERNAME}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 بررسی عضویت",
                    callback_data=f"check_member:{pending_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data="home"
                )
            ]
        ]
    )


async def check_membership(user_id):

    try:

        member = await bot.get_chat_member(
            CHANNEL_USERNAME,
            user_id
        )

        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR
        )

    except Exception as e:

        print(
            f"[MEMBERSHIP ERROR] user={user_id} error={e}"
        )

        return False


@dp.callback_query(F.data.startswith("check_member:"))
async def check_member(callback: CallbackQuery):

    uid = callback.from_user.id

    pending_id = int(
        callback.data.split(":")[1]
    )

    pending = get_pending(pending_id)

    if not pending:

        await callback.answer(
            "این پیام منقضی شده است.",
            show_alert=True
        )

        return

    member = await check_membership(uid)

    if not member:

        await callback.answer(
            "هنوز عضو کانال نیستی.",
            show_alert=True
        )

        return

    target_id = pending["receiver_id"]

    if is_blocked(target_id, uid):

        delete_pending(pending_id)

        await safe_delete(callback.message)

        await send_home(
            uid,
            delete_old=True,
            extra_text="🚫 این کاربر شما را مسدود کرده است."
        )

        return

    message_id = save_message(
        sender_id=pending["sender_id"],
        receiver_id=pending["receiver_id"],
        message_type=pending["message_type"],
        message_text=pending["message_text"],
        telegram_message_id=pending["telegram_message_id"],
        parent_id=pending["parent_id"],
        media_file_id=pending["media_file_id"]
    )

    delete_pending(pending_id)

    try:

        # برای گیرنده هیچ اسم یا هویت فرستنده نمایش داده نمی‌شود
        if pending["parent_id"]:

            notify_text = (
                "💬 <b>یک پاسخ جدید برای پیامت داری!</b>"
            )

        else:

            notify_text = (
                "💌 <b>یک پیام ناشناس داری!</b>"
            )

        await bot.send_message(
            chat_id=target_id,
            text=notify_text,
            reply_markup=notification_keyboard(message_id)
        )

        print(
            f"[DELIVERY OK] "
            f"message={message_id} "
            f"sender={pending['sender_id']} "
            f"receiver={target_id}"
        )

    except Exception as e:

        print(
            f"[DELIVERY ERROR] "
            f"message={message_id} "
            f"sender={pending['sender_id']} "
            f"receiver={target_id} "
            f"error={e}"
        )

        await safe_delete(callback.message)

        await send_home(
            uid,
            delete_old=True,
            extra_text="❌ ارسال پیام انجام نشد. لطفاً دوباره تلاش کن."
        )

        return

    await safe_delete(callback.message)

    # برای فرستنده اسم گیرنده نمایش داده نمی‌شود
    if pending["parent_id"]:

        success_text = (
            "✅ <b>پاسخ شما با موفقیت ارسال شد.</b>"
        )

    else:

        success_text = (
            "✅ <b>پیامت با موفقیت ارسال شد.</b>"
        )

    await send_home(
        uid,
        delete_old=True,
        extra_text=success_text
    )

    await callback.answer(
        "✅ پیام ارسال شد."
    )


# =========================================================
# HOME CALLBACK
# =========================================================

@dp.callback_query(F.data == "home")
async def home(callback: CallbackQuery):

    uid = callback.from_user.id

    states.pop(uid, None)

    await safe_delete(callback.message)

    await send_home(
        uid,
        delete_old=True
    )

    await callback.answer()


# =========================================================
# ALL MESSAGES
# =========================================================

@dp.message()
async def all_messages(message: Message):
    remember_user_message(message)

    ensure_user(message)

    uid = message.from_user.id

    # Main menu fallback
    if message.text == "📊 آمار لینک":

        await my_stats(message)
        return

    if message.text == "👑 پنل مدیریت":

        if uid != ADMIN_ID:
            await safe_delete(message)
            return

        await admin_panel(message)
        return

    if is_banned(uid):

        await safe_delete(message)

        await delete_screen(uid)

        sent = await bot.send_message(
            uid,
            "🚫 <b>حساب شما توسط مدیریت مسدود شده است.</b>"
        )

        await remember_bot_message(uid, sent)

        return

    state = states.get(uid)

    # =====================================================
    # ALIAS
    # =====================================================

    if state and state["mode"] == "alias":

        if not message.text:

            await safe_delete(message)

            await delete_screen(uid)

            sent = await bot.send_message(
                uid,
                "❌ اسم مستعار باید به‌صورت متن ارسال شود.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔙 بازگشت",
                                callback_data="settings_back"
                            )
                        ]
                    ]
                )
            )

            await remember_bot_message(uid, sent)

            return

        alias = message.text.strip()

        if len(alias) < 2 or len(alias) > 40:

            await safe_delete(message)

            await delete_screen(uid)

            sent = await bot.send_message(
                uid,
                "❌ اسم مستعار باید بین ۲ تا ۴۰ کاراکتر باشد."
            )

            await remember_bot_message(uid, sent)

            return

        set_alias(
            uid,
            alias
        )

        states.pop(uid, None)

        await safe_delete(message)

        await send_home(
            uid,
            delete_old=True,
            extra_text=f"✅ اسم مستعار شما به <b>{alias}</b> تغییر کرد."
        )

        return


    # =====================================================
    # BROADCAST
    # =====================================================

    if uid == ADMIN_ID and state and state["mode"] == "broadcast":

        states.pop(uid, None)

        conn = db()

        users = conn.execute(
            "SELECT telegram_id FROM users"
        ).fetchall()

        conn.close()

        sent_count = 0
        failed_count = 0

        for user in users:

            target_id = user["telegram_id"]

            try:

                await bot.copy_message(
                    chat_id=target_id,
                    from_chat_id=uid,
                    message_id=message.message_id
                )

                sent_count += 1

            except Exception:

                failed_count += 1

            await asyncio.sleep(0.05)

        await safe_delete(message)

        await send_home(
            uid,
            delete_old=True
        )

        result = await bot.send_message(
            uid,
            f"""📢 <b>نتیجه ارسال همگانی</b>

✅ موفق: <b>{sent_count}</b>
❌ ناموفق: <b>{failed_count}</b>"""
        )

        await remember_bot_message(uid, result)

        return


    # =====================================================
    # ADMIN BAN
    # =====================================================

    if uid == ADMIN_ID and state and state["mode"] == "admin_unban":

        raw_id = (message.text or "").strip()

        if not raw_id.isdigit():
            await safe_delete(message)

            sent = await bot.send_message(
                uid,
                """❌ <b>آیدی نامعتبر است.</b>

لطفاً فقط آیدی عددی کاربر را ارسال کنید.

مثال:
<code>123456789</code>""",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔙 پنل مدیریت",
                                callback_data="admin_home"
                            )
                        ]
                    ]
                )
            )

            await remember_bot_message(uid, sent)
            return

        target_id = int(raw_id)

        user = get_user(target_id)

        if not user:
            await safe_delete(message)

            sent = await bot.send_message(
                uid,
                f"""❌ <b>کاربر پیدا نشد.</b>

🆔 <code>{target_id}</code>""",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔙 پنل مدیریت",
                                callback_data="admin_home"
                            )
                        ]
                    ]
                )
            )

            await remember_bot_message(uid, sent)
            states.pop(uid, None)
            return

        # حذف مسدودیت مدیریتی
        with db() as con:
            con.execute(
                "UPDATE users SET banned_until=NULL WHERE telegram_id=?",
                (target_id,)
            )
            con.commit()

        states.pop(uid, None)

        await safe_delete(message)
        await delete_screen(uid)

        sent = await bot.send_message(
            uid,
            f"""✅ <b>رفع مسدودیت انجام شد.</b>

👤 {display_name(target_id)}
🆔 <code>{target_id}</code>""",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔙 پنل مدیریت",
                            callback_data="admin_home"
                        )
                    ]
                ]
            )
        )

        await remember_bot_message(uid, sent)

        # اطلاع به کاربر
        try:
            notice = await bot.send_message(
                target_id,
                """✅ <b>مسدودیت حساب شما برداشته شد.</b>

اکنون می‌توانید دوباره از ربات استفاده کنید."""
            )
            await remember_bot_message(
                target_id,
                notice
            )
        except Exception:
            pass

        return


    if uid == ADMIN_ID and state and state["mode"] == "ban_user":

        if not message.text or not message.text.isdigit():

            await safe_delete(message)

            sent = await bot.send_message(
                uid,
                "❌ فقط آیدی عددی کاربر را ارسال کن."
            )

            await remember_bot_message(uid, sent)

            return

        target_id = int(message.text)

        states.pop(uid, None)

        await safe_delete(message)

        sent = await bot.send_message(
            uid,
            f"""🔨 <b>مسدود کردن کاربر</b>

آیدی:
<code>{target_id}</code>

مدت مسدودی را انتخاب کن:""",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🚫 دائمی",
                            callback_data=f"ban_direct:{target_id}:0"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⏱ 24 ساعت",
                            callback_data=f"ban_direct:{target_id}:1440"
                        ),
                        InlineKeyboardButton(
                            text="⏱ 7 روز",
                            callback_data=f"ban_direct:{target_id}:10080"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="❌ لغو",
                            callback_data="admin_home"
                        )
                    ]
                ]
            )
        )

        await remember_bot_message(uid, sent)

        return


    # =====================================================
    # ANONYMOUS / REPLY
    # =====================================================

    if state and state["mode"] in (
        "anonymous",
        "reply"
    ):

        if message.text == "🔙 بازگشت":

            states.pop(uid, None)

            await safe_delete(message)

            await send_home(
                uid,
                delete_old=True
            )

            return

        target_id = state["target_id"]
        parent_id = state.get("parent_id")

        if is_blocked(target_id, uid):

            states.pop(uid, None)

            await safe_delete(message)

            await send_home(
                uid,
                delete_old=True,
                extra_text="🚫 این کاربر شما را مسدود کرده است."
            )

            return

        # -----------------------------------------
        # فقط ایموجی قبول نشود
        # -----------------------------------------

        if message.text and not valid_text(message.text):

            await safe_delete(message)

            await delete_screen(uid)

            sent = await bot.send_message(
                uid,
                "❌ پیام نمی‌تواند فقط شامل ایموجی باشد.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔙 بازگشت",
                                callback_data="home"
                            )
                        ]
                    ]
                )
            )

            await remember_bot_message(uid, sent)

            return

        mtype = get_message_type(message)
        mtext = get_message_text(message)
        media_id = get_media_file_id(message)

        if mtype == "other":

            await safe_delete(message)

            await delete_screen(uid)

            sent = await bot.send_message(
                uid,
                "❌ این نوع پیام پشتیبانی نمی‌شود."
            )

            await remember_bot_message(uid, sent)

            return

        pending_id = save_pending(
            sender_id=uid,
            receiver_id=target_id,
            telegram_message_id=message.message_id,
            message_type=mtype,
            message_text=mtext,
            parent_id=parent_id,
            media_file_id=media_id
        )

        states.pop(uid, None)

        member = await check_membership(uid)

        if not member:

            # پیام اصلی کاربر همین‌جا حذف شود
            await safe_delete(message)

            await delete_screen(uid)

            sent = await bot.send_message(
                uid,
                """🔐 <b>برای ارسال پیام باید عضو کانال ما باشی.</b>

ابتدا عضو کانال شو و سپس روی «بررسی عضویت» بزن.""",
                reply_markup=membership_keyboard(
                    pending_id
                )
            )

            await remember_bot_message(uid, sent)

            return


        # =================================================
        # SEND DIRECT
        # =================================================

        message_id = save_message(
            uid,
            target_id,
            mtype,
            mtext,
            message.message_id,
            parent_id,
            media_id
        )

        delete_pending(
            pending_id
        )

        try:

            # مهم:
            # هیچ اسم یا اطلاعاتی درباره فرستنده نمایش داده نمی‌شود

            if parent_id:

                notify_text = (
                    "💬 <b>یک پاسخ جدید برای پیامت داری!</b>"
                )

            else:

                notify_text = (
                    "💌 <b>یک پیام ناشناس داری!</b>"
                )

            await bot.send_message(
                chat_id=target_id,
                text=notify_text,
                reply_markup=notification_keyboard(
                    message_id
                )
            )

            print(
                f"[DELIVERY OK] "
                f"message={message_id} "
                f"sender={uid} "
                f"receiver={target_id}"
            )

        except Exception as e:

            print(
                f"[DELIVERY ERROR] "
                f"message={message_id} "
                f"sender={uid} "
                f"receiver={target_id} "
                f"error={e}"
            )

            await safe_delete(message)

            await send_home(
                uid,
                delete_old=True,
                extra_text="❌ پیام ارسال نشد. لطفاً دوباره تلاش کن."
            )

            return


        # پیام اصلی فرستنده حذف شود
        await safe_delete(message)


        # هیچ نامی از گیرنده نشان نده
        if parent_id:

            success_text = (
                "✅ <b>پاسخ شما با موفقیت ارسال شد.</b>"
            )

        else:

            success_text = (
                "✅ <b>پیامت با موفقیت ارسال شد.</b>"
            )

        await send_home(
            uid,
            delete_old=True,
            extra_text=success_text
        )

        return


    # =====================================================
    # COMMANDS
    # =====================================================

    if message.text and message.text.startswith("/"):

        await safe_delete(message)

        await send_home(
            uid,
            delete_old=True
        )

        return


    # =====================================================
    # UNKNOWN MESSAGE
    # =====================================================

    await safe_delete(message)

    await send_home(
        uid,
        delete_old=True
    )


# =========================================================
# ADMIN HOME
# =========================================================

def admin_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚠️ گزارش‌های دریافتی",
                    callback_data="admin_reports"
                ),
                InlineKeyboardButton(
                    text="📊 آمار کلیک",
                    callback_data="admin_clicks"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 آمار کاربران",
                    callback_data="admin_users"
                ),
                InlineKeyboardButton(
                    text="📢 ارسال همگانی",
                    callback_data="broadcast"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔨 مسدود کردن کاربر",
                    callback_data="admin_ban"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔓 رفع مسدودیت کاربر",
                    callback_data="admin_unban"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data="home"
                )
            ]
        ]
    )


@dp.message(F.text == "👑 پنل مدیریت")
async def admin_panel(message: Message):

    if message.from_user.id != ADMIN_ID:
        await safe_delete(message)
        return

    await safe_delete(message)
    await delete_screen(ADMIN_ID)

    sent = await bot.send_message(
        ADMIN_ID,
        "👑 <b>پنل مدیریت</b>",
        reply_markup=admin_keyboard()
    )

    await remember_bot_message(
        ADMIN_ID,
        sent
    )


@dp.callback_query(F.data == "admin_home")
async def admin_home(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    await callback.message.edit_text(
        "👑 <b>پنل مدیریت</b>",
        reply_markup=admin_keyboard()
    )

    await callback.answer()


# =========================================================
# ADMIN USERS
# =========================================================

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    conn = db()

    users = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    messages = conn.execute(
        "SELECT COUNT(*) FROM messages"
    ).fetchone()[0]

    reports = conn.execute("""
        SELECT COUNT(*)
        FROM reports
        WHERE status='pending'
    """).fetchone()[0]

    conn.close()

    await callback.message.edit_text(
        f"""👥 <b>آمار کاربران</b>

👤 کاربران: <b>{users}</b>
💌 پیام‌ها: <b>{messages}</b>
⚠️ گزارش‌های باز: <b>{reports}</b>""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 پنل مدیریت",
                        callback_data="admin_home"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# ADMIN CLICKS
# =========================================================

@dp.callback_query(F.data == "admin_clicks")
async def admin_clicks(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    conn = db()

    total = conn.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE event_type='click'
    """).fetchone()[0]

    today = conn.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE event_type='click'
        AND date(created_at)=date('now','localtime')
    """).fetchone()[0]

    week = conn.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE event_type='click'
        AND datetime(created_at)
        >= datetime('now','-7 day','localtime')
    """).fetchone()[0]

    month = conn.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE event_type='click'
        AND datetime(created_at)
        >= datetime('now','-30 day','localtime')
    """).fetchone()[0]

    conn.close()

    await callback.message.edit_text(
        f"""📊 <b>آمار کلیک لینک‌ها</b>

👆 کل ورود از لینک: <b>{total}</b>
📅 امروز: <b>{today}</b>
🗓 ۷ روز اخیر: <b>{week}</b>
📆 ۳۰ روز اخیر: <b>{month}</b>

ℹ️ هر ورود از لینک اختصاصی به‌عنوان یک کلیک ثبت می‌شود.

{BOT_USERNAME}""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 پنل مدیریت",
                        callback_data="admin_home"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# ADMIN REPORTS
# =========================================================

@dp.callback_query(F.data == "admin_reports")
async def admin_reports(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    reports = get_pending_reports()

    if not reports:

        await callback.message.edit_text(
            "✅ هیچ گزارش بررسی‌نشده‌ای وجود ندارد.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔙 پنل مدیریت",
                            callback_data="admin_home"
                        )
                    ]
                ]
            )
        )

        await callback.answer()
        return

    keyboard = []

    for report in reports:

        keyboard.append([
            InlineKeyboardButton(
                text=f"📄 گزارش #{report['id']}",
                callback_data=f"view_report:{report['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="🔙 پنل مدیریت",
            callback_data="admin_home"
        )
    ])

    await callback.message.edit_text(
        f"⚠️ <b>{len(reports)} گزارش بررسی‌نشده</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("view_report:"))
async def view_report(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    report_id = int(
        callback.data.split(":")[1]
    )

    conn = db()

    report = conn.execute(
        "SELECT * FROM reports WHERE id=?",
        (report_id,)
    ).fetchone()

    conn.close()

    if not report:

        await callback.answer(
            "گزارش پیدا نشد.",
            show_alert=True
        )

        return

    row = get_message(
        report["message_id"]
    )

    if not row:

        await callback.message.edit_text(
            "❌ پیام مربوط به گزارش پیدا نشد."
        )

        return

    text = f"""⚠️ <b>گزارش #{report_id}</b>

👤 گزارش‌دهنده:
<code>{report["reporter_id"]}</code>

👤 فرستنده:
<code>{report["reported_user_id"]}</code>

👤 دریافت‌کننده:
<code>{row["receiver_id"]}</code>

📌 نوع پیام:
<b>{row["message_type"]}</b>

📝 متن:
{row["message_text"] or "رسانه‌ای"}

🕐 زمان:
{row["created_at"]}"""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚫 مسدود دائمی",
                    callback_data=f"aban:{row['sender_id']}:0:{report_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏱ 24 ساعت",
                    callback_data=f"aban:{row['sender_id']}:1440:{report_id}"
                ),
                InlineKeyboardButton(
                    text="⏱ 7 روز",
                    callback_data=f"aban:{row['sender_id']}:10080:{report_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ بستن گزارش",
                    callback_data=f"close_report:{report_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 گزارش‌ها",
                    callback_data="admin_reports"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    if row["message_type"] != "text":

        try:

            await send_stored_message(
                ADMIN_ID,
                row
            )

        except Exception:
            pass

    await callback.answer()


# =========================================================
# ADMIN BAN
# =========================================================

@dp.callback_query(F.data.startswith("aban:"))
async def admin_ban(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    _, user_id, minutes, report_id = callback.data.split(":")

    user_id = int(user_id)
    minutes = int(minutes)
    report_id = int(report_id)

    if minutes == 0:

        ban_user(user_id)
        duration = "دائمی"

    else:

        ban_user(
            user_id,
            minutes
        )

        duration = f"{minutes // 60} ساعت"

    close_report(report_id)

    try:

        await bot.send_message(
            user_id,
            f"""🚫 <b>حساب شما توسط مدیریت مسدود شد.</b>

مدت مسدودی: <b>{duration}</b>"""
        )

    except Exception:
        pass

    await callback.message.edit_text(
        f"""🚫 کاربر <code>{user_id}</code> مسدود شد.

مدت: <b>{duration}</b>

گزارش #{report_id} بسته شد.""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 پنل مدیریت",
                        callback_data="admin_home"
                    )
                ]
            ]
        )
    )

    await callback.answer(
        "کاربر مسدود شد"
    )


# =========================================================
# CLOSE REPORT
# =========================================================

@dp.callback_query(F.data.startswith("close_report:"))
async def close_report_callback(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    report_id = int(
        callback.data.split(":")[1]
    )

    close_report(
        report_id
    )

    await callback.message.edit_text(
        f"✅ گزارش #{report_id} بسته شد.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 گزارش‌ها",
                        callback_data="admin_reports"
                    )
                ]
            ]
        )
    )

    await callback.answer(
        "گزارش بسته شد"
    )


# =========================================================
# BROADCAST
# =========================================================

@dp.callback_query(F.data == "broadcast")
async def broadcast_start(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    states[ADMIN_ID] = {
        "mode": "broadcast"
    }

    await callback.message.edit_text(
        """📢 <b>ارسال همگانی</b>

پیام بعدی را ارسال کن.

متن، عکس، ویس، ویدئو یا فایل قابل ارسال است.""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ لغو",
                        callback_data="admin_home"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# ADMIN BAN MANUAL
# =========================================================

@dp.callback_query(F.data == "admin_unban")
async def admin_unban_start(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    states[ADMIN_ID] = {
        "mode": "admin_unban"
    }

    await callback.message.edit_text(
        """🔓 <b>رفع مسدودیت کاربر</b>

آیدی عددی کاربر را ارسال کنید.

مثال:
<code>123456789</code>""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 پنل مدیریت",
                        callback_data="admin_home"
                    )
                ]
            ]
        )
    )

    await callback.answer()


@dp.callback_query(F.data == "admin_ban")
async def admin_ban_start(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    states[ADMIN_ID] = {
        "mode": "ban_user"
    }

    await callback.message.edit_text(
        """🔨 <b>مسدود کردن کاربر</b>

آیدی عددی کاربر را ارسال کن:""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ لغو",
                        callback_data="admin_home"
                    )
                ]
            ]
        )
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("ban_direct:"))
async def ban_direct(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    _, user_id, minutes = callback.data.split(":")

    user_id = int(user_id)
    minutes = int(minutes)

    if minutes == 0:

        ban_user(user_id)
        duration = "دائمی"

    else:

        ban_user(
            user_id,
            minutes
        )

        duration = f"{minutes // 60} ساعت"

    states.pop(
        ADMIN_ID,
        None
    )

    try:

        await bot.send_message(
            user_id,
            f"""🚫 حساب شما توسط مدیریت مسدود شد.

مدت: <b>{duration}</b>"""
        )

    except Exception:
        pass

    await callback.message.edit_text(
        f"""✅ کاربر <code>{user_id}</code> مسدود شد.

مدت: <b>{duration}</b>""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 پنل مدیریت",
                        callback_data="admin_home"
                    )
                ]
            ]
        )
    )

    await callback.answer()


# =========================================================
# MAIN
# =========================================================

async def main():

    init_db()

    print("======================================")
    print("Hidden Sender Telegram Bot")
    print("Bot:", BOT_USERNAME)
    print("Database:", DB_PATH)
    print("======================================")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
