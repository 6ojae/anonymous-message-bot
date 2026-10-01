import sqlite3
import secrets
from datetime import datetime


DB_NAME = "anonymous_bot.db"


def now():
    return datetime.now().isoformat(timespec="seconds")


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            alias TEXT,
            link_token TEXT UNIQUE,
            link_active INTEGER DEFAULT 1,
            banned_until TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message_type TEXT NOT NULL,
            message_text TEXT,
            telegram_message_id INTEGER,
            is_read INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0,
            parent_id INTEGER,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blocked_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            blocked_user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, blocked_user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            reporter_id INTEGER NOT NULL,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS link_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            token TEXT NOT NULL,
            visitor_id INTEGER,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_messages (
            sender_id INTEGER PRIMARY KEY,
            target_id INTEGER NOT NULL,
            telegram_message_id INTEGER NOT NULL,
            message_type TEXT NOT NULL,
            message_text TEXT,
            parent_id INTEGER,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            notifications_enabled INTEGER DEFAULT 1
        )
    """)

    conn.commit()

    # -----------------------------------------------------
    # MIGRATION FOR OLD DATABASE
    # -----------------------------------------------------

    existing = []

    cursor.execute("PRAGMA table_info(users)")
    columns = [row["name"] for row in cursor.fetchall()]

    if "alias" not in columns:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN alias TEXT"
        )

    if "link_token" not in columns:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN link_token TEXT"
        )

        cursor.execute(
            "SELECT telegram_id FROM users"
        )

        for row in cursor.fetchall():

            token = secrets.token_urlsafe(10)

            cursor.execute(
                """
                UPDATE users
                SET link_token = ?
                WHERE telegram_id = ?
                """,
                (token, row["telegram_id"])
            )

    if "link_active" not in columns:
        cursor.execute(
            """
            ALTER TABLE users
            ADD COLUMN link_active INTEGER DEFAULT 1
            """
        )

    if "banned_until" not in columns:
        cursor.execute(
            """
            ALTER TABLE users
            ADD COLUMN banned_until TEXT
            """
        )

    conn.commit()
    conn.close()


# =========================================================
# USERS
# =========================================================

def create_user(
    telegram_id,
    username=None,
    first_name=None,
    last_name=None
):

    conn = get_connection()
    cursor = conn.cursor()

    token = secrets.token_urlsafe(10)

    cursor.execute("""
        INSERT OR IGNORE INTO users
        (
            telegram_id,
            username,
            first_name,
            last_name,
            link_token,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        telegram_id,
        username,
        first_name,
        last_name,
        token,
        now()
    ))

    cursor.execute("""
        UPDATE users
        SET username = ?,
            first_name = ?,
            last_name = ?
        WHERE telegram_id = ?
    """, (
        username,
        first_name,
        last_name,
        telegram_id
    ))

    conn.commit()
    conn.close()


def get_user(telegram_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM users
        WHERE telegram_id = ?
    """, (telegram_id,))

    result = cursor.fetchone()

    conn.close()

    return result


def get_user_by_token(token):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM users
        WHERE link_token = ?
    """, (token,))

    result = cursor.fetchone()

    conn.close()

    return result


def get_display_name(user):

    if not user:
        return "کاربر"

    return (
        user["alias"]
        or user["first_name"]
        or user["username"]
        or "کاربر"
    )


def set_alias(user_id, alias):

    conn = get_connection()

    conn.execute("""
        UPDATE users
        SET alias = ?
        WHERE telegram_id = ?
    """, (
        alias,
        user_id
    ))

    conn.commit()
    conn.close()


def set_link_active(user_id, active):

    conn = get_connection()

    conn.execute("""
        UPDATE users
        SET link_active = ?
        WHERE telegram_id = ?
    """, (
        1 if active else 0,
        user_id
    ))

    conn.commit()
    conn.close()


def reset_link(user_id):

    token = secrets.token_urlsafe(10)

    conn = get_connection()

    conn.execute("""
        UPDATE users
        SET link_token = ?
        WHERE telegram_id = ?
    """, (
        token,
        user_id
    ))

    conn.commit()
    conn.close()

    return token


