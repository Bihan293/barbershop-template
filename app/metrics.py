from __future__ import annotations
"""Лёгкие метрики без внешнего APM.

Всё считается в памяти процесса: количество запросов, ошибок, время
ответа, уникальные посетители за день, размер БД и медиа. Этого достаточно,
чтобы понять нагрузку на одного пользователя и запас сервера.
"""
import logging
import os
import shutil
import time
from collections import Counter, deque
from datetime import datetime
from typing import Any, Optional

from aiohttp import web

from .core import esc
from .media import clear_admin_media, format_bytes

LOG = logging.getLogger("lezvie.metrics")


class Metrics:
    def __init__(self) -> None:
        self.started_at = time.time()
        self.requests_total = 0
        self.errors_total = 0
        self.requests_by_status: Counter[str] = Counter()
        self.requests_by_path: Counter[str] = Counter()
        self.durations_ms: deque[float] = deque(maxlen=1000)
        self.visitors: dict[str, str] = {}
        self.visitors_day = ""
        self.bookings_site = 0
        self.bookings_telegram = 0

    def record_request(
        self,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
        remote: str = "",
    ) -> None:
        self.requests_total += 1
        if status >= 500:
            self.errors_total += 1
        self.requests_by_status[str(status)] += 1
        if path.startswith("/media/"):
            key = "/media/*"
        else:
            key = path
        self.requests_by_path[key] += 1
        self.durations_ms.append(max(0.0, duration_ms))

        today = datetime.now().date().isoformat()
        if self.visitors_day != today:
            self.visitors_day = today
            self.visitors.clear()
        if remote:
            if remote not in self.visitors and len(self.visitors) >= 5000:
                # Ограничиваем память: забываем самого давнего посетителя.
                try:
                    self.visitors.pop(next(iter(self.visitors)))
                except StopIteration:
                    pass
            self.visitors[remote] = today

    def record_booking(self, source: str) -> None:
        if source == "site":
            self.bookings_site += 1
        else:
            self.bookings_telegram += 1

    def percentiles(self) -> tuple[float, float, float]:
        if not self.durations_ms:
            return 0.0, 0.0, 0.0
        values = sorted(self.durations_ms)
        count = len(values)
        p50 = values[min(count - 1, int(count * 0.5))]
        p95 = values[min(count - 1, int(count * 0.95))]
        return p50, p95, values[-1]

    def top_paths(self, limit: int = 8) -> list[dict[str, Any]]:
        return [
            {"path": path, "count": count}
            for path, count in self.requests_by_path.most_common(limit)
        ]

    @staticmethod
    def _process_rss() -> int:
        try:
            with open("/proc/self/status", "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError):
            pass
        return 0

    @staticmethod
    def _media_size(media_dir) -> tuple[int, int]:
        total = 0
        count = 0
        if not media_dir.exists():
            return 0, 0
        for path in media_dir.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                    count += 1
                except OSError:
                    pass
        return total, count

    async def snapshot(self, ctx) -> dict[str, Any]:
        counts = await ctx.db.counts()
        sources = await ctx.db.source_counts()
        try:
            db_size = await ctx.db.database_size()
        except Exception:
            db_size = 0
        media_size, media_count = self._media_size(ctx.cfg.media_dir)
        p50, p95, slowest = self.percentiles()
        uptime = max(0.0, time.time() - self.started_at)
        disk = shutil.disk_usage(ctx.cfg.media_dir if ctx.cfg.media_dir.exists() else ctx.cfg.base_dir)
        return {
            "ok": True,
            "time": datetime.now(ctx.cfg.tz).isoformat(timespec="seconds"),
            "uptime_seconds": round(uptime, 1),
            "database": "postgresql" if ctx.db.is_postgres else "sqlite",
            "db_size_bytes": db_size,
            "media": {
                "files": media_count,
                "bytes": media_size,
            },
            "disk": {
                "total_bytes": disk.total,
                "free_bytes": disk.free,
            },
            "process": {
                "rss_bytes": self._process_rss(),
                "pid": os.getpid(),
            },
            "http": {
                "requests": self.requests_total,
                "errors": self.errors_total,
                "status": dict(self.requests_by_status),
                "top_paths": self.top_paths(),
                "latency_ms": {
                    "p50": round(p50, 1),
                    "p95": round(p95, 1),
                    "max": round(slowest, 1),
                },
                "unique_visitors_today": len(self.visitors),
            },
            "bookings": {
                "site": self.bookings_site,
                "telegram": self.bookings_telegram,
                "site_total": sources.get("site", 0),
                "telegram_total": sources.get("telegram", 0),
                "admin_total": sources.get("admin", 0),
            },
            "counts": counts,
            "bot_running": bool(ctx.bot),
        }


def metrics_text(ctx, data: dict) -> str:
    http = data.get("http", {})
    latency = http.get("latency_ms", {})
    media = data.get("media", {})
    disk = data.get("disk", {})
    counts = data.get("counts", {})
    uptime = float(data.get("uptime_seconds", 0))
    days = int(uptime // 86400)
    hours = int((uptime % 86400) // 3600)
    minutes = int((uptime % 3600) // 60)
    return (
        "📊 <b>Нагрузка и состояние</b>\n\n"
        f"⏱ Аптайм: <b>{days}д {hours}ч {minutes}м</b>\n"
        f"🗄 База: <b>{esc(data.get('database', '—'))}</b> · {format_bytes(data.get('db_size_bytes', 0))}\n"
        f"🖼 Медиа: <b>{media.get('files', 0)}</b> файлов · {format_bytes(media.get('bytes', 0))}\n"
        f"💾 Диск: свободно {format_bytes(disk.get('free_bytes', 0))} из {format_bytes(disk.get('total_bytes', 0))}\n"
        f"🧠 RAM процесса: {format_bytes(data.get('process', {}).get('rss_bytes', 0))}\n\n"
        f"🌐 Запросов: <b>{http.get('requests', 0)}</b> · ошибок 5xx: <b>{http.get('errors', 0)}</b>\n"
        f"👥 Уникальных посетителей сегодня: <b>{http.get('unique_visitors_today', 0)}</b>\n"
        f"⚡ Ответ: p50 <b>{latency.get('p50', 0)} мс</b> · p95 <b>{latency.get('p95', 0)} мс</b> · max {latency.get('max', 0)} мс\n\n"
        f"📥 Заявок в базе — сайт: <b>{data.get('bookings', {}).get('site_total', 0)}</b> · "
        f"Telegram: <b>{data.get('bookings', {}).get('telegram_total', 0)}</b> · "
        f"вручную: <b>{data.get('bookings', {}).get('admin_total', 0)}</b>\n"
        f"↳ с последнего запуска: сайт {data.get('bookings', {}).get('site', 0)} · "
        f"Telegram {data.get('bookings', {}).get('telegram', 0)}\n"
        f"📅 Заказов: всего {counts.get('orders_total', 0)}, сегодня {counts.get('orders_today', 0)}, "
        f"актуальных {counts.get('orders_upcoming', 0)}\n"
        f"👨‍💈 Мастеров: {counts.get('masters_active', 0)} из {counts.get('masters', 0)}\n\n"
        "Данные только для оценки нагрузки. Память и CPU контейнера смотрите в панели хостинга."
    )


async def cmd_stats(update, context) -> None:
    ctx = context.application.bot_data["ctx"]
    if not ctx.is_admin(update.effective_user.id):
        await update.effective_message.reply_text("Нет доступа.")
        return
    await clear_admin_media(ctx, update.effective_user.id)
    metrics = ctx.metrics or Metrics()
    snapshot = await metrics.snapshot(ctx)
    await update.effective_message.reply_text(
        metrics_text(ctx, snapshot),
        parse_mode="HTML",
        reply_markup=None,
        link_preview_options=None,
    )


def create_metrics_middleware():
    @web.middleware
    async def metrics_middleware(request: web.Request, handler):
        started = time.perf_counter()
        status = 500
        try:
            response = await handler(request)
            status = response.status
            return response
        except web.HTTPException as exc:
            status = exc.status
            raise
        except Exception:
            status = 500
            raise
        finally:
            duration = (time.perf_counter() - started) * 1000
            metrics: Optional[Metrics] = request.app.get("metrics")
            if metrics is not None:
                forwarded = request.headers.get("X-Forwarded-For", "")
                remote = forwarded.split(",")[0].strip() if forwarded else (request.remote or "")
                metrics.record_request(
                    request.method,
                    request.path,
                    status,
                    duration,
                    remote,
                )
            if status >= 500:
                LOG.warning(
                    "Ошибка HTTP %s %s → %s · %.0f мс",
                    request.method,
                    request.path,
                    status,
                    duration,
                )
            elif duration > 1500:
                LOG.warning(
                    "Медленный запрос: %s %s → %s · %.0f мс",
                    request.method,
                    request.path,
                    status,
                    duration,
                )
            elif request.method == "POST" or request.path in {"/", "/privacy.html"}:
                LOG.info(
                    "HTTP %s %s → %s · %.0f мс",
                    request.method,
                    request.path,
                    status,
                    duration,
                )

    return metrics_middleware
