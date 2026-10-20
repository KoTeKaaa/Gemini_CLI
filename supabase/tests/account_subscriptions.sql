-- Run in an isolated Supabase preview database after migration; rolls back fixtures.
begin;
insert into auth.users(id) values
    ('00000000-0000-0000-0000-000000000001'),
    ('00000000-0000-0000-0000-000000000002');
insert into public.account_subscriptions(user_id, status, expires_at) values
    ('00000000-0000-0000-0000-000000000001', 'active', now() + interval '1 day'),
    ('00000000-0000-0000-0000-000000000002', 'active', now() + interval '1 day');
update public.account_subscriptions set request_limit = 10;
do $$ begin
    if exists (select 1 from public.account_subscriptions where rights_version <> 2) then
        raise exception 'rights version not incremented';
    end if;
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', true);
do $$ begin
    if (select count(*) from public.account_subscriptions) <> 1
       or exists (select 1 from public.account_subscriptions where user_id <> auth.uid()) then
        raise exception 'user A isolation failed';
    end if;
    begin
        update public.account_subscriptions set status = 'active';
        raise exception 'self update allowed';
    exception when insufficient_privilege then null; end;
    begin
        insert into public.account_subscriptions(expires_at) values (now());
        raise exception 'self insert allowed';
    exception when insufficient_privilege then null; end;
    begin
        delete from public.account_subscriptions;
        raise exception 'self delete allowed';
    exception when insufficient_privilege then null; end;
    begin
        select token_hash from public.subscription_invitations;
        raise exception 'invitation readable';
    exception when insufficient_privilege then null; end;
end $$;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', true);
do $$ begin
    if (select count(*) from public.account_subscriptions) <> 1
       or exists (select 1 from public.account_subscriptions where user_id <> auth.uid()) then
        raise exception 'user B isolation failed';
    end if;
end $$;
set local role anon;
do $$ begin
    begin
        select id from public.account_subscriptions;
        raise exception 'anonymous read allowed';
    exception when insufficient_privilege then null; end;
end $$;
rollback;
