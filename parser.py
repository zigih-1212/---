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
