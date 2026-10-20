-- Additive migration: existing chat/auth tables are unchanged.
begin;

create table public.account_subscriptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid unique references auth.users(id) on delete cascade,
    status text not null default 'suspended'
        check (status in ('active', 'suspended', 'revoked')),
    expires_at timestamptz not null,
    models text[] not null default '{}'
        check (cardinality(models) between 0 and 32 and array_position(models, null) is null),
    features text[] not null default '{}'
        check (cardinality(features) between 0 and 64 and array_position(features, null) is null),
    request_limit integer not null default 0 check (request_limit between 0 and 1000000),
    window_seconds integer not null default 86400 check (window_seconds between 60 and 2678400),
    parallel_limit integer not null default 1 check (parallel_limit between 1 and 8),
    rights_version bigint not null default 1 check (rights_version > 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table public.subscription_invitations (
    id uuid primary key default gen_random_uuid(),
    subscription_id uuid not null references public.account_subscriptions(id) on delete cascade,
    token_hash text not null unique check (token_hash ~ '^[0-9a-f]{64}$'),
    expires_at timestamptz not null,
    revoked_at timestamptz,
    activated_at timestamptz,
    activated_by uuid references auth.users(id) on delete cascade,
    created_at timestamptz not null default now(),
    check ((activated_at is null) = (activated_by is null))
);
create index subscription_invitations_subscription_idx
    on public.subscription_invitations(subscription_id);
create index subscription_invitations_recipient_idx
    on public.subscription_invitations(activated_by);

create function public.bump_subscription_rights_version()
returns trigger language plpgsql set search_path = '' as $$
begin
    new.rights_version := old.rights_version + 1;
    new.updated_at := clock_timestamp();
    return new;
end;
$$;
revoke all on function public.bump_subscription_rights_version() from public, anon, authenticated;
create trigger subscription_rights_version before update on public.account_subscriptions
    for each row execute function public.bump_subscription_rights_version();

alter table public.account_subscriptions enable row level security;
alter table public.subscription_invitations enable row level security;
revoke all on public.account_subscriptions, public.subscription_invitations from public, anon, authenticated;
grant select on public.account_subscriptions to authenticated;
grant all on public.account_subscriptions, public.subscription_invitations to service_role;
create policy own_subscription on public.account_subscriptions for select to authenticated
    using ((select auth.uid()) = user_id);

commit;
