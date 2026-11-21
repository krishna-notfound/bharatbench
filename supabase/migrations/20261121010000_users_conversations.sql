-- f10: user profiles, conversations and messages (shared by voice and text). Not applied automatically.
-- Backend (service role) writes; authenticated users may read their own rows via RLS.

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  is_anonymous boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, display_name, is_anonymous)
  values (new.id, coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name'),
          coalesce(new.is_anonymous, false))
  on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users (id) on delete cascade,
  mode text not null check (mode in ('voice', 'text')),
  title text,
  created_at timestamptz not null default now()
);
create index if not exists conversations_user_created_idx on public.conversations (user_id, created_at desc);

create table if not exists public.messages (
  id bigint generated always as identity primary key,
  conversation_id uuid not null references public.conversations (id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'tool')),
  content text not null,
  interrupted boolean not null default false,
  meta jsonb,
  created_at timestamptz not null default now()
);
create index if not exists messages_conversation_created_idx on public.messages (conversation_id, created_at);

alter table public.profiles enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;

create policy profiles_select_own on public.profiles
  for select to authenticated using ((select auth.uid()) = id);
create policy profiles_update_own on public.profiles
  for update to authenticated using ((select auth.uid()) = id) with check ((select auth.uid()) = id);
create policy conversations_select_own on public.conversations
  for select to authenticated using ((select auth.uid()) = user_id);
create policy conversations_delete_own on public.conversations
  for delete to authenticated using ((select auth.uid()) = user_id);
create policy messages_select_own on public.messages
  for select to authenticated using (
    exists (select 1 from public.conversations c where c.id = conversation_id and c.user_id = (select auth.uid()))
  );
