"""
bot.py
Telegram bot listener (python-telegram-bot v21+).

Responsibilities:
    - /start (with optional deep-link param, e.g. `?start=team_ABC123` or
      `?start=shield_<team_id>`): greets the user and opens the Mini App
      via an inline "Open EverTree 3D" WebApp button, forwarding the
      start_param so the Mini App can auto-join a team.
    - /shield: sends a Telegram Stars invoice (XTR currency) for the
      "10-Day Magical Shield".
    - pre_checkout_query + successful_payment handlers: validate and then
      activate the shield in the database.
    - /status: quick text summary of the caller's tree/team.

Run with:  python bot.py
Requires:  BOT_TOKEN and WEBAPP_URL environment variables.
"""

from __future__ import annotations

import logging
import os

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Update,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
)

from database import (
    SHIELD_COST_STARS,
    activate_shield,
    get_or_create_user,
    get_session,
    init_db,
    task_status,
    ALL_ROLES,
    ROLE_LABELS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("evertree3d.bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://your-streamlit-app-url.example.com")


def _webapp_keyboard(start_param: str = "") -> InlineKeyboardMarkup:
    url = WEBAPP_URL
    if start_param:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}startapp={start_param}"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🌳 Open EverTree 3D", web_app=WebAppInfo(url=url))]]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_user = update.effective_user
    args = context.args or []
    start_param = args[0] if args else ""

    db = get_session()
    get_or_create_user(
        db,
        telegram_id=tg_user.id,
        first_name=tg_user.first_name or "",
        last_name=tg_user.last_name or "",
        username=tg_user.username or "",
        photo_url="",  # profile photo fetched client-side via WebApp initDataUnsafe
    )
    db.close()

    if start_param.startswith("shield_"):
        team_id = start_param.replace("shield_", "")
        await send_shield_invoice(update, context, team_id=team_id)
        return

    await update.message.reply_text(
        f"🌳 Welcome to EverTree 3D, {tg_user.first_name}!\n\n"
        "Grow a magical tree together with up to 5 friends. Water it, tend it, "
        "protect it from pests — or let it wither if you slack off.\n\n"
        "Tap below to open the Mini App:",
        reply_markup=_webapp_keyboard(start_param),
    )


async def shield_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explicit /shield command — looks up the caller's team and invoices them."""
    tg_user = update.effective_user
    db = get_session()
    user = get_or_create_user(db, telegram_id=tg_user.id, first_name=tg_user.first_name or "")
    if not user.team_id:
        await update.message.reply_text("Join or start a Grove in the Mini App first! /start")
        db.close()
        return
    team_id = user.team_id
    db.close()
    await send_shield_invoice(update, context, team_id=str(team_id))


async def send_shield_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, team_id: str) -> None:
    chat_id = update.effective_chat.id
    await context.bot.send_invoice(
        chat_id=chat_id,
        title="10-Day Magical Shield",
        description="Protects your EverTree from degradation for 10 days, even if tasks are missed.",
        payload=f"shield:{team_id}",
        provider_token="",  # Telegram Stars payments use an empty provider_token
        currency="XTR",     # Telegram Stars currency code
        prices=[LabeledPrice("Magical Shield (10 days)", SHIELD_COST_STARS)],
    )


async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("shield:"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Unknown item.")


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    payment = update.message.successful_payment
    payload = payment.invoice_payload  # "shield:<team_id>"
    tg_user = update.effective_user

    if not payload.startswith("shield:"):
        return

    team_id = int(payload.split(":", 1)[1])
    db = get_session()
    from database import Team

    team = db.query(Team).filter_by(id=team_id).first()
    if team:
        shield = activate_shield(
            db,
            team,
            purchaser_telegram_id=str(tg_user.id),
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
            stars_paid=payment.total_amount,
        )
        await update.message.reply_text(
            f"🛡️ Magical Shield activated for {team.name}! "
            f"Active until {shield.expires_at.strftime('%Y-%m-%d %H:%M UTC')}."
        )
    db.close()


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_user = update.effective_user
    db = get_session()
    user = get_or_create_user(db, telegram_id=tg_user.id, first_name=tg_user.first_name or "")
    if not user.team_id:
        await update.message.reply_text("You haven't joined a Grove yet. Use /start.")
        db.close()
        return

    team = user.team
    tree = team.tree
    lines = [f"🌳 *{team.name}* — Level {tree.level} ({tree.xp} XP)"]
    for role in ALL_ROLES:
        s = task_status(db, team, role)
        dot = {"done": "🟢", "warning": "🟡", "missed": "🔴", "pending": "⚪", "shielded": "🛡️"}[s["state"]]
        lines.append(f"{dot} {ROLE_LABELS[role]}: {s['completions']}/{s['required']}")
    db.close()
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def main() -> None:
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("shield", shield_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    logger.info("EverTree 3D bot starting (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
