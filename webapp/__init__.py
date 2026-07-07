# webapp/__init__.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from webapp.routes_admin import router as admin_router
from webapp.routes_user import router as user_router

def create_app(bot) -> FastAPI:
    app = FastAPI()
    app.state.bot = bot

    # Подключаем статику (CSS)
    app.mount("/static", StaticFiles(directory="webapp/static"), name="static")

    # Регистрируем роутеры
    app.include_router(admin_router, prefix="/admin", tags=["admin"])
    app.include_router(user_router, prefix="/my-stats", tags=["user"])

    return app
