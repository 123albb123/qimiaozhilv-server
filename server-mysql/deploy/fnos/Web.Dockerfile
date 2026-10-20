FROM node:22.16.0-alpine3.22 AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM nginx:1.28-alpine
COPY --from=build /web/dist/ /usr/share/nginx/html/
COPY server-mysql/deploy/gm/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
