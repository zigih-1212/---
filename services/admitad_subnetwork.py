# services/admitad_subnetwork.py
import time
import re
import logging
import base64
import httpx
from typing import Optional, Dict
from services.db import get_db
from config import ADMITAD_CLIENT_ID, ADMITAD_CLIENT_SECRET

logger = logging.getLogger("autopost_bot.admitad_subnetwork")

TOKEN_URL = "https://api.admitad.com/token/"
SUBNETWORK_WEBSITES_URL = "https://api.admitad.com/subnetworks/v1/websites/create/"
SUBNETWORK_STATUSES_URL = "https://api.admitad.com/subnetworks/v1/advcampaign/{advcampaign_id}/statuses/"


def _get_basic_auth_header() -> str:
    creds = f"{ADMITAD_CLIENT_ID}:{ADMITAD_CLIENT_SECRET}"
    encoded = base64.b64encode(creds.encode()).decode()
    return f"Basic {encoded}"


def _get_token_from_db() -> Optional[Dict]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT access_token, expires_at FROM admitad_tokens ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"access_token": row["access_token"], "expires_at": row["expires_at"]}


def _save_token_to_db(access_token: str, expires_at: float):
    conn = get_db()
    try:
        conn.execute("DELETE FROM admitad_tokens")
        conn.execute(
            "INSERT INTO admitad_tokens (access_token, expires_at) VALUES (?, ?)",
            (access_token, expires_at)
        )
        conn.commit()
    finally:
        conn.close()


async def get_access_token() -> Optional[str]:
    cached = _get_token_from_db()
    if cached and cached["expires_at"] > time.time() + 300:
        return cached["access_token"]

    logger.info("🔑 Запрашиваем новый OAuth access_token от Admitad...")
    auth_header = _get_basic_auth_header()
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(
                TOKEN_URL,
                headers={"Authorization": auth_header},
                data={
                    "grant_type": "client_credentials",
                    "scope": "advcampaigns manage_websites advcampaigns_for_website"
                }
            )
            if resp.status_code != 200:
                logger.error(f"❌ OAuth error {resp.status_code}: {resp.text[:300]}")
                return cached["access_token"] if cached else None
            data = resp.json()
            token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            _save_token_to_db(token, time.time() + expires_in)
            logger.info("✅ OAuth access_token получен")
            return token
        except Exception as e:
            logger.error(f"❌ OAuth exception: {e}")
            return cached["access_token"] if cached else None


async def create_subnetwork_website(
    name: str,
    url: str,
    region: list[str] = None,
    category: list[int] = None,
    native_kind: str = "social_network_other"
) -> Optional[Dict]:
    token = await get_access_token()
    if not token:
        logger.error("❌ Нет access_token для создания подплощадки")
        return None

    payload = {
        "name": name[:200],
        "native_kind": native_kind,
        "url": url[:255],
    }
    if region:
        payload["region"] = region
    if category:
        payload["category"] = category

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(
                SUBNETWORK_WEBSITES_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=[payload]
            )
            data = resp.json()
            if resp.status_code == 200 and "0" in data:
                website = data["0"]
                logger.info(f"✅ Подплощадка создана: id={website.get('id')}, name={name}")
                return website
            else:
                logger.error(f"❌ Ошибка создания подплощадки: {resp.status_code} {data}")
                return None
        except Exception as e:
            logger.error(f"❌ Исключение при создании подплощадки: {e}")
            return None


async def get_website_connection_status(advcampaign_id: int, website_ids: list[int]) -> list:
    token = await get_access_token()
    if not token:
        return []

    ids_str = ",".join(str(wid) for wid in website_ids[:30])
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(
                SUBNETWORK_STATUSES_URL.format(advcampaign_id=advcampaign_id),
                headers={"Authorization": f"Bearer {token}"},
                params={"websites_id": ids_str}
            )
            if resp.status_code == 200:
                return resp.json()
            logger.error(f"❌ Status check error {resp.status_code}: {resp.text[:200]}")
            return []
        except Exception as e:
            logger.error(f"❌ Status check exception: {e}")
            return []


