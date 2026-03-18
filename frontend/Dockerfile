FROM node:22-alpine AS build
WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json tsconfig.base.json .npmrc ./
COPY artifacts/chat-app/package.json artifacts/chat-app/vite.config.ts artifacts/chat-app/tsconfig.json artifacts/chat-app/index.html ./artifacts/chat-app/
COPY lib/api-client-react/package.json lib/api-client-react/tsconfig.json ./lib/api-client-react/
COPY lib/api-zod/package.json lib/api-zod/tsconfig.json ./lib/api-zod/
COPY lib/api-spec/package.json lib/api-spec/orval.config.ts lib/api-spec/openapi.yaml ./lib/api-spec/

RUN pnpm install --frozen-lockfile

COPY . .

ARG VITE_API_BASE_URL=/v1
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV PORT=3000
ENV BASE_PATH=/

RUN pnpm build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/artifacts/chat-app/dist/public /usr/share/nginx/html

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
