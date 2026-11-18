"""Only send actors and rooms that belong to the current material pack."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ContextPack:
    messages: list[dict]
    actors: dict
    conversations: dict


def assemble_context(base: dict, rows: list[dict]) -> ContextPack:
    senders = {row['sender_id'] for row in rows} | {base['contact_id']}
    rooms = {row['conversation_id'] for row in rows}
    return ContextPack(
        rows,
        {key: actor for key, actor in base['actors'].items() if key in senders},
        {key: room for key, room in base['conversations'].items() if key in rooms},
    )
