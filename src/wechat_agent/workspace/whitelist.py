"""Settings-only exclusions. Shared actor/conversation rules retain all archives."""

from ..identity import clean_name, is_group_source, location
from ..source_scope import list_sources, set_sources
from .queue import reconcile
from .store import stable
from .views import source_people


def pending_groups(db):
    rows = db.rows(
        "SELECT e.source_id,e.reason,COALESCE(NULLIF(i.remark,''),NULLIF(i.nickname,''),e.source_id) name FROM actor_exclusions e LEFT JOIN identity_metadata i ON i.account_id=e.account_id AND i.source_id=e.source_id WHERE e.account_id=? AND e.source_id LIKE '%@chatroom' AND NOT EXISTS(SELECT 1 FROM conversations v WHERE v.account_id=e.account_id AND v.source_id=e.source_id)",
        (db.settings.source_account,),
    )
    return [
        r
        | {
            "id": "pending-group:" + stable(db.settings.source_account, r["source_id"]),
            "kind": "group",
            "pending": True,
        }
        for r in rows
    ]


def group_exclusions(db):
    rows = db.rows(
        "SELECT id,source_id,title name,kind,allowlisted FROM conversations WHERE account_id=? AND kind='group' AND followup_source=0",
        (db.settings.source_account,),
    )
    for r in rows:
        r["name"] = clean_name(r["name"], r["source_id"])
        if not r["name"] or r["name"] == r["source_id"]:
            r["name"] = "群名待同步" if r["kind"] == "group" else "联系人名称待同步"
        r["members"] = db.rows(
            "SELECT COUNT(DISTINCT source_id) n FROM effective_actor_exclusions WHERE account_id=? AND group_source_id=?",
            (db.settings.source_account, r["source_id"]),
        )[0]["n"]
    return rows + pending_groups(db)


def excluded_people(db):
    rows = db.rows(
        "SELECT source_id,MAX(origin<>'group') manual FROM effective_actor_exclusions WHERE account_id=? GROUP BY source_id",
        (db.settings.source_account,),
    )
    for row in rows:
        loc = location(db, row["source_id"])
        private_title = next(
            (c["title"] for c in loc["conversations"] if c["kind"] == "private"), ""
        )
        role_names = db.rows(
            "SELECT r.display_name FROM contact_roles r JOIN conversations v ON v.id=r.conversation_id WHERE v.account_id=? AND r.sender_id=? AND r.display_name<>'' ORDER BY v.id LIMIT 1",
            (db.settings.source_account, row["source_id"]),
        )
        member_name = (
            clean_name(role_names[0]["display_name"], row["source_id"])
            if role_names
            else ""
        )
        row.update(
            id=row["source_id"],
            name=loc["remark"]
            or loc["nickname"]
            or private_title
            or member_name
            or row["source_id"],
        )
        row["groups"] = db.rows(
            "SELECT DISTINCT v.source_id,v.title name FROM effective_actor_exclusions e JOIN conversations v ON v.account_id=e.account_id AND v.source_id=e.group_source_id AND v.kind='group' WHERE e.account_id=? AND e.source_id=? AND e.origin='group' ORDER BY v.source_id,v.title",
            (db.settings.source_account, row["source_id"]),
        )
        row["can_restore"] = not row["groups"]
    return rows


def listing(db, entity="people", q="", scope="archive", page=1):
    if entity == "conversations":
        entity = "groups"  # Old frontend compatibility; private peers are people.
    if (
        not isinstance(entity, str)
        or entity not in {"people", "groups"}
        or scope not in {"archive", "customer"}
        or len(q) > 200
        or not 1 <= page <= 100000
    ):
        raise ValueError("workspace_invalid_query")
    people = excluded_people(db)
    groups = group_exclusions(db)
    counts = {"people": len(people), "groups": len(groups)}
    if entity == "groups" and scope == "customer":
        result = list_sources(db, q, "group", scope, page)
        result["items"] = [r | {"name": r["title"]} for r in result["items"]]
        return result | {"counts": counts}
    rows = (
        groups
        if entity == "groups"
        else [p | {"id": p["source_id"]} for p in source_people(db)]
        if scope == "customer"
        else people
    )
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
        "counts": counts,
    }


def change(db, entity, ident, excluded):
    if entity == "conversations":
        entity = "groups"
    if (
        not isinstance(entity, str)
        or entity not in {"people", "groups"}
        or not isinstance(ident, str)
        or not 0 < len(ident) <= 200
        or type(excluded) is not bool
    ):
        raise ValueError("workspace_invalid_control")
    if entity == "groups":
        pending = next((r for r in pending_groups(db) if r["id"] == ident), None)
        if pending and not excluded:
            with db.tx() as c:
                if c.execute(
                    "SELECT 1 FROM conversations WHERE account_id=? AND source_id=?",
                    (db.settings.source_account, pending["source_id"]),
                ).fetchone():
                    raise ValueError("群聊已同步，请刷新白名单后恢复该会话")
                c.execute(
                    "DELETE FROM actor_exclusions WHERE account_id=? AND source_id=?",
                    (db.settings.source_account, pending["source_id"]),
                )
                db.event(
                    c,
                    ident,
                    "pending_group_exclusion_removed",
                    {"source_id": pending["source_id"]},
                )
        else:
            if not db.rows(
                "SELECT 1 FROM conversations WHERE id=? AND account_id=? AND kind='group'",
                (ident, db.settings.source_account),
            ):
                raise ValueError("私信按人物管理，请在人物白名单中操作")
            set_sources(db, [ident], not excluded)
    else:
        with db.tx() as c:
            if is_group_source(c, db.settings.source_account, ident):
                raise ValueError("这是群聊会话，请在会话白名单中管理")
            existing = c.execute(
                "SELECT 1 FROM effective_actor_exclusions WHERE account_id=? AND source_id=?",
                (db.settings.source_account, ident),
            ).fetchone()
            if not existing and ident not in {
                p["source_id"] for p in source_people(db)
            }:
                raise ValueError("workspace_excluded_person")
            if (
                not excluded
                and c.execute(
                    "SELECT 1 FROM effective_actor_exclusions WHERE account_id=? AND source_id=? AND origin='group'",
                    (db.settings.source_account, ident),
                ).fetchone()
            ):
                raise ValueError("此人随白名单群免跟进，请先在群聊会话中恢复所属群")
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
            if not excluded:
                c.execute(
                    "UPDATE conversations SET followup_source=1 WHERE account_id=? AND source_id=? AND kind='private'",
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
