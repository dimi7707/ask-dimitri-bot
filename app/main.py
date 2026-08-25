from fastapi import FastAPI
from mangum import Mangum

from app.api.routes import chat, health

app = FastAPI(title="AskDimitri Backend")
app.include_router(health.router)
app.include_router(chat.router)

handler = Mangum(app)
