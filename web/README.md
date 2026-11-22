# BharatBench web

Next.js 16 (App Router), React 19, TypeScript, Tailwind v4, shadcn/ui. Talks only to the API
(`NEXT_PUBLIC_API_URL`), never to Sarvam or the harness. Pages: `app/` (home, `/new`, `/runs`, `/chat`, `/login`,
`/onboarding`). Realtime voice client: `lib/realtime/`, `lib/audio/`. Types mirror `api/app/models.py` in `lib/types.ts`.

```bash
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_URL, NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY
npm run dev                  # http://localhost:3000
npm run lint && npx next typegen && npx tsc --noEmit && npm run build
```

There are no web unit tests; CI runs lint, tsc and build (`.github/workflows/ci-cd.yml`). Note `AGENTS.md` in this
folder: this Next.js version differs from older training data, read `node_modules/next/dist/docs/` before changing APIs.
