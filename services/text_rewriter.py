# services/text_rewriter.py
import random

TEMPLATES = [
    "🔥 <b>{title}</b>\n\n💰 {price_label}: {price} {currency}\n👉 {link}",
    "⚡️ {title}\n\n💵 {price_label}: {price} {currency}\n🚀 {link}",
    "🎉 {title}\n\n💸 {price_label}: {price} {currency}\n🔗 {link}",
    "✨ {title}\n\n💲 {price_label}: {price} {currency}\n📦 {link}",
    "🛍 <b>{title}</b>\n\n💳 Всего {price} {currency}\n📎 {link}",
    "🎁 {title}\n\n💵 {price} {currency}\n🔹 {link}",
    "📌 {title}\n\n💲 Стоимость: {price} {currency}\n🔸 {link}",
    "🔹 {title}\n\nЦена: {price} {currency}\n🔗 {link}",
]

PRICE_LABELS = ["Цена", "Стоимость", "Ценник", "Всего"]

def generate_post_text(title, price, currency, advertiser, erid, partner_url, adult=False):
    # Выбираем случайный шаблон
    template = random.choice(TEMPLATES)
    price_label = random.choice(PRICE_LABELS)

    # Округляем цену красиво
    if price == int(price):
        price_str = f"{int(price)}"
    else:
        price_str = f"{price:.2f}"

    link_text = f"<a href='{partner_url}'>Посмотреть и заказать</a>"
    caption = template.format(
        title=title,
        price_label=price_label,
        price=price_str,
        currency=currency,
        link=link_text
    )
    caption += f"\n\nРеклама. {advertiser}. Erid: {erid}"
    if adult:
        caption = "🔞 18+\n" + caption
    return caption
