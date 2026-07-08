from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from webapp.routes_admin import router as admin_router
from webapp.routes_user import router as user_router

def create_app(bot) -> FastAPI:
    app = FastAPI()
    app.state.bot = bot

    app.include_router(admin_router, prefix="/admin", tags=["admin"])
    app.include_router(user_router, prefix="/my-stats", tags=["user"])

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return HTMLResponse(
            content=f"<h2>Страница не найдена</h2><p>Вы пытались открыть: {request.url.path}</p>",
            status_code=404
        )

    return app
