# webapp/dependencies.py
from fastapi import Request
from services.db import get_db

async def get_bot(request: Request):
    return request.app.state.bot
  
