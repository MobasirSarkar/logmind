FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy package manifests
COPY pyproject.toml README.md ./

# Install dependencies in production mode
RUN uv sync --no-dev

# Copy source code and gunicorn configuration
COPY app ./app
COPY gunicorn_conf.py ./

EXPOSE 8000

CMD ["uv", "run", "gunicorn", "-c", "gunicorn_conf.py", "app.main:app"]
