-- Isolated preview database only. Run after S4.1 migration; fixtures roll back.
begin;
insert into auth.users(id) values
    ('00000000-0000-0000-0000-000000000041'),
    ('00000000-0000-0000-0000-000000000042');
insert into public.chats(id,user_id,title) values
    ('00000000-0000-0000-0000-000000000051', '00000000-0000-0000-0000-000000000041', 'history A'),
    ('00000000-0000-0000-0000-000000000052', '00000000-0000-0000-0000-000000000042', 'history B');
insert into public.messages(chat_id,role,content) values
    ('00000000-0000-0000-0000-000000000052', 'user', 'own B');
set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000041', true);
-- Legacy insert shape remains valid; the server assigns event ID and order.
insert into public.messages(chat_id,role,content) values
    ('00000000-0000-0000-0000-000000000051', 'user', 'same prompt');
insert into public.messages(chat_id,role,content,turn_id,request_id,event_index,status) values
    ('00000000-0000-0000-0000-000000000051', 'user', 'same prompt',
     '00000000-0000-0000-0000-000000000061', '00000000-0000-0000-0000-000000000071', 0, 'completed');
do $$ declare changed integer; begin
    if (select count(*) from public.messages where chat_id = '00000000-0000-0000-0000-000000000051') <> 2
       or not exists (select 1 from public.messages where chat_id = '00000000-0000-0000-0000-000000000051'
                      and status = 'legacy' and request_id is null and sequence > 0 and id is not null) then
        raise exception 'legacy insert or independent event identity failed';
    end if;
    if exists (select 1 from public.chats where id = '00000000-0000-0000-0000-000000000052')
       or exists (select 1 from public.messages where chat_id = '00000000-0000-0000-0000-000000000052') then
        raise exception 'foreign rows visible to A';
    end if;
    begin
        insert into public.messages(chat_id,role,content,request_id,event_index) values
            ('00000000-0000-0000-0000-000000000051', 'user', 'duplicate',
             '00000000-0000-0000-0000-000000000071', 0);
        raise exception 'duplicate request ordinal accepted';
    exception when unique_violation then null; end;
    begin
        insert into public.messages(chat_id,role,content) values
            ('00000000-0000-0000-0000-000000000052', 'user', 'forbidden');
        raise exception 'foreign insert allowed to A';
    exception when insufficient_privilege then null; end;
    update public.messages set content = 'forbidden'
        where chat_id = '00000000-0000-0000-0000-000000000052';
    get diagnostics changed = row_count;
    if changed <> 0 then
        raise exception 'foreign update allowed to A';
    end if;
end $$;
-- A direct table owner cannot forge another user's fork parent or summary.
set constraints all immediate;
do $$ begin
    begin
        insert into public.chats(user_id,title,fork_parent_id) values
            (auth.uid(), 'forbidden fork', '00000000-0000-0000-0000-000000000052');
        raise exception 'foreign fork parent accepted';
    exception when foreign_key_violation then null; end;
    begin
        update public.chats set summary = 'forbidden', summary_boundary =
            (select id from public.messages where chat_id = '00000000-0000-0000-0000-000000000051' limit 1)
            where id = '00000000-0000-0000-0000-000000000052';
        -- No foreign chat can be changed, even with an own-message boundary.
        if found then raise exception 'foreign summary update allowed'; end if;
    end;
end $$;
insert into public.chats(id,user_id,title,fork_parent_id,fork_boundary) values
    ('00000000-0000-0000-0000-000000000053', '00000000-0000-0000-0000-000000000041', 'fork A',
     '00000000-0000-0000-0000-000000000051',
     (select id from public.messages where chat_id = '00000000-0000-0000-0000-000000000051' order by sequence desc limit 1));
do $$ begin
    begin
        update public.chats set summary = 'wrong chat', summary_boundary =
            (select id from public.messages where chat_id = '00000000-0000-0000-0000-000000000051' limit 1)
            where id = '00000000-0000-0000-0000-000000000053';
        raise exception 'cross-chat summary boundary accepted';
    exception when foreign_key_violation then null; end;
end $$;
delete from public.chats where id = '00000000-0000-0000-0000-000000000051';
do $$ begin
    if not exists (select 1 from public.chats where id = '00000000-0000-0000-0000-000000000053'
                   and fork_parent_id is null) then
        raise exception 'source deletion removed fork or owner';
    end if;
end $$;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000042', true);
do $$ begin
    if exists (select 1 from public.messages where chat_id = '00000000-0000-0000-0000-000000000051')
       or not exists (select 1 from public.messages where chat_id = '00000000-0000-0000-0000-000000000052') then
        raise exception 'user B isolation failed';
    end if;
    begin
        insert into public.messages(chat_id,role,content) values
            ('00000000-0000-0000-0000-000000000051', 'tool', 'forbidden');
        raise exception 'foreign insert allowed to B';
    exception when insufficient_privilege then null; end;
end $$;
set local role anon;
select set_config('request.jwt.claim.sub', '', true);
do $$ begin
    begin
        perform id from public.messages;
        raise exception 'anonymous read permission remains';
    exception when insufficient_privilege then null; end;
    begin
        insert into public.messages(chat_id,role,content) values
            ('00000000-0000-0000-0000-000000000051', 'user', 'forbidden');
        raise exception 'anonymous insert allowed';
    exception when insufficient_privilege then null; end;
end $$;
rollback;
