# services/text_rewriter.py
import random

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
                       delivery_info="", promocode=""):
    template = random.choice(TEMPLATES)
    price_label = random.choice(PRICE_LABELS)
    price_str = f"{int(price)}" if price == int(price) else f"{price:.2f}"

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

    if promocode:
        caption += f"\n🎟 Промокод: <code>{promocode}</code>"

    if delivery_info:
        caption += f"\n🚚 {delivery_info}"

    caption += f"\n\nРеклама. {advertiser}. Erid: {erid}"
    if adult:
        caption = "🔞 18+\n" + caption
    return caption
