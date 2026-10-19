begin;
insert into auth.users(id) values ('00000000-0000-0000-0000-000000000031');
do $$ declare row jsonb; conflict jsonb; values_json jsonb; begin
    values_json := '{"user_id":null,"status":"active","expires_at":"2099-01-01T00:00:00Z",
        "models":["fixture"],"features":[],"request_limit":10,"window_seconds":3600,"parallel_limit":1}';
    row := public.manage_subscription('00000000-0000-0000-0000-000000000031', null, null, values_json);
    if row->>'rights_version' <> '1' then raise exception 'creation failed'; end if;
    row := public.manage_subscription('00000000-0000-0000-0000-000000000031',
        (row->>'id')::uuid, 1, values_json || '{"status":"revoked"}');
    if row->>'rights_version' <> '2' or row->>'status' <> 'revoked' then
        raise exception 'update failed'; end if;
    conflict := public.manage_subscription('00000000-0000-0000-0000-000000000031',
        (row->>'id')::uuid, 1, values_json);
    if conflict is not null then raise exception 'version conflict bypass'; end if;
    if (select count(*) from public.subscription_audit where subscription_id = (row->>'id')::uuid) <> 2 then
        raise exception 'audit failed'; end if;
end $$;
rollback;
