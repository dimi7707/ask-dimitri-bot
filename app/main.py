from fastapi import FastAPI
from mangum import Mangum

from app.api.routes import health

app = FastAPI(title="AskDimitri Backend")
app.include_router(health.router)

handler = Mangum(app)
