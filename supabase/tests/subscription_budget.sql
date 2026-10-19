begin;
insert into auth.users(id) values ('00000000-0000-0000-0000-000000000011');
insert into public.account_subscriptions(user_id, status, expires_at, models, request_limit)
    values ('00000000-0000-0000-0000-000000000011', 'active', now() + interval '1 day', '{fixture}', 1);
do $$ declare result text; begin
    result := public.reserve_subscription_request('00000000-0000-0000-0000-000000000011',
        '00000000-0000-0000-0000-000000000021', 'gemini', 'fixture', '{}');
    if result <> 'reserved' then raise exception 'reservation failed: %', result; end if;
    result := public.reserve_subscription_request('00000000-0000-0000-0000-000000000011',
        '00000000-0000-0000-0000-000000000021', 'gemini', 'fixture', '{}');
    if result <> 'duplicate' then raise exception 'idempotency failed'; end if;
    result := public.reserve_subscription_request('00000000-0000-0000-0000-000000000011',
        '00000000-0000-0000-0000-000000000022', 'gemini', 'fixture', '{}');
    if result <> 'exhausted' then raise exception 'budget bypass'; end if;
    update public.subscription_requests set reserved_at = now() - interval '32 days';
    result := public.reserve_subscription_request('00000000-0000-0000-0000-000000000011',
        '00000000-0000-0000-0000-000000000022', 'gemini', 'fixture', '{}');
    if result <> 'reserved' then raise exception 'window failed'; end if;
    update public.account_subscriptions set status = 'revoked';
    result := public.reserve_subscription_request('00000000-0000-0000-0000-000000000011',
        '00000000-0000-0000-0000-000000000023', 'gemini', 'fixture', '{}');
    if result <> 'denied' then raise exception 'revocation bypass'; end if;
end $$;
rollback;
