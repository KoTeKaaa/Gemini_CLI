begin;
insert into auth.users(id) values ('00000000-0000-0000-0000-000000000041'),
    ('00000000-0000-0000-0000-000000000042');
do $$ declare sid uuid; invite uuid; result uuid; begin
    insert into public.account_subscriptions(status, expires_at) values ('active', now() + interval '1 day')
        returning id into sid;
    invite := public.issue_subscription_invitation('00000000-0000-0000-0000-000000000041',
        sid, repeat('a',64), now() + interval '1 hour');
    perform public.issue_subscription_invitation('00000000-0000-0000-0000-000000000041',
        sid, repeat('b',64), now() + interval '1 hour');
    result := public.activate_subscription_invitation('00000000-0000-0000-0000-000000000041', repeat('a',64));
    if result is not null then raise exception 'revoked invitation activated'; end if;
    update public.subscription_invitations set expires_at = now() - interval '1 second'
        where token_hash = repeat('b',64);
    result := public.activate_subscription_invitation('00000000-0000-0000-0000-000000000041', repeat('b',64));
    if result is not null then raise exception 'expired invitation activated'; end if;
    update public.subscription_invitations set expires_at = now() + interval '1 hour'
        where token_hash = repeat('b',64);
    result := public.activate_subscription_invitation('00000000-0000-0000-0000-000000000041', repeat('b',64));
    if result is distinct from sid then raise exception 'activation failed'; end if;
    result := public.activate_subscription_invitation('00000000-0000-0000-0000-000000000041', repeat('b',64));
    if result is distinct from sid then raise exception 'retry failed'; end if;
    result := public.activate_subscription_invitation('00000000-0000-0000-0000-000000000042', repeat('b',64));
    if result is not null then raise exception 'recipient changed'; end if;
end $$;
rollback;
