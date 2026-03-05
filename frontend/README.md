# Frontend (Next.js App Router)

## Requirements
- Node.js 20+
- Backend running with API at `/v1`

## Setup
1. Copy env file:
   - `cp .env.example .env.local` (or create `.env.local` on Windows)
2. Set `NEXT_PUBLIC_API_BASE_URL` (example: `http://localhost:8000`)
3. Install dependencies:
   - `npm install`
4. Run dev server:
   - `npm run dev`

## Routes
- `/login`
- `/register`
- `/app`
- `/app/channels/[channel_id]`
- `/settings/sessions`
- `/invites/[token]`

## Notes
- REST base path is always `${NEXT_PUBLIC_API_BASE_URL}/v1`.
- WebSocket URL is derived from the same variable and connects to `/v1/ws`.
- Access token is in-memory, refresh token is persisted in localStorage.
- On startup and reconnect, client runs `/v1/sync` to catch up.

