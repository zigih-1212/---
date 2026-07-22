import logging
import hashlib
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from services.db import get_db

logger = logging.getLogger("autopost_bot.advertiser")

router = APIRouter()

PAGE = '''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{name} — Статистика</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#e6edf3;padding:20px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px;margin-bottom:16px}}
h1{{font-size:1.5em}}
.stat{{font-size:2em;font-weight:700;color:#58a6ff}}
.stat-label{{color:#8b949e;font-size:0.85em}}
table{{width:100%;border-collapse:collapse;margin-top:12px}}
th{{text-align:left;padding:8px;border-bottom:2px solid #30363d;color:#8b949e;font-size:0.85em}}
td{{padding:8px;border-bottom:1px solid #21262d}}
.link{{color:#58a6ff;text-decoration:none}}
.link:hover{{text-decoration:underline}}
.muted{{color:#8b949e;font-size:0.9em}}
</style>
</head>
<body>
<div class="card">
<div class="muted">Статистика CPC-кампании</div>
<h1>{name}</h1>
<div style="margin-top:16px;display:flex;gap:32px;flex-wrap:wrap">
<div><div class="stat">{total_posts}</div><div class="stat-label">Всего публикаций</div></div>
<div><div class="stat">{total_users}</div><div class="stat-label">Пользователей</div></div>
<div><div class="stat">{total_clicks}</div><div class="stat-label">Кликов (все каналы)</div></div>
</div>
</div>
<div class="card">
<h2 style="font-size:1.1em;margin-bottom:12px">&#128202; По каналам</h2>
{channels_table}
</div>
<div class="card">
<h2 style="font-size:1.1em;margin-bottom:12px">&#128196; Последние публикации</h2>
{recent_posts}
</div>
</body>
</html>'''

CHANNEL_ROW = '<tr><td>{title}</td><td>{posts}</td><td>{clicks}</td></tr>'
POST_ROW = '<div style="padding:8px 0;border-bottom:1px solid #21262d"><a class="link" href="{link}" target="_blank">{channel}</a><span class="muted" style="float:right">{date}</span></div>'
EMPTY = '<div class="muted">Нет данных</div>'


def _advertiser_token(campaign_id: int) -> str:
    return hashlib.md5(f"adv_cpc_{campaign_id}_salt24".encode()).hexdigest()[:16]


def _find_campaign_by_token(token: str) -> int:
    conn = get_db()
    try:
        rows = conn.execute("SELECT campaign_id FROM cpc_campaigns").fetchall()
    finally:
        conn.close()
    for r in rows:
        if _advertiser_token(r["campaign_id"]) == token:
            return r["campaign_id"]
    return 0


@router.get("/campaign/{token}", response_class=HTMLResponse)
async def advertiser_campaign_page(token: str):
    campaign_id = _find_campaign_by_token(token)
    if not campaign_id:
        return HTMLResponse("<h1>Кампания не найдена</h1>", status_code=404)

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT name FROM cpc_campaigns WHERE campaign_id=? LIMIT 1",
            (campaign_id,)
        ).fetchone()
        if not campaign:
            return HTMLResponse("<h1>Кампания не найдена</h1>", status_code=404)

        name = campaign["name"]

        total_posts = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE donor_post_id LIKE ? AND status='published'",
            (f"cpc_{campaign_id}_%",)
        ).fetchone()[0] or 0

        total_users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM cpc_campaigns WHERE campaign_id=?",
            (campaign_id,)
        ).fetchone()[0] or 0

        channel_rows = conn.execute("""
            SELECT c.channel_title, c.channel_id, COUNT(p.id) as posts
            FROM posts p
            JOIN channels c ON c.channel_id = p.channel_id AND c.user_id = p.user_id
            WHERE p.donor_post_id LIKE ? AND p.status='published'
            GROUP BY c.channel_id
            ORDER BY posts DESC
        """, (f"cpc_{campaign_id}_%",)).fetchall()

        channels_buf = []
        for r in channel_rows:
            sub = conn.execute(
                "SELECT sub_id FROM channels WHERE channel_id=? LIMIT 1",
                (r["channel_id"],)
            ).fetchone()
            sub_id = sub[0] if sub else ""
            ch_clicks = conn.execute(
                "SELECT COALESCE(clicks_count,0) FROM subid_stats WHERE subid1=?",
                (sub_id,)
            ).fetchone()
            channels_buf.append({
                "title": r["channel_title"] or r["channel_id"],
                "posts": r["posts"],
                "clicks": ch_clicks[0] if ch_clicks else 0,
            })

        total_clicks = sum(ch["clicks"] for ch in channels_buf)

        recent = conn.execute("""
            SELECT p.channel_id, p.published_at
            FROM posts p
            WHERE p.donor_post_id LIKE ? AND p.status='published'
            ORDER BY p.published_at DESC LIMIT 10
        """, (f"cpc_{campaign_id}_%",)).fetchall()

        recent_buf = []
        for r in recent:
            ch_title = conn.execute(
                "SELECT channel_title FROM channels WHERE channel_id=? LIMIT 1",
                (r["channel_id"],)
            ).fetchone()
            recent_buf.append({
                "channel": ch_title[0] if ch_title else r["channel_id"],
                "link": f"https://t.me/{r['channel_id'].lstrip('@')}",
                "date": r["published_at"][:10] if r["published_at"] else "",
            })

    finally:
        conn.close()

    ch_rows = "".join(
        CHANNEL_ROW.format(title=ch["title"], posts=ch["posts"], clicks=ch["clicks"])
        for ch in channels_buf
    ) if channels_buf else EMPTY

    if ch_rows != EMPTY:
        channels_table = '<table><thead><tr><th>Канал</th><th>Публикаций</th><th>Кликов</th></tr></thead><tbody>' + ch_rows + '</tbody></table>'
    else:
        channels_table = EMPTY

    posts_html = "".join(
        POST_ROW.format(link=p["link"], channel=p["channel"], date=p["date"])
        for p in recent_buf
    ) if recent_buf else EMPTY

    html = PAGE.format(
        name=name,
        total_posts=total_posts,
        total_users=total_users,
        total_clicks=total_clicks,
        channels_table=channels_table,
        recent_posts=posts_html,
    )

    return HTMLResponse(content=html)
