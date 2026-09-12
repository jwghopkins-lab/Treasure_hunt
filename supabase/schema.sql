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

-- Added after the second walk: what happened on the camera screen, one row
-- per opening, so the pass lines and the stencils can be tuned on what
-- players actually saw rather than on what the audit predicts. The phone
-- posts it as the screen closes and never reads it back; the session reads
-- it through the connector. A row names its player and run, as the board's
-- rows do. `trace` is the smoothed score once a second, 0 to 99, the last
-- eight minutes of the opening, a blank for a second in which nothing was
-- evaluated (the camera not yet up, the page hidden). `dist_m` is how far
-- the phone was from where the photograph was taken, for a located stencil,
-- capped at a thousand kilometres, and no position is kept.
create table attempts (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null,
  hunt text not null check (length(hunt) between 1 and 40),
  stencil text not null check (length(stencil) between 1 and 40),
  name text check (length(name) between 1 and 24),
  outcome text not null check (outcome in ('match', 'skip', 'back')),
  line real check (line >= 0 and line <= 1),
  ms integer not null check (ms between 0 and 86400000),
  evals integer not null check (evals between 0 and 100000),
  peak real not null check (peak >= 0 and peak <= 1),
  peak_on real check (peak_on >= 0 and peak_on <= 100),
  peak_off real check (peak_off >= 0 and peak_off <= 100),
  peak_smooth real not null check (peak_smooth >= 0 and peak_smooth <= 1),
  last_smooth real check (last_smooth >= 0 and last_smooth <= 1),
  above_ms integer not null check (above_ms between 0 and 86400000),
  hinted boolean not null default false,
  work_px integer check (work_px in (240, 320)),
  eval_ms real check (eval_ms >= 0 and eval_ms <= 60000),
  frame text check (length(frame) <= 16),
  dist_m real check (dist_m >= 0 and dist_m <= 1000000),
  acc_m real check (acc_m >= 0 and acc_m <= 1000000),
  trace text check (length(trace) <= 2000),
  opened_at timestamptz not null,
  created_at timestamptz not null default now()
);
create index on attempts (hunt, stencil, opened_at);
alter table attempts enable row level security;
create policy "the phone may post an attempt" on attempts
  for insert to anon with check (true);
-- no select for anon: the rows say which stencils are weak and where people
-- stood, and only the session reads them.

-- What to ask it. Per stencil, how often an opening ended in a pass, the
-- typical best score and the typical time spent:
--   select hunt, stencil, count(*) as openings,
--          round(avg((outcome = 'match')::int), 2) as pass_rate,
--          round(percentile_cont(0.5) within group (order by peak)::numeric, 3) as peak_median,
--          round(percentile_cont(0.5) within group (order by ms) / 1000) as secs_median
--     from attempts group by 1, 2 order by 1, pass_rate, 2;
-- And the openings that ended in a back with a score near the line, which
-- are the ones a lower line would have passed:
--   select hunt, stencil, name, peak_smooth, above_ms, ms, trace
--     from attempts where outcome = 'back' and peak_smooth >= 0.15
--    order by opened_at;
