FROM node:22-alpine AS build
WORKDIR /app
ARG VITE_DEMO=false
ENV VITE_DEMO=$VITE_DEMO
COPY frontend/package.json ./
# 首次 npm install 后生成 lockfile；后续应提交 lockfile 并改用 npm ci。
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:stable-alpine
COPY --from=build /app/dist/ /usr/share/nginx/html/
COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
