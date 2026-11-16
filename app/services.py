from __future__ import annotations
from typing import Any


def combine_services(services: list[dict]) -> dict[str, Any]:
    """Одна запись может содержать несколько услуг: суммируем цену и время."""
    valid = [item for item in services if item]
    if not valid:
        return {"id": None, "name": "", "price": 0, "duration": 30}
    return {
        "id": valid[0].get("id"),
        "name": " + ".join(str(item.get("name") or "") for item in valid),
        "price": sum(int(item.get("price") or 0) for item in valid),
        "duration": sum(int(item.get("duration") or 0) for item in valid),
    }


def service_items(services: list[dict]) -> list[dict]:
    return [
        {
            "id": item.get("id"),
            "name": str(item.get("name") or ""),
            "price": int(item.get("price") or 0),
            "duration": int(item.get("duration") or 0),
        }
        for item in services
        if item
    ]
