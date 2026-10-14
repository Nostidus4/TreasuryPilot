FROM node:22.22.0-alpine AS build
WORKDIR /app

RUN apk add --no-cache python3 make g++ \
    && corepack enable \
    && corepack prepare pnpm@9.15.9 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY contracts/package.json contracts/package.json
RUN pnpm install --frozen-lockfile --filter @treasurypilot/web...

COPY apps/web apps/web
ARG VITE_API_URL=/api
ARG VITE_CHAIN_ID=31337
ARG VITE_RPC_URL=http://localhost:8545
ARG VITE_SENTRY_DSN=
ENV VITE_API_URL=$VITE_API_URL \
    VITE_CHAIN_ID=$VITE_CHAIN_ID \
    VITE_RPC_URL=$VITE_RPC_URL \
    VITE_SENTRY_DSN=$VITE_SENTRY_DSN
RUN pnpm --filter @treasurypilot/web build

FROM nginx:1.27.4-alpine
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/web/dist /usr/share/nginx/html
EXPOSE 80
