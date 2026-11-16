from __future__ import annotations
import math
from .deps import *
from aiohttp import web
from .scheduling import public_schedule_label
from .services import combine_services, service_items
from .metrics import Metrics, create_metrics_middleware

# ============================================================
# API и сайт
# ============================================================

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


class RateLimiter:
    def __init__(self, limit: int = 12, window: int = 600) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, list[float]] = {}
        self._calls = 0

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        self._calls += 1
        if self._calls % 500 == 0 and len(self._hits) > 1000:
            self._hits = {
                item_key: [stamp for stamp in stamps if now - stamp < self.window]
                for item_key, stamps in self._hits.items()
                if any(now - stamp < self.window for stamp in stamps)
            }
        bucket = [stamp for stamp in self._hits.get(key, []) if now - stamp < self.window]
        if len(bucket) >= self.limit:
            self._hits[key] = bucket
            return False
        bucket.append(now)
        self._hits[key] = bucket
        return True


RATE = RateLimiter()
PORTAL_RATE = RateLimiter(limit=60, window=600)


def client_ip(request: web.Request) -> str:
    """IP клиента за прокси; для rate limit, не для авторизации."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.remote or "unknown"


def public_base(cfg: Config, request: Optional[web.Request] = None) -> str:
    if cfg.public_url:
        return cfg.public_url
    if request is not None:
        return f"{request.scheme}://{request.host}"
    return cfg.local_base


def media_url(cfg: Config, relative: str, request: Optional[web.Request] = None) -> str:
    if not relative:
        return ""
    if relative.startswith("http://") or relative.startswith("https://"):
        return relative
    relative = relative.lstrip("/")
    return f"{public_base(cfg, request)}/media/{relative}"


async def site_payload(ctx: Ctx, request: web.Request) -> dict:
    db = ctx.db
    settings = await db.get_settings()
    services = await db.list_services()
    gallery = await db.list_gallery()
    reviews = await db.list_reviews()
    why_items = await db.list_why()
    stats_rows = await db.list_site_stats()
    masters = await db.list_masters(active_only=True)
    master_items = []
    for master in masters:
        schedule = await db.get_master_schedule(int(master["id"]))
        master_items.append(
            {
                "id": master["id"],
                "name": master["name"],
                "description": master["description"],
                "photo_url": media_url(ctx.cfg, master["photo"], request),
                "hours": public_schedule_label(schedule),
            }
        )

    return {
        "brand": settings.get("brand", "ЛЕЗВИЕ"),
        "city": settings.get("city", "Алматы"),
        "services": [
            {
                "id": item["id"],
                "name": item["name"],
                "description": item["description"],
                "price": item["price"],
                "duration": item["duration"],
                "photo_url": media_url(ctx.cfg, item["photo"], request),
            }
            for item in services
        ],
        "gallery": [
            {
                "id": item["id"],
                "caption": item["caption"],
                "image_url": media_url(ctx.cfg, item["image"], request),
            }
            for item in gallery
        ],
        "reviews": [
            {
                "id": item["id"],
                "name": item["name"],
                "text": item["text"],
                "rating": item["rating"],
                "source": item["source"],
            }
            for item in reviews
        ],
        "masters": master_items,
        "why": [
            {
                "id": item["id"],
                "icon": item["icon"],
                "title": item["title"],
                "text": item["text"],
            }
            for item in why_items
        ],
        "contacts": {
            "address": settings.get("address", ""),
            "address_note": settings.get("address_note", ""),
            "hours": settings.get("hours", ""),
            "hours_note": settings.get("hours_note", ""),
            "phone": settings.get("phone", ""),
            "phone_digits": phone_digits(settings.get("phone", "")),
            "whatsapp": whatsapp_digits(settings),
            "twogis_url": settings.get("twogis_url", ""),
            "instagram": settings.get("instagram", ""),
            "instagram_label": instagram_label(settings.get("instagram", "")),
        },
        "stats": site_stats_payload(stats_rows),
        "settings": {
            "booking_enabled": settings.get("booking_enabled", "1") == "1",
            "slot_step": int(settings.get("slot_step", "30") or 30),
            "work_start": settings.get("work_start", "10:00"),
            "work_end": settings.get("work_end", "21:00"),
            "last_slot": settings.get("last_slot", "20:00"),
        },
    }


def parse_stat_value(raw: Any) -> tuple[Optional[float], int]:
    text = str(raw or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return None, 0
    try:
        number = float(text)
    except ValueError:
        return None, 0
    if not math.isfinite(number):
        return None, 0
    decimals = 0
    if "." in text:
        decimals = min(2, len(text.split(".", 1)[1]))
    return number, decimals


def site_stats_payload(rows: list[dict]) -> list[dict]:
    result: list[dict] = []
    for row in rows:
        raw_value = str(row.get("value") or "").strip()
        number, decimals = parse_stat_value(raw_value)
        result.append(
            {
                "id": row.get("id"),
                "value": number if number is not None else raw_value,
                "numeric": number is not None,
                "decimals": decimals,
                "plus": bool(int(row.get("plus") or 0)) and number is not None,
                "label": str(row.get("label") or ""),
            }
        )
    return result


async def api_site(request: web.Request) -> web.Response:
    ctx: Ctx = request.app["ctx"]
    cache = request.app.get("site_cache")
    lock = request.app.get("site_cache_lock")
    key = public_base(ctx.cfg, request)
    now = time.monotonic()
    if cache and lock:
        cached = cache.get("data")
        if cached and cache.get("key") == key and now < cache.get("expires", 0):
            return web.json_response(cached, headers={"Cache-Control": "no-store"})
        async with lock:
            now = time.monotonic()
            cached = cache.get("data")
            if cached and cache.get("key") == key and now < cache.get("expires", 0):
                return web.json_response(cached, headers={"Cache-Control": "no-store"})
            payload = await site_payload(ctx, request)
            cache.update({"key": key, "data": payload, "expires": now + 2.0})
            return web.json_response(payload, headers={"Cache-Control": "no-store"})
    payload = await site_payload(ctx, request)
    return web.json_response(payload, headers={"Cache-Control": "no-store"})


async def api_slots(request: web.Request) -> web.Response:
    ctx: Ctx = request.app["ctx"]
    day = valid_iso_date(request.query.get("date"))
    if not day:
        return web.json_response({"ok": False, "error": "Некорректная дата"}, status=400)
    duration = 30
    services: list[dict] = []
    raw_ids = request.query.get("service_ids", "")
    raw_values = [part for part in str(raw_ids).split(",") if part.strip()]
    if not raw_values and request.query.get("service_id"):
        raw_values = [str(request.query.get("service_id"))]
    seen: set[int] = set()
    for raw in raw_values[:10]:
        try:
            service = await ctx.db.get_service(int(raw))
        except (TypeError, ValueError):
            service = None
        if service and int(service["id"]) not in seen:
            seen.add(int(service["id"]))
            services.append(service)
    if services:
        duration = sum(int(item["duration"] or 0) for item in services)
    master_id: Optional[int] = None
    raw_master = request.query.get("master_id")
    if raw_master:
        try:
            value = int(raw_master)
            master_id = value if value > 0 else None
        except ValueError:
            master_id = None
    cache = request.app.get("slots_cache")
    lock = request.app.get("slots_cache_lock")
    key = (day, int(duration), int(master_id) if master_id else 0)
    now = time.monotonic()
    if cache is not None and lock is not None:
        cached = cache.get(key)
        if cached and now < cached[1]:
            return web.json_response(
                {"ok": True, "date": day, "duration": duration, "slots": cached[0]},
                headers={"Cache-Control": "no-store"},
            )
        async with lock:
            now = time.monotonic()
            cached = cache.get(key)
            if cached and now < cached[1]:
                return web.json_response(
                    {"ok": True, "date": day, "duration": duration, "slots": cached[0]},
                    headers={"Cache-Control": "no-store"},
                )
            slots = await ctx.db.available_slots(day, duration, master_id=master_id)
            if len(cache) > 500:
                cache.clear()
            cache[key] = (slots, now + 1.0)
            return web.json_response(
                {"ok": True, "date": day, "duration": duration, "slots": slots},
                headers={"Cache-Control": "no-store"},
            )
    slots = await ctx.db.available_slots(day, duration, master_id=master_id)
    return web.json_response(
        {"ok": True, "date": day, "duration": duration, "slots": slots},
        headers={"Cache-Control": "no-store"},
    )


async def portal_order_payload(ctx: Ctx, order: dict) -> dict:
    now = datetime.now(ctx.cfg.tz)
    active = order.get("status") in {"new", "confirmed"}
    can_change = False
    past = False
    try:
        start = datetime.strptime(
            f"{order['date']} {order['time']}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=ctx.cfg.tz)
        past = start <= now
        can_change = active and not past
    except ValueError:
        pass

    attention = ""
    if active and past:
        attention = "Время записи уже прошло — свяжитесь с салоном"
    master_id = order.get("master_id")
    if active:
        if master_id:
            master = await ctx.db.get_master(int(master_id))
            if not master or not int(master.get("active") or 0):
                attention = "Мастер сейчас недоступен"
            else:
                try:
                    weekday = date_from_iso(order["date"]).weekday()
                except ValueError:
                    weekday = -1
                schedule = await ctx.db.get_master_schedule_day(int(master_id), weekday)
                day_off = await ctx.db.get_day_off(int(master_id), order["date"])
                if day_off:
                    attention = "У мастера выходной в этот день"
                elif not schedule or not int(schedule.get("enabled") or 0):
                    attention = "Мастер не работает в этот день"
        if not attention and can_change:
            slots = await ctx.db.available_slots(
                order["date"],
                int(order["duration"] or 30),
                exclude_order_id=int(order["id"]),
                master_id=int(master_id) if master_id else None,
            )
            if order["time"] not in slots:
                attention = "Время записи изменилось — свяжитесь с салоном"

    service_rows = await ctx.db.get_order_services(int(order["id"]))
    return {
        "id": order["id"],
        "name": order.get("name", ""),
        "service": order.get("service_name", ""),
        "services": [
            {
                "name": row.get("service_name", ""),
                "price": row.get("price", 0),
                "duration": row.get("duration", 0),
            }
            for row in service_rows
        ],
        "price": order.get("price", 0),
        "duration": order.get("duration", 0),
        "master": order.get("master_name", ""),
        "date": order.get("date", ""),
        "time": order.get("time", ""),
        "status": order.get("status", ""),
        "status_label": status_label(order.get("status", "")),
        "comment": order.get("comment", ""),
        "source": order.get("source", ""),
        "can_cancel": can_change,
        "can_reschedule": can_change and not attention,
        "needs_attention": bool(attention),
        "attention_reason": attention,
    }


async def api_my_bookings(request: web.Request) -> web.Response:
    ctx: Ctx = request.app["ctx"]
    if not PORTAL_RATE.allow(client_ip(request)):
        return web.json_response(
            {"ok": False, "error": "Слишком много запросов. Попробуйте позже."},
            status=429,
        )
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Некорректные данные"}, status=400)
    raw_tokens = data.get("tokens") if isinstance(data, dict) else None
    if not isinstance(raw_tokens, list):
        raw_tokens = []
    tokens = [str(token).strip() for token in raw_tokens if str(token).strip()][:20]
    orders = await ctx.db.orders_by_tokens(tokens)
    payload = [await portal_order_payload(ctx, order) for order in orders]
    return web.json_response({"ok": True, "orders": payload}, headers={"Cache-Control": "no-store"})


def portal_tokens(data: dict) -> list[str]:
    raw = data.get("tokens")
    if not isinstance(raw, list):
        raw = [data.get("token")] if data.get("token") else []
    return [str(token).strip() for token in raw if str(token).strip()][:20]


async def api_my_cancel(request: web.Request) -> web.Response:
    ctx: Ctx = request.app["ctx"]
    if not PORTAL_RATE.allow(client_ip(request)):
        return web.json_response({"ok": False, "error": "Слишком много запросов"}, status=429)
    try:
        data = await request.json()
        tokens = portal_tokens(data)
        order_id = int(data.get("order_id") or 0)
    except Exception:
        return web.json_response({"ok": False, "error": "Некорректные данные"}, status=400)
    order = await ctx.db.get_order(order_id)
    if not order or str(order.get("public_token") or "") not in tokens:
        return web.json_response({"ok": False, "error": "Запись не найдена"}, status=404)
    canceled, error = await ctx.db.cancel_order_by_token(
        order_id, str(order.get("public_token") or "")
    )
    if error or not canceled:
        return web.json_response({"ok": False, "error": error or "Не удалось отменить"}, status=409)
    text = (
        "❌ <b>Клиент отменил запись с сайта</b>\n\n"
        f"👤 {esc(canceled['name'])}\n"
        f"📞 {esc(display_phone(canceled['phone']) or canceled['phone'])}\n"
        f"💈 {esc(canceled['service_name'])} · {esc(canceled.get('master_name') or 'любой мастер')}\n"
        f"📅 {date_label(canceled['date'])}, <b>{canceled['time']}</b>"
    )
    await send_admins(
        ctx,
        text,
        Kb([[
            Btn("📋 Открыть заказ", callback_data=f"adm:order:{order_id}"),
            Btn("💬 WhatsApp", url=order_whatsapp_url(ctx, canceled)),
        ]]),
    )
    return web.json_response(
        {"ok": True, "order": await portal_order_payload(ctx, canceled)},
        headers={"Cache-Control": "no-store"},
    )


async def api_my_slots(request: web.Request) -> web.Response:
    ctx: Ctx = request.app["ctx"]
    if not PORTAL_RATE.allow(client_ip(request)):
        return web.json_response({"ok": False, "error": "Слишком много запросов"}, status=429)
    try:
        data = await request.json()
        tokens = portal_tokens(data)
        order_id = int(data.get("order_id") or 0)
        day = valid_iso_date(data.get("date"))
    except Exception:
        return web.json_response({"ok": False, "error": "Некорректные данные"}, status=400)
    order = await ctx.db.get_order(order_id)
    if not order or str(order.get("public_token") or "") not in tokens:
        return web.json_response({"ok": False, "error": "Запись не найдена"}, status=404)
    if not day:
        return web.json_response({"ok": False, "error": "Некорректная дата"}, status=400)
    slots = await ctx.db.available_slots(
        day,
        int(order["duration"] or 30),
        exclude_order_id=order_id,
        master_id=int(order["master_id"]) if order.get("master_id") else None,
    )
    return web.json_response(
        {"ok": True, "date": day, "slots": slots},
        headers={"Cache-Control": "no-store"},
    )


async def api_my_reschedule(request: web.Request) -> web.Response:
    ctx: Ctx = request.app["ctx"]
    if not PORTAL_RATE.allow(client_ip(request)):
        return web.json_response({"ok": False, "error": "Слишком много запросов"}, status=429)
    try:
        data = await request.json()
        tokens = portal_tokens(data)
        order_id = int(data.get("order_id") or 0)
        day = valid_iso_date(data.get("date"))
        slot = valid_time(data.get("time"))
    except Exception:
        return web.json_response({"ok": False, "error": "Некорректные данные"}, status=400)
    if not day or not slot:
        return web.json_response({"ok": False, "error": "Некорректная дата или время"}, status=400)
    old = await ctx.db.get_order(order_id)
    if not old or str(old.get("public_token") or "") not in tokens:
        return web.json_response({"ok": False, "error": "Запись не найдена"}, status=404)
    if old.get("master_id"):
        master = await ctx.db.get_master(int(old["master_id"]))
        if not master or not int(master.get("active") or 0):
            return web.json_response(
                {"ok": False, "error": "Мастер сейчас недоступен — позвоните в салон"},
                status=409,
            )
    updated, error = await ctx.db.reschedule_order(
        order_id, day, slot, owner_token=str(old.get("public_token") or "")
    )
    if error or not updated:
        return web.json_response({"ok": False, "error": error or "Не удалось перенести"}, status=409)
    text = (
        "📅 <b>Клиент перенёс запись с сайта</b>\n\n"
        f"👤 {esc(updated['name'])}\n"
        f"📞 {esc(display_phone(updated['phone']) or updated['phone'])}\n"
        f"💈 {esc(updated['service_name'])} · {esc(updated.get('master_name') or 'любой мастер')}\n"
        f"Было: {date_label(old['date'])}, {old['time']}\n"
        f"Стало: <b>{date_label(updated['date'])}, {updated['time']}</b>"
    )
    await send_admins(
        ctx,
        text,
        Kb([[
            Btn("📋 Открыть заказ", callback_data=f"adm:order:{order_id}"),
            Btn("💬 WhatsApp", url=order_whatsapp_url(ctx, updated)),
        ]]),
    )
    return web.json_response(
        {"ok": True, "order": await portal_order_payload(ctx, updated)},
        headers={"Cache-Control": "no-store"},
    )


async def api_book(request: web.Request) -> web.Response:
    ctx: Ctx = request.app["ctx"]
    if not RATE.allow(client_ip(request)):
        return web.json_response(
            {"ok": False, "error": "Слишком много заявок. Попробуйте через несколько минут."},
            status=429,
        )

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Некорректные данные"}, status=400)
    if not isinstance(data, dict):
        return web.json_response({"ok": False, "error": "Некорректные данные"}, status=400)

    # Ловушка для ботов: поле скрыто на сайте.
    if str(data.get("company") or "").strip():
        return web.json_response({"ok": True, "order_id": 0, "message": "Спасибо!"})

    settings = await ctx.db.get_settings()
    if settings.get("booking_enabled", "1") != "1":
        return web.json_response(
            {"ok": False, "error": "Онлайн-запись временно недоступна. Позвоните нам."},
            status=403,
        )
    if not await ctx.db.list_masters(active_only=True):
        return web.json_response(
            {"ok": False, "error": "Сейчас нет доступных мастеров. Позвоните нам."},
            status=403,
        )

    consent = data.get("consent")
    if consent not in (True, 1, "true", "1"):
        return web.json_response(
            {"ok": False, "error": "Подтвердите согласие с политикой обработки персональных данных."},
            status=400,
        )

    name = clean_text(data.get("name"), 60)
    phone = normalize_phone(data.get("phone"))
    comment = clean_text(data.get("comment"), 300)
    channel = str(data.get("channel") or "telegram").lower()
    if channel not in {"telegram", "whatsapp"}:
        channel = "telegram"

    if len(name) < 2:
        return web.json_response({"ok": False, "error": "Укажите имя"}, status=400)
    if not phone:
        return web.json_response({"ok": False, "error": "Укажите корректный телефон"}, status=400)

    services: list[dict] = []
    seen: set[int] = set()
    raw_ids = data.get("service_ids")
    if isinstance(raw_ids, list):
        for raw in raw_ids[:10]:
            try:
                service = await ctx.db.get_service(int(raw))
            except (TypeError, ValueError):
                service = None
            if not service:
                return web.json_response({"ok": False, "error": "Одна из услуг недоступна"}, status=400)
            if int(service["id"]) not in seen:
                seen.add(int(service["id"]))
                services.append(service)
    if not services:
        raw_names = data.get("services")
        if isinstance(raw_names, list):
            for raw in raw_names[:10]:
                service = await ctx.db.find_service_by_name(clean_text(raw, 80))
                if not service:
                    return web.json_response({"ok": False, "error": "Одна из услуг недоступна"}, status=400)
                if int(service["id"]) not in seen:
                    seen.add(int(service["id"]))
                    services.append(service)
    if not services:
        try:
            service_id = int(data.get("service_id") or 0)
        except (TypeError, ValueError):
            service_id = 0
        if service_id:
            service = await ctx.db.get_service(service_id)
            if service:
                services = [service]
    if not services:
        service_name = clean_text(data.get("service"), 80)
        if service_name:
            service = await ctx.db.find_service_by_name(service_name)
            if service:
                services = [service]
    if not services:
        return web.json_response({"ok": False, "error": "Выберите услугу"}, status=400)
    service = combine_services(services)
    items = service_items(services)

    master_id: Optional[int] = None
    try:
        master_value = int(data.get("master_id") or 0)
        master_id = master_value if master_value > 0 else None
    except (TypeError, ValueError):
        master_id = None

    day = valid_iso_date(data.get("date"))
    slot = valid_time(data.get("time"))
    if not day or not slot:
        return web.json_response({"ok": False, "error": "Укажите дату и время"}, status=400)

    today = datetime.now(ctx.cfg.tz).date()
    selected = date_from_iso(day)
    if selected < today:
        return web.json_response({"ok": False, "error": "Дата уже прошла"}, status=400)
    if selected > today + timedelta(days=90):
        return web.json_response({"ok": False, "error": "Слишком далёкая дата"}, status=400)

    if master_id is not None:
        master = await ctx.db.get_master(master_id)
        if not master or not int(master.get("active") or 0):
            return web.json_response(
                {"ok": False, "error": "Выбранный мастер недоступен. Выберите другого."},
                status=409,
            )

    available = await ctx.db.available_slots(
        day,
        int(service["duration"] or 30),
        master_id=master_id,
    )
    if slot not in available:
        return web.json_response(
            {"ok": False, "error": "Это время уже занято. Выберите другое."},
            status=409,
        )

    order, error = await ctx.db.create_order(
        name=name,
        phone=phone,
        service=service,
        day=day,
        slot=slot,
        channel=channel,
        comment=comment,
        source="site",
        tg_id=None,
        master_id=master_id,
        consent_at=datetime.now(ctx.cfg.tz).isoformat(timespec="seconds"),
        service_items=items,
    )
    if error or not order:
        return web.json_response({"ok": False, "error": error or "Не удалось создать заявку"}, status=409)

    request.app.get("slots_cache", {}).clear()
    if ctx.metrics:
        ctx.metrics.record_booking("site")
    LOG.info(
        "Новая заявка с сайта #%s: %s %s, мастер %s",
        order["id"],
        day,
        slot,
        order.get("master_name") or "—",
    )
    try:
        await notify_new_order(ctx, order)
    except Exception:
        LOG.exception("Заявка #%s создана, но уведомление не отправлено", order["id"])

    return web.json_response(
        {
            "ok": True,
            "order_id": order["id"],
            "date": order["date"],
            "time": order["time"],
            "service": order["service_name"],
            "services": [item["name"] for item in items],
            "price": order["price"],
            "duration": order["duration"],
            "master": order.get("master_name", ""),
            "access_token": order.get("public_token", ""),
            "channel": order["channel"],
            "status": order["status"],
            "message": "Заявка принята",
        }
    )


async def api_health(request: web.Request) -> web.Response:
    ctx: Ctx = request.app["ctx"]
    try:
        await ctx.db.fetchone("SELECT 1 AS ok")
        db_ok = True
    except Exception:
        db_ok = False
    return web.json_response(
        {
            "ok": db_ok,
            "service": "lezvie-barbershop",
            "time": datetime.now(ctx.cfg.tz).isoformat(timespec="seconds"),
            "bot": bool(ctx.bot),
            "database": "postgresql" if ctx.db.is_postgres else "sqlite",
        },
        status=200 if db_ok else 503,
    )


def metrics_allowed(ctx: Ctx, request: web.Request) -> bool:
    if ctx.cfg.metrics_token:
        token = request.headers.get("X-Metrics-Token") or request.query.get("token") or ""
        return secrets.compare_digest(str(token), ctx.cfg.metrics_token)
    return (request.remote or "") in {"127.0.0.1", "::1", "localhost"}


async def api_metrics(request: web.Request) -> web.Response:
    ctx: Ctx = request.app["ctx"]
    if not metrics_allowed(ctx, request):
        return web.json_response(
            {"ok": False, "error": "Нужен METRICS_TOKEN или локальный доступ"},
            status=403,
        )
    snapshot = await ctx.metrics.snapshot(ctx)
    return web.json_response(snapshot, headers={"Cache-Control": "no-store"})


async def handle_index(request: web.Request) -> web.StreamResponse:
    ctx: Ctx = request.app["ctx"]
    index_path = ctx.cfg.base_dir / "site" / "index.html"
    if not index_path.exists():
        return web.Response(text="site/index.html не найден рядом с main.py", status=500)
    return web.FileResponse(index_path, headers={"Cache-Control": "no-cache"})


async def handle_site_asset(request: web.Request) -> web.StreamResponse:
    ctx: Ctx = request.app["ctx"]
    name = request.path.lstrip("/")
    allowed = {
        "theme.css": "text/css; charset=utf-8",
        "app.js": "application/javascript; charset=utf-8",
        "privacy.html": "text/html; charset=utf-8",
    }
    if name not in allowed:
        return web.Response(status=404)
    path = ctx.cfg.base_dir / "site" / name
    if not path.exists():
        return web.Response(status=404)
    return web.FileResponse(path, headers={"Cache-Control": "no-cache"})


async def handle_privacy(request: web.Request) -> web.StreamResponse:
    ctx: Ctx = request.app["ctx"]
    path = ctx.cfg.base_dir / "site" / "privacy.html"
    if not path.exists():
        return web.Response(status=404, text="privacy.html не найден")
    settings = await ctx.db.get_settings()
    html = path.read_text(encoding="utf-8")
    replacements = {
        "{{brand}}": settings.get("brand", "ЛЕЗВИЕ"),
        "{{city}}": settings.get("city", "Алматы"),
        "{{address}}": settings.get("address", ""),
        "{{phone}}": settings.get("phone", ""),
        "{{phone_digits}}": phone_digits(settings.get("phone", "")),
        "{{privacy_updated}}": settings.get("privacy_updated", ""),
    }
    for key, value in replacements.items():
        html = html.replace(key, esc(value))
    return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-cache"})


async def handle_webhook(request: web.Request) -> web.Response:
    ctx: Ctx = request.app["ctx"]
    secret = request.match_info.get("secret", "")
    if not secrets.compare_digest(secret, ctx.cfg.webhook_secret):
        return web.Response(status=403)
    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if header_secret and not secrets.compare_digest(header_secret, ctx.cfg.webhook_secret):
        return web.Response(status=403)
    if ctx.bot is None or ctx.update_queue is None:
        return web.Response(status=503)
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400)
    update = Update.de_json(data, ctx.bot)
    if update is not None:
        await ctx.update_queue.put(update)
    return web.json_response({"ok": True})


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        headers = dict(CORS_HEADERS)
        if request.headers.get("Access-Control-Request-Private-Network") == "true":
            headers["Access-Control-Allow-Private-Network"] = "true"
        return web.Response(status=204, headers=headers)
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc
    except Exception:
        LOG.exception("Ошибка API: %s %s", request.method, request.path)
        if request.path.startswith("/api/"):
            response = web.json_response({"ok": False, "error": "Внутренняя ошибка"}, status=500)
        else:
            response = web.Response(status=500, text="Internal Server Error")
    response.headers.update(CORS_HEADERS)
    if request.headers.get("Access-Control-Request-Private-Network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


def create_web_app(ctx: Ctx) -> web.Application:
    metrics = ctx.metrics or Metrics()
    ctx.metrics = metrics
    app = web.Application(middlewares=[create_metrics_middleware(), cors_middleware])
    app["ctx"] = ctx
    app["metrics"] = metrics
    app["site_cache"] = {"key": "", "data": None, "expires": 0.0}
    app["site_cache_lock"] = asyncio.Lock()
    app["slots_cache"] = {}
    app["slots_cache_lock"] = asyncio.Lock()

    app.router.add_get("/", handle_index)
    app.router.add_get("/index.html", handle_index)
    app.router.add_get("/theme.css", handle_site_asset)
    app.router.add_get("/app.js", handle_site_asset)
    app.router.add_get("/privacy.html", handle_privacy)
    app.router.add_get("/api/site", api_site)
    app.router.add_get("/api/slots", api_slots)
    app.router.add_post("/api/bookings", api_book)
    app.router.add_post("/api/my-bookings", api_my_bookings)
    app.router.add_post("/api/my-bookings/cancel", api_my_cancel)
    app.router.add_post("/api/my-bookings/slots", api_my_slots)
    app.router.add_post("/api/my-bookings/reschedule", api_my_reschedule)
    app.router.add_get("/api/health", api_health)
    app.router.add_get("/health", api_health)
    app.router.add_get("/metrics", api_metrics)
    app.router.add_get("/api/metrics", api_metrics)

    ctx.cfg.media_dir.mkdir(parents=True, exist_ok=True)
    for subdir in ("services", "gallery", "masters"):
        folder = ctx.cfg.media_dir / subdir
        folder.mkdir(parents=True, exist_ok=True)
        app.router.add_static(
            f"/media/{subdir}/",
            folder,
            show_index=False,
            follow_symlinks=False,
        )

    if ctx.cfg.use_webhook:
        app.router.add_post(
            f"/tg/webhook/{ctx.cfg.webhook_secret}",
            handle_webhook,
            name="telegram_webhook",
        )
    return app
