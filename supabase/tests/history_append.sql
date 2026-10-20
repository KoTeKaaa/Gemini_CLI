-- Disposable database only, after history_events.sql and history_append.sql.
begin;
insert into auth.users(id) values
    ('00000000-0000-0000-0000-000000000081'), ('00000000-0000-0000-0000-000000000082');
insert into public.chats(id,user_id,title) values
    ('00000000-0000-0000-0000-000000000081','00000000-0000-0000-0000-000000000081','append A'),
    ('00000000-0000-0000-0000-000000000082','00000000-0000-0000-0000-000000000082','append B');
set local role authenticated;
select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000081',true);
do $$ declare
    chat uuid := '00000000-0000-0000-0000-000000000081';
    req uuid := '00000000-0000-0000-0000-000000000083';
    batch jsonb := '[{"id":"00000000-0000-0000-0000-000000000084","role":"model","content":"call","name":"read_local_files","args":{"path":"fixture.txt"},"call_id":"call1","thought_signature":"c2ln","turn_id":"00000000-0000-0000-0000-000000000085","request_id":"00000000-0000-0000-0000-000000000083","event_index":0,"status":"running"}]';
begin
    if public.append_history_events(chat,batch) <> 1
       or public.append_history_events(chat,batch) <> 0
       or public.append_history_events(chat,jsonb_build_array((batch->0) - 'id')) <> 0 then
        raise exception 'append or exact replay failed';
    end if;
    if not exists (select 1 from public.messages where chat_id = chat and call_id = 'call1'
                   and thought_signature = 'c2ln' and args->>'path' = 'fixture.txt') then
        raise exception 'tool metadata lost';
    end if;
    begin
        perform public.append_history_events(chat,jsonb_set(batch,'{0,id}',
            '"00000000-0000-0000-0000-000000000088"'));
        raise exception 'mismatched event id accepted';
    exception when unique_violation then null; end;
    begin
        perform public.append_history_events(chat,jsonb_build_array(
            jsonb_build_object('role','user','content','rollback'),
            jsonb_set(batch->0,'{content}','"changed"')));
        raise exception 'mismatched replay accepted';
    exception when unique_violation then null; end;
    if exists (select 1 from public.messages where chat_id = chat and content = 'rollback') then
        raise exception 'partial batch committed';
    end if;
    if public.update_history_request_status(chat,req,'completed') <> 1
       or public.update_history_request_status(chat,req,'cancelled') <> 0 then
        raise exception 'terminal status overwritten';
    end if;
    if public.append_history_events(chat,batch) <> 0 or not exists
       (select 1 from public.messages where chat_id = chat and request_id = req and status = 'completed') then
        raise exception 'running replay changed finalized event';
    end if;
    batch := jsonb_set(jsonb_set(batch,'{0,id}','"00000000-0000-0000-0000-000000000086"'),
                       '{0,request_id}','"00000000-0000-0000-0000-000000000087"');
    perform public.append_history_events(chat,batch);
    if public.update_history_request_status(chat,'00000000-0000-0000-0000-000000000087','cancelled') <> 1
       or public.update_history_request_status(chat,'00000000-0000-0000-0000-000000000087','completed') <> 0 then
        raise exception 'cancelled status overwritten';
    end if;
    if public.append_history_events(chat,batch) <> 0 or not exists
       (select 1 from public.messages where chat_id = chat
        and request_id = '00000000-0000-0000-0000-000000000087' and status = 'cancelled') then
        raise exception 'running replay changed cancelled event';
    end if;
    perform public.append_history_events(chat,'[{"role":"user","content":"legacy"}]');
    perform public.update_history_request_status(chat,req,'failed');
    if not exists (select 1 from public.messages where chat_id = chat and status = 'legacy') then
        raise exception 'legacy status changed';
    end if;
    begin
        perform public.append_history_events('00000000-0000-0000-0000-000000000082',batch);
        raise exception 'foreign append allowed';
    exception when insufficient_privilege then null; end;
    begin
        perform public.update_history_request_status('00000000-0000-0000-0000-000000000082',req,'failed');
        raise exception 'foreign finalize allowed';
    exception when insufficient_privilege then null; end;
end $$;
set local role anon;
select set_config('request.jwt.claim.sub','',true);
do $$ begin
    begin
        perform public.append_history_events('00000000-0000-0000-0000-000000000081','[]');
        raise exception 'anonymous append RPC allowed';
    exception when insufficient_privilege then null; end;
    begin
        perform public.update_history_request_status('00000000-0000-0000-0000-000000000081',
            '00000000-0000-0000-0000-000000000083','completed');
        raise exception 'anonymous finalize RPC allowed';
    exception when insufficient_privilege then null; end;
end $$;
rollback;
