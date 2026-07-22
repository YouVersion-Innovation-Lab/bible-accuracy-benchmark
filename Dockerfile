# Stage 1: build the React SPA
FROM node:22-alpine AS frontend-builder
WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci --silent
COPY web/ ./
RUN npm run build

# Stage 2: Python API serving /api/* + the built SPA
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[api]"

COPY config/ ./config/
COPY dataset/ ./dataset/
COPY --from=frontend-builder /app/web/dist ./web/dist

ENV PORT=8080
ENV WEB_DIST=/app/web/dist
EXPOSE 8080
# create_app() is a factory; results come from BENCH_RESULTS_BUCKET (set at deploy)
CMD ["sh", "-c", "uvicorn bible_bench.api.app:create_app --factory --host 0.0.0.0 --port ${PORT} --workers 2"]
