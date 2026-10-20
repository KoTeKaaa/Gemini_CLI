"""Private in-memory chat drafts/context, scoped to backend/account identity."""
from copy import deepcopy

from .draft import Draft


class ChatBuffers:
    """Use a hashable opaque scope that changes with backend/origin/account.

    Keys/tokens aren't required; model and cwd intentionally remain caller-owned.
    Saving isn't a visit. Mark a first backend load with visit() after success.
    """
    def __init__(self):
        self._buffers = {}
        self._recent = {}

    def save(self, scope, chat_id, history, draft, summary=None):
        self._buffers[(scope, chat_id)] = deepcopy({
            "history": history, "draft": draft, "summary": summary})

    def visit(self, scope, chat_id):
        recent = self._recent.setdefault(scope, [])
        if chat_id in recent:
            recent.remove(chat_id)
        recent.insert(0, chat_id)

    def restore(self, scope, chat_id):
        """Return an independent snapshot, or None when backend loading is needed."""
        snapshot = self._buffers.get((scope, chat_id))
        if snapshot is not None:
            self.visit(scope, chat_id)
        return deepcopy(snapshot)

    def recent_ids(self, scope):
        return tuple(self._recent.get(scope, ()))

    def clear_temporary(self, scope, active_turn=None):
        """Cancel late results first, then replace only this scope's temporary chat."""
        if active_turn is not None:
            active_turn.cancel()
        self.save(scope, None, [], Draft())
        return deepcopy(self._buffers[(scope, None)])


def filter_chats(chats, query, current_id=None, recent_ids=()):
    """Case-insensitive title search; current/recent first, original order otherwise.

    IDs remain unchanged even when titles repeat. Returned rows are independent and
    carry `is_current` for menu labelling. No visit is recorded by merely listing.
    """
    query = (query or "").strip().casefold()
    ranks = {}
    for chat_id in recent_ids:
        ranks.setdefault(chat_id, len(ranks))
    matched = [deepcopy(chat) for chat in chats
               if query in str(chat.get("title", "")).casefold()]
    matched.sort(key=lambda chat: (chat.get("id") != current_id,
                                  ranks.get(chat.get("id"), len(ranks))))
    for chat in matched:
        chat["is_current"] = chat.get("id") == current_id
    return matched