async def register_channel_as_website(channel_id: str, channel_name: str) -> Optional[int]:
    clean_name = channel_name.lstrip("@") or channel_id.lstrip("@")
    # Удаляем недопустимые символы из имени и URL
    safe_name = re.sub(r'[^\w\s\-]', '', clean_name)[:180]
    url_clean = re.sub(r'[^\w\-]', '', clean_name)
    url = f"https://t.me/{url_clean}" if url_clean else f"https://t.me/channel_{channel_id}"

    result = await create_subnetwork_website(
        name=f"TG - {safe_name}",
        url=url,
        region=["RU"],
        native_kind="social_network_other"
    )
    if result and result.get("id"):
        website_id = result["id"]
        conn = get_db()
        try:
            conn.execute(
                "UPDATE channels SET admitad_website_id = ? WHERE channel_id = ?",
                (website_id, channel_id)
            )
            conn.commit()
        finally:
            conn.close()
        return website_id
    return None


async def backfill_existing_channels():
    """Регистрирует подплощадки для всех каналов без admitad_website_id."""
    conn = get_db()
    try:
        channels = conn.execute(
            "SELECT channel_id, channel_title FROM channels WHERE admitad_website_id IS NULL"
        ).fetchall()
    finally:
        conn.close()

    if not channels:
        logger.info("✅ Все каналы уже имеют admitad_website_id")
        return

    logger.info(f"🔄 Бэктейл: найдено {len(channels)} каналов без подплощадки")
    registered = 0
    failed = 0
    for ch in channels:
        ch_id = ch["channel_id"]
        ch_name = ch["channel_title"] or ch_id
        website_id = await register_channel_as_website(ch_id, ch_name)
        if website_id:
            registered += 1
            logger.info(f"  ✅ {ch_id} → website_id={website_id}")
        else:
            failed += 1
            logger.warning(f"  ❌ {ch_id} — не удалось зарегистрировать")

    logger.info(f"📊 Бэктейл завершён: {registered} создано, {failed} ошибок")


# =============================================================================
# Получение подключенных рекламных кампаний для площадки
# =============================================================================
async def get_website_campaigns(website_id: int) -> list:
    """Возвращает список рекламодателей, подключенных к площадке."""
    token = await get_access_token()
    if not token:
        return []

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(
                f"https://api.admitad.com/advcampaigns/website/{website_id}/",
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": 200}
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("results", [])
            logger.error(f"❌ get_website_campaigns error {resp.status_code}: {resp.text[:200]}")
            return []
        except Exception as e:
            logger.error(f"❌ get_website_campaigns exception: {e}")
            return []


async def search_all_cpc_campaigns(query: str = "", limit: int = 50) -> list:
    """Поиск по всем рекламодателям Admitad, возвращает только с CPC-ставками."""
    token = await get_access_token()
    if not token:
        return []

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            params = {"limit": limit, "region": "RU"}
            if query:
                params["q"] = query
            resp = await client.get(
                "https://api.admitad.com/advcampaigns/",
                headers={"Authorization": f"Bearer {token}"},
                params=params
            )
            if resp.status_code != 200:
                logger.error(f"❌ search_all error {resp.status_code}: {resp.text[:200]}")
                return []
            data = resp.json()
            results = data.get("results", [])
            # Оставляем только тех, у кого есть CPC-действие
            cpc_campaigns = []
            for c in results:
                actions = c.get("actions", [])
                has_cpc = any("клик" in (a.get("name", "") or "").lower() for a in actions)
                if has_cpc:
                    cpc_campaigns.append(c)
            return cpc_campaigns
        except Exception as e:
            logger.error(f"❌ search_all_cpc exception: {e}")
            return []
