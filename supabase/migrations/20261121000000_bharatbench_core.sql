-- BharatBench core tables (mirror of api/app/storage/sqlite.py; JSON payloads are pydantic models from api/app/models.py).
-- RLS enabled with no policies: only the API (service role key, server-side) can read/write.
-- user_id is nullable until Supabase Auth is wired in.

create table if not exists public.runs (
  id text primary key,
  user_id uuid references auth.users (id) on delete set null,
  apk_path text not null,
  status text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null default now(),
  data jsonb not null
);
create index if not exists runs_created_at_idx on public.runs (created_at desc);
create index if not exists runs_user_id_idx on public.runs (user_id);

create table if not exists public.findings (
  ord bigint generated always as identity primary key,
  id text not null,
  run_id text not null references public.runs (id) on delete cascade,
  score real,
  data jsonb not null
);
create index if not exists findings_run_id_idx on public.findings (run_id);

create table if not exists public.events (
  run_id text not null references public.runs (id) on delete cascade,
  seq integer not null,
  ts timestamptz not null,
  type text not null,
  data jsonb not null,
  primary key (run_id, seq)
);

alter table public.runs enable row level security;
alter table public.findings enable row level security;
alter table public.events enable row level security;
