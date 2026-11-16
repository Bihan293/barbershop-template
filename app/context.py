from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional
from .core import Config
from .database import Database

class FlowStore:
    """Короткие состояния диалогов в памяти."""

    def __init__(self) -> None:
        self._data: dict[int, dict] = {}

    def get(self, user_id: int) -> Optional[dict]:
        return self._data.get(user_id)

    def state(self, user_id: int) -> Optional[str]:
        item = self._data.get(user_id)
        return item.get("state") if item else None

    def set(self, user_id: int, state: str, **data: Any) -> None:
        payload = {"state": state}
        payload.update(data)
        self._data[user_id] = payload

    def update(self, user_id: int, **data: Any) -> None:
        item = self._data.setdefault(user_id, {})
        item.update(data)

    def data(self, user_id: int) -> dict:
        return self._data.get(user_id, {})

    def clear(self, user_id: int) -> None:
        self._data.pop(user_id, None)


@dataclass
class Ctx:
    cfg: Config
    db: Database
    flows: FlowStore
    bot: Any = None
    tg_app: Any = None
    update_queue: Optional[asyncio.Queue] = None
    media_messages: dict[int, tuple[int, int]] = field(default_factory=dict)
    metrics: Any = None

    @property
    def admin_ids(self) -> tuple[int, ...]:
        return self.cfg.admin_ids

    def is_admin(self, user_id: Optional[int]) -> bool:
        return bool(user_id) and user_id in self.cfg.admin_ids
