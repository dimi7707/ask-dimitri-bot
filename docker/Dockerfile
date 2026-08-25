# Local development image: runs FastAPI under uvicorn with hot reload.
# The Lambda (production) image is docker/Dockerfile.lambda — it serves the same app
# through the Mangum handler instead.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Dependencies first so source edits don't invalidate the install layer. The venv lives outside
# /app because docker-compose bind-mounts the repo over /app for hot reload.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