def get_all_users():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM users
        ORDER BY created_at DESC
    """)

    result = cursor.fetchall()

    conn.close()

    return result


# =========================================================
# BAN
# =========================================================

def ban_user(user_id, until=None):

    conn = get_connection()

    conn.execute("""
        UPDATE users
        SET banned_until = ?
        WHERE telegram_id = ?
    """, (
        until,
        user_id
    ))

    conn.commit()
    conn.close()


def unban_user(user_id):

    conn = get_connection()

    conn.execute("""
        UPDATE users
        SET banned_until = NULL
        WHERE telegram_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()


def is_banned(user_id):

    user = get_user(user_id)

    if not user:
        return False

    until = user["banned_until"]

    if not until:
        return False

    try:

        expire = datetime.fromisoformat(until)

        if datetime.now() >= expire:

            unban_user(user_id)

            return False

        return True

    except Exception:

        return True


# =========================================================
# MESSAGES
# =========================================================

def save_message(
    sender_id,
    receiver_id,
    message_type,
    message_text=None,
    telegram_message_id=None,
    parent_id=None
):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO messages
        (
            sender_id,
            receiver_id,
            message_type,
            message_text,
            telegram_message_id,
            parent_id,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        sender_id,
        receiver_id,
        message_type,
        message_text,
        telegram_message_id,
        parent_id,
        now()
    ))

    message_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return message_id


def get_message(message_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM messages
        WHERE id = ?
    """, (message_id,))

    result = cursor.fetchone()

    conn.close()

    return result


def get_messages(user_id, limit=50):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM messages
        WHERE receiver_id = ?
        AND is_deleted = 0
        ORDER BY id DESC
        LIMIT ?
    """, (
        user_id,
        limit
    ))

    result = cursor.fetchall()

    conn.close()

    return result


def mark_read(message_id):

    conn = get_connection()

    conn.execute("""
        UPDATE messages
        SET is_read = 1
        WHERE id = ?
    """, (message_id,))

    conn.commit()
    conn.close()


def delete_message(message_id):

    conn = get_connection()

    conn.execute("""
        UPDATE messages
        SET is_deleted = 1
        WHERE id = ?
    """, (message_id,))

    conn.commit()
    conn.close()


def count_messages(user_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM messages
        WHERE receiver_id = ?
        AND is_deleted = 0
    """, (user_id,))

    result = cursor.fetchone()[0]

    conn.close()

    return result


# =========================================================
# BLOCK
# =========================================================

def block_user(user_id, blocked_user_id):

    conn = get_connection()

    conn.execute("""
        INSERT OR IGNORE INTO blocked_users
        (
            user_id,
            blocked_user_id,
            created_at
        )
        VALUES (?, ?, ?)
    """, (
        user_id,
        blocked_user_id,
        now()
    ))

    conn.commit()
    conn.close()


def unblock_user(user_id, blocked_user_id):

    conn = get_connection()

    conn.execute("""
        DELETE FROM blocked_users
        WHERE user_id = ?
        AND blocked_user_id = ?
    """, (
        user_id,
        blocked_user_id
    ))

    conn.commit()
    conn.close()


def is_blocked(user_id, blocked_user_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT id
        FROM blocked_users
        WHERE user_id = ?
        AND blocked_user_id = ?
    """, (
        user_id,
        blocked_user_id
    ))

    result = cursor.fetchone()

    conn.close()

    return result is not None


def get_blocked_users(user_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT u.*
        FROM blocked_users b
        JOIN users u
        ON u.telegram_id = b.blocked_user_id
        WHERE b.user_id = ?
        ORDER BY b.id DESC
    """, (user_id,))

    result = cursor.fetchall()

    conn.close()

    return result


# =========================================================
# REPORTS
# =========================================================

def create_report(
    message_id,
    reporter_id,
    reason=""
):

    conn = get_connection()

    conn.execute("""
        INSERT INTO reports
        (
            message_id,
            reporter_id,
            reason,
            created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        message_id,
        reporter_id,
        reason,
        now()
    ))

    conn.commit()
    conn.close()


