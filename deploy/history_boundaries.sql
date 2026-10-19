-- Planned S4 migration after history_events/history_append; ownership stays invoker-scoped.
begin;
create function public.history_boundary_valid(target_chat uuid, boundary_id uuid)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare
    boundary public.messages%rowtype;
    event public.messages%rowtype;
    first_sequence bigint;
    users integer;
    matches integer;
    position integer;
    pending jsonb := '[]';
begin
    select m.* into boundary from public.messages m join public.chats c on c.id = m.chat_id
        where m.chat_id = target_chat and m.id = boundary_id and c.user_id = auth.uid();
    if not found or boundary.turn_id is null or boundary.role <> 'model' or boundary.name is not null
       or boundary.status <> 'completed' or btrim(boundary.content) = '' then return false; end if;
    select min(sequence), count(*) filter (where role = 'user') into first_sequence, users
        from public.messages where chat_id = target_chat and turn_id = boundary.turn_id;
    if users <> 1 or (select role from public.messages where sequence = first_sequence) <> 'user'
       or exists (select 1 from public.messages where chat_id = target_chat and turn_id = boundary.turn_id
                  and (status <> 'completed' or sequence > boundary.sequence))
       or exists (select 1 from public.messages where chat_id = target_chat
                  and sequence between first_sequence and boundary.sequence
                  and turn_id is distinct from boundary.turn_id) then return false; end if;
    for event in select * from public.messages where chat_id = target_chat
                 and turn_id = boundary.turn_id order by sequence loop
        if event.role = 'model' and event.name is not null then
            pending := pending || jsonb_build_array(jsonb_build_object('name',event.name,'call_id',event.call_id));
        elsif event.role = 'tool' then
            select count(*), min(ordinality)::integer - 1 into matches, position
                from jsonb_array_elements(pending) with ordinality as p(call,ordinality)
                where call->>'name' = event.name
                  and (event.call_id is null or call->>'call_id' = event.call_id);
            if matches <> 1 then return false; end if;
            pending := pending - position;
        end if;
    end loop;
    return pending = '[]'::jsonb;
end;
$$;

create function public.set_history_summary(target_chat uuid, summary_text text, boundary_id uuid)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare boundary_sequence bigint; previous_sequence bigint;
begin
    perform 1 from public.chats where id = target_chat and user_id = auth.uid() for update;
    if not found then raise insufficient_privilege using message = 'Chat unavailable'; end if;
    if summary_text is null or btrim(summary_text) = '' or char_length(summary_text) > 8192
       or not public.history_boundary_valid(target_chat,boundary_id) then
        raise invalid_parameter_value using message = 'Invalid summary boundary or text';
    end if;
    select sequence into boundary_sequence from public.messages where chat_id = target_chat and id = boundary_id;
    select m.sequence into previous_sequence from public.chats c join public.messages m
        on m.chat_id = c.id and m.id = c.summary_boundary where c.id = target_chat;
    if previous_sequence > boundary_sequence or not exists
       (select 1 from public.messages where chat_id = target_chat and role = 'user' and sequence > boundary_sequence) then
        raise invalid_parameter_value using message = 'Summary must retain the latest user turn';
    end if;
    update public.chats set summary = summary_text, summary_boundary = boundary_id where id = target_chat;
    return true;
end;
$$;

create function public.fork_history_chat(target_chat uuid, new_title text, boundary_id uuid default null)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
    parent public.chats%rowtype;
    child public.chats%rowtype;
    boundary public.messages%rowtype;
    source public.messages%rowtype;
    copied_id uuid;
    copied_summary_boundary uuid;
    copied_args jsonb;
begin
    select * into parent from public.chats where id = target_chat and user_id = auth.uid() for update;
    if not found then raise insufficient_privilege using message = 'Chat unavailable'; end if;
    if new_title is null or btrim(new_title) = '' or char_length(new_title) > 200 then
        raise invalid_parameter_value using message = 'Invalid fork title';
    end if;
    select * into boundary from public.messages where chat_id = target_chat
        and (boundary_id is null or id = boundary_id) and public.history_boundary_valid(target_chat,id)
        order by sequence desc limit 1;
    if not found then raise invalid_parameter_value using message = 'No completed whole-turn boundary'; end if;
    insert into public.chats(user_id,title,fork_parent_id,fork_boundary)
        values (auth.uid(),btrim(new_title),target_chat,boundary.id) returning * into child;
    for source in select * from public.messages where chat_id = target_chat
                  and sequence <= boundary.sequence order by sequence loop
        copied_id := gen_random_uuid();
        copied_args := null;
        if source.role = 'model' and source.name is not null then
            select coalesce(jsonb_object_agg(key,value),'{}'::jsonb) into copied_args
                from jsonb_each(case when jsonb_typeof(source.args) = 'object' then source.args else '{}'::jsonb end)
                where key in ('filepath','start_line','end_line','path')
                  and (jsonb_typeof(value) in ('string','boolean') or
                       (jsonb_typeof(value) = 'number' and value::text ~ '^-?[0-9]+$'));
        end if;
        insert into public.messages(id,chat_id,role,content,name,args,call_id,thought_signature,
                                    turn_id,request_id,event_index,status,created_at)
            values (copied_id,child.id,source.role,
                case when source.role = 'tool' or (source.role = 'model' and source.name is not null)
                     then '{"status":"redacted","message":"Содержимое инструмента не сохраняется"}'
                     else source.content end,
                source.name,copied_args,source.call_id,source.thought_signature,
                source.turn_id,source.request_id,source.event_index,source.status,source.created_at);
        if source.id = parent.summary_boundary then copied_summary_boundary := copied_id; end if;
    end loop;
    if copied_summary_boundary is not null then
        update public.chats set summary = parent.summary, summary_boundary = copied_summary_boundary
            where id = child.id returning * into child;
    end if;
    return to_jsonb(child);
end;
$$;
revoke all on function public.history_boundary_valid(uuid,uuid) from public,anon;
revoke all on function public.set_history_summary(uuid,text,uuid) from public,anon;
revoke all on function public.fork_history_chat(uuid,text,uuid) from public,anon;
grant execute on function public.history_boundary_valid(uuid,uuid) to authenticated;
grant execute on function public.set_history_summary(uuid,text,uuid) to authenticated;
grant execute on function public.fork_history_chat(uuid,text,uuid) to authenticated;
commit;
