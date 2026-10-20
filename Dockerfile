FROM python:3.15-alpine AS build
WORKDIR /src
COPY build.py oracle-free-server.py agent-prompt.md ./
COPY web web
RUN python build.py

FROM caddy:2-alpine
COPY container/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/site /srv