def get_pending_reports(limit=50):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            r.*,
            m.sender_id,
            m.receiver_id,
            m.message_type,
            m.message_text,
            m.telegram_message_id
        FROM reports r
        JOIN messages m
        ON m.id = r.message_id
        WHERE r.status = 'pending'
        ORDER BY r.id DESC
        LIMIT ?
    """, (limit,))

    result = cursor.fetchall()

    conn.close()

    return result


def set_report_status(report_id, status):

    conn = get_connection()

    conn.execute("""
        UPDATE reports
        SET status = ?
        WHERE id = ?
    """, (
        status,
        report_id
    ))

    conn.commit()
    conn.close()


# =========================================================
# LINK EVENTS
# =========================================================

def add_link_event(
    owner_id,
    token,
    visitor_id,
    event_type
):

    conn = get_connection()

    conn.execute("""
        INSERT INTO link_events
        (
            owner_id,
            token,
            visitor_id,
            event_type,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        owner_id,
        token,
        visitor_id,
        event_type,
        now()
    ))

    conn.commit()
    conn.close()


def get_link_stats(user_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE owner_id = ?
        AND event_type = 'click'
    """, (user_id,))

    total_clicks = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE owner_id = ?
        AND event_type = 'start'
    """, (user_id,))

    total_starts = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE owner_id = ?
        AND event_type = 'click'
        AND date(created_at) = date('now','localtime')
    """, (user_id,))

    today = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE owner_id = ?
        AND event_type = 'click'
        AND datetime(created_at) >= datetime('now','localtime','-7 days')
    """, (user_id,))

    week = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE owner_id = ?
        AND event_type = 'click'
        AND datetime(created_at) >= datetime('now','localtime','-30 days')
    """, (user_id,))

    month = cursor.fetchone()[0]

    conn.close()

    return {
        "total_clicks": total_clicks,
        "total_starts": total_starts,
        "today": today,
        "week": week,
        "month": month
    }


# =========================================================
# PENDING MESSAGE
# =========================================================

def save_pending(
    sender_id,
    target_id,
    telegram_message_id,
    message_type,
    message_text=None,
    parent_id=None
):

    conn = get_connection()

    conn.execute("""
        INSERT OR REPLACE INTO pending_messages
        (
            sender_id,
            target_id,
            telegram_message_id,
            message_type,
            message_text,
            parent_id,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        sender_id,
        target_id,
        telegram_message_id,
        message_type,
        message_text,
        parent_id,
        now()
    ))

    conn.commit()
    conn.close()


def get_pending(sender_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM pending_messages
        WHERE sender_id = ?
    """, (sender_id,))

    result = cursor.fetchone()

    conn.close()

    return result


def delete_pending(sender_id):

    conn = get_connection()

    conn.execute("""
        DELETE FROM pending_messages
        WHERE sender_id = ?
    """, (sender_id,))

    conn.commit()
    conn.close()


# =========================================================
# SETTINGS
# =========================================================

def notifications_enabled(user_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT notifications_enabled
        FROM user_settings
        WHERE user_id = ?
    """, (user_id,))

    result = cursor.fetchone()

    conn.close()

    if not result:
        return True

    return bool(result["notifications_enabled"])


def set_notifications(user_id, enabled):

    conn = get_connection()

    conn.execute("""
        INSERT INTO user_settings
        (
            user_id,
            notifications_enabled
        )
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
        notifications_enabled = excluded.notifications_enabled
    """, (
        user_id,
        1 if enabled else 0
    ))

    conn.commit()
    conn.close()


# =========================================================
# GLOBAL STATS
# =========================================================

def global_stats():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM users
    """)

    users = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM messages
    """)

    messages = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM reports
        WHERE status = 'pending'
    """)

    reports = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM link_events
        WHERE event_type = 'click'
    """)

    clicks = cursor.fetchone()[0]

    conn.close()

    return {
        "users": users,
        "messages": messages,
        "reports": reports,
        "clicks": clicks
    }


if __name__ == "__main__":

    init_db()
    print("Database initialized successfully.")

def add_user(telegram_id, username=None, first_name=None, last_name=None, anonymous_link=None):
    create_user(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name
    )

    conn = get_connection()

    if anonymous_link:
        conn.execute("""
            UPDATE users
            SET anonymous_link = ?
            WHERE telegram_id = ?
        """, (anonymous_link, telegram_id))

    conn.commit()
    conn.close()


def mark_message_read(message_id):
    mark_read(message_id)


def report_message(message_id, reporter_id, reason=""):
    create_report(
        message_id=message_id,
        reporter_id=reporter_id,
        reason=reason
    )


def get_user_by_token(token):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM users
        WHERE link_token = ?
    """, (token,))

    result = cursor.fetchone()
    conn.close()

    return result
