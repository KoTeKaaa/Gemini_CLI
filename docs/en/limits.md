# Remote subscription budget

[Русский](../limits.md) · [English](limits.md) · [Home](../../README.en.md)

`/limits` shows the service subscription limit, accounted calls, remaining budget
and reset time. `/limits refresh` requests a fresh snapshot without generating
a model response. These commands are available only in Remote.

This is the server owner's budget, not Gemini or Tavily provider quota. A provider
can reject a request before the subscription budget runs out. Local has no server
budget indicator and does not need Google Monitoring authorization.

Server generations, tool continuations, compaction and server search consume
budget. One message may require several calls. Reservations are not refunded
after failure or cancellation because the provider may already have processed them.

The default fixed window is one day starting at 00:00 UTC; an owner can configure
another duration. It is not a rolling last-24-hours counter. Subscription expiry
restricts access independently of the remaining budget.

The input status also shows workspace, model, backend, chat and estimated context.
Unknown values appear as `—`, estimates as `≈`. Unsent drafts are estimated locally;
status refresh does not send draft text or clipboard images to the server. If image
context is not measured, its occupancy stays unknown. Stale or unavailable data
is not displayed as zero. The server rechecks the budget before the next call.
