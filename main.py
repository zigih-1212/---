"""
Telegram-бот: граббер каналов + Gemini рерайтер + постинг в канал
Запуск: python bot.py
Деплой: Railway / VPS / локально
"""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

import httpx
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
# КОНФИГУРАЦИЯ
# ─────────────────────────────────────────────
from config import (
    BOT_TOKEN,
    TARGET_CHANNEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    DONOR_CHANNELS,
    RUN_INTERVAL_SECONDS,
    FIRST_RUN_POSTS_COUNT,
    CURSORS_FILE,
)

# ─────────────────────────────────────────────
# ЛОГИРОВАНИЕ
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# КОНСТАНТЫ
# ─────────────────────────────────────────────
MARKETPLACE_PATTERNS = [
    "wildberries", "wb.ru", "wb.link",
    "ozon.ru", "ozon.link", "ozon.by",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

# ─────────────────────────────────────────────
# ХРАНИЛИЩЕ КУРСОРОВ (LAST_ID)
# ─────────────────────────────────────────────
def load_cursors() -> dict:
    if Path(CURSORS_FILE).exists():
        with open(CURSORS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cursors(cursors: dict) -> None:
    with open(CURSORS_FILE, "w", encoding="utf-8") as f:
        json.dump(cursors, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# ПАРСИНГ HTML-КАНАЛА
# ─────────────────────────────────────────────
def extract_post_id(href: str, channel: str) -> int | None:
    """Извлекает числовой ID поста из href вида /channel/123 (case-insensitive)."""
    pattern = rf"/{re.escape(channel)}/(\d+)"
    m = re.search(pattern, href, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def extract_links_from_post(post_tag) -> list[str]:
    """Собирает все ссылки из поста."""
    links = []
    for a in post_tag.find_all("a", href=True):
        links.append(a["href"])
    # Также data-href у кнопок
    for el in post_tag.find_all(attrs={"data-href": True}):
        links.append(el["data-href"])
    return links


def resolve_redirect(url: str) -> str:
    """Если ссылка содержит redirectTo= — вытаскивает финальный URL."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in qs:
        if "redirect" in key.lower():
            val = qs[key][0]
            return unquote(val)
    return url


def is_marketplace_link(url: str) -> bool:
    u = url.lower()
    return any(p in u for p in MARKETPLACE_PATTERNS)


def find_marketplace_link(links: list[str]) -> str | None:
    """Находит первую ссылку на маркетплейс, раскрывая редиректы."""
    for raw in links:
        clean = resolve_redirect(raw)
        if is_marketplace_link(clean):
            return clean
        # Также проверяем исходную
        if is_marketplace_link(raw):
            return resolve_redirect(raw)
    return None


def detect_marketplace(url: str) -> str:
    u = url.lower()
    if any(p in u for p in ["wildberries", "wb.ru", "wb.link"]):
        return "wildberries"
    return "ozon"


def clean_text(text: str) -> str:
    """Убирает все http/https ссылки и упоминания доменов/каналов из текста."""
    # Удаляем URL
    text = re.sub(r"https?://\S+", "", text)
    # Удаляем @упоминания каналов
    text = re.sub(r"@\w+", "", text)
    # Удаляем t.me/что-угодно
    text = re.sub(r"t\.me/\S+", "", text)
    # Убираем множественные пробелы/переносы
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


async def fetch_channel_page(client: httpx.AsyncClient, channel: str) -> BeautifulSoup | None:
    url = f"https://t.me/s/{channel}"
    try:
        resp = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.error(f"[{channel}] Ошибка загрузки страницы канала: {e}")
        return None


async def fetch_post_image(client: httpx.AsyncClient, channel: str, post_id: int) -> str | None:
    """Парсит og:image из превью поста для HD-качества."""
    url = f"https://t.me/{channel}/{post_id}"
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            img_url = og["content"]
            # Заменяем _a.jpg на _w.jpg для максимального разрешения
            img_url = img_url.replace("_a.jpg", "_w.jpg")
            return img_url
    except Exception as e:
        log.warning(f"[{channel}/{post_id}] Не удалось получить og:image: {e}")
    return None


def parse_posts(soup: BeautifulSoup, channel: str) -> list[dict]:
    """
    Возвращает список постов в виде:
    [{"id": int, "text": str, "links": [str], "raw_tag": tag}, ...]
    """
    posts = []
    # Ищем блоки постов
    for msg in soup.find_all("div", class_=re.compile(r"tgme_widget_message\b", re.I)):
        # Ссылка на пост
        a_tag = msg.find("a", class_=re.compile(r"tgme_widget_message_date", re.I))
        if not a_tag:
            # fallback: ищем любую ссылку с /channel/id
            a_tag = msg.find("a", href=re.compile(rf"/{re.escape(channel)}/\d+", re.I))
        if not a_tag:
            continue

        href = a_tag.get("href", "")
        post_id = extract_post_id(href, channel)
        if not post_id:
            continue

        # Текст поста
        text_div = msg.find("div", class_=re.compile(r"tgme_widget_message_text", re.I))
        text = text_div.get_text("\n") if text_div else ""

        # Все ссылки в посте
        links = extract_links_from_post(msg)

        posts.append({
            "id": post_id,
            "text": text,
            "links": links,
            "raw_tag": msg,
        })

    return posts


# ─────────────────────────────────────────────
# GEMINI API
# ─────────────────────────────────────────────
async def gemini_rewrite(
    client: httpx.AsyncClient,
    image_url: str | None,
    clean_donor_text: str,
    marketplace: str,
) -> str | None:
    """
    Отправляет в Gemini картинку + текст, получает рерайт описания.
    Поддерживает multimodal (vision).
    """
    marketplace_name = "Wildberries" if marketplace == "wildberries" else "Ozon"
    prompt = (
        f"Внимательно посмотри на это изображение товара с {marketplace_name}. "
        "Твоя задача — написать абсолютно новое, уникальное, продающее описание для Telegram-канала, "
        "основываясь на том, ЧТО ТЫ ВИДИШЬ на фото. "
        "Сделай описание развернутым (минимум 3-4 предложения). "
        "Добавь классные эмодзи. "
        "СТРОЖАЙШЕ ЗАПРЕЩЕНО упоминать цены, скидки, артикулы или чужие ссылки. "
        "Ответь ТОЛЬКО готовым текстом нового описания на русском языке."
    )

    # Собираем parts для Gemini
    parts = []

    # Картинка (если есть)
    if image_url:
        try:
            img_resp = await client.get(image_url, headers=HEADERS, timeout=20, follow_redirects=True)
            img_resp.raise_for_status()
            import base64
            img_b64 = base64.b64encode(img_resp.content).decode()
            # Определяем mime
            ct = img_resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            parts.append({
                "inline_data": {
                    "mime_type": ct,
                    "data": img_b64,
                }
            })
        except Exception as e:
            log.warning(f"Не удалось загрузить картинку для Gemini ({image_url}): {e}")

    # Текст донора как контекст + промпт
    full_prompt = prompt
    if clean_donor_text:
        full_prompt = f"Контекст из источника (для понимания товара):\n{clean_donor_text}\n\n{prompt}"
    parts.append({"text": full_prompt})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 1024,
        },
    }

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )

    try:
        resp = await client.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates:
            content = candidates[0].get("content", {})
            parts_out = content.get("parts", [])
            text_out = " ".join(p.get("text", "") for p in parts_out if p.get("text"))
            return text_out.strip()
    except Exception as e:
        log.error(f"Ошибка Gemini API: {e}")

    return None


# ─────────────────────────────────────────────
# TELEGRAM API
# ─────────────────────────────────────────────
async def send_telegram_post(
    client: httpx.AsyncClient,
    text: str,
    image_url: str | None,
    button_label: str,
    button_url: str,
) -> bool:
    """
    Отправляет пост в TARGET_CHANNEL.
    Если есть картинка — sendPhoto с caption, иначе sendMessage.
    Кнопка крепится как InlineKeyboardButton.
    """
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    keyboard = {
        "inline_keyboard": [[{"text": button_label, "url": button_url}]]
    }

    # Telegram ограничивает caption до 1024 символов
    caption = text[:1024] if text else ""

    try:
        if image_url:
            payload = {
                "chat_id": TARGET_CHANNEL,
                "photo": image_url,
                "caption": caption,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard),
            }
            resp = await client.post(f"{base}/sendPhoto", json=payload, timeout=30)
        else:
            payload = {
                "chat_id": TARGET_CHANNEL,
                "text": text[:4096],
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard),
                "disable_web_page_preview": False,
            }
            resp = await client.post(f"{base}/sendMessage", json=payload, timeout=30)

        data = resp.json()
        if data.get("ok"):
            return True
        else:
            log.error(f"Telegram API error: {data}")
            return False

    except Exception as e:
        log.error(f"Ошибка отправки в Telegram: {e}")
        return False


# ─────────────────────────────────────────────
# ОСНОВНАЯ ЛОГИКА ОБРАБОТКИ ОДНОГО ДОНОРА
# ─────────────────────────────────────────────
async def process_donor(
    client: httpx.AsyncClient,
    channel: str,
    cursors: dict,
) -> None:
    log.info(f"[{channel}] Начинаю обработку...")

    soup = await fetch_channel_page(client, channel)
    if not soup:
        return

    all_posts = parse_posts(soup, channel)
    if not all_posts:
        log.info(f"[{channel}] Посты не найдены на странице.")
        return

    # Сортируем по ID (от старых к новым)
    all_posts.sort(key=lambda p: p["id"])

    last_id = cursors.get(channel, None)
    is_first_run = last_id is None

    # Фильтруем посты с маркетплейс-ссылками
    mp_posts = [p for p in all_posts if find_marketplace_link(p["links"])]

    if not mp_posts:
        log.info(f"[{channel}] Нет постов с ссылками на маркетплейсы.")
        # Всё равно фиксируем last_id если первый запуск
        if is_first_run and all_posts:
            new_last_id = all_posts[-1]["id"]
            cursors[channel] = new_last_id
            log.info(f"[{channel}] Первый запуск: LAST_ID = {new_last_id} (постов с маркетплейсами не было)")
        return

    # ── ПЕРВЫЙ ЗАПУСК ──
    if is_first_run:
        # Берём 5 самых свежих с маркетплейс-ссылками
        to_process = mp_posts[-FIRST_RUN_POSTS_COUNT:]
        # LAST_ID = самый новый пост на странице (не только среди mp_posts)
        new_last_id = all_posts[-1]["id"]
        log.info(f"[{channel}] Первый запуск: обрабатываю {len(to_process)} постов, LAST_ID будет {new_last_id}")
    else:
        # ── ПОСЛЕДУЮЩИЕ ЗАПУСКИ ──
        to_process = [p for p in mp_posts if p["id"] > last_id]
        if not to_process:
            log.info(f"[{channel}] Новых постов нет (LAST_ID={last_id})")
            return
        new_last_id = max(p["id"] for p in to_process)
        log.info(f"[{channel}] Новых постов: {len(to_process)}, новый LAST_ID будет {new_last_id}")

    # ── ОБРАБОТКА ПОСТОВ ──
    for post in to_process:
        pid = post["id"]
        log.info(f"[{channel}] Обрабатываю пост #{pid}")

        # Находим ссылку маркетплейса
        mp_link = find_marketplace_link(post["links"])
        if not mp_link:
            continue

        marketplace = detect_marketplace(mp_link)
        button_label = "ЗАБРАТЬ НА WILDBERRIES 🛍" if marketplace == "wildberries" else "ЗАБРАТЬ НА OZON 🛒"

        # Получаем HD-картинку
        image_url = await fetch_post_image(client, channel, pid)

        # Чистим текст донора
        donor_text = clean_text(post["text"])

        # Рерайт через Gemini
        rewritten = await gemini_rewrite(client, image_url, donor_text, marketplace)
        if not rewritten:
            log.warning(f"[{channel}] Gemini не вернул текст для поста #{pid}, пропускаю.")
            continue

        # Отправляем в канал
        success = await send_telegram_post(
            client=client,
            text=rewritten,
            image_url=image_url,
            button_label=button_label,
            button_url=mp_link,
        )

        if success:
            log.info(f"[{channel}] Пост #{pid} успешно опубликован ✅")
        else:
            log.warning(f"[{channel}] Пост #{pid} не удалось опубликовать ❌")

        # Пауза 35 сек для Gemini Free tier (2 req/min)
        await asyncio.sleep(35)

    # Обновляем курсор ПОСЛЕ успешной обработки
    cursors[channel] = new_last_id
    save_cursors(cursors)
    log.info(f"[{channel}] Курсор обновлён: LAST_ID = {new_last_id}")


# ─────────────────────────────────────────────
# ГЛАВНЫЙ ЦИКЛ
# ─────────────────────────────────────────────
async def run_once() -> None:
    """Один проход по всем донорам."""
    cursors = load_cursors()

    async with httpx.AsyncClient() as client:
        for channel in DONOR_CHANNELS:
            try:
                await process_donor(client, channel, cursors)
            except Exception as e:
                log.error(f"[{channel}] КРИТИЧЕСКАЯ ОШИБКА (канал пропущен): {e}", exc_info=True)

    log.info("Проход завершён.")


async def main() -> None:
    log.info("🤖 Бот запущен")
    log.info(f"Доноры: {DONOR_CHANNELS}")
    log.info(f"Интервал: {RUN_INTERVAL_SECONDS} сек.")

    while True:
        await run_once()
        log.info(f"💤 Следующий запуск через {RUN_INTERVAL_SECONDS} сек...")
        await asyncio.sleep(RUN_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
