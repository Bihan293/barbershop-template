from __future__ import annotations
import argparse
import html
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import date as Date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# ============================================================
# Пути и конфигурация
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

LOG = logging.getLogger("lezvie")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
# httpx печатает полный URL Bot API вместе с токеном — отключаем.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

MONTHS_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
MONTHS_NOM = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)
WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


def parse_admin_ids(raw: str) -> tuple[int, ...]:
    return tuple(sorted({int(x) for x in re.findall(r"\d+", raw or "")}))


@dataclass
class Config:
    base_dir: Path
    db_path: Path
    media_dir: Path
    bot_token: str
    admin_ids: tuple[int, ...]
    public_url: str
    site_url: str
    host: str
    port: int
    timezone: str
    use_webhook: bool
    webhook_secret: str
    api_only: bool
    database_url: str = ""
    metrics_token: str = ""
    tz: ZoneInfo = field(init=False)

    def __post_init__(self) -> None:
        try:
            self.tz = ZoneInfo(self.timezone)
        except Exception:
            LOG.warning("Неизвестная таймзона %s, использую UTC", self.timezone)
            self.tz = ZoneInfo("UTC")

    @property
    def local_base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def site_link(self) -> str:
        return (self.site_url or self.public_url or self.local_base).rstrip("/")


def build_config(args: argparse.Namespace) -> Config:
    db_path = Path(os.getenv("DB_PATH", "data/barbershop.db"))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    media_dir = Path(os.getenv("MEDIA_DIR", "media"))
    if not media_dir.is_absolute():
        media_dir = BASE_DIR / media_dir

    public_url = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
    use_webhook = env_bool("USE_WEBHOOK", False) and bool(public_url) and not args.api_only
    secret = os.getenv("WEBHOOK_SECRET", "").strip() or secrets.token_urlsafe(24)

    return Config(
        base_dir=BASE_DIR,
        db_path=db_path,
        media_dir=media_dir,
        database_url=os.getenv("DATABASE_URL", "").strip(),
        metrics_token=os.getenv("METRICS_TOKEN", "").strip(),
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        admin_ids=parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        public_url=public_url,
        site_url=os.getenv("SITE_URL", "").strip().rstrip("/"),
        host=args.host or os.getenv("HOST", "0.0.0.0"),
        port=int(args.port or os.getenv("PORT", "8080")),
        timezone=os.getenv("TIMEZONE", "Asia/Almaty").strip() or "Asia/Almaty",
        use_webhook=use_webhook,
        webhook_secret=secret,
        api_only=args.api_only,
    )


# ============================================================
# Утилиты
# ============================================================

