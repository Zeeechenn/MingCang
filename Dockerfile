FROM python:3.11-slim AS backend

WORKDIR /app

# 方案 B（pyproject 单一真理源）：需要 backend/ 存在才能 install，
# 改 backend 代码会让本层缓存失效（多 ~30s 重装依赖）；后续可用 uv 加速到 < 5s
COPY pyproject.toml README.md ./
COPY backend/ ./backend/
RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app

# 非 root 运行：创建有家目录的用户，家目录承载 ~/.mingcang 运行时数据
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Frontend build stage ──────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ── Final image with nginx serving frontend ───────────────────────────────────
FROM nginx:alpine AS frontend

COPY --from=frontend-build /app/frontend/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
