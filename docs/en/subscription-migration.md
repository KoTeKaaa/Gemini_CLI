# Remote subscriptions and owner panel

[Русский](../subscription-migration.md) · [English](subscription-migration.md) · [Deployment](auto-deploy.md)

Test `supabase/migrations` in an isolated preview project first. The SQL fixtures
under `supabase/tests` use reserved user UUIDs and roll back their records; do not
run them in an unrelated live database. Back up production before schema changes.

The subscription schema preserves existing auth/chats/messages. It does not grant
old accounts access automatically. Before enabling admission checks, create a
subscription for each intended `auth.users.id`, with expiry, allowed models/features,
request budget/window and concurrency. Verify the user ID; email and editable
metadata are not authority. Without an active subscription, working APIs are closed.

Service-role manages subscription records only on the server. Users can read their
own subscription but cannot change rights. Invitations are not publicly readable;
activating one never grants owner/admin access. Rights versions change on updates.

## Request budget and account access

`subscription_requests` and the reservation RPC are service-role-only. Keep
`SUPABASE_SERVICE_ROLE_KEY` in the private server environment, never the client.
Gemini/Tavily calls, including continuations, get distinct request IDs. Duplicate
IDs are rejected and reservations are not refunded after timeout/restart. Windows
are fixed against the UTC epoch; this is not a provider-quota report.

Disable **Allow new users to sign up** and **Allow anonymous sign-ins** in the
preview Auth settings. Server `/auth/signup` returns 403. The owner invites an
account through `/admin/api/accounts/invite`; account registration does not itself
grant a subscription. Allow the panel's `/account/confirm` redirect in Auth URL
Configuration. Do not change live Auth settings as a side effect of local development.

## API and panel environment

Set `SUPABASE_SERVICE_ROLE_KEY`, trusted owner UUID `ADMIN_USER_ID`, a random
`ADMIN_SESSION_SECRET` of at least 32 characters and exact HTTPS `ADMIN_ORIGIN`
in the private server environment. Keep the session secret stable across restarts
unless deliberate session invalidation is intended. Do not commit these values.

Run the deployment preflight with the host, private env and certificate arguments
described in the Russian installation reference in [README](../../README.md).
The API and panel use separate HTTPS listeners. Owner identity, session, CSRF and
exact Origin enforce authorization; a port number is not an access-control mechanism.

Verify invitation/activation/revocation with two disposable preview accounts,
foreign-account denial and the absence of access without a subscription before
changing production. Database migrations and live owner entitlement are separate
operator actions; normal client installation does not perform them.

## Rollback

Export the new records and stop the dependent preview service before using
`deploy/rollback_account_subscriptions.sql`. It removes subscription objects,
not auth or history. Roll back later migrations in reverse order; destructive
CASCADE is deliberately absent. Verify rollback in preview first.
