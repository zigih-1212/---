from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from webapp.routes_admin import router as admin_router
from webapp.routes_user import router as user_router
from webapp.routes_postback import router as postback_router
from webapp.routes_advertiser import router as advertiser_router

def _token_error_page(status: int, detail: str) -> HTMLResponse:
    messages = {
        401: ("Ссылка истекла", "Вернитесь в бота и нажмите «Статистика» заново, чтобы получить новую ссылку."),
        404: ("Ссылка недействительна", "Проверьте, что вы скопировали полную ссылку из бота."),
    }
    title, desc = messages.get(status, ("Ошибка", detail))
    html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{title}</title>
    <style>body{{background:#1a1a2e;color:#fff;font-family:sans-serif;display:flex;justify-content:center;
    align-items:center;min-height:100vh;margin:0;}}
    .box{{text-align:center;padding:40px;max-width:400px;}}
    h1{{font-size:2em;margin-bottom:10px;}} p{{color:#aaa;font-size:1.1em;}}
    a{{color:#ff4444;text-decoration:none;font-weight:bold;}}</style></head>
    <body><div class="box"><h1>{title}</h1><p>{desc}</p><p style="margin-top:20px;"><a href="https://t.me/bot_username">Открыть бота</a></p></div></body></html>"""
    return HTMLResponse(content=html, status_code=status)

def create_app(bot) -> FastAPI:
    app = FastAPI()
    app.state.bot = bot
    app.include_router(admin_router, prefix="/admin", tags=["admin"])
    app.include_router(user_router, prefix="/my-stats", tags=["user"])
    app.include_router(postback_router, tags=["postback"])
    app.include_router(advertiser_router, prefix="/advertiser", tags=["advertiser"])

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        from fastapi.exceptions import HTTPException
        if isinstance(exc, HTTPException) and exc.status_code in (401, 404):
            detail = getattr(exc, "detail", "Error")
            if detail in ("Token expired", "Token not found"):
                return _token_error_page(exc.status_code, detail)
        return HTMLResponse(content="<h1>Ошибка сервера</h1>", status_code=500)

    return app
