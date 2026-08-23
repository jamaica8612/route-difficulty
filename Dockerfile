FROM node:24-alpine AS build
LABEL org.opencontainers.image.source="https://github.com/jamaica8612/route-difficulty"
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.js eslint.config.js ./
COPY src ./src
COPY public ./public
ARG VITE_NAVER_MAP_CLIENT_ID=""
ENV VITE_NAVER_MAP_CLIENT_ID=$VITE_NAVER_MAP_CLIENT_ID
RUN npm run build

FROM nginx:stable-alpine
LABEL org.opencontainers.image.source="https://github.com/jamaica8612/route-difficulty"
COPY deploy/oracle/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
