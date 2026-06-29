create table if not exists public.license_admins (
    user_id uuid primary key references auth.users(id) on delete cascade,
    created_at timestamptz not null default now()
);

create table if not exists public.pro_licenses (
    id uuid primary key default gen_random_uuid(),
    code_hash text not null unique,
    customer_email text not null,
    status text not null default 'active' check (status in ('active', 'revoked')),
    max_activations integer not null default 3 check (max_activations > 0),
    created_at timestamptz not null default now(),
    created_by uuid references auth.users(id) on delete set null
);

create table if not exists public.license_activations (
    id uuid primary key default gen_random_uuid(),
    license_id uuid not null references public.pro_licenses(id) on delete cascade,
    device_hash text not null,
    token_hash text not null,
    created_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    unique (license_id, device_hash)
);

alter table public.license_admins enable row level security;
alter table public.pro_licenses enable row level security;
alter table public.license_activations enable row level security;

-- No client policies are intentional. Only the service-role Edge Functions can
-- read or mutate licensing records.

