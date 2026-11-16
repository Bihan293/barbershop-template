from __future__ import annotations
from typing import Optional
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb
from telegram.constants import ParseMode
from telegram.error import TelegramError
import contextlib
import logging

LOG = logging.getLogger("lezvie.ui")


def cancel_row(callback: str, text: str = "❌ Отмена") -> Kb:
    return Kb([[Btn(text, callback_data=callback)]])


async def edit_q(q, text: str, kb: Optional[Kb] = None) -> None:
    """Редактирует текст или подпись фото, не падая на служебных ошибках."""
    try:
        if q.message and (q.message.photo or q.message.document):
            await q.edit_message_caption(
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        else:
            await q.edit_message_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
    except TelegramError as exc:
        if "not modified" in str(exc).lower():
            return
        LOG.warning("edit_q: %s", exc)
        with contextlib.suppress(Exception):
            await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def safe_answer(q, text: Optional[str] = None, show_alert: bool = False) -> None:
    with contextlib.suppress(TelegramError):
        await q.answer(text=text, show_alert=show_alert)
