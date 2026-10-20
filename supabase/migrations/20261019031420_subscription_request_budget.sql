begin;
create table public.subscription_requests (
    subscription_id uuid not null references public.account_subscriptions(id) on delete cascade,
    request_id uuid not null,
    operation text not null check (operation in ('gemini', 'web_search')),
    reserved_at timestamptz not null default clock_timestamp(),
    primary key (subscription_id, request_id)
);
create index subscription_requests_window_idx
    on public.subscription_requests(subscription_id, reserved_at);
alter table public.subscription_requests enable row level security;
revoke all on public.subscription_requests from public, anon, authenticated;
grant all on public.subscription_requests to service_role;

-- The subscription lock serializes budget checks and administrator changes.
-- Reservations are never refunded: timeout/crash may have consumed provider quota.
create function public.reserve_subscription_request(
    account_id uuid, call_id uuid, operation_name text, model_id text, required_features text[]
) returns text language plpgsql security definer set search_path = '' as $$
declare
    rights public.account_subscriptions;
    window_start timestamptz;
    request_time timestamptz;
    used bigint;
begin
    select * into rights from public.account_subscriptions
        where user_id = account_id for update;
    request_time := clock_timestamp();
    if not found or rights.status <> 'active' or rights.expires_at <= request_time then
        return 'denied';
    end if;
    if (model_id is not null and not model_id = any(rights.models))
        or required_features is null or not required_features <@ rights.features then return 'denied'; end if;
    if exists(select 1 from public.subscription_requests
        where subscription_id = rights.id and request_id = call_id) then
        return 'duplicate';
    end if;
    window_start := to_timestamp(floor(extract(epoch from request_time) /
                                     rights.window_seconds) * rights.window_seconds);
    select count(*) into used from public.subscription_requests
        where subscription_id = rights.id and reserved_at >= window_start;
    if used >= rights.request_limit then return 'exhausted'; end if;
    insert into public.subscription_requests(subscription_id, request_id, operation)
        values (rights.id, call_id, operation_name);
    return 'reserved';
end;
$$;
revoke all on function public.reserve_subscription_request(uuid, uuid, text, text, text[])
    from public, anon, authenticated;
grant execute on function public.reserve_subscription_request(uuid, uuid, text, text, text[])
    to service_role;
commit;
