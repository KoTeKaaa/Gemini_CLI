-- Disposable PostgreSQL only; all fixture rows roll back.
begin;
insert into auth.users(id) values
    ('00000000-0000-0000-0000-000000000101'),('00000000-0000-0000-0000-000000000102');
insert into public.chats(id,user_id,title) values
    ('00000000-0000-0000-0000-000000000111','00000000-0000-0000-0000-000000000101','boundary A'),
    ('00000000-0000-0000-0000-000000000112','00000000-0000-0000-0000-000000000102','boundary B');
set local role authenticated;
select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000101',true);
do $$ declare
    chat uuid := '00000000-0000-0000-0000-000000000111';
    first_end uuid := '00000000-0000-0000-0000-000000000124';
    second_end uuid := '00000000-0000-0000-0000-000000000126';
    bad_end uuid := '00000000-0000-0000-0000-000000000129';
    child jsonb;
    copied uuid;
    count_before integer;
begin
    perform public.append_history_events(chat,'[
      {"id":"00000000-0000-0000-0000-000000000121","role":"user","content":"first","turn_id":"00000000-0000-0000-0000-000000000131","request_id":"00000000-0000-0000-0000-000000000141","event_index":0,"status":"completed"},
      {"id":"00000000-0000-0000-0000-000000000122","role":"model","content":"PRIVATE_ARG","name":"execute_command","args":{"command":"PRIVATE_ARG","path":"safe.txt"},"call_id":"call1","thought_signature":"c2ln","turn_id":"00000000-0000-0000-0000-000000000131","request_id":"00000000-0000-0000-0000-000000000141","event_index":1,"status":"completed"},
      {"id":"00000000-0000-0000-0000-000000000123","role":"tool","content":"RAW_BASE64","name":"execute_command","call_id":"call1","turn_id":"00000000-0000-0000-0000-000000000131","request_id":"00000000-0000-0000-0000-000000000141","event_index":2,"status":"completed"},
      {"id":"00000000-0000-0000-0000-000000000124","role":"model","content":"first answer","turn_id":"00000000-0000-0000-0000-000000000131","request_id":"00000000-0000-0000-0000-000000000141","event_index":3,"status":"completed"},
      {"id":"00000000-0000-0000-0000-000000000125","role":"user","content":"second","turn_id":"00000000-0000-0000-0000-000000000132","request_id":"00000000-0000-0000-0000-000000000142","event_index":0,"status":"completed"},
      {"id":"00000000-0000-0000-0000-000000000126","role":"model","content":"second answer","turn_id":"00000000-0000-0000-0000-000000000132","request_id":"00000000-0000-0000-0000-000000000142","event_index":1,"status":"completed"}
    ]');
    begin
        perform public.set_history_summary(chat,'too recent',second_end);
        raise exception 'latest user turn compacted';
    exception when invalid_parameter_value then null; end;
    perform public.set_history_summary(chat,'safe summary',first_end);
    child := public.fork_history_chat(chat,'selected',first_end);
    copied := (child->>'id')::uuid;
    if (select count(*) from public.messages where chat_id = copied) <> 4
       or child->>'summary' <> 'safe summary' or child->>'fork_boundary' <> first_end::text
       or not exists (select 1 from public.messages where chat_id = copied
                      and id = (child->>'summary_boundary')::uuid and content = 'first answer')
       or exists (select 1 from public.messages m join public.messages source on source.id = m.id where m.chat_id = copied and source.chat_id = chat)
       or exists (select 1 from public.messages where chat_id = copied and (content like '%PRIVATE_ARG%' or content like '%RAW_BASE64%' or args::text like '%PRIVATE_ARG%'))
       or not exists (select 1 from public.messages where chat_id = copied and role = 'model'
                      and name = 'execute_command' and call_id = 'call1' and thought_signature = 'c2ln' and args = '{"path":"safe.txt"}')
       or (select array_agg(role order by sequence) from public.messages where chat_id = copied) <> array['user','model','tool','model'] then
        raise exception 'fork prefix, redaction, identity or summary mapping failed';
    end if;
    perform public.append_history_events(chat,'[
      {"id":"00000000-0000-0000-0000-000000000127","role":"user","content":"bad turn","turn_id":"00000000-0000-0000-0000-000000000133","status":"completed"},
      {"id":"00000000-0000-0000-0000-000000000128","role":"tool","name":"execute_command","call_id":"orphan","content":"lost","turn_id":"00000000-0000-0000-0000-000000000133","status":"completed"},
      {"id":"00000000-0000-0000-0000-000000000129","role":"model","content":"invalid answer","turn_id":"00000000-0000-0000-0000-000000000133","status":"completed"}
    ]');
    count_before := (select count(*) from public.chats);
    begin
        perform public.fork_history_chat(chat,'invalid',bad_end);
        raise exception 'orphan tool boundary accepted';
    exception when invalid_parameter_value then null; end;
    if (select count(*) from public.chats) <> count_before then raise exception 'partial fork listed'; end if;
    child := public.fork_history_chat(chat,'latest');
    if child->>'fork_boundary' <> second_end::text then raise exception 'latest safe turn not chosen'; end if;
    perform public.set_history_summary(chat,'new summary',second_end);
    begin
        perform public.set_history_summary(chat,'backwards',first_end);
        raise exception 'summary moved backwards';
    exception when invalid_parameter_value then null; end;
    begin
        perform public.set_history_summary(chat,repeat('x',8193),second_end);
        raise exception 'oversized summary accepted';
    exception when invalid_parameter_value then null; end;
    child := public.fork_history_chat(chat,'before summary',first_end);
    if child->>'summary' is not null or (select count(*) from public.messages where chat_id = chat) <> 9 then
        raise exception 'excluded summary copied or parent changed';
    end if;
    begin
        perform public.fork_history_chat('00000000-0000-0000-0000-000000000112','foreign');
        raise exception 'foreign fork allowed';
    exception when insufficient_privilege then null; end;
    begin
        perform public.set_history_summary('00000000-0000-0000-0000-000000000112','foreign',first_end);
        raise exception 'foreign summary allowed';
    exception when insufficient_privilege then null; end;
end $$;
set local role anon;
do $$ begin
    begin
        perform public.fork_history_chat('00000000-0000-0000-0000-000000000111','anon');
        raise exception 'anonymous fork allowed';
    exception when insufficient_privilege then null; end;
    begin
        perform public.set_history_summary('00000000-0000-0000-0000-000000000111','anon',
            '00000000-0000-0000-0000-000000000124');
        raise exception 'anonymous summary allowed';
    exception when insufficient_privilege then null; end;
end $$;
rollback;
