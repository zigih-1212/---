def is_video_processed(video_id: str) -> bool:
    conn = get_db()
    # Ищем в базе, был ли уже опубликован этот видео-ID
    row = conn.execute("SELECT 1 FROM posts WHERE donor_post_id=?", (video_id,)).fetchone()
    conn.close()
    return row is not None
def get_video_full_details(video_url: str):
    """Извлекает полную информацию, включая описание, для обработки."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            # Получаем все данные (включая описание)
            info = ydl.extract_info(video_url, download=False)
            return info
        except Exception as e:
            logger.error(f"Ошибка при получении деталей видео: {e}")
            return None
async def get_product_data(sku: str, sub_id: str) -> dict:
    """
    Запрашивает данные товара и формирует партнерскую ссылку с хвостом блогера.
    """
    url = "https://api.takprodam.ru/v1/products/info"
    # Ваш Master Token для доступа к API
    headers = {"Authorization": f"Bearer {TAKPRODAM_MASTER_TOKEN}"}
    
    async with httpx.AsyncClient() as client:
        try:
            # Запрашиваем данные по артикулу
            resp = await client.get(url, params={"sku": sku}, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                
                # Добавляем sub_id (хвостик блогера) к ссылке товара
                # Предполагаем, что API возвращает base_link
                original_link = data.get("link", "")
                
                # Формируем партнерскую ссылку с меткой
                # Логика добавления хвоста зависит от структуры ваших ссылок
                affiliate_link = f"{original_link}?sub_id={sub_id}"
                
                return {
                    "erid": data.get("erid"),
                    "advertiser": data.get("advertiser"),
                    "link": affiliate_link,
                    "price": data.get("price"),
                    "discount": data.get("discount")
                }
        except Exception as e:
            logger.error(f"Ошибка API ТакПродам: {e}")
    
    # Если товар не найден или ошибка API — возвращаем None
    return None
