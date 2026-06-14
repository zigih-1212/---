def is_video_processed(video_id: str) -> bool:
    conn = get_db()
    # Ищем в базе, был ли уже опубликован этот видео-ID
    row = conn.execute("SELECT 1 FROM posts WHERE donor_post_id=?", (video_id,)).fetchone()
    conn.close()
    return row is not None
