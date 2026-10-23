# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend-build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

FROM --platform=$BUILDPLATFORM golang:1.27-bookworm AS server-build
ARG TARGETOS
ARG TARGETARCH
WORKDIR /src
COPY server/go.mod server/go.sum ./
RUN go mod download
COPY server/ ./
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -ldflags="-s -w" -o /gallery .

# Python exists only for one-shot Pillow jobs. No Python web server, nginx,
# supervisor, or idle image worker is started in the running container.
FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/image_worker.py ./image_worker.py
COPY --from=server-build /gallery /app/gallery
COPY --from=frontend-build /src/dist /app/web
ENV DATA_DIR=/data WEB_DIR=/app/web IMAGE_WORKER=/app/image_worker.py \
    PYTHON=python LISTEN_ADDR=:80 GOMEMLIMIT=40MiB GOGC=50 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["/app/gallery", "healthcheck"]
ENTRYPOINT ["/app/gallery"]
