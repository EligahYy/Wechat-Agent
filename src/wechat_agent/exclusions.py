"""One effective person whitelist: manual people plus members of excluded groups."""

from .db import dumps, now, uid

SCHEMA = """
CREATE VIEW IF NOT EXISTS effective_actor_exclusions AS
WITH group_members AS (
 SELECT v.account_id,m.sender_id source_id,v.source_id group_source_id
 FROM conversations v JOIN messages m ON m.conversation_id=v.id
 WHERE v.kind='group' AND v.followup_source=0 AND m.direction='incoming'
 UNION
 SELECT v.account_id,r.sender_id,v.source_id
 FROM conversations v JOIN contact_roles r ON r.conversation_id=v.id
 WHERE v.kind='group' AND v.followup_source=0
)
SELECT e.account_id,e.source_id,e.reason,'manual' origin,NULL group_source_id
FROM actor_exclusions e
WHERE e.source_id NOT LIKE '%@chatroom'
 AND NOT EXISTS(SELECT 1 FROM conversations v WHERE v.account_id=e.account_id AND v.source_id=e.source_id AND v.kind='group')
UNION
SELECT v.account_id,v.source_id,'私信免跟进','legacy_private',NULL
FROM conversations v WHERE v.kind='private' AND v.followup_source=0 AND v.source_id NOT LIKE '%@chatroom'
UNION
SELECT g.account_id,g.source_id,'随群免跟进','group',g.group_source_id
FROM group_members g
WHERE g.source_id NOT IN ('','unknown',g.account_id)
 AND g.source_id NOT LIKE '%@chatroom'
 AND NOT EXISTS(SELECT 1 FROM conversations v WHERE v.account_id=g.account_id AND v.source_id=g.source_id AND v.kind='group');
"""


def legacy_private_exclusions(c):
    return c.execute(
        "SELECT * FROM conversations WHERE kind='private' AND followup_source=0 AND source_id NOT LIKE '%@chatroom'"
    ).fetchall()


def repair_private_exclusions(c):
    rows = legacy_private_exclusions(c)
    for old in rows:
        c.execute(
            "INSERT OR IGNORE INTO actor_exclusions VALUES(?,?,'由旧私信白名单归并')",
            (old["account_id"], old["source_id"]),
        )
        c.execute("UPDATE conversations SET followup_source=1 WHERE id=?", (old["id"],))
        c.execute(
            "INSERT INTO events VALUES(?,?,?,?,?)",
            (
                uid(),
                old["account_id"],
                "private_exclusion_repaired",
                dumps({"conversation_id": old["id"], "source_id": old["source_id"]}),
                now(),
            ),
        )
    return len(rows)
