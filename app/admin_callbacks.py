from __future__ import annotations
from .deps import *
from .admin_ui import *
from .admin_text import *
from .master_callbacks import handle_master_cb
from .admin_booking import handle_admin_booking_cb
from .metrics import Metrics, metrics_text

# ============================================================
# Админские callback-и
# ============================================================

def cleanup_flow_temp(ctx: Ctx, uid: int) -> None:
    data = ctx.flows.data(uid)
    remove_photo(ctx, data.get("photo_tmp", ""))
    draft = data.get("draft") or {}
    if isinstance(draft, dict):
        remove_photo(ctx, draft.get("photo_tmp", ""))


async def handle_admin_cb(ctx: Ctx, q, data: str) -> None:
    uid = q.from_user.id
    await clear_admin_media(ctx, uid)
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action in {
        "home", "orders", "order", "ostatus", "ostatusok", "services", "svc",
        "gallery", "gal", "reviews", "rev", "whys", "why", "contacts", "settings",
        "mst", "masters", "media", "stats", "site_stats",
    }:
        cleanup_flow_temp(ctx, uid)

    if action in {"svc_add", "gal_add"}:
        cleanup_flow_temp(ctx, uid)

    if action == "masters" or action == "mst" or action.startswith("mst_"):
        if await handle_master_cb(ctx, q, data):
            return

    if action.startswith("ab_"):
        if await handle_admin_booking_cb(ctx, q, data):
            return

    # ---------- навигация ----------
    if action == "home":
        ctx.flows.clear(uid)
        await show_admin_home_q(ctx, q)
        return

    if action == "orders" and len(parts) >= 4:
        ctx.flows.clear(uid)
        filter_name = parts[2]
        try:
            page = int(parts[3])
        except ValueError:
            page = 0
        text, kb = await orders_screen(ctx, filter_name, page)
        await edit_q(q, text, kb)
        return

    if action == "order" and len(parts) >= 3:
        ctx.flows.clear(uid)
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        text, kb = await order_detail_screen(ctx, order_id)
        await edit_q(q, text, kb)
        return

    if action == "move" and len(parts) >= 3:
        ctx.flows.clear(uid)
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        await admin_move_dates_screen(ctx, q, order_id)
        return

    if action == "move_date" and len(parts) >= 4:
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        await admin_move_times_screen(ctx, q, order_id, parts[3])
        return

    if action == "move_time" and len(parts) >= 5:
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        await admin_move_confirm_screen(ctx, q, order_id, parts[3], ":".join(parts[4:]))
        return

    if action == "move_ok" and len(parts) >= 5:
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        await apply_admin_move(ctx, q, order_id, parts[3], ":".join(parts[4:]))
        return

    if action == "ostatus" and len(parts) >= 4:
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        text, kb = await ask_order_status(ctx, order_id, parts[3])
        await edit_q(q, text, kb)
        return

    if action == "ostatusok" and len(parts) >= 4:
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        updated = await apply_order_status(ctx, order_id, parts[3])
        if not updated:
            await safe_answer(q, "Заказ не найден или статус уже изменился", show_alert=True)
            return
        text, kb = await order_detail_screen(ctx, order_id)
        suffix = "\n\n✅ Статус обновлён."
        if parts[3] == "cancel":
            if updated.get("client_notified"):
                suffix += " Клиент получил уведомление об отмене в Telegram."
            elif updated.get("tg_id"):
                suffix += (
                    " ⚠️ Не удалось отправить уведомление клиенту. "
                    f"Напишите ему: {esc(display_phone(updated['phone']))}"
                )
            else:
                if updated.get("source") == "admin":
                    suffix += (
                        "\n\n⚠️ <b>Запись создана вручную — сообщите клиенту об отмене.</b>"
                        f"\n📞 <b>{esc(display_phone(updated['phone']))}</b>"
                    )
                else:
                    suffix += (
                        "\n\n⚠️ <b>Клиент записался через сайт — напишите ему, что заказ отменён.</b>"
                        f"\n📞 <b>{esc(display_phone(updated['phone']))}</b>"
                    )
        await edit_q(q, text + suffix, kb)
        return

    if action == "site":
        ctx.flows.clear(uid)
        await edit_q(
            q,
            f"🌐 <b>Сайт</b>\n\n<code>{esc(ctx.cfg.site_link)}</code>\n\n"
            "Откройте адрес в браузере телефона, пока запущен бот. "
            "Для публичной ссылки задайте PUBLIC_URL в .env.",
            Kb([[Btn("← В админ-панель", callback_data="adm:home")]]),
        )
        return

    if action == "services":
        ctx.flows.clear(uid)
        text, kb = await services_screen(ctx)
        await edit_q(q, text, kb)
        return

    if action == "svc" and len(parts) >= 3:
        ctx.flows.clear(uid)
        await show_service_detail(ctx, q, int(parts[2]))
        return

    if action == "svc_add":
        ctx.flows.set(uid, "svc_add_name", draft={})
        await edit_q(
            q,
            "➕ <b>Новая услуга</b>\n\nШаг 1 из 5. Введите название услуги:",
            cancel_row("adm:svc_add_cancel"),
        )
        return

    if action == "svc_add_skip":
        draft = ctx.flows.data(uid).get("draft", {})
        ctx.flows.set(uid, "svc_add_save", draft=draft)
        await edit_q(
            q,
            service_preview(draft),
            Kb([
                [Btn("✅ Сохранить", callback_data="adm:svc_add_save")],
                [Btn("❌ Отмена", callback_data="adm:svc_add_cancel")],
            ]),
        )
        return

    if action == "svc_add_cancel":
        draft = ctx.flows.data(uid).get("draft", {})
        remove_photo(ctx, draft.get("photo_tmp", ""))
        ctx.flows.clear(uid)
        await edit_q(q, "Добавление услуги отменено.", Kb([[Btn("← К услугам", callback_data="adm:services")]]))
        return

    if action == "svc_add_save":
        draft = ctx.flows.data(uid).get("draft", {})
        if not draft.get("name") or draft.get("price") is None:
            await safe_answer(q, "Заполните услугу заново", show_alert=True)
            return
        photo = move_photo(ctx, draft.get("photo_tmp", ""), "services")
        service_id = await ctx.db.add_service(
            name=draft["name"],
            description=draft.get("description", ""),
            price=int(draft.get("price", 0)),
            duration=int(draft.get("duration", 60)),
            photo=photo,
        )
        ctx.flows.clear(uid)
        await edit_q(
            q,
            f"✅ Услуга «{esc(draft['name'])}» добавлена.",
            Kb([
                [Btn("💈 Открыть услугу", callback_data=f"adm:svc:{service_id}")],
                [Btn("← К услугам", callback_data="adm:services")],
            ]),
        )
        return

    if action == "svc_edit" and len(parts) >= 4:
        try:
            service_id = int(parts[2])
        except ValueError:
            service_id = 0
        field = parts[3]
        service = await ctx.db.get_service(service_id)
        if not service:
            await edit_q(q, "Услуга не найдена.", Kb([[Btn("← К услугам", callback_data="adm:services")]]))
            return
        if field == "photo":
            ctx.flows.set(uid, "svc_edit_photo", service_id=service_id)
            await edit_q(
                q,
                f"🖼 Отправьте новое фото для «{esc(service['name'])}».\n\n"
                "Сейчас фото: " + ("есть" if service.get("photo") else "нет"),
                cancel_row(f"adm:svc:{service_id}"),
            )
            return
        labels = {"name": "название", "description": "описание", "price": "цену", "duration": "длительность"}
        ctx.flows.set(uid, "svc_edit_value", service_id=service_id, field=field)
        current = service.get(field, "")
        if field == "price":
            current = money(current)
        await edit_q(
            q,
            f"✏️ Введите новое {labels.get(field, field)} для «{esc(service['name'])}».\n\n"
            f"Сейчас: <b>{esc(current)}</b>",
            cancel_row(f"adm:svc:{service_id}"),
        )
        return

    if action == "svc_edit_save":
        data_now = ctx.flows.data(uid)
        service_id = int(data_now.get("service_id", 0))
        field = data_now.get("field", "")
        value = data_now.get("value")
        if field in {"name", "description", "price", "duration"}:
            await ctx.db.update_service(service_id, **{field: value})
        ctx.flows.clear(uid)
        await show_service_detail(ctx, q, service_id)
        return

    if action == "svc_photo_save":
        data_now = ctx.flows.data(uid)
        service_id = int(data_now.get("service_id", 0))
        old = await ctx.db.get_service(service_id)
        new_photo = move_photo(ctx, data_now.get("photo_tmp", ""), "services")
        if not new_photo:
            ctx.flows.clear(uid)
            await edit_q(
                q,
                "Фото не найдено. Откройте услугу и загрузите изображение заново.",
                Kb([[Btn("💈 К услуге", callback_data=f"adm:svc:{service_id}")]]),
            )
            return
        await ctx.db.update_service(service_id, photo=new_photo)
        if old and old.get("photo"):
            remove_photo(ctx, old["photo"])
        ctx.flows.clear(uid)
        await edit_q(
            q,
            "✅ Фото услуги обновлено.",
            Kb([
                [Btn("💈 К услуге", callback_data=f"adm:svc:{service_id}")],
                [Btn("← К услугам", callback_data="adm:services")],
            ]),
        )
        return

    if action == "svc_photo_del" and len(parts) >= 3:
        service = await ctx.db.get_service(int(parts[2]))
        if not service or not service.get("photo"):
            await safe_answer(q, "У услуги уже нет фото", show_alert=True)
            return
        await edit_q(
            q,
            f"🗑 <b>Удалить фото услуги?</b>\n\n{esc(service['name'])} · {money(service['price'])}\n\n"
            "Сама услуга и её цена останутся, фотография исчезнет с сайта.",
            Kb([
                [Btn("✅ Да, удалить фото", callback_data=f"adm:svc_photo_delok:{service['id']}")],
                [Btn("← Нет, назад", callback_data=f"adm:svc:{service['id']}")],
            ]),
        )
        return

    if action == "svc_photo_delok" and len(parts) >= 3:
        service_id = int(parts[2])
        service = await ctx.db.get_service(service_id)
        if service and service.get("photo"):
            remove_photo(ctx, service["photo"])
            await ctx.db.update_service(service_id, photo="")
        ctx.flows.clear(uid)
        await show_service_detail(ctx, q, service_id)
        return

    if action == "svc_del" and len(parts) >= 3:
        service = await ctx.db.get_service(int(parts[2]))
        if not service:
            await safe_answer(q, "Услуга не найдена", show_alert=True)
            return
        await edit_q(
            q,
            f"🗑 <b>Удалить услугу?</b>\n\n<b>{esc(service['name'])}</b> · {money(service['price'])}\n\n"
            "Заказы сохранят название и цену, но услуга исчезнет с сайта и из записи.",
            Kb([
                [Btn("✅ Да, удалить", callback_data=f"adm:svc_delok:{service['id']}")],
                [Btn("← Нет, назад", callback_data=f"adm:svc:{service['id']}")],
            ]),
        )
        return

    if action == "svc_delok" and len(parts) >= 3:
        service_id = int(parts[2])
        service = await ctx.db.delete_service(service_id)
        if service and service.get("photo"):
            remove_photo(ctx, service["photo"])
        ctx.flows.clear(uid)
        text, kb = await services_screen(ctx)
        await edit_q(q, "✅ Услуга удалена.\n\n" + text, kb)
        return

    # ---------- галерея ----------
    if action == "gallery":
        ctx.flows.clear(uid)
        text, kb = await gallery_screen(ctx)
        await edit_q(q, text, kb)
        return

    if action == "gal" and len(parts) >= 3:
        ctx.flows.clear(uid)
        await show_gallery_detail(ctx, q, int(parts[2]))
        return

    if action == "gal_add":
        ctx.flows.set(uid, "gal_add_photo", draft={})
        await edit_q(
            q,
            "🖼 <b>Новое фото в галерею</b>\n\nОтправьте изображение.",
            cancel_row("adm:gallery"),
        )
        return

    if action == "gal_skip_caption":
        data_now = ctx.flows.data(uid)
        draft = data_now.get("draft", {})
        draft["caption"] = ""
        ctx.flows.set(uid, "gal_add_save", draft=draft)
        await send_gallery_preview(ctx, q.message, uid, draft, "Новое фото")
        return

    if action == "gal_add_save":
        data_now = ctx.flows.data(uid)
        draft = data_now.get("draft", {})
        image = move_photo(ctx, draft.get("photo_tmp", ""), "gallery")
        if not image:
            await safe_answer(q, "Фото не найдено", show_alert=True)
            return
        item_id = await ctx.db.add_gallery(image=image, caption=draft.get("caption", ""))
        ctx.flows.clear(uid)
        await edit_q(
            q,
            f"✅ Фото добавлено в галерею.\n\nПодпись: {esc(draft.get('caption')) or 'без подписи'}",
            Kb([
                [Btn("🖼 К галерее", callback_data="adm:gallery")],
                [Btn("➕ Добавить ещё", callback_data="adm:gal_add")],
            ]),
        )
        return

    if action == "gal_add_cancel":
        draft = ctx.flows.data(uid).get("draft", {})
        remove_photo(ctx, draft.get("photo_tmp", ""))
        ctx.flows.clear(uid)
        await edit_q(q, "Добавление фото отменено.", Kb([[Btn("← К галерее", callback_data="adm:gallery")]]))
        return

    if action == "gal_caption" and len(parts) >= 3:
        item_id = int(parts[2])
        item = await ctx.db.get_gallery(item_id)
        if not item:
            await safe_answer(q, "Фото не найдено", show_alert=True)
            return
        ctx.flows.set(uid, "gal_edit_caption", item_id=item_id)
        await edit_q(
            q,
            f"✏️ Введите новую подпись.\n\nСейчас: {esc(item['caption']) or 'без подписи'}\n"
            "Отправьте «-», чтобы убрать подпись.",
            cancel_row(f"adm:gal:{item_id}"),
        )
        return

    if action == "gal_caption_save":
        data_now = ctx.flows.data(uid)
        item_id = int(data_now.get("item_id", 0))
        await ctx.db.update_gallery(item_id, caption=data_now.get("caption", ""))
        ctx.flows.clear(uid)
        await show_gallery_detail(ctx, q, item_id)
        return

    if action == "gal_photo" and len(parts) >= 3:
        item_id = int(parts[2])
        ctx.flows.set(uid, "gal_edit_photo", item_id=item_id)
        await edit_q(
            q,
            "🖼 Отправьте новое изображение для этого пункта галереи.",
            cancel_row(f"adm:gal:{item_id}"),
        )
        return

    if action == "gal_photo_save":
        data_now = ctx.flows.data(uid)
        item_id = int(data_now.get("item_id", 0))
        item = await ctx.db.get_gallery(item_id)
        new_image = move_photo(ctx, data_now.get("photo_tmp", ""), "gallery")
        if not new_image:
            ctx.flows.clear(uid)
            await edit_q(
                q,
                "Фото не найдено. Откройте карточку и загрузите изображение заново.",
                Kb([[Btn("🖼 К галерее", callback_data="adm:gallery")]]),
            )
            return
        await ctx.db.update_gallery(item_id, image=new_image)
        if item and item.get("image"):
            remove_photo(ctx, item["image"])
        ctx.flows.clear(uid)
        await edit_q(
            q,
            "✅ Фото обновлено.",
            Kb([
                [Btn("🖼 К галерее", callback_data="adm:gallery")],
                [Btn("👁 Открыть пункт", callback_data=f"adm:gal:{item_id}")],
            ]),
        )
        return

    if action == "gal_photo_del" and len(parts) >= 3:
        item = await ctx.db.get_gallery(int(parts[2]))
        if not item or not item.get("image"):
            await safe_answer(q, "В карточке уже нет фото", show_alert=True)
            return
        await edit_q(
            q,
            f"🗑 <b>Удалить фото из карточки?</b>\n\n{esc(item['caption']) or 'Без подписи'}\n\n"
            "Карточка и подпись останутся, на сайте будет заглушка.",
            Kb([
                [Btn("✅ Да, удалить фото", callback_data=f"adm:gal_photo_delok:{item['id']}")],
                [Btn("← Нет, назад", callback_data=f"adm:gal:{item['id']}")],
            ]),
        )
        return

    if action == "gal_photo_delok" and len(parts) >= 3:
        item_id = int(parts[2])
        item = await ctx.db.get_gallery(item_id)
        if item and item.get("image"):
            remove_photo(ctx, item["image"])
            await ctx.db.update_gallery(item_id, image="")
        ctx.flows.clear(uid)
        await show_gallery_detail(ctx, q, item_id)
        return

    if action == "gal_del" and len(parts) >= 3:
        item = await ctx.db.get_gallery(int(parts[2]))
        if not item:
            await safe_answer(q, "Фото не найдено", show_alert=True)
            return
        await edit_q(
            q,
            f"🗑 <b>Удалить фото из галереи?</b>\n\n{esc(item['caption']) or 'Без подписи'}\n\n"
            "Действие нельзя отменить.",
            Kb([
                [Btn("✅ Да, удалить", callback_data=f"adm:gal_delok:{item['id']}")],
                [Btn("← Нет, назад", callback_data=f"adm:gal:{item['id']}")],
            ]),
        )
        return

    if action == "gal_delok" and len(parts) >= 3:
        item = await ctx.db.delete_gallery(int(parts[2]))
        if item and item.get("image"):
            remove_photo(ctx, item["image"])
        ctx.flows.clear(uid)
        text, kb = await gallery_screen(ctx)
        await edit_q(q, "✅ Фото удалено.\n\n" + text, kb)
        return

    # ---------- отзывы ----------
    if action == "reviews":
        ctx.flows.clear(uid)
        text, kb = await reviews_screen(ctx)
        await edit_q(q, text, kb)
        return

    if action == "rev" and len(parts) >= 3:
        ctx.flows.clear(uid)
        await show_review_detail(ctx, q, int(parts[2]))
        return

    if action == "rev_add":
        ctx.flows.set(uid, "rev_add_name", draft={})
        await edit_q(
            q,
            "➕ <b>Новый отзыв</b>\n\nШаг 1 из 4. Введите имя гостя:",
            cancel_row("adm:rev_add_cancel"),
        )
        return

    if action == "rev_rating" and len(parts) >= 3:
        rating = int_in_range(parts[2], 1, 5)
        if rating is None:
            await safe_answer(q, "Оценка от 1 до 5", show_alert=True)
            return
        draft = ctx.flows.data(uid).get("draft", {})
        draft["rating"] = rating
        ctx.flows.set(uid, "rev_add_source", draft=draft)
        await edit_q(
            q,
            f"Оценка: {'★' * rating}{'☆' * (5 - rating)}\n\n"
            "Источник и дата, например: 2ГИС · ноябрь 2026. Можно пропустить.",
            Kb([
                [Btn("⏭ Пропустить", callback_data="adm:rev_add_skip")],
                [Btn("❌ Отмена", callback_data="adm:rev_add_cancel")],
            ]),
        )
        return

    if action == "rev_add_skip":
        draft = ctx.flows.data(uid).get("draft", {})
        draft["source"] = "2ГИС"
        ctx.flows.set(uid, "rev_add_save", draft=draft)
        await edit_q(
            q,
            review_preview(draft),
            Kb([
                [Btn("✅ Сохранить", callback_data="adm:rev_add_save")],
                [Btn("❌ Отмена", callback_data="adm:rev_add_cancel")],
            ]),
        )
        return

    if action == "rev_add_save":
        draft = ctx.flows.data(uid).get("draft", {})
        if not draft.get("name") or not draft.get("text"):
            await safe_answer(q, "Заполните отзыв заново", show_alert=True)
            return
        await ctx.db.add_review(
            name=draft["name"],
            text=draft["text"],
            rating=int(draft.get("rating", 5)),
            source=draft.get("source", "2ГИС"),
        )
        ctx.flows.clear(uid)
        await edit_q(
            q,
            "✅ Отзыв добавлен.",
            Kb([
                [Btn("⭐ К отзывам", callback_data="adm:reviews")],
                [Btn("➕ Добавить ещё", callback_data="adm:rev_add")],
            ]),
        )
        return

    if action == "rev_add_cancel":
        ctx.flows.clear(uid)
        await edit_q(q, "Добавление отзыва отменено.", Kb([[Btn("← К отзывам", callback_data="adm:reviews")]]))
        return

    if action == "rev_edit" and len(parts) >= 4:
        review_id = int(parts[2])
        field = parts[3]
        review = await ctx.db.get_review(review_id)
        if not review:
            await safe_answer(q, "Отзыв не найден", show_alert=True)
            return
        labels = {"name": "имя", "text": "текст", "rating": "оценку (1–5)", "source": "источник"}
        if field not in labels:
            await safe_answer(q, "Неизвестное поле", show_alert=True)
            return
        ctx.flows.set(uid, "rev_edit_value", review_id=review_id, field=field)
        await edit_q(
            q,
            f"✏️ Введите {labels[field]}.\n\nСейчас: <b>{esc(review.get(field))}</b>",
            cancel_row(f"adm:rev:{review_id}"),
        )
        return

    if action == "rev_edit_save":
        data_now = ctx.flows.data(uid)
        review_id = int(data_now.get("review_id", 0))
        field = data_now.get("field", "")
        value = data_now.get("value")
        if field in {"name", "text", "rating", "source"}:
            await ctx.db.update_review(review_id, **{field: value})
        ctx.flows.clear(uid)
        await show_review_detail(ctx, q, review_id)
        return

    if action == "rev_del" and len(parts) >= 3:
        review = await ctx.db.get_review(int(parts[2]))
        if not review:
            await safe_answer(q, "Отзыв не найден", show_alert=True)
            return
        await edit_q(
            q,
            f"🗑 <b>Удалить отзыв?</b>\n\n<b>{esc(review['name'])}</b>\n<i>{esc(review['text'])[:200]}</i>",
            Kb([
                [Btn("✅ Да, удалить", callback_data=f"adm:rev_delok:{review['id']}")],
                [Btn("← Нет, назад", callback_data=f"adm:rev:{review['id']}")],
            ]),
        )
        return

    if action == "rev_delok" and len(parts) >= 3:
        await ctx.db.delete_review(int(parts[2]))
        ctx.flows.clear(uid)
        text, kb = await reviews_screen(ctx)
        await edit_q(q, "✅ Отзыв удалён.\n\n" + text, kb)
        return

    # ---------- почему мы ----------
    if action == "whys":
        ctx.flows.clear(uid)
        why_text_value, why_kb_value = await why_screen(ctx)
        await edit_q(q, why_text_value, why_kb_value)
        return

    if action == "why" and len(parts) >= 3:
        ctx.flows.clear(uid)
        await show_why_detail(ctx, q, int(parts[2]))
        return

    if action == "why_add":
        ctx.flows.set(uid, "why_add_icon", draft={})
        await edit_q(
            q,
            "➕ <b>Новая карточка «Почему мы»</b>\n\n"
            "Шаг 1 из 3. Отправьте эмодзи или иконку, например ✂️:",
            cancel_row("adm:why_add_cancel"),
        )
        return

    if action == "why_add_cancel":
        ctx.flows.clear(uid)
        await edit_q(q, "Добавление карточки отменено.", Kb([[Btn("← К «Почему мы»", callback_data="adm:whys")]]))
        return

    if action == "why_add_save":
        draft = ctx.flows.data(uid).get("draft", {})
        if not draft.get("icon") or not draft.get("title") or not draft.get("text"):
            await safe_answer(q, "Заполните карточку заново", show_alert=True)
            return
        await ctx.db.add_why(
            icon=draft["icon"],
            title=draft["title"],
            text=draft["text"],
        )
        ctx.flows.clear(uid)
        await edit_q(
            q,
            "✅ Карточка добавлена.",
            Kb([
                [Btn("💡 К «Почему мы»", callback_data="adm:whys")],
                [Btn("➕ Добавить ещё", callback_data="adm:why_add")],
            ]),
        )
        return

    if action == "why_edit" and len(parts) >= 4:
        item_id = int(parts[2])
        field = parts[3]
        item = await ctx.db.get_why(item_id)
        if not item:
            await safe_answer(q, "Карточка не найдена", show_alert=True)
            return
        labels = {"icon": "иконку (эмодзи)", "title": "заголовок", "text": "текст"}
        if field not in labels:
            await safe_answer(q, "Неизвестное поле", show_alert=True)
            return
        ctx.flows.set(uid, "why_edit_value", item_id=item_id, field=field)
        await edit_q(
            q,
            f"✏️ Введите {labels[field]}.\n\nСейчас: <b>{esc(item.get(field))}</b>",
            cancel_row(f"adm:why:{item_id}"),
        )
        return

    if action == "why_edit_save":
        data_now = ctx.flows.data(uid)
        item_id = int(data_now.get("item_id", 0))
        field = data_now.get("field", "")
        value = data_now.get("value")
        if field in {"icon", "title", "text"}:
            await ctx.db.update_why(item_id, **{field: value})
        ctx.flows.clear(uid)
        await show_why_detail(ctx, q, item_id)
        return

    if action == "why_del" and len(parts) >= 3:
        item = await ctx.db.get_why(int(parts[2]))
        if not item:
            await safe_answer(q, "Карточка не найдена", show_alert=True)
            return
        await edit_q(
            q,
            f"🗑 <b>Удалить карточку?</b>\n\n{esc(item['icon'])} <b>{esc(item['title'])}</b>\n\n"
            "Она исчезнет с сайта.",
            Kb([
                [Btn("✅ Да, удалить", callback_data=f"adm:why_delok:{item['id']}")],
                [Btn("← Нет, назад", callback_data=f"adm:why:{item['id']}")],
            ]),
        )
        return

    if action == "why_delok" and len(parts) >= 3:
        await ctx.db.delete_why(int(parts[2]))
        ctx.flows.clear(uid)
        why_text_value, why_kb_value = await why_screen(ctx)
        await edit_q(q, "✅ Карточка удалена.\n\n" + why_text_value, why_kb_value)
        return

    # ---------- контакты ----------
    if action == "contacts":
        ctx.flows.clear(uid)
        text, kb = await contacts_screen(ctx)
        await edit_q(q, text, kb)
        return

    if action == "con_edit" and len(parts) >= 3:
        key = parts[2]
        if key not in CONTACT_MAP:
            await safe_answer(q, "Неизвестное поле", show_alert=True)
            return
        settings = await ctx.db.get_settings()
        current = settings.get(key, "")
        if key == "whatsapp":
            current = display_phone(whatsapp_digits(settings))
        ctx.flows.set(uid, "con_value", key=key)
        label, placeholder = CONTACT_MAP[key]
        await edit_q(
            q,
            f"📍 <b>{esc(label)}</b>\n\nСейчас: <b>{esc(current) or '—'}</b>\n\n"
            + ("Коротко, как на вывеске — до 24 символов.\n\n" if key == "brand" else "")
            + f"Введите новое значение. Например: {esc(placeholder)}",
            cancel_row("adm:contacts"),
        )
        return

    if action == "con_save":
        data_now = ctx.flows.data(uid)
        key = data_now.get("key", "")
        value = data_now.get("value", "")
        sync_note = ""
        if key:
            old_settings = await ctx.db.get_settings()
            old_phone_digits = phone_digits(old_settings.get("phone", ""))
            old_wa_digits = digits_only(old_settings.get("whatsapp", ""))
            await ctx.db.set_setting(key, value)
            if key == "phone":
                new_phone_digits = phone_digits(value)
                if new_phone_digits and (
                    not old_wa_digits
                    or old_wa_digits == old_phone_digits
                    or old_wa_digits == "77000000000"
                ):
                    await ctx.db.set_setting("whatsapp", new_phone_digits)
                    sync_note = " WhatsApp обновлён на новый номер."
        ctx.flows.clear(uid)
        text, kb = await contacts_screen(ctx)
        await edit_q(q, "✅ Сохранено." + sync_note + "\n\n" + text, kb)
        return

    # ---------- настройки ----------
    if action == "media":
        ctx.flows.clear(uid)
        text, kb = await media_screen(ctx)
        await edit_q(q, text, kb)
        return

    if action == "media_check":
        result = await cleanup_orphan_media(ctx, dry_run=True)
        text, kb = await media_screen(ctx)
        prefix = (
            f"🔍 Проверка: лишних файлов <b>{result['removed']}</b> · {format_bytes(result['bytes'])}. "
            "Ничего не удалено.\n\n"
        )
        await edit_q(q, prefix + text, kb)
        return

    if action == "media_clean":
        await edit_q(
            q,
            "🗑 <b>Удалить лишние фото?</b>\n\n"
            "Будут удалены только файлы старше 24 часов, на которые не ссылается база. "
            "Фото услуг, галереи и мастеров, которые используются, останутся.",
            Kb([
                [Btn("✅ Да, удалить", callback_data="adm:media_clean_ok")],
                [Btn("← Нет, назад", callback_data="adm:media")],
            ]),
        )
        return

    if action == "media_clean_ok":
        result = await cleanup_orphan_media(ctx, dry_run=False)
        text, kb = await media_screen(ctx)
        prefix = (
            f"✅ Удалено файлов: <b>{result['removed']}</b> · {format_bytes(result['bytes'])}.\n\n"
        )
        await edit_q(q, prefix + text, kb)
        return

    if action == "site_stats":
        ctx.flows.clear(uid)
        text, kb = await site_stats_screen(ctx)
        await edit_q(q, text, kb)
        return

    if action == "stat" and len(parts) >= 3:
        ctx.flows.clear(uid)
        await show_site_stat_detail(ctx, q, int(parts[2]))
        return

    if action == "stat_add":
        ctx.flows.set(uid, "stat_add_value", draft={})
        await edit_q(
            q,
            "➕ <b>Новое достижение</b>\n\n"
            "Шаг 1 из 3. Введите значение.\n\n"
            "Это может быть число: <b>50</b>, <b>3000</b>, <b>4.9</b> — "
            "или короткий текст: <b>ЗНАМЕНИТОСТИ</b>, <b>ТОП-1</b>.",
            cancel_row("adm:stat_add_cancel"),
        )
        return

    if action == "stat_add_plus":
        draft = ctx.flows.data(uid).get("draft", {})
        draft["plus"] = 0 if int(draft.get("plus") or 0) else 1
        ctx.flows.set(uid, "stat_add_save", draft=draft)
        await edit_q(q, stat_add_preview_text(draft), stat_add_preview_kb(draft))
        return

    if action == "stat_add_save":
        draft = ctx.flows.data(uid).get("draft", {})
        value = clean_text(draft.get("value", ""), 24)
        label = clean_text(draft.get("label", ""), 80)
        if not value or not label:
            await safe_answer(q, "Заполните достижение заново", show_alert=True)
            return
        await ctx.db.add_site_stat(
            value=value,
            label=label,
            plus=1 if draft.get("plus") else 0,
        )
        ctx.flows.clear(uid)
        text, kb = await site_stats_screen(ctx)
        await edit_q(q, "✅ Достижение добавлено.\n\n" + text, kb)
        return

    if action == "stat_add_cancel":
        ctx.flows.clear(uid)
        text, kb = await site_stats_screen(ctx)
        await edit_q(q, "Добавление отменено.\n\n" + text, kb)
        return

    if action == "stat_edit" and len(parts) >= 4:
        stat_id = int(parts[2])
        field = parts[3]
        item = await ctx.db.get_site_stat(stat_id)
        if not item:
            await safe_answer(q, "Достижение не найдено", show_alert=True)
            return
        labels = {
            "value": "значение (число или короткий текст)",
            "label": "подпись (можно использовать | для переноса строки)",
        }
        if field not in labels:
            await safe_answer(q, "Неизвестное поле", show_alert=True)
            return
        ctx.flows.set(uid, "stat_edit_value", stat_id=stat_id, field=field)
        current = stat_display_label(item.get(field, ""))
        await edit_q(
            q,
            f"✏️ <b>Изменить {labels[field]}</b>\n\n"
            f"Сейчас: <b>{esc(current)}</b>\n\n"
            "Введите новое значение.",
            cancel_row(f"adm:stat:{stat_id}"),
        )
        return

    if action == "stat_edit_save":
        data_now = ctx.flows.data(uid)
        stat_id = int(data_now.get("stat_id", 0))
        field = data_now.get("field", "")
        value = data_now.get("value")
        if field in {"value", "label"}:
            await ctx.db.update_site_stat(stat_id, **{field: value})
        ctx.flows.clear(uid)
        item = await ctx.db.get_site_stat(stat_id)
        if not item:
            text, kb = await site_stats_screen(ctx)
            await edit_q(q, "✅ Обновлено.\n\n" + text, kb)
            return
        await edit_q(q, "✅ Обновлено.\n\n" + site_stat_text(item), site_stat_kb(item))
        return

    if action == "stat_plus" and len(parts) >= 3:
        stat_id = int(parts[2])
        item = await ctx.db.get_site_stat(stat_id)
        if not item:
            await safe_answer(q, "Достижение не найдено", show_alert=True)
            return
        if not stat_is_numeric(item.get("value")):
            await safe_answer(q, "Плюсик доступен только для числа", show_alert=True)
            return
        await ctx.db.update_site_stat(
            stat_id,
            plus=0 if int(item.get("plus") or 0) else 1,
        )
        item = await ctx.db.get_site_stat(stat_id)
        if item:
            await edit_q(q, "✅ Обновлено.\n\n" + site_stat_text(item), site_stat_kb(item))
        return

    if action == "stat_del" and len(parts) >= 3:
        item = await ctx.db.get_site_stat(int(parts[2]))
        if not item:
            await safe_answer(q, "Достижение не найдено", show_alert=True)
            return
        plus = stat_plus_suffix(item.get("value"), item.get("plus"))
        await edit_q(
            q,
            "🗑 <b>Удалить достижение?</b>\n\n"
            f"<b>{esc(item.get('value'))}{plus}</b>\n"
            f"{esc(stat_display_label(item.get('label', '')))}\n\n"
            "Оно исчезнет с главной страницы.",
            Kb([
                [Btn("✅ Да, удалить", callback_data=f"adm:stat_delok:{item['id']}")],
                [Btn("← Нет, назад", callback_data=f"adm:stat:{item['id']}")],
            ]),
        )
        return

    if action == "stat_delok" and len(parts) >= 3:
        await ctx.db.delete_site_stat(int(parts[2]))
        ctx.flows.clear(uid)
        text, kb = await site_stats_screen(ctx)
        await edit_q(q, "✅ Достижение удалено.\n\n" + text, kb)
        return

    if action == "stats":
        ctx.flows.clear(uid)
        metrics = ctx.metrics or Metrics()
        snapshot = await metrics.snapshot(ctx)
        await edit_q(
            q,
            metrics_text(ctx, snapshot),
            Kb([[Btn("← В админ-панель", callback_data="adm:home")]]),
        )
        return

    if action == "settings":
        ctx.flows.clear(uid)
        text, kb = await settings_screen(ctx)
        await edit_q(q, text, kb)
        return

    if action == "set_toggle":
        settings = await ctx.db.get_settings()
        enabled = settings.get("booking_enabled", "1") == "1"
        await edit_q(
            q,
            "Выключить онлайн-запись?" if enabled else "Включить онлайн-запись?",
            Kb([
                [Btn("✅ Да", callback_data="adm:set_toggle_ok")],
                [Btn("← Нет, назад", callback_data="adm:settings")],
            ]),
        )
        return

    if action == "set_toggle_ok":
        settings = await ctx.db.get_settings()
        enabled = settings.get("booking_enabled", "1") == "1"
        await ctx.db.set_setting("booking_enabled", "0" if enabled else "1")
        text, kb = await settings_screen(ctx)
        await edit_q(q, ("Онлайн-запись выключена.\n\n" if enabled else "Онлайн-запись включена.\n\n") + text, kb)
        return

    if action == "set_step":
        await edit_q(
            q,
            "⏱ <b>Шаг слотов</b>\n\nВыберите интервал между доступными стартами:",
            Kb([
                [Btn("15 минут", callback_data="adm:set_step_pick:15"),
                 Btn("30 минут", callback_data="adm:set_step_pick:30"),
                 Btn("60 минут", callback_data="adm:set_step_pick:60")],
                [Btn("← Назад", callback_data="adm:settings")],
            ]),
        )
        return

    if action == "set_step_pick" and len(parts) >= 3:
        step = int_in_range(parts[2], 5, 120)
        if step is None:
            await safe_answer(q, "Некорректный шаг", show_alert=True)
            return
        await edit_q(
            q,
            f"Изменить шаг слотов на <b>{step} мин</b>?",
            Kb([
                [Btn("✅ Да", callback_data=f"adm:set_step_ok:{step}")],
                [Btn("← Нет, назад", callback_data="adm:settings")],
            ]),
        )
        return

    if action == "set_step_ok" and len(parts) >= 3:
        step = int_in_range(parts[2], 5, 120)
        if step is None:
            await safe_answer(q, "Некорректный шаг", show_alert=True)
            return
        await ctx.db.set_setting("slot_step", str(step))
        text, kb = await settings_screen(ctx)
        await edit_q(q, f"Шаг слотов: {step} мин.\n\n" + text, kb)
        return

    if action == "set_edit" and len(parts) >= 3:
        key = parts[2]
        if key not in SETTING_LABELS:
            await safe_answer(q, "Неизвестная настройка", show_alert=True)
            return
        settings = await ctx.db.get_settings()
        ctx.flows.set(uid, "set_value", key=key)
        await edit_q(
            q,
            f"⚙️ <b>{esc(SETTING_LABELS[key])}</b>\n\nСейчас: <b>{esc(settings.get(key, ''))}</b>\n\n"
            "Введите новое значение" + (" (ЧЧ:ММ)" if key != "reminder_minutes" else " в минутах") + ".",
            cancel_row("adm:settings"),
        )
        return

    if action == "set_save":
        data_now = ctx.flows.data(uid)
        key = data_now.get("key", "")
        value = data_now.get("value", "")
        if key:
            await ctx.db.set_setting(key, value)
        ctx.flows.clear(uid)
        text, kb = await settings_screen(ctx)
        await edit_q(q, "✅ Сохранено.\n\n" + text, kb)
        return

    await show_admin_home_q(ctx, q)


# ============================================================
