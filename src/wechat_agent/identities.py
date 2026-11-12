"""Structural identity checks, independent of display names and wxid prefixes."""

import unicodedata


def is_person_identifier(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 512
        and not value.endswith("@chatroom")
        and not value.startswith("unknown:")
        and all(
            character.isprintable()
            and not character.isspace()
            and character not in '<>"\'{}[]=\\'
            and character != "\ufffd"
            for character in value
        )
    )


def usable_name(value, identifier):
    if not isinstance(value, str) or not value.strip() or value.strip() == identifier:
        return None
    if "\ufffd" in value or any(unicodedata.category(c) in {"Cc", "Cs"} for c in value):
        return None
    return value.strip()


def choose_name(remark, nickname, identifier):
    for field, value in (("remark", remark), ("nickname", nickname)):
        name = usable_name(value, identifier)
        if name:
            return name, field
    return None, "missing"
