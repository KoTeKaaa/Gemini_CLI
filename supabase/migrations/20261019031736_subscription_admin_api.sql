begin;
create table public.subscription_audit (
    id bigint generated always as identity primary key,
    actor uuid not null references auth.users(id),
    action text not null,
    subscription_id uuid not null,
    created_at timestamptz not null default clock_timestamp()
);
alter table public.subscription_audit enable row level security;
revoke all on public.subscription_audit from public, anon, authenticated;
grant all on public.subscription_audit to service_role;
grant usage, select on sequence public.subscription_audit_id_seq to service_role;

create function public.manage_subscription(actor_id uuid, subscription_id uuid,
    expected_version bigint, changes jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare result public.account_subscriptions; action_name text; begin
    if subscription_id is null then
        insert into public.account_subscriptions(user_id, status, expires_at, models, features,
            request_limit, window_seconds, parallel_limit)
        values ((changes->>'user_id')::uuid, changes->>'status', (changes->>'expires_at')::timestamptz,
            array(select jsonb_array_elements_text(changes->'models')),
            array(select jsonb_array_elements_text(changes->'features')),
            (changes->>'request_limit')::integer, (changes->>'window_seconds')::integer,
            (changes->>'parallel_limit')::integer) returning * into result;
        action_name := 'create';
    else
        update public.account_subscriptions s set
            status = changes->>'status', expires_at = (changes->>'expires_at')::timestamptz,
            models = array(select jsonb_array_elements_text(changes->'models')),
            features = array(select jsonb_array_elements_text(changes->'features')),
            request_limit = (changes->>'request_limit')::integer,
            window_seconds = (changes->>'window_seconds')::integer,
            parallel_limit = (changes->>'parallel_limit')::integer
        where s.id = subscription_id and s.rights_version = expected_version
            and s.user_id is not distinct from (changes->>'user_id')::uuid
        returning s.* into result;
        if not found then return null; end if;
        action_name := changes->>'status';
    end if;
    insert into public.subscription_audit(actor, action, subscription_id)
        values (actor_id, action_name, result.id);
    return to_jsonb(result);
end;
$$;
revoke all on function public.manage_subscription(uuid, uuid, bigint, jsonb) from public, anon, authenticated;
grant execute on function public.manage_subscription(uuid, uuid, bigint, jsonb) to service_role;
commit;
