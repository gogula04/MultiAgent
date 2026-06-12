FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY templates ./templates
COPY docs ./docs
COPY tests ./tests

RUN pip install --no-cache-dir .

EXPOSE 8787

CMD ["verification-automation-web", "--host", "0.0.0.0", "--port", "8787", "--repo-root", "/app"]
