import logging
from collections import defaultdict
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ForceReply,
)
from telegram.error import Forbidden, BadRequest
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import BOT_TOKEN, ADMIN_ID, MAX_MESSAGES_PER_MINUTE
from database import (
    init_db,
    block_user,
    unblock_user,
    is_blocked,
    get_all_blocked,
    save_message,
    mark_replied,
    get_stats,
)

# -------- لاگ‌گیری --------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# -------- Rate Limiting (در RAM — فقط شمارنده موقت) --------
# key: user_id  →  value: list of datetime
user_message_times: dict[int, list[datetime]] = defaultdict(list)


def is_rate_limited(user_id: int) -> bool:
    """بررسی اینکه آیا کاربر بیش از حد پیام فرستاده"""
    now = datetime.now()
    cutoff = now - timedelta(minutes=1)
    times = [t for t in user_message_times[user_id] if t > cutoff]
    user_message_times[user_id] = times
    if len(times) >= MAX_MESSAGES_PER_MINUTE:
        return True
    user_message_times[user_id].append(now)
    return False


# -------- /start --------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """خوشامدگویی به کاربر"""
    user = update.effective_user
    if is_blocked(user.id):
        return
    await update.message.reply_text(
        "سلام ❤️\n"
        "پیامی که می‌خوای به صورت ناشناس بفرستی رو اینجا بنویس.\n"
        "منتظر بمون تا جوابت رو همینجا دریافت کنی 🤝"
    )
    logger.info(f"کاربر {user.id} (@{user.username}) استارت زد.")


# -------- /stats (فقط ادمین) --------
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش آمار ربات به ادمین"""
    if update.effective_user.id != ADMIN_ID:
        return
    s = get_stats()
    text = (
        "📊 آمار ربات\n\n"
        f"📩 کل پیام‌ها: {s['total_messages']}\n"
        f"👥 کاربران منحصربه‌فرد: {s['unique_users']}\n"
        f"⛔ کاربران مسدود: {s['blocked_count']}\n"
        f"📭 پیام‌های بی‌پاسخ: {s['unanswered']}"
    )
    await update.message.reply_text(text)


# -------- /blocked (فقط ادمین) --------
async def blocked_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لیست کاربران مسدود"""
    if update.effective_user.id != ADMIN_ID:
        return
    blocked = get_all_blocked()
    if not blocked:
        await update.message.reply_text("هیچ کاربری مسدود نشده ✅")
        return
    lines = ["⛔ کاربران مسدود شده:\n"]
    for b in blocked:
        date_str = b["blocked_at"][:10]
        lines.append(f"🆔 {b['user_id']} — {date_str}")
    await update.message.reply_text("\n".join(lines))


# -------- /unblock (فقط ادمین) --------
async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """رفع مسدودیت با دستور /unblock user_id"""
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("فرمت صحیح:\n/unblock 123456789")
        return
    uid = int(args[0])
    success = unblock_user(uid)
    if success:
        await update.message.reply_text(f"✅ کاربر {uid} از مسدودیت خارج شد.")
        logger.info(f"ادمین کاربر {uid} را آنبلاک کرد.")
    else:
        await update.message.reply_text(f"⚠️ کاربر {uid} در لیست مسدودها نبود.")


# -------- پیام متنی کاربران --------
async def user_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دریافت پیام متنی از کاربر و ارسال به ادمین"""
    user = update.effective_user
    if user.id == ADMIN_ID:
        return
    if is_blocked(user.id):
        await update.message.reply_text("⛔ شما توسط ادمین مسدود شده‌اید.")
        return
    if is_rate_limited(user.id):
        await update.message.reply_text(
            "⚠️ خیلی سریع پیام می‌فرستی! لطفاً چند لحظه صبر کن."
        )
        return

    text = update.message.text
    username = user.username or "NoUsername"
    msg_id = save_message(user.id, username, text, media_type="text")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✉️ پاسخ", callback_data=f"reply:{user.id}:{msg_id}"),
            InlineKeyboardButton("⛔ مسدود", callback_data=f"block_confirm:{user.id}"),
        ],
        [
            InlineKeyboardButton("🔓 رفع مسدودیت", callback_data=f"unblock:{user.id}"),
        ]
    ])
    msg = (
        f"📩 پیام جدید — شماره #{msg_id}\n\n"
        f"👤 یوزرنیم: @{username}\n"
        f"🆔 آیدی: {user.id}\n\n"
        f"✉️ متن پیام:\n{text}"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=msg, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"خطا در ارسال به ادمین: {e}")

    await update.message.reply_text("✅ پیام شما به صورت ناشناس ارسال شد.")
    logger.info(f"پیام #{msg_id} از کاربر {user.id} دریافت شد.")


# -------- پیام مدیا (عکس، ویس، ویدیو، فایل) --------
async def user_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دریافت مدیا از کاربر و forward به ادمین"""
    user = update.effective_user
    if user.id == ADMIN_ID:
        return
    if is_blocked(user.id):
        await update.message.reply_text("⛔ شما توسط ادمین مسدود شده‌اید.")
        return
    if is_rate_limited(user.id):
        await update.message.reply_text("⚠️ خیلی سریع پیام می‌فرستی! لطفاً صبر کن.")
        return

    username = user.username or "NoUsername"

    # تشخیص نوع مدیا
    if update.message.photo:
        media_type = "photo"
    elif update.message.voice:
        media_type = "voice"
    elif update.message.video:
        media_type = "video"
    elif update.message.document:
        media_type = "document"
    else:
        media_type = "other"

    caption = update.message.caption or ""
    msg_id = save_message(user.id, username, caption or f"[{media_type}]", media_type=media_type)

    header = (
        f"📩 پیام جدید — شماره #{msg_id}\n"
        f"👤 @{username} | 🆔 {user.id}\n"
        f"نوع: {media_type}"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✉️ پاسخ", callback_data=f"reply:{user.id}:{msg_id}"),
            InlineKeyboardButton("⛔ مسدود", callback_data=f"block_confirm:{user.id}"),
        ]
    ])

    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=header)
        await update.message.forward(chat_id=ADMIN_ID)
        # ارسال دکمه‌ها جداگانه
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text="⬆️ پیام بالا",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"خطا در forward مدیا به ادمین: {e}")

    await update.message.reply_text("✅ پیام شما به صورت ناشناس ارسال شد.")


