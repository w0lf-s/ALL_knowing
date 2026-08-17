create table if not exists companies (
  key text primary key,
  query text,
  ticker text,
  name text,
  dossier jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists workspace (
  id int primary key default 1,
  bookmarks jsonb not null default '[]'::jsonb,
  leads jsonb not null default '[]'::jsonb,
  linkedin jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists source_cache (
  source text not null,
  cache_key text not null,
  data jsonb,
  fetched_at timestamptz not null default now(),
  primary key (source, cache_key)
);

create table if not exists news_days (
  company_key text not null,
  day date not null,
  data jsonb not null,
  primary key (company_key, day)
);

create table if not exists bookmarks (
  company_key text primary key,
  created_at timestamptz not null default now()
);

create table if not exists people (
  key text primary key,
  linkedin_url text,
  name text,
  company text,
  email text,
  phone text,
  emails jsonb not null default '[]'::jsonb,
  phones jsonb not null default '[]'::jsonb,
  sources jsonb not null default '[]'::jsonb,
  profile jsonb,
  updated_at timestamptz not null default now()
);

alter table companies enable row level security;
alter table bookmarks enable row level security;
alter table people enable row level security;
alter table workspace enable row level security;
alter table source_cache enable row level security;
alter table news_days enable row level security;

drop policy if exists bookmarks_all on bookmarks;
drop policy if exists people_all on people;
drop policy if exists companies_all on companies;
drop policy if exists workspace_all on workspace;
drop policy if exists source_cache_all on source_cache;
drop policy if exists news_days_all on news_days;

create policy bookmarks_all on bookmarks for all using (true) with check (true);
create policy people_all on people for all using (true) with check (true);
create policy companies_all on companies for all using (true) with check (true);
create policy workspace_all on workspace for all using (true) with check (true);
create policy source_cache_all on source_cache for all using (true) with check (true);
create policy news_days_all on news_days for all using (true) with check (true);
