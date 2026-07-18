# services/text_rewriter.py
import random
import logging
from config import CTA_PHRASES

logger = logging.getLogger(__name__)

TEMPLATES = [
    "🔥 <b>{title}</b>\n\n💰 {price_label}: {price} {currency}{discount_line}\n👉 {link}",
    "⚡️ {title}\n\n💵 {price_label}: {price} {currency}{discount_line}\n🚀 {link}",
    "🎉 {title}\n\n💸 {price_label}: {price} {currency}{discount_line}\n🔗 {link}",
    "✨ {title}\n\n💲 {price_label}: {price} {currency}{discount_line}\n📦 {link}",
    "🛍 <b>{title}</b>\n\n💳 Всего {price} {currency}{discount_line}\n📎 {link}",
    "🎁 {title}\n\n💵 {price} {currency}{discount_line}\n🔹 {link}",
    "📌 {title}\n\n💲 Стоимость: {price} {currency}{discount_line}\n🔸 {link}",
    "🔹 {title}\n\nЦена: {price} {currency}{discount_line}\n🔗 {link}",
]

PRICE_LABELS = ["Цена", "Стоимость", "Ценник", "Всего"]

def generate_post_text(title, price, currency, advertiser, erid, partner_url,
                       adult=False, old_price=None, discount_percent=None,
                       delivery_info="", promocode="", custom_template=None):
    if custom_template:
        template = custom_template
        # Формируем discount_line, delivery_line, promocode_line как раньше
        discount_line = ""
        if old_price and discount_percent:
            old_price_str = f"{int(old_price)}" if old_price == int(old_price) else f"{old_price:.2f}"
            discount_line = f"\n🔥 Скидка {discount_percent}% (было {old_price_str} {currency})"
        delivery_line = f"\n🚚 {delivery_info[:150]}" if delivery_info else ""
        promocode_line = f"\n🎟 Промокод: <code>{promocode}</code>" if promocode else ""
        price_str = f"{int(price)}" if price == int(price) else f"{price:.2f}"
        link_text = f"<a href='{partner_url}'>Посмотреть и заказать</a>"
        try:
            caption = template.format(
                title=title,
                price=price_str,
                currency=currency,
                advertiser=advertiser,
                erid=erid,
                partner_url=partner_url,
                link=link_text,
                old_price=old_price or "",
                discount_percent=discount_percent or 0,
                discount_line=discount_line,
                delivery_line=delivery_line,
                promocode_line=promocode_line,
                price_label="Цена",
                cta_phrase=""   # <-- ДОБАВИТЬ ЭТУ СТРОКУ
            )
        except KeyError as e:
            logger.warning(f"Custom template error: {e}, using default")
            custom_template = None

    if not custom_template:
        # Стандартная логика со случайным шаблоном
        template = random.choice(TEMPLATES)
        price_label = random.choice(PRICE_LABELS)
        if price == int(price):
            price_str = f"{int(price)}"
        else:
            price_str = f"{price:.2f}"
        discount_line = ""
        if old_price and discount_percent:
            old_price_str = f"{int(old_price)}" if old_price == int(old_price) else f"{old_price:.2f}"
            discount_line = f"\n🔥 Скидка {discount_percent}% (было {old_price_str} {currency})"
        link_text = f"<a href='{partner_url}'>Посмотреть и заказать</a>"
        caption = template.format(
            title=title,
            price_label=price_label,
            price=price_str,
            currency=currency,
            discount_line=discount_line,
            link=link_text
        )
        # Добавляем промокод с отступом
        if promocode:
            caption += f"\n\n🎟 Промокод: <code>{promocode}</code>"
        # Добавляем доставку с отступом
        if delivery_info:
            short_delivery = delivery_info[:150].rstrip()
            if len(delivery_info) > 150:
                short_delivery += '...'
            caption += f"\n\n🚚 {short_delivery}"
        # Рекламная метка с ERID (обязательно, компактно)
        # Делаем текст более компактным и менее визуально выделяющимся, но сохраняя видимость
        caption += f"\nРеклама: {advertiser} (ERID: {erid})"
        if adult:
            caption = "🔞 18+\n" + caption

    # Подстановка CTA-фразы, если в шаблоне есть {cta_phrase}
    if '{cta_phrase}' in caption and CTA_PHRASES:
        caption = caption.replace('{cta_phrase}', random.choice(CTA_PHRASES))
    elif '{cta_phrase}' in caption:
        caption = caption.replace('{cta_phrase}', '')  # если список пуст, убираем плейсхолдер
            
    if len(caption) > 1000:
        caption = caption[:1000] + '...'

    return caption
