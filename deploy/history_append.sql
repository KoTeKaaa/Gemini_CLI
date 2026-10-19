-- Planned S4.2 migration, after history_events.sql. No provider calls here.
begin;
create function public.append_history_events(target_chat uuid, events jsonb)
returns integer language plpgsql security invoker set search_path = '' as $$
declare
    item jsonb;
    incoming public.messages%rowtype;
    previous public.messages%rowtype;
    matched integer;
    appended integer := 0;
begin
    -- Serialize this adapter's append/finalize operations, retaining ordinary RLS.
    perform 1 from public.chats where id = target_chat and user_id = auth.uid() for update;
    if not found then raise insufficient_privilege using message = 'Chat unavailable'; end if;
    if events is null or jsonb_typeof(events) <> 'array' or jsonb_array_length(events) > 100 then
        raise invalid_parameter_value using message = 'Invalid event batch';
    end if;
    for item in select value from jsonb_array_elements(events) loop
        if jsonb_typeof(item) <> 'object' then
            raise invalid_parameter_value using message = 'Invalid event';
        end if;
        select * into incoming from jsonb_populate_record(null::public.messages, item);
        incoming.chat_id := target_chat;
        incoming.status := coalesce(incoming.status, 'legacy');
        if (incoming.request_id is null) <> (incoming.event_index is null)
           or (incoming.request_id is not null and incoming.turn_id is null) then
            raise invalid_parameter_value using message = 'Incomplete event identity';
        end if;
        select count(*) into matched from public.messages m where m.chat_id = target_chat and
            ((incoming.id is not null and m.id = incoming.id) or
             (incoming.request_id is not null and m.request_id = incoming.request_id
              and m.event_index = incoming.event_index));
        if matched > 1 then
            raise unique_violation using message = 'Conflicting event identities';
        elsif matched = 1 then
            select * into previous from public.messages m where m.chat_id = target_chat and
                ((incoming.id is not null and m.id = incoming.id) or
                 (incoming.request_id is not null and m.request_id = incoming.request_id
                  and m.event_index = incoming.event_index));
            if (incoming.id is not null and previous.id <> incoming.id) or
               row(previous.role, previous.content, previous.name, previous.args, previous.call_id,
                   previous.thought_signature, previous.turn_id, previous.request_id,
                   previous.event_index) is distinct from
               row(incoming.role, incoming.content, incoming.name, incoming.args, incoming.call_id,
                   incoming.thought_signature, incoming.turn_id, incoming.request_id,
                   incoming.event_index) or
               (previous.status <> incoming.status and not
                (incoming.status = 'running' and previous.status in ('completed', 'cancelled', 'failed'))) then
                raise unique_violation using message = 'Event replay differs';
            end if;
            continue;
        end if;
        insert into public.messages(id, chat_id, role, content, name, args, call_id,
                                    thought_signature, turn_id, request_id, event_index, status)
            values (coalesce(incoming.id, gen_random_uuid()), target_chat, incoming.role,
                    incoming.content, incoming.name, incoming.args, incoming.call_id,
                    incoming.thought_signature, incoming.turn_id, incoming.request_id,
                    incoming.event_index, incoming.status);
        appended := appended + 1;
    end loop;
    return appended;
end;
$$;

create function public.update_history_request_status(target_chat uuid, request_uuid uuid, new_status text)
returns integer language plpgsql security invoker set search_path = '' as $$
declare changed integer;
begin
    perform 1 from public.chats where id = target_chat and user_id = auth.uid() for update;
    if not found then raise insufficient_privilege using message = 'Chat unavailable'; end if;
    if request_uuid is null or new_status is null or new_status not in ('completed', 'cancelled', 'failed') then
        raise invalid_parameter_value using message = 'Invalid terminal status';
    end if;
    update public.messages set status = new_status where chat_id = target_chat
        and request_id = request_uuid and status = 'running';
    get diagnostics changed = row_count;
    return changed;
end;
$$;
revoke all on function public.append_history_events(uuid, jsonb) from public, anon;
revoke all on function public.update_history_request_status(uuid, uuid, text) from public, anon;
grant execute on function public.append_history_events(uuid, jsonb) to authenticated;
grant execute on function public.update_history_request_status(uuid, uuid, text) to authenticated;
commit;