def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def money(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return f"{number:,}".replace(",", " ") + " ₸"


def digits_only(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_phone(value: Any) -> Optional[str]:
    digits = digits_only(value)
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if not (10 <= len(digits) <= 15):
        return None
    return "+" + digits


def phone_digits(value: Any) -> str:
    normalized = normalize_phone(value)
    return digits_only(normalized or value)


def whatsapp_digits(settings: dict) -> str:
    """Номер WhatsApp с защитой от старого placeholder 77000000000."""
    wa = digits_only(settings.get("whatsapp", ""))
    phone = digits_only(settings.get("phone", ""))
    if (not wa or wa == "77000000000") and phone:
        return phone
    return wa or phone


def display_phone(value: Any) -> str:
    digits = digits_only(value)
    if len(digits) == 11 and digits.startswith("7"):
        return f"+7 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:11]}"
    if len(digits) == 10:
        return f"+7 {digits[0:3]} {digits[3:6]} {digits[6:8]} {digits[8:10]}"
    return ("+" + digits) if digits else ""


def money_number(value: Any) -> Optional[int]:
    raw = str(value or "")
    cleaned = re.sub(r"[^\d]", "", raw)
    if not cleaned:
        return None
    number = int(cleaned)
    if number < 0 or number > 10_000_000:
        return None
    return number


def int_in_range(value: Any, minimum: int, maximum: int) -> Optional[int]:
    raw = re.sub(r"[^\d]", "", str(value or ""))
    if not raw:
        return None
    number = int(raw)
    if not (minimum <= number <= maximum):
        return None
    return number


def hhmm_to_min(value: Any, default: int = -1) -> int:
    raw = str(value or "").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if not match:
        return default
    hours, minutes = int(match.group(1)), int(match.group(2))
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return default
    return hours * 60 + minutes


def min_to_hhmm(total: int) -> str:
    total = max(0, min(total, 23 * 60 + 59))
    return f"{total // 60:02d}:{total % 60:02d}"


def valid_iso_date(value: Any) -> Optional[str]:
    try:
        return Date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        return None


def date_from_iso(value: str) -> Date:
    return Date.fromisoformat(value)


def date_label(value: str) -> str:
    try:
        d = date_from_iso(value)
    except (TypeError, ValueError):
        return str(value or "—")
    return f"{d.day} {MONTHS_GEN[d.month - 1]}, {WEEKDAYS[d.weekday()]}"


def short_date_label(value: str, tz: ZoneInfo) -> str:
    try:
        d = date_from_iso(value)
    except (TypeError, ValueError):
        return str(value or "—")
    today = datetime.now(tz).date()
    if d == today:
        prefix = "сегодня"
    elif d == today + timedelta(days=1):
        prefix = "завтра"
    else:
        prefix = WEEKDAYS[d.weekday()]
    return f"{prefix}, {d.day} {MONTHS_GEN[d.month - 1]}"


def move_day_label(day: str, tz: ZoneInfo) -> str:
    d = date_from_iso(day)
    today = datetime.now(tz).date()
    if d == today:
        return "Сегодня"
    if d == today + timedelta(days=1):
        return "Завтра"
    return f"{d.day} {MONTHS_GEN[d.month - 1][:3]}, {WEEKDAYS[d.weekday()]}"


def valid_time(value: Any) -> Optional[str]:
    minutes = hhmm_to_min(value)
    if minutes < 0:
        return None
    return min_to_hhmm(minutes)


def overlaps(start_a: int, dur_a: int, start_b: int, dur_b: int) -> bool:
    return start_a < start_b + dur_b and start_b < start_a + dur_a


def is_public_http_url(url: str) -> bool:
    """Telegram не любит localhost/private IP в URL-кнопках."""
    text = str(url or "").strip()
    if not re.match(r"^https?://", text, re.I):
        return False
    host = re.sub(r"^https?://", "", text, flags=re.I).split("/")[0]
    host = host.split("@")[-1]
    if host.startswith("["):
        host_part = host.split("]")[0] + "]"
    else:
        host_part = host.split(":")[0]
    host_part = host_part.lower()
    if host_part in {"localhost", "127.0.0.1", "0.0.0.0", "[::1]", "::1"}:
        return False
    if host_part.startswith("127.") or host_part.startswith("10.") or host_part.startswith("192.168."):
        return False
    if re.match(r"^172\.(1[6-9]|2\d|3[01])\.", host_part):
        return False
    return True


def public_site_link(cfg: Config) -> str:
    return cfg.site_link if is_public_http_url(cfg.site_link) else ""


def initials(name: str) -> str:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    if not parts:
        return "Г"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def clean_text(value: Any, max_len: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_len]


def valid_url(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not re.match(r"^https?://", text, re.I):
        return None
    if len(text) > 500:
        return None
    return text


def normalize_instagram(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("@"):
        handle = text[1:].strip()
        if not re.fullmatch(r"[A-Za-z0-9._]{2,40}", handle):
            return None
        return f"https://instagram.com/{handle}"
    url = valid_url(text)
    if not url:
        handle = text.strip("/")
        if re.fullmatch(r"[A-Za-z0-9._]{2,40}", handle):
            return f"https://instagram.com/{handle}"
        return None
    return url


def instagram_label(url: str) -> str:
    match = re.search(r"instagram\.com/([^/?#]+)", url or "", re.I)
    if match:
        return "@" + match.group(1)
    return url or "@instagram"


def status_label(status: str) -> str:
    return {
        "new": "новый",
        "confirmed": "подтверждён",
        "cancelled": "отменён",
        "completed": "завершён",
    }.get(status, status)


def status_icon(status: str) -> str:
    return {
        "new": "🆕",
        "confirmed": "✅",
        "cancelled": "❌",
        "completed": "🏁",
    }.get(status, "•")


def channel_label(channel: str) -> str:
    return {
        "whatsapp": "WhatsApp",
        "telegram": "Telegram",
        "admin": "Телефон / админ",
    }.get(str(channel or "").lower(), str(channel or "Telegram"))
