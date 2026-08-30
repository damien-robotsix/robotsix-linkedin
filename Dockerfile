FROM python:3.11-slim AS base

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY src/ src/

EXPOSE 8000

CMD ["python", "-m", "linkedin_service"]
