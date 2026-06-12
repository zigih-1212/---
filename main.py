import asyncio
import logging
import os
import httpx
import json
import re
import urllib.parse
import random
from bs4 import BeautifulSoup

# КОНФИГ
TOKEN = "8800001861:AAGW0Qlgk3NRh5ruzrlI7OxZ4-LPmUT18ms"
CHANNEL = "@wb_skidochniki"
DONOR = "wb_skidkamam"
TAKPRODAM_ID = "36498e27-9209-4b9a-b85b-f4750ef56904"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

# Шаблоны для вариативности текста
TEMPLATES = [
    "🔥 <b>Находка дня!</b>\n\nСмотри, какой крутой товар я нашел. Идеальное сочетание цены и качества, которое точно тебе понравится. Успей забрать, пока всё не разобрали! 👇",
    "✨ <b>Твой идеальный выбор!</b>\n\nДавно искал что-то подобное? Этот товар — настоящий топ по отзывам. Очень рекомендую присмотреться, пока действует скидка. 😉",
    "🚀 <b>Хит продаж!</b>\n\nНе упусти возможность обновить свои покупки. Качественная вещь по приятной цене уже ждет тебя. Переходи по ссылке и оформляй заказ! 👇",
    "💎 <b>Топ-находка с маркетплейса!</b>\n\nСобрал для тебя всё самое лучшее. Отличный товар, который сделает твою жизнь чуточку комфортнее. Скорее переходи и забирай свой экземпляр!"
]

async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        log.info("Бот запущен и работает в стабильном режиме!")
        last_id = 0
        while True:
            try:
                resp = await client.get(f"https://t.me/s/{DONOR}")
                soup = BeautifulSoup(resp.text, 'html.parser')
                posts = soup.find_all('div', class
