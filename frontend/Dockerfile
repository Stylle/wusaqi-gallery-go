# ---- 构建阶段 ----
FROM node:22-slim AS build
WORKDIR /app

# 依赖清单单独 COPY + npm ci（按 lockfile 精确安装，可复现且走缓存）
COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit

COPY . .
RUN npm run build

# ---- 运行阶段 ----
FROM nginx:1.27-slim
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
