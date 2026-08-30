FROM python:3.11-slim AS base

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "-m", "linkedin_service"]
