# syntax=docker/dockerfile:1

# ---- build: compile the Vite app to static files ----
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.js ./
COPY src ./src

# Vite inlines these at build time. /api is same-origin, proxied by nginx below.
ARG VITE_API_BASE_URL=/api
ARG VITE_ENABLE_GUEST=false
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_ENABLE_GUEST=$VITE_ENABLE_GUEST
RUN npm run build

# ---- serve: nginx with just the built files ----
FROM nginx:1.27-alpine
# Rendered into conf.d at container start, from the variables below.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

# Defaults for local compose; a host overrides them (Railway sets PORT, and
# BACKEND_URL is configured per deployment).
ENV PORT=80 \
    BACKEND_URL=http://backend:8000 \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1
EXPOSE 80
