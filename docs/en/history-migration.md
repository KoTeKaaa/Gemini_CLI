# Chat history schema migration

[Русский](../history-migration.md) · [English](history-migration.md) · [Deployment](auto-deploy.md)

Apply these schema sources in order: `deploy/history_events.sql`,
`deploy/history_append.sql`, then `deploy/history_boundaries.sql`. Deployment
does not execute SQL. Check the current schema and migration history first;
do not reapply changes already registered in the database.

## Event identity and compatibility

`messages.id` is a stable event UUID. `turn_id` groups a user turn, `request_id`
identifies a generation/continuation, and nonnegative `event_index` orders its
events. `(chat_id, request_id, event_index)` uniqueness prevents identified-event
replays. Legacy inserts remain compatible; the database assigns identity/order
and marks them `legacy`. New statuses are `running`, `completed`, `cancelled` and
`failed`. Preserve tool `call_id` and `thought_signature`, while filtering private content.

Read chat events by `sequence`. Backfill uses `(created_at,id)`; UUID order breaks
ties reproducibly but does not recover unknown causal order. Sequence gaps are normal.

Summary text and boundary must refer to the same chat. Fork parent/boundary links
must preserve ownership. Referential integrity alone does not prove a completed
turn; the boundary RPCs perform that validation. PostgreSQL 17 is required by the
documented selective `ON DELETE SET NULL` behavior.

## Before production

Use an isolated preview database containing the original chats/messages tables
and ownership policies. Subscription tables alone are not that baseline. Take a
backup and account for backfill locks on large message tables. Verify both an
empty database and old rows with equal timestamps.

The migration preserves authenticated ownership policies and Supabase Auth, removes
the old permissive anonymous message policies and revokes public/anonymous message
access. Service-role remains a server secret. Test with two users plus anonymous
access; fixtures use reserved UUIDs and belong only in isolated databases.

Apply compatible schema before the runtime that needs it. Do not automatically
drop new columns to roll back a successful migration: that destroys event identity,
summaries and fork provenance. Existing runtime remains compatible with added fields.

## Append and finalize

`append_history_events(target_chat,events)` accepts up to 100 already-filtered
events and returns the number inserted. The whole batch is atomic and a chat lock
serializes appends. Exact replays are no-ops; changed replays or conflicting IDs fail.
If request/event index is supplied, both and `turn_id` are required. Redaction is
the caller's responsibility before RPC, not performed by this append function.

`update_history_request_status(target_chat,request_uuid,new_status)` changes only
running events to a terminal status. It does not overwrite terminal/legacy rows
or create a tombstone when no events exist. Runtime cancellation and spending
reservations still guard late generation; this is not exactly-once external execution.

Both functions are security-invoker, use an empty search path, require authenticated
access and explicitly verify chat ownership.

## Summary and fork

`set_history_summary(target_chat,summary_text,boundary_id)` accepts a bounded
summary only at a safe whole completed turn before the last user message. The
boundary cannot move backward; original messages remain intact.

`fork_history_chat(target_chat,new_title,boundary_id)` copies the safe prefix with
new event UUIDs, original turn/request/tool identities and order. A null boundary
selects the last safe one. The summary is copied only if its boundary is included,
with remapped UUIDs. Copied tool outputs and named model-call content are redacted,
and arguments retain only safe path/line fields. Source history is unchanged.
Creation, copy and summary happen in one transaction; failures leave no partial fork.