# -------- دکمه‌های ادمین --------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مدیریت کلیک دکمه‌ها توسط ادمین"""
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    data = query.data
    parts = data.split(":")

    action = parts[0]

    # ---- پاسخ دادن ----
    if action == "reply":
        user_id = int(parts[1])
        msg_id = int(parts[2])
        # ذخیره اطلاعات پاسخ در context
        context.user_data["pending_reply"] = {
            "user_id": user_id,
            "msg_id": msg_id,
        }
        sent = await query.message.reply_text(
            f"✏️ پاسخ به پیام #{msg_id} را بنویسید:",
            reply_markup=ForceReply(selective=True),
        )
        # ذخیره آیدی پیام ForceReply برای تشخیص دقیق پاسخ
        context.user_data["force_reply_msg_id"] = sent.message_id

    # ---- تأیید مسدود کردن ----
    elif action == "block_confirm":
        user_id = int(parts[1])
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ بله، مسدود کن", callback_data=f"block:{user_id}"),
                InlineKeyboardButton("❌ انصراف", callback_data="cancel"),
            ]
        ])
        await query.message.reply_text(
            f"⚠️ آیا مطمئنی که می‌خوای کاربر {user_id} را مسدود کنی؟",
            reply_markup=confirm_keyboard,
        )

    # ---- مسدود کردن قطعی ----
    elif action == "block":
        user_id = int(parts[1])
        block_user(user_id)
        await query.message.reply_text(f"⛔ کاربر {user_id} مسدود شد.")
        logger.info(f"ادمین کاربر {user_id} را مسدود کرد.")

    # ---- رفع مسدودیت ----
    elif action == "unblock":
        user_id = int(parts[1])
        success = unblock_user(user_id)
        if success:
            await query.message.reply_text(f"✅ مسدودیت کاربر {user_id} برداشته شد.")
        else:
            await query.message.reply_text(f"ℹ️ کاربر {user_id} مسدود نبود.")

    # ---- انصراف ----
    elif action == "cancel":
        await query.message.reply_text("❌ عملیات لغو شد.")


# -------- پاسخ ادمین (reply به ForceReply) --------
async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ارسال پاسخ ادمین به کاربر"""
    if update.effective_user.id != ADMIN_ID:
        return

    pending = context.user_data.get("pending_reply")
    force_reply_msg_id = context.user_data.get("force_reply_msg_id")

    # بررسی اینکه ادمین دقیقاً به همان پیام ForceReply جواب داده
    reply_to = update.message.reply_to_message
    if not pending or not reply_to or reply_to.message_id != force_reply_msg_id:
        return

    user_id = pending["user_id"]
    msg_id = pending["msg_id"]
    text = update.message.text

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✉️ جواب پیامت رسید:\n\n{text}",
        )
        mark_replied(msg_id)
        await update.message.reply_text("✅ پاسخ ارسال شد.")
        logger.info(f"ادمین به پیام #{msg_id} (کاربر {user_id}) پاسخ داد.")
    except Forbidden:
        await update.message.reply_text("⚠️ کاربر ربات را بلاک کرده و پیام نرسید.")
        logger.warning(f"کاربر {user_id} ربات را بلاک کرده.")
    except BadRequest as e:
        await update.message.reply_text(f"⚠️ خطا در ارسال: {e}")
        logger.error(f"BadRequest برای کاربر {user_id}: {e}")
    finally:
        context.user_data.pop("pending_reply", None)
        context.user_data.pop("force_reply_msg_id", None)


# -------- اجرای ربات --------
def main() -> None:
    init_db()
    logger.info("ربات در حال راه‌اندازی...")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # دستورات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("blocked", blocked_command))
    app.add_handler(CommandHandler("unblock", unblock_command))

    # پاسخ ادمین — باید قبل از user_text_message باشد
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT & filters.User(ADMIN_ID), admin_reply))

    # پیام متنی کاربران
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, user_text_message))

    # پیام مدیا
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VOICE | filters.VIDEO | filters.Document.ALL,
        user_media_message
    ))

    # دکمه‌ها
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("ربات با موفقیت راه‌اندازی شد ✅")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
