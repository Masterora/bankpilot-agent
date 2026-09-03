# 文件职责：构建 BankPilot Web 的多阶段生产镜像。
# 主要内容：Node 阶段安装锁定依赖并构建 SPA，Nginx 阶段只接收静态产物。
# 关键边界：运行镜像不携带 Node 开发依赖，并使用非特权 Nginx 端口 8080。
FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
