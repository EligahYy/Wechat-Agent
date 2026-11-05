import json
from datetime import UTC, datetime

from .db import now, uid
from .ingestion import enqueue


class Conflict(ValueError):
    pass


def create_merchant(db, name):
    if not name.strip():
        raise ValueError("商家名称不能为空")
    mid = uid()
    with db.tx() as c:
        c.execute(
            "INSERT INTO merchants(id,name,created_at) VALUES(?,?,?)",
            (mid, name.strip(), now()),
        )
    return mid


def create_project(db, merchant_id, name, market=""):
    if not name.strip():
        raise ValueError("项目名称不能为空")
    pid = uid()
    with db.tx() as c:
        c.execute(
            "INSERT INTO projects(id,merchant_id,name,market) VALUES(?,?,?,?)",
            (pid, merchant_id, name, market),
        )
    return pid


def allow_conversation(
    db,
    source,
    account,
    source_id,
    title,
    kind,
    merchant_id=None,
    project_id=None,
    egress=False,
    followup_source=None,
):
    if (
        source not in {"fixture", "manual", "wx_cli"}
        or kind not in {"group", "private"}
        or not account
        or not source_id
    ):
        raise ValueError("会话配置不完整")
    with db.tx() as c:
        if project_id:
            project = c.execute(
                "SELECT * FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            if project is None or project["merchant_id"] != merchant_id:
                raise ValueError("项目与商家不匹配")
        old = c.execute(
            "SELECT id,followup_source FROM conversations WHERE source=? AND account_id=? AND source_id=?",
            (source, account, source_id),
        ).fetchone()
        cid = old["id"] if old else uid()
        c.execute(
            "INSERT INTO conversations(id,source,account_id,source_id,title,kind,merchant_id,project_id,allowlisted,egress,followup_source) VALUES(?,?,?,?,?,?,?,?,1,?,?) ON CONFLICT(source,account_id,source_id) DO UPDATE SET title=excluded.title,merchant_id=excluded.merchant_id,project_id=excluded.project_id,allowlisted=1,egress=excluded.egress,followup_source=excluded.followup_source",
            (
                cid,
                source,
                account,
                source_id,
                title,
                kind,
                merchant_id,
                project_id,
                int(egress),
                int(
                    old["followup_source"]
                    if old and followup_source is None
                    else (True if followup_source is None else bool(followup_source))
                ),
            ),
        )
        c.execute(
            "UPDATE suggestions SET status='stale' WHERE status='pending' AND job_id IN (SELECT id FROM jobs WHERE json_extract(payload,'$.conversation_id')=?)",
            (cid,),
        )
        enqueue(c, cid)
        db.event(
            c,
            cid,
            "conversation_policy",
            {"egress": bool(egress), "project_id": project_id},
        )
    return cid


def accept(db, sid):
    with db.tx() as c:
        suggestion = c.execute(
            "SELECT * FROM suggestions WHERE id=?", (sid,)
        ).fetchone()
        if suggestion is None:
            raise ValueError("建议不存在")
        existing = c.execute(
            "SELECT id FROM tasks WHERE suggestion_id=?", (sid,)
        ).fetchone()
        if existing:
            return existing["id"]
        if suggestion["status"] != "pending":
            raise Conflict("建议已失效或已处理")
        item = json.loads(suggestion["payload"])
        chat = c.execute(
            "SELECT * FROM conversations WHERE id=?", (item["conversation_id"],)
        ).fetchone()
        if (
            not chat
            or chat["merchant_id"] != item["merchant_id"]
            or chat["project_id"] != item["project_id"]
        ):
            raise Conflict("商家／批次关联已变化")
        for evidence in item["evidence"]:
            row = c.execute(
                "SELECT revision FROM messages WHERE id=? AND conversation_id=?",
                (evidence["id"], chat["id"]),
            ).fetchone()
            if row is None or row["revision"] != evidence["revision"]:
                raise Conflict("证据已变更，请重新分析")
        tid = uid()
        state = (
            "waiting_external"
            if item["responsible_party"] in {"merchant", "service_provider", "other"}
            else "open"
        )
        c.execute(
            "INSERT INTO tasks(id,merchant_id,project_id,suggestion_id,summary,party,state,due_text,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                tid,
                item["merchant_id"],
                item["project_id"],
                sid,
                item["summary"],
                item["responsible_party"],
                state,
                item.get("due_text"),
                now(),
            ),
        )
        c.execute("UPDATE suggestions SET status='accepted' WHERE id=?", (sid,))
        db.event(c, tid, "task_created", {"suggestion_id": sid})
        return tid


def transition_task(db, tid, state, version, due_at=None):
    if state not in {"open", "waiting_external", "snoozed", "done", "cancelled"}:
        raise ValueError("无效任务状态")
    if due_at:
        dt = datetime.fromisoformat(due_at)
        if dt.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        due_at = dt.astimezone(UTC).isoformat()
    if state == "snoozed" and not due_at:
        raise ValueError("暂缓需填写下次跟进时间")
    with db.tx() as c:
        row = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if not row or row["version"] != version:
            raise Conflict("任务不存在或已被修改，请刷新")
        c.execute(
            "UPDATE tasks SET state=?,due_at=?,version=version+1 WHERE id=?",
            (state, due_at, tid),
        )
        db.event(
            c,
            tid,
            "task_transition",
            {"before": dict(row), "state": state, "due_at": due_at},
        )


def project_stage(db, pid, stage, version):
    if stage not in {
        "needs",
        "connecting",
        "proposal",
        "planned",
        "executing",
        "verification",
        "done",
        "paused",
        "cancelled",
    }:
        raise ValueError("无效项目阶段")
    with db.tx() as c:
        row = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        if not row or row["version"] != version:
            raise Conflict("项目版本已变化")
        if (
            stage == "done"
            and not c.execute(
                "SELECT 1 FROM milestones WHERE project_id=? AND kind='stocking_result' AND verified=1",
                (pid,),
            ).fetchone()
        ):
            raise ValueError(
                "须先人工核验 stocking_result 节点，并在备注记录平台完成口径"
            )
        c.execute(
            "UPDATE projects SET stage=?,version=version+1 WHERE id=?", (stage, pid)
        )
        db.event(c, pid, "project_transition", {"before": row["stage"], "after": stage})


def material_usable(row):
    if (
        row["status"] != "approved"
        or row["scope"] != "external"
        or not row["valid_until"]
    ):
        return False
    return datetime.fromisoformat(row["valid_until"]) > datetime.now(UTC)


def activation(db):
    # Only deterministic market match; not a purchase-interest claim.
    result = []
    for p in db.rows(
        "SELECT p.*,m.name merchant_name FROM projects p JOIN merchants m ON m.id=p.merchant_id WHERE m.do_not_contact=0 AND p.stage NOT IN ('cancelled','paused')"
    ):
        touched = db.rows(
            "SELECT contacted_at FROM touchpoints WHERE merchant_id=? ORDER BY contacted_at DESC LIMIT 1",
            (p["merchant_id"],),
        )
        if (
            touched
            and (
                datetime.now(UTC) - datetime.fromisoformat(touched[0]["contacted_at"])
            ).days
            < 14
        ):
            continue
        cards = [
            m
            for m in db.rows("SELECT * FROM materials WHERE market=?", (p["market"],))
            if p["market"] and material_usable(m)
        ]
        if cards:
            result.append(
                {
                    "project": p,
                    "materials": cards,
                    "reason": "市场匹配；请人工核对货型、计费与历史顾虑，不代表客户有当前备货意向",
                }
            )
    return result[:5]
