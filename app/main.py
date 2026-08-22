from fastapi import FastAPI
from mangum import Mangum

app = FastAPI(title="AskDimitri Backend")

handler = Mangum(app)
