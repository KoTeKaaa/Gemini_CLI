begin;
create function public.issue_subscription_invitation(actor_id uuid, target_id uuid,
    secret_hash text, deadline timestamptz)
returns uuid language plpgsql security definer set search_path = '' as $$
declare invitation_id uuid; begin
    perform 1 from public.account_subscriptions where id = target_id and user_id is null for update;
    if not found or deadline <= clock_timestamp() then return null; end if;
    update public.subscription_invitations set revoked_at = clock_timestamp()
        where subscription_id = target_id and revoked_at is null and activated_at is null;
    insert into public.subscription_invitations(subscription_id, token_hash, expires_at)
        values (target_id, secret_hash, deadline) returning id into invitation_id;
    insert into public.subscription_audit(actor, action, subscription_id)
        values (actor_id, 'invite_issue', target_id);
    return invitation_id;
end;
$$;

create function public.activate_subscription_invitation(account_id uuid, secret_hash text)
returns uuid language plpgsql security definer set search_path = '' as $$
declare invitation public.subscription_invitations; rights public.account_subscriptions; begin
    select * into invitation from public.subscription_invitations where token_hash = secret_hash;
    if not found then return null; end if;
    -- All invitation operations lock subscription before invitation to avoid deadlocks.
    select * into rights from public.account_subscriptions where id = invitation.subscription_id for update;
    if not found then return null; end if;
    select * into invitation from public.subscription_invitations where token_hash = secret_hash for update;
    if not found then return null; end if;
    if invitation.activated_by = account_id then return rights.id; end if;
    if invitation.activated_at is not null or invitation.revoked_at is not null
        or invitation.expires_at <= clock_timestamp() or rights.user_id is not null
        or rights.status <> 'active' or rights.expires_at <= clock_timestamp() then return null; end if;
    if exists(select 1 from public.account_subscriptions where user_id = account_id) then return null; end if;
    begin
        update public.account_subscriptions set user_id = account_id where id = rights.id;
    exception when unique_violation then return null; end;
    update public.subscription_invitations set activated_at = clock_timestamp(), activated_by = account_id
        where id = invitation.id;
    insert into public.subscription_audit(actor, action, subscription_id)
        values (account_id, 'activate', rights.id);
    return rights.id;
end;
$$;
revoke all on function public.issue_subscription_invitation(uuid, uuid, text, timestamptz),
    public.activate_subscription_invitation(uuid, text) from public, anon, authenticated;
grant execute on function public.issue_subscription_invitation(uuid, uuid, text, timestamptz),
    public.activate_subscription_invitation(uuid, text) to service_role;
commit;
