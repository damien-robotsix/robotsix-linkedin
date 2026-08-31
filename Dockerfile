FROM python:3.14-slim AS base

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir "robotsix-config @ git+https://github.com/damien-robotsix/robotsix-config@b68476fa9aab58f70697d870da956220ecf9cf48" \
    && pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "-m", "linkedin_service"]
