from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
import shutil
import sys
import time
import uuid
from datetime import date as Date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import web
from telegram import (
    BotCommand,
    BotCommandScopeChat,
    InlineKeyboardButton as Btn,
    InlineKeyboardMarkup as Kb,
    KeyboardButton,
    LinkPreviewOptions,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .core import *
from .database import Database
from .context import Ctx, FlowStore
from .ui import cancel_row, edit_q, safe_answer
from .media import (
    photo_path,
    download_photo,
    move_photo,
    cleanup_old_temp_files,
    remove_photo,
    register_admin_media,
    clear_admin_media,
    send_photo_file,
    replace_admin_screen,
    cleanup_orphan_media,
    media_inventory,
    format_bytes,
)
from .notifications import (
    order_card_text,
    order_whatsapp_url,
    order_notification_kb,
    send_admins,
    notify_new_order,
    notify_client,
)
