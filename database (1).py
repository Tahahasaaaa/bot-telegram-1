import sqlite3
from datetime import datetime

DB_PATH = "bot_data.db"


def get_connection() -> sqlite3.Connection:
    """اتصال به دیتابیس SQLite"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """ساخت جداول دیتابیس در صورت نبود"""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_id   INTEGER PRIMARY KEY,
                blocked_at TEXT NOT NULL,
                reason    TEXT DEFAULT 'مسدود شده توسط ادمین'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                username    TEXT,
                text        TEXT,
                media_type  TEXT,
                timestamp   TEXT NOT NULL,
                replied     INTEGER DEFAULT 0
            )
        """)
        conn.commit()


# -------- blocked_users --------

def block_user(user_id: int, reason: str = "مسدود شده توسط ادمین") -> None:
    """مسدود کردن کاربر"""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO blocked_users (user_id, blocked_at, reason) VALUES (?, ?, ?)",
            (user_id, datetime.now().isoformat(), reason)
        )
        conn.commit()


def unblock_user(user_id: int) -> bool:
    """رفع مسدودیت کاربر — True اگر کاربر واقعاً مسدود بوده"""
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM blocked_users WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount > 0


def is_blocked(user_id: int) -> bool:
    """بررسی مسدود بودن کاربر"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM blocked_users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row is not None


def get_all_blocked() -> list[dict]:
    """لیست تمام کاربران مسدود شده"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT user_id, blocked_at, reason FROM blocked_users ORDER BY blocked_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# -------- messages --------

def save_message(user_id: int, username: str, text: str | None, media_type: str | None = None) -> int:
    """ذخیره پیام و برگرداندن شماره پیام"""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO messages (user_id, username, text, media_type, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, text, media_type, datetime.now().isoformat())
        )
        conn.commit()
        return cur.lastrowid


def mark_replied(message_id: int) -> None:
    """علامت‌گذاری پیام به عنوان پاسخ داده شده"""
    with get_connection() as conn:
        conn.execute("UPDATE messages SET replied = 1 WHERE id = ?", (message_id,))
        conn.commit()


def get_stats() -> dict:
    """آمار کلی ربات"""
    with get_connection() as conn:
        total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        unique_users = conn.execute("SELECT COUNT(DISTINCT user_id) FROM messages").fetchone()[0]
        blocked_count = conn.execute("SELECT COUNT(*) FROM blocked_users").fetchone()[0]
        unanswered = conn.execute("SELECT COUNT(*) FROM messages WHERE replied = 0").fetchone()[0]
        return {
            "total_messages": total_messages,
            "unique_users": unique_users,
            "blocked_count": blocked_count,
            "unanswered": unanswered,
        }
