-- The leaderboard and the capture drop, on Supabase (handoff section 12).
-- Applied through the connector with apply_migration; kept here so the
-- policies can be read without a login. Anyone with the anon key can insert
-- a row; the checks bound what a row can be, and that is the whole of the
-- protection, which is right for a game among friends.

create table completions (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null unique,
  hunt text not null check (length(hunt) between 1 and 40),
  name text not null check (length(name) between 1 and 24),
  ms integer not null check (ms between 1000 and 86400000),
  created_at timestamptz not null default now()
);
create index on completions (hunt, ms);
alter table completions enable row level security;
create policy "anyone may post a completion" on completions
  for insert to anon with check (true);
create policy "anyone may read the board" on completions
  for select to anon using (true);

create table captures (
  id uuid primary key default gen_random_uuid(),
  hunt text not null check (length(hunt) between 1 and 40),
  path text not null,
  clue text check (length(clue) <= 200),
  lat double precision, lon double precision, accuracy double precision,
  taken_at timestamptz not null default now()
);
alter table captures enable row level security;
create policy "the capture page may post" on captures
  for insert to anon with check (true);
-- no select for anon: the rows say where the answers are, and only the
-- session reads them, through the connector.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values ('captures', 'captures', true, 8000000, '{image/jpeg}');
create policy "the capture page may upload" on storage.objects
  for insert to anon with check (bucket_id = 'captures');
-- public read, unguessable names: the path carries sixteen random hex
-- characters, and nothing lists the bucket.
