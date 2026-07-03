create table if not exists public.release_metadata (
    channel text primary key,
    version text not null,
    download_url text not null,
    sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    virustotal_url text not null,
    file_size_bytes bigint not null check (file_size_bytes > 0),
    published_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.release_metadata enable row level security;

-- No client policies are intentional. The public website reads through the
-- release-metadata Edge Function, and only that function's service role can
-- update the current release.

insert into public.release_metadata (
    channel,
    version,
    download_url,
    sha256,
    virustotal_url,
    file_size_bytes
) values (
    'windows-stable',
    '1.0.3',
    'https://github.com/Gendire123/E2DM2-Releases/releases/download/v1.0.3/E2DM2-Setup-1.0.3.exe',
    '8cc4c886d0f07bd752dcc8b41c0bebc43c04cdd8898fce6e207139d1b9eac19c',
    'https://www.virustotal.com/gui/file/8cc4c886d0f07bd752dcc8b41c0bebc43c04cdd8898fce6e207139d1b9eac19c',
    445873859
) on conflict (channel) do nothing;
