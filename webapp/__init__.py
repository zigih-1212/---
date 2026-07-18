from fastapi import FastAPI
from webapp.routes_admin import router as admin_router
from webapp.routes_user import router as user_router
from webapp.routes_postback import router as postback_router

def create_app(bot) -> FastAPI:
    app = FastAPI()
    app.state.bot = bot
    app.include_router(admin_router, prefix="/admin", tags=["admin"])
    app.include_router(user_router, prefix="/my-stats", tags=["user"])
    app.include_router(postback_router, prefix="/postback", tags=["postback"])
    return app
