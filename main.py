# ─────────────────────────────────────────────
# GROQ API (бесплатно, vision)
# ─────────────────────────────────────────────
async def gemini_rewrite(
    client: httpx.AsyncClient,
    image_url: str | None,
    clean_donor_text: str,
    marketplace: str,
) -> str | None:
    """
    Отправляет в Groq картинку + текст, получает рерайт описания.
    Модель: llama-3.2-11b-vision-preview (бесплатная, vision).
    """
    import base64
    from config import GROQ_API_KEY

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

    content_parts = []

    # Картинка (если есть)
    if image_url:
        try:
            img_resp = await client.get(image_url, headers=HEADERS, timeout=20, follow_redirects=True)
            img_resp.raise_for_status()
            img_b64 = base64.b64encode(img_resp.content).decode()
            ct = img_resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{ct};base64,{img_b64}"}
            })
        except Exception as e:
            log.warning(f"Не удалось загрузить картинку для Groq ({image_url}): {e}")

    # Текст промпта
    full_prompt = prompt
    if clean_donor_text:
        full_prompt = f"Контекст из источника (для понимания товара):\n{clean_donor_text}\n\n{prompt}"
    content_parts.append({"type": "text", "text": full_prompt})

    # Настройки модели
    payload = {
        "model": "llama-3.2-11b-vision-preview",
        "messages": [{"role": "user", "content": content_parts}],
        "temperature": 0.8,
        "max_tokens": 1024,
    }

    # Заголовки авторизации
    groq_headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers=groq_headers,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text_out = data["choices"][0]["message"]["content"]
        return text_out.strip()
    except Exception as e:
        log.error(f"Ошибка Groq API: {e}")

    return None
