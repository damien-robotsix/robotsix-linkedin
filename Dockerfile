FROM python:3.14-slim AS base

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml ./
COPY chat-skill.md ./
COPY src/ src/

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && pip install --no-cache-dir "robotsix-config @ git+https://github.com/damien-robotsix/robotsix-config@b68476fa9aab58f70697d870da956220ecf9cf48" \
    && pip install --no-cache-dir "robotsix-http @ git+https://github.com/damien-robotsix/robotsix-http@0dfb8eccd60942cdcb401d78f054e388a9c84a9b" \
    && pip install --no-cache-dir . \
    && apt-get purge -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

CMD ["python", "-m", "linkedin_service"]
