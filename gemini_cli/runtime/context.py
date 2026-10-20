"""One context policy for persisted/temporary, local/server conversations."""
from .history import persistent_history_rows, complete_tool_pairs
from .attachments import restore_images


def current_turn(history):
    start = next((i for i in range(len(history) - 1, -1, -1)
                  if history[i].get("role") == "user"), None)
    if start is None:
        raise ValueError("Нет исходного сообщения хода")
    return history[start:]


def before_turn(stored, turn_id=None):
    if turn_id:
        for index, row in enumerate(stored):
            if row.get("turn_id") == str(turn_id):
                return stored[:index]
    # Legacy continuation has no persisted turn identifiers. Only its latest
    # saved user turn can be active; never search by user message contents.
    start = next((i for i in range(len(stored) - 1, -1, -1)
                  if stored[i].get("role") == "user"), None)
    if start is None:
        return stored
    if turn_id and stored[start].get("turn_id"):
        raise ValueError("Продолжение относится к другому ходу")
    return stored[:start]


def select_context(stored, incoming, *, continuing=False, turn_id=None,
                   summary=None, summary_boundary=None):
    """Return a fresh provider context, retaining whole turns and all rows.

    `stored=None` denotes an in-memory conversation. Stored history is always
    authoritative. Images can be restored only from this client's live RAM.
    """
    incoming = [dict(row) for row in incoming]
    if stored is None:
        active = current_turn(incoming) if continuing and incoming else []
        previous = incoming[:len(incoming) - len(active)]
    elif continuing:
        active = current_turn(incoming)
        previous = before_turn(stored, turn_id)
    else:
        active = []
        previous = list(stored)
    previous = persistent_history_rows(previous)
    if summary is not None:
        index = next((i for i, row in enumerate(previous)
                      if row.get("id") == summary_boundary), None)
        if index is None:
            raise ValueError("Граница сводки отсутствует в истории")
        previous = ([{"role": "user", "content": "Сводка предыдущего диалога:\n" + summary}]
                    + previous[index + 1:])
    previous = restore_images(previous, incoming)
    return complete_tool_pairs(previous + active)
