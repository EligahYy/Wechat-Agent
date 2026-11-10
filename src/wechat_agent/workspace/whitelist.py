"""Settings-only exclusions. Shared actor/conversation rules retain all archives."""

from ..identity import location
from ..source_scope import list_sources, set_sources
from .queue import reconcile
from .store import stable
from .views import source_people


def listing(db, entity="people", q="", scope="archive", page=1):
    if (
        not isinstance(entity, str)
        or entity not in {"people", "conversations"}
        or scope not in {"archive", "customer"}
        or len(q) > 200
        or not 1 <= page <= 100000
    ):
        raise ValueError("workspace_invalid_query")
    if entity == "conversations":
        result = list_sources(db, q, "all", scope, page)
        result["items"] = [r | {"name": r["title"]} for r in result["items"]]
        return result
    if scope == "customer":
        rows = [p | {"id": p["source_id"]} for p in source_people(db)]
    else:
        rows = []
        for row in db.rows(
            "SELECT source_id,reason FROM actor_exclusions WHERE account_id=?",
            (db.settings.source_account,),
        ):
            loc = location(db, row["source_id"])
            private_title = next(
                (c["title"] for c in loc["conversations"] if c["kind"] == "private"),
                "",
            )
            name = loc["remark"] or loc["nickname"] or private_title or row["source_id"]
            rows.append(row | {"id": row["source_id"], "name": name})
    rows = sorted(
        (
            r
            for r in rows
            if q.casefold() in r["name"].casefold()
            or q.casefold() in r["source_id"].casefold()
        ),
        key=lambda r: (r["name"], r["id"]),
    )
    total = len(rows)
    pages = max(1, (total + 49) // 50)
    page = min(page, pages)
    return {
        "items": rows[(page - 1) * 50 : page * 50],
        "total": total,
        "page": page,
        "pages": pages,
        "has_more": page < pages,
        "page_size": 50,
    }


def change(db, entity, ident, excluded):
    if (
        not isinstance(entity, str)
        or entity not in {"people", "conversations"}
        or not isinstance(ident, str)
        or not 0 < len(ident) <= 200
        or type(excluded) is not bool
    ):
        raise ValueError("workspace_invalid_control")
    if entity == "conversations":
        set_sources(db, [ident], not excluded)
    else:
        existing = db.rows(
            "SELECT 1 FROM actor_exclusions WHERE account_id=? AND source_id=?",
            (db.settings.source_account, ident),
        )
        if not existing and ident not in {p["source_id"] for p in source_people(db)}:
            raise ValueError("workspace_excluded_person")
        with db.tx() as c:
            if excluded:
                c.execute(
                    "INSERT INTO actor_exclusions VALUES(?,?,'人工免跟进') ON CONFLICT(account_id,source_id) DO NOTHING",
                    (db.settings.source_account, ident),
                )
            else:
                c.execute(
                    "DELETE FROM actor_exclusions WHERE account_id=? AND source_id=?",
                    (db.settings.source_account, ident),
                )
            db.event(
                c,
                "workspace-person:" + stable(db.settings.source_account, ident),
                "person_exclusion",
                {"enabled": excluded},
            )
    reconcile(db)
    return {"ok": True, "excluded": excluded}
