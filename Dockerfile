# ============================================================
# wusaqi-gallery 单容器镜像：nginx（静态+反代+图片缓存）
#                            + uvicorn（FastAPI）同容器运行
# 多阶段：node 编译前端 → python 运行时
# ============================================================

# ---- 阶段 1：构建前端 ----
FROM node:22-slim AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# ---- 阶段 2：运行时 ----
FROM python:3.13-slim

WORKDIR /app

# 系统依赖：nginx；进程管理：supervisor（pip 装省一层 apt 源）
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default \
    && pip install --no-cache-dir supervisor

# 后端依赖单独 COPY，利用构建缓存
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend-build /app/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/supervisord.conf /etc/supervisor/conf.d/wusaqi.conf

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 80
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/wusaqi.conf"]
