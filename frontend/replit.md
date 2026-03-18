# Workspace

## Overview

pnpm workspace monorepo using TypeScript. Contains the Chat App frontend (React + Vite) and an Express API server.

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)
- **Frontend**: React + Vite + TanStack Query + Zustand + shadcn/ui + Tailwind CSS

## Structure

```text
artifacts-monorepo/
├── artifacts/              # Deployable applications
│   ├── api-server/         # Express API server (internal only, not chat backend)
│   └── chat-app/           # React + Vite chat frontend
├── lib/                    # Shared libraries
│   ├── api-spec/           # OpenAPI spec + Orval codegen config
│   ├── api-client-react/   # Generated React Query hooks
│   ├── api-zod/            # Generated Zod schemas from OpenAPI
│   └── db/                 # Drizzle ORM schema + DB connection
├── scripts/                # Utility scripts (single workspace package)
├── pnpm-workspace.yaml     # pnpm workspace
├── tsconfig.base.json      # Shared TS options
├── tsconfig.json           # Root TS project references
└── package.json            # Root package
```

## Chat App (`artifacts/chat-app`)

A production-ready Telegram/Slack-like chat application.

### Features
- Authentication: login, register, sessions management with auto token refresh
- Channel sidebar: My Channels + Discover tabs, search, unread badges, last message preview
- Real-time messaging via WebSocket with reconnect & exponential backoff
- Full messaging: infinite scroll upward, replies, reactions (add/remove), pins, edit/delete
- Channel management: roles (owner/admin/member), member management, invite links
- File uploads: POST /uploads → PUT to upload_url → include in message
- Sync: /v1/sync called on reconnect and tab focus
- Sessions page at /settings/sessions
- Invite acceptance at /invites/:token

### Architecture
- **State**: Zustand for auth (user, accessToken, isAuthenticated), React Query for all data
- **Auth tokens**: access_token in Zustand store (memory), refresh_token in localStorage
- **API client**: `src/lib/apiClient.ts` — auto-injects Bearer token, auto-refreshes on 401
- **WebSocket**: `src/hooks/use-websocket.tsx` — WSProvider wraps app, handles reconnect
- **Types**: `src/types/api.ts` — mirrors backend OpenAPI schemas

### Environment Variables
- `VITE_API_BASE_URL` — backend base URL (e.g., `http://localhost:8000`)
- REST: `${VITE_API_BASE_URL}/v1/...`
- WebSocket: `${VITE_API_BASE_URL.replace(/^http/, 'ws')}/v1/ws`

### Routing
- `/` — redirects based on auth state
- `/login`, `/register` — auth pages
- `/app` — main layout with sidebar (protected)
- `/app/channels/:channelId` — channel chat view
- `/settings/sessions` — session management
- `/invites/:token` — invite acceptance

### Running
```bash
# Install deps
pnpm install

# Start dev server (uses PORT env var set by Replit)
pnpm --filter @workspace/chat-app run dev

# Copy and fill out env
cp artifacts/chat-app/.env.example artifacts/chat-app/.env
```

## TypeScript & Composite Projects

Every package extends `tsconfig.base.json` which sets `composite: true`. The root `tsconfig.json` lists all packages as project references.

- **Always typecheck from the root** — run `pnpm run typecheck`
- **`emitDeclarationOnly`** — only emit `.d.ts` files during typecheck
- **Project references** — when package A depends on B, A's `tsconfig.json` must list B in `references`

## Root Scripts

- `pnpm run build` — runs `typecheck` first, then recursively runs `build` in all packages
- `pnpm run typecheck` — runs `tsc --build --emitDeclarationOnly` using project references

## Packages

### `artifacts/chat-app` (`@workspace/chat-app`)

React + Vite chat frontend. Connects to an external backend at `VITE_API_BASE_URL`.
- Entry: `src/main.tsx`
- App: `src/App.tsx` — Router + Providers (QueryClient, WSProvider, TooltipProvider)
- Pages: login, register, app-layout, channel-view, sessions, invite
- Components: AppSidebar, shadcn/ui components
- Hooks: use-auth, use-channels, use-messages, use-websocket
- Store: authStore (Zustand)
- API client: src/lib/apiClient.ts

### `artifacts/api-server` (`@workspace/api-server`)

Express 5 API server (workspace's own health check, not the external chat backend).

### `lib/api-spec` (`@workspace/api-spec`)

OpenAPI 3.1 spec covering all chat API endpoints. Run codegen: `pnpm --filter @workspace/api-spec run codegen`

### `lib/db` (`@workspace/db`)

Database layer using Drizzle ORM with PostgreSQL.
