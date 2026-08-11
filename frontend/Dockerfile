FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./

RUN --mount=type=cache,id=npm-cache,target=/root/.npm \
    npm config set fetch-retries 10 && \
    npm config set fetch-retry-factor 2 && \
    npm config set fetch-retry-mintimeout 10000 && \
    npm config set fetch-retry-maxtimeout 120000 && \
    npm ci --no-audit --no-fund

COPY . .

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/v1
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV PORT=3000
ENV BASE_PATH=/

RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN addgroup -S -g 10001 messaging && adduser -S -u 10001 -G messaging messaging

COPY --from=build --chown=messaging:messaging /app/.next/standalone ./
COPY --from=build --chown=messaging:messaging /app/.next/static ./.next/static
COPY --from=build --chown=messaging:messaging /app/public ./public
RUN mkdir -p /app/.next/cache && chown -R messaging:messaging /app/.next

EXPOSE 3000

USER messaging

CMD ["node", "server.js"]
