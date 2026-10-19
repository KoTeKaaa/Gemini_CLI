-- Destructive rollback of S0.1 only. Export these new tables first.
-- Refuses to run once later migrations depend on the schema.
begin;
drop table public.subscription_invitations;
drop table public.account_subscriptions;
drop function public.bump_subscription_rights_version();
commit;
