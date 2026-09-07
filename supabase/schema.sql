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

-- Added after the first hunt was walked: who is where, so the board can be
-- read before anybody has finished. One row per run, upserted by the phone as
-- stencils pass (POST with Prefer: resolution=merge-duplicates). The
-- completions table keeps the finishing times; this keeps the live state.
create table progress (
  run_id uuid primary key,
  hunt text not null check (length(hunt) between 1 and 40),
  name text not null check (length(name) between 1 and 24),
  done integer not null check (done between 0 and 100),
  total integer not null check (total between 1 and 100),
  ms integer check (ms between 0 and 86400000),
  updated_at timestamptz not null default now()
);
create index on progress (hunt, done desc, ms);
alter table progress enable row level security;
create policy "anyone may post progress" on progress
  for insert to anon with check (true);
-- A run is identified by a uuid made on the phone, so an update is only ever
-- of a row whose id the phone already knows: guessing one is the whole of
-- what it would take, and the checks bound what a row can say.
create policy "anyone may move their run on" on progress
  for update to anon using (true) with check (true);
create policy "anyone may read the board" on progress
  for select to anon using (true);
