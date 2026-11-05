"""Automatic, evidence-backed customer records and next actions on local SQLite."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

from .db import dumps, now, uid
from .message_value import classify

TZ = ZoneInfo("Asia/Shanghai")

SCHEMA = """
CREATE TABLE crm_policies(account_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 0,include_new INTEGER NOT NULL DEFAULT 1,daily_budget INTEGER NOT NULL DEFAULT 100000,version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE crm_contacts(id TEXT PRIMARY KEY,account_id TEXT NOT NULL,source_id TEXT NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'unknown',UNIQUE(account_id,source_id));
CREATE TABLE crm_customers(id TEXT PRIMARY KEY,contact_id TEXT UNIQUE REFERENCES crm_contacts(id),account_id TEXT NOT NULL,name TEXT NOT NULL,do_not_contact INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
CREATE TABLE crm_facts(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL REFERENCES crm_customers(id),field TEXT NOT NULL,value TEXT NOT NULL,evidence TEXT NOT NULL,event_time TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',locked INTEGER NOT NULL DEFAULT 0,UNIQUE(customer_id,field,value));
CREATE TABLE crm_plans(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL REFERENCES crm_customers(id),name TEXT NOT NULL,stage TEXT NOT NULL DEFAULT 'needs',evidence TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(customer_id,name));
CREATE TABLE crm_actions(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL REFERENCES crm_customers(id),plan_id TEXT REFERENCES crm_plans(id),contact_id TEXT REFERENCES crm_contacts(id),action_key TEXT NOT NULL,summary TEXT NOT NULL,reason TEXT NOT NULL,party TEXT NOT NULL,state TEXT NOT NULL,due_date TEXT,due_text TEXT,date_kind TEXT NOT NULL,evidence TEXT NOT NULL,event_time TEXT NOT NULL,locked INTEGER NOT NULL DEFAULT 0,version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,UNIQUE(customer_id,action_key));
CREATE TABLE crm_reviews(id TEXT PRIMARY KEY,account_id TEXT NOT NULL,question TEXT NOT NULL,evidence TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',resolution TEXT,created_at TEXT NOT NULL,UNIQUE(account_id,question,evidence));
CREATE INDEX crm_actions_due ON crm_actions(state,due_date);
"""


def stable_actor(account, source_id):
    return "C" + hashlib.sha256(dumps([account, source_id]).encode()).hexdigest()[:12]


def index_contacts(c, account):
    people = c.execute(
        "SELECT DISTINCT m.sender_id FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE v.account_id=? AND m.direction='incoming' AND m.sender_id NOT IN ('unknown',?) UNION SELECT source_id FROM conversations WHERE account_id=? AND kind='private'",
        (account, account, account),
    ).fetchall()
    for person in people:
        source_id = person[0]
        if source_id == account or source_id == "unknown":
            continue
        private = c.execute(
            "SELECT title FROM conversations WHERE account_id=? AND source_id=? AND kind='private' ORDER BY rowid DESC LIMIT 1",
            (account, source_id),
        ).fetchone()
        role = c.execute(
            "SELECT r.display_name FROM contact_roles r JOIN conversations v ON v.id=r.conversation_id WHERE v.account_id=? AND r.sender_id=? AND r.display_name<>'' LIMIT 1",
            (account, source_id),
        ).fetchone()
        name = (
            private[0]
            if private
            else role[0]
            if role
            else "群聊联系人 · " + source_id[-6:]
        )
        metadata = c.execute(
            "SELECT remark,nickname FROM identity_metadata WHERE account_id=? AND source_id=?",
            (account, source_id),
        ).fetchone()
        if metadata and (metadata["remark"] or metadata["nickname"]):
            name = metadata["remark"] or metadata["nickname"]
        previous = c.execute(
            "SELECT name FROM crm_contacts WHERE id=?",
            (stable_actor(account, source_id),),
        ).fetchone()
        if previous and previous["name"] != name:
            c.execute(
                "UPDATE crm_customers SET name=? WHERE contact_id=? AND name=?",
                (name, stable_actor(account, source_id), previous["name"]),
            )
        c.execute(
            "INSERT INTO crm_contacts(id,account_id,source_id,name) VALUES(?,?,?,?) ON CONFLICT(account_id,source_id) DO UPDATE SET name=excluded.name",
            (stable_actor(account, source_id), account, source_id, name),
        )


def index_touchpoints(c, account):
    # Private-chat outgoing messages establish an actual contact, never task
    # completion. Group attribution is left to evidenced model interpretation.
    c.execute(
        "INSERT OR IGNORE INTO events(id,entity_id,kind,payload,created_at) SELECT 'contact:'||m.id,u.id,'crm_contact',json_object('message_id',m.id,'event_time',m.event_time,'direction','outgoing'),m.event_time FROM messages m JOIN conversations v ON v.id=m.conversation_id JOIN crm_contacts n ON n.source_id=v.source_id AND n.account_id=v.account_id JOIN crm_customers u ON u.contact_id=n.id WHERE v.account_id=? AND v.kind='private' AND m.direction='outgoing'",
        (account,),
    )


def configure(db, enabled, budget=100000, include_new=True):
    account = db.settings.source_account
    if not account:
        raise ValueError("请先确认工作账号")
    if (
        type(enabled) is not bool
        or type(include_new) is not bool
        or type(budget) is not int
        or not 1000 <= budget <= 10000000
    ):
        raise ValueError("授权或预算参数无效")
    with db.tx() as c:
        previous = c.execute(
            "SELECT * FROM crm_policies WHERE account_id=?", (account,)
        ).fetchone()
        c.execute(
            "INSERT INTO crm_policies(account_id,enabled,include_new,daily_budget) VALUES(?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET enabled=excluded.enabled,include_new=excluded.include_new,daily_budget=excluded.daily_budget,version=crm_policies.version+CASE WHEN crm_policies.enabled<>excluded.enabled OR crm_policies.include_new<>excluded.include_new THEN 1 ELSE 0 END",
            (account, int(enabled), int(include_new), budget),
        )
        if (
            not previous
            or bool(previous["enabled"]) != enabled
            or bool(previous["include_new"]) != include_new
        ):
            c.execute(
                "UPDATE conversations SET egress=CASE WHEN ?=1 AND COALESCE((SELECT json_extract(e.payload,'$.enabled') FROM events e WHERE e.entity_id=conversations.id AND e.kind='crm_scope_change' ORDER BY e.created_at DESC LIMIT 1),1)=1 THEN 1 ELSE 0 END WHERE account_id=? AND allowlisted=1",
                (int(enabled), account),
            )
        # Existing old extraction jobs must not compete with the new pipeline.
        c.execute(
            "UPDATE jobs SET status='superseded' WHERE json_extract(payload,'$.engine') IS NULL AND status NOT IN ('succeeded','failed')"
        )
        db.event(
            c, account, "analysis_authorization", {"enabled": enabled, "budget": budget}
        )
    if enabled:
        schedule(db, retry=True)


def schedule(db, retry=False):
    from .planning import schedule as plan

    return plan(db, retry=retry)


def evidence_for(refs, evidence):
    return [
        {"id": evidence[r]["id"], "revision": evidence[r]["revision"]}
        for r in sorted(set(refs))
    ]


def review(c, account, question, evidence):
    c.execute(
        "INSERT OR IGNORE INTO crm_reviews(id,account_id,question,evidence,created_at) VALUES(?,?,?,?,?)",
        (uid(), account, question, dumps(evidence), now()),
    )


def apply(c, db, chat, evidence, result, participants):
    """Called within the job's lease-checked write transaction."""
    account = chat["account_id"]
    # Only actors present in this actual input can be referenced by the model.
    actors = {
        stable_actor(account, m["sender_id"]): m["sender_id"]
        for m in evidence.values()
        if m["sender_id"] != "unknown" and m["direction"] == "incoming"
    }
    if chat["kind"] == "private":
        actors[stable_actor(account, chat["source_id"])] = chat["source_id"]
    for row in c.execute(
        "SELECT DISTINCT sender_id FROM messages WHERE conversation_id=? AND direction='incoming' AND sender_id<>'unknown'",
        (chat["id"],),
    ):
        actors[stable_actor(account, row[0])] = row[0]
    actors = {key: value for key, value in actors.items() if key in participants}
    refs = (
        [p.evidence_refs for p in result.people]
        + [f.evidence_refs for p in result.people for f in p.facts]
        + [a.evidence_refs for a in result.actions]
        + [a.evidence_refs for a in result.ambiguities]
        + [v.evidence_refs for v in result.business_events]
    )
    if any(not set(r) <= evidence.keys() for r in refs):
        raise ValueError("model_unknown_evidence")
    if any(v.customer_ref not in actors for v in result.business_events):
        raise ValueError("model_unknown_actor")
    if any(p.actor_ref not in actors for p in result.people) or any(
        a.customer_ref not in actors or (a.contact_ref and a.contact_ref not in actors)
        for a in result.actions
    ):
        raise ValueError("model_unknown_actor")
    index_contacts(c, account)
    excluded = {
        stable_actor(account, r[0])
        for r in c.execute(
            "SELECT source_id FROM actor_exclusions WHERE account_id=?", (account,)
        )
    }
    private_excluded = (
        chat["kind"] == "private"
        and stable_actor(account, chat["source_id"]) in excluded
    )
    if private_excluded:
        return
    if result.conversation_type != "unknown":
        c.execute(
            "INSERT INTO conversation_classifications VALUES(?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET kind=excluded.kind,evidence=excluded.evidence,updated_at=excluded.updated_at",
            (
                chat["id"],
                result.conversation_type,
                dumps(
                    [
                        {"id": m["id"], "revision": m["revision"]}
                        for m in evidence.values()
                    ]
                ),
                now(),
            ),
        )
    if result.conversation_type in {"internal", "buyer", "provider", "announcement"}:
        return
    for person in result.people:
        if person.actor_ref in excluded:
            continue
        person_evidence = evidence_for(person.evidence_refs, evidence)
        contact = c.execute(
            "SELECT * FROM crm_contacts WHERE id=?", (person.actor_ref,)
        ).fetchone()
        corrected_role = c.execute(
            "SELECT 1 FROM crm_reviews WHERE account_id=? AND question=? AND status='resolved' LIMIT 1",
            (account, "联系人角色存在冲突：" + contact["name"]),
        ).fetchone()
        if contact["role"] not in {"unknown", person.role} and not corrected_role:
            review(
                c, account, "联系人角色存在冲突：" + contact["name"], person_evidence
            )
            continue
        c.execute(
            "UPDATE crm_contacts SET role=? WHERE id=?", (person.role, person.actor_ref)
        )
        if person.role != "merchant":
            if corrected_role:
                c.execute(
                    "UPDATE crm_customers SET do_not_contact=1 WHERE contact_id=?",
                    (person.actor_ref,),
                )
            continue
        if chat["kind"] == "private" and chat["merchant_id"]:
            c.execute(
                "UPDATE crm_customers SET contact_id=? WHERE id=? AND contact_id IS NULL",
                (person.actor_ref, "legacy:" + account + ":" + chat["merchant_id"]),
            )
        c.execute(
            "INSERT OR IGNORE INTO crm_customers(id,contact_id,account_id,name,created_at) VALUES(?,?,?,?,?)",
            (uid(), person.actor_ref, account, contact["name"], now()),
        )
        customer = c.execute(
            "SELECT * FROM crm_customers WHERE contact_id=?", (person.actor_ref,)
        ).fetchone()
        for fact in person.facts:
            evid = evidence_for(fact.evidence_refs, evidence)
            when = max(evidence[r]["event_time"] for r in fact.evidence_refs)
            prior = c.execute(
                "SELECT * FROM crm_facts WHERE customer_id=? AND field=? AND status='active' ORDER BY event_time DESC LIMIT 1",
                (customer["id"], fact.field),
            ).fetchone()
            resolved = c.execute(
                "SELECT 1 FROM crm_reviews WHERE account_id=? AND question=? AND status='resolved' LIMIT 1",
                (account, "客户信息存在冲突：" + contact["name"] + " · " + fact.field),
            ).fetchone()
            if (
                prior
                and prior["value"] != fact.value
                and (prior["locked"] or (fact.field == "company" and not resolved))
            ):
                review(
                    c,
                    account,
                    "客户信息存在冲突：" + contact["name"] + " · " + fact.field,
                    evid,
                )
                continue
            c.execute(
                "INSERT INTO crm_facts(id,customer_id,field,value,evidence,event_time) VALUES(?,?,?,?,?,?) ON CONFLICT(customer_id,field,value) DO UPDATE SET evidence=excluded.evidence,event_time=excluded.event_time WHERE crm_facts.locked=0 AND crm_facts.event_time<=excluded.event_time",
                (uid(), customer["id"], fact.field, fact.value, dumps(evid), when),
            )
    for event in result.business_events:
        if event.kind == "shipment_reported":
            statements = [evidence[r]["text"] for r in event.evidence_refs]
            explicit = any(
                re.search(
                    r"(?:已|已经).{0,8}(?:发货|发出|出运|装柜|提货)|(?:发货|发出|出运|装柜|提货)了",
                    t,
                )
                and not re.search(r"还没|尚未|未发|没发|如果|预计|准备|计划", t)
                for t in statements
            )
            if not explicit:
                continue
        if event.customer_ref in excluded:
            continue
        refs = evidence_for(event.evidence_refs, evidence)
        when = max(evidence[r]["event_time"] for r in event.evidence_refs)
        c.execute(
            "INSERT OR IGNORE INTO business_events VALUES(?,?,?,?,?,?,?)",
            (
                uid(),
                account,
                event.customer_ref,
                event.opportunity,
                event.kind,
                dumps(refs),
                when,
            ),
        )
        if event.kind in {"shipment_reported", "cancelled"}:
            state = (
                "reported_complete" if event.kind == "shipment_reported" else "paused"
            )
            c.execute(
                "UPDATE crm_plans SET stage=?,evidence=?,updated_at=? WHERE name=? AND customer_id IN (SELECT id FROM crm_customers WHERE account_id=? AND contact_id=?) AND updated_at<=?",
                (
                    state,
                    dumps(refs),
                    when,
                    event.opportunity,
                    account,
                    event.customer_ref,
                    when,
                ),
            )
            c.execute(
                "UPDATE crm_actions SET state=?,version=version+1 WHERE locked=0 AND event_time<=? AND plan_id IN (SELECT p.id FROM crm_plans p JOIN crm_customers u ON u.id=p.customer_id WHERE p.name=? AND u.account_id=? AND u.contact_id=?)",
                (
                    "done" if event.kind == "shipment_reported" else "cancelled",
                    when,
                    event.opportunity,
                    account,
                    event.customer_ref,
                ),
            )
    for item in result.actions:
        if item.customer_ref in excluded or item.contact_ref in excluded:
            continue
        if item.operation in {"create", "update", "wait"} and (
            not item.followup_required
            or item.stage in {"shipping", "reported_complete", "paused"}
        ):
            continue
        customer = c.execute(
            "SELECT * FROM crm_customers WHERE contact_id=?", (item.customer_ref,)
        ).fetchone()
        if not customer:
            review(
                c,
                account,
                "需求的客户归属待确认：" + item.summary,
                evidence_for(item.evidence_refs, evidence),
            )
            continue
        if item.plan_ref:
            known = c.execute(
                "SELECT name FROM crm_plans WHERE id=? AND customer_id=?",
                (item.plan_ref, customer["id"]),
            ).fetchone()
            if not known:
                raise ValueError("model_unknown_opportunity")
            item = item.model_copy(update={"opportunity": known["name"]})
        ended = c.execute(
            "SELECT event_time FROM business_events WHERE account_id=? AND actor_ref=? AND opportunity=? AND kind IN ('shipment_reported','cancelled') ORDER BY event_time DESC LIMIT 1",
            (account, item.customer_ref, item.opportunity),
        ).fetchone()
        if ended and item.operation in {"create", "update", "wait"}:
            continue
        evid = evidence_for(item.evidence_refs, evidence)
        when = max(evidence[r]["event_time"] for r in item.evidence_refs)
        item_key = item.action_key
        if item.opportunity and not item_key.startswith(item.opportunity + "::"):
            item_key = item.opportunity + "::" + item_key
        existing = c.execute(
            "SELECT * FROM crm_actions WHERE customer_id=? AND action_key=?",
            (customer["id"], item_key),
        ).fetchone()
        if not existing:
            candidates = c.execute(
                "SELECT a.* FROM crm_actions a LEFT JOIN crm_plans p ON p.id=a.plan_id WHERE a.customer_id=? AND COALESCE(p.name,'')=?",
                (customer["id"], item.opportunity),
            ).fetchall()

            def norm(text):
                return re.sub(r"[\W_]+", "", text)

            for candidate in candidates:
                if (
                    SequenceMatcher(
                        None, norm(candidate["summary"]), norm(item.summary)
                    ).ratio()
                    >= 0.90
                ):
                    existing = candidate
                    item_key = candidate["action_key"]
                    break
        if existing and (existing["locked"] or existing["event_time"] > when):
            continue
        plan_id = None
        if item.opportunity:
            c.execute(
                "INSERT INTO crm_plans VALUES(?,?,?,?,?,?) ON CONFLICT(customer_id,name) DO UPDATE SET stage=excluded.stage,evidence=excluded.evidence,updated_at=excluded.updated_at WHERE crm_plans.updated_at<=excluded.updated_at",
                (
                    uid(),
                    customer["id"],
                    item.opportunity,
                    item.stage,
                    dumps(evid),
                    when,
                ),
            )
            plan_id = c.execute(
                "SELECT id FROM crm_plans WHERE customer_id=? AND name=?",
                (customer["id"], item.opportunity),
            ).fetchone()[0]
        state = {
            "create": "open",
            "update": "open",
            "complete": "done",
            "cancel": "cancelled",
            "wait": "waiting_external",
        }[item.operation]
        # Keep completion/cancellation tombstones even when recent evidence
        # arrives before the older request during history backfill. They can
        # only affect the same evidenced customer and plan-scoped action key.
        from .followup_dates import due_date as resolve_due

        due = resolve_due(item.due_text, when)
        if item.due_date and not due:
            due = datetime.strptime(item.due_date, "%Y-%m-%d").date().isoformat()
        if not due:
            days = (
                2 if item.stage == "quoting" else 3 if item.stage == "preparing" else 7
            )
            day = datetime.fromisoformat(when).astimezone(TZ).date()
            while days:
                day += timedelta(days=1)
                if day.weekday() < 5:
                    days -= 1
            due = day.isoformat()
        if (
            state in {"open", "waiting_external"}
            and datetime.fromisoformat(when) < datetime.now(UTC) - timedelta(days=30)
            and due < datetime.now(TZ).date().isoformat()
        ):
            state = "historical_unresolved"
        if customer["do_not_contact"] and state == "open":
            state = "snoozed"
        c.execute(
            "INSERT INTO crm_actions(id,customer_id,plan_id,contact_id,action_key,summary,reason,party,state,due_date,due_text,date_kind,evidence,event_time,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(customer_id,action_key) DO UPDATE SET plan_id=excluded.plan_id,contact_id=excluded.contact_id,summary=excluded.summary,reason=excluded.reason,party=excluded.party,state=excluded.state,due_date=excluded.due_date,due_text=excluded.due_text,date_kind=excluded.date_kind,evidence=excluded.evidence,event_time=excluded.event_time,version=crm_actions.version+1",
            (
                uid(),
                customer["id"],
                plan_id,
                item.contact_ref or item.customer_ref,
                item_key,
                item.summary,
                item.reason,
                item.party,
                state,
                due,
                item.due_text,
                item.date_kind,
                dumps(evid),
                when,
                now(),
            ),
        )
    index_touchpoints(c, account)
    for ambiguity in result.ambiguities:
        review(
            c,
            account,
            ambiguity.question,
            evidence_for(ambiguity.evidence_refs, evidence),
        )


def valid_evidence(db, encoded):
    refs = json.loads(encoded)
    result = []
    for ref in refs:
        found = db.rows(
            "SELECT m.*,v.title conversation_title FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE m.id=? AND m.revision=? AND v.account_id=?",
            (ref["id"], ref["revision"], db.settings.source_account),
        )
        if not found:
            return []
        result.append(found[0] | classify(found[0]))
    return result


def overview(db):
    from .config import secret

    account = db.settings.source_account
    policy = db.rows("SELECT * FROM crm_policies WHERE account_id=?", (account,))
    today = datetime.now(TZ).date().isoformat()
    actions = db.rows(
        "SELECT a.*,c.name customer_name,c.do_not_contact,p.name opportunity,n.name contact_name FROM crm_actions a JOIN crm_customers c ON c.id=a.customer_id LEFT JOIN crm_plans p ON p.id=a.plan_id LEFT JOIN crm_contacts n ON n.id=a.contact_id WHERE c.account_id=? ORDER BY a.due_date,a.created_at",
        (account,),
    )
    checks = {
        r["id"]: r
        for r in db.rows(
            "SELECT a.id,json_array_length(a.evidence) refs,NOT EXISTS (SELECT 1 FROM json_each(a.evidence) e LEFT JOIN messages m ON m.id=json_extract(e.value,'$.id') LEFT JOIN conversations v ON v.id=m.conversation_id WHERE m.id IS NULL OR m.revision<>json_extract(e.value,'$.revision') OR v.account_id<>?) valid FROM crm_actions a JOIN crm_customers c ON c.id=a.customer_id WHERE c.account_id=?",
            (account, account),
        )
    }
    for a in actions:
        check = checks[a["id"]]
        a["evidence_valid"] = bool(check["refs"] and check["valid"]) or bool(
            a["locked"] and not check["refs"]
        )
    from .source_scope import allowed_evidence, counts

    excluded_actors = {
        stable_actor(account, r["source_id"])
        for r in db.rows(
            "SELECT source_id FROM actor_exclusions WHERE account_id=?", (account,)
        )
    }

    excluded_customers = {
        r["id"]
        for r in db.rows(
            "SELECT id FROM crm_customers WHERE contact_id IN (SELECT id FROM crm_contacts WHERE account_id=? AND source_id IN (SELECT source_id FROM actor_exclusions WHERE account_id=?))",
            (account, account),
        )
    }
    for action in actions:
        action["source_eligible"] = (
            action["contact_id"] not in excluded_actors
            and action["customer_id"] not in excluded_customers
            and (
                allowed_evidence(db, action["evidence"])
                if json.loads(action["evidence"])
                else bool(action["locked"])
            )
        )
    active = [
        a
        for a in actions
        if a["evidence_valid"] and a["source_eligible"] and not a["do_not_contact"]
    ]
    due = [
        a
        for a in active
        if a["state"] in {"open", "snoozed", "waiting_external"}
        and a["due_date"]
        and a["due_date"] <= today
    ]
    contact_stamps = {
        r["entity_id"]: r["stamp"]
        for r in db.rows(
            "SELECT e.entity_id,MAX(e.created_at) stamp FROM events e JOIN crm_customers c ON c.id=e.entity_id WHERE c.account_id=? AND e.kind='crm_contact' GROUP BY e.entity_id",
            (account,),
        )
    }
    cold = []
    for a in due:
        stamp = contact_stamps.get(a["customer_id"])
        if (
            a["date_kind"] != "explicit"
            and stamp
            and datetime.fromisoformat(stamp) > datetime.now(UTC) - timedelta(days=3)
            and stamp >= a["event_time"]
        ):
            continue
        cold.append(a)
    due = cold
    due.sort(
        key=lambda a: (
            a["date_kind"] != "explicit",
            a["due_date"],
            a["state"] == "waiting_external",
        )
    )
    jobs = db.rows(
        "SELECT status,COUNT(*) n FROM jobs WHERE json_extract(payload,'$.engine')='crm_v2' AND json_extract(payload,'$.conversation_id') IN (SELECT id FROM conversations WHERE account_id=?) GROUP BY status",
        (account,),
    )
    return {
        "source_scope": counts(db),
        "account_id": account,
        "account_name": db.settings.source_name or account,
        "policy": policy[0] if policy else None,
        "key_configured": bool(secret("DEEPSEEK_API_KEY")),
        "today": today,
        "actions": due[:10],
        "due_count": len(due),
        "all_actions": actions,
        "waiting_count": sum(a["state"] == "waiting_external" for a in active),
        "customers_count": db.rows(
            "SELECT COUNT(*) n FROM crm_customers WHERE account_id=?", (account,)
        )[0]["n"],
        "reviews_count": db.rows(
            "SELECT COUNT(*) n FROM crm_reviews WHERE account_id=? AND status='pending'",
            (account,),
        )[0]["n"],
        "jobs": jobs,
        "runtime": db.rows("SELECT * FROM runtime"),
        "messages": db.rows(
            "SELECT COUNT(*) n FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE v.account_id=?",
            (account,),
        )[0]["n"],
        "usage": db.rows(
            "SELECT day,SUM(COALESCE(actual,reserved)) tokens FROM usage GROUP BY day ORDER BY day DESC LIMIT 7"
        ),
    }


def customer_details(db, customer_id):
    customer = db.rows(
        "SELECT c.*,n.source_id FROM crm_customers c LEFT JOIN crm_contacts n ON n.id=c.contact_id WHERE c.id=? AND c.account_id=?",
        (customer_id, db.settings.source_account),
    )
    if not customer:
        raise ValueError("客户不存在")
    facts = db.rows(
        "SELECT * FROM crm_facts WHERE customer_id=? AND status='active' ORDER BY locked DESC,event_time DESC",
        (customer_id,),
    )
    for f in facts:
        f["sources"] = valid_evidence(db, f["evidence"])
        f["evidence_valid"] = bool(f["sources"]) or bool(f["locked"])
    identity = customer[0]["source_id"]
    from .identity import location

    locator = location(db, identity)
    locator["excluded"] = bool(
        db.rows(
            "SELECT 1 FROM actor_exclusions WHERE account_id=? AND source_id=?",
            (db.settings.source_account, identity),
        )
    )
    messages = db.rows(
        "SELECT m.*,v.title conversation_title FROM messages m JOIN conversations v ON v.id=m.conversation_id WHERE v.account_id=? AND (m.sender_id=? OR (v.kind='private' AND v.source_id=?)) ORDER BY m.event_time DESC LIMIT 300",
        (db.settings.source_account, identity, identity),
    )
    return {
        "customer": customer[0],
        "location": locator,
        "facts": facts,
        "plans": db.rows("SELECT * FROM crm_plans WHERE customer_id=?", (customer_id,)),
        "messages": [m | classify(m) for m in messages],
        "touchpoints": db.rows(
            "SELECT payload,created_at FROM events WHERE entity_id=? AND kind='crm_contact' ORDER BY created_at DESC LIMIT 10",
            (customer_id,),
        ),
    }


def transition(db, action_id, state, version, due_date=None, note=""):
    from .services import Conflict

    if (
        state not in {"open", "waiting_external", "snoozed", "done", "cancelled"}
        or type(version) is not int
    ):
        raise ValueError("任务状态无效")
    if not isinstance(note, str) or len(note) > 1000:
        raise ValueError("补充结果过长")
    if due_date is not None:
        due_date = datetime.strptime(due_date, "%Y-%m-%d").date().isoformat()
    if state == "snoozed" and not due_date:
        raise ValueError("改期需要日期")
    with db.tx() as c:
        row = c.execute(
            "SELECT a.* FROM crm_actions a JOIN crm_customers u ON u.id=a.customer_id WHERE a.id=? AND u.account_id=?",
            (action_id, db.settings.source_account),
        ).fetchone()
        if not row or row["version"] != version:
            raise Conflict("任务已更新，请刷新后重试")
        c.execute(
            "UPDATE crm_actions SET state=?,due_date=COALESCE(?,due_date),locked=?,version=version+1 WHERE id=?",
            (
                state,
                due_date,
                int(state in {"done", "cancelled", "snoozed"}),
                action_id,
            ),
        )
        db.event(
            c,
            action_id,
            "user_task_change",
            {"state": state, "due_date": due_date, "note": note},
        )
    return {"ok": True}


def resolve_review(db, review_id, resolution):
    if (
        not isinstance(resolution, str)
        or not resolution.strip()
        or len(resolution) > 1000
    ):
        raise ValueError("请简要填写确认结果")
    with db.tx() as c:
        row = c.execute(
            "SELECT * FROM crm_reviews WHERE id=? AND account_id=? AND status='pending'",
            (review_id, db.settings.source_account),
        ).fetchone()
        if not row:
            raise ValueError("确认项不存在或已处理")
        c.execute(
            "UPDATE crm_reviews SET status='resolved',resolution=? WHERE id=?",
            (resolution, review_id),
        )
        db.event(c, review_id, "review_resolved", {"resolution": resolution})
    schedule(db, retry=True)
    return {"ok": True}


def migrate_legacy(c):
    """Keep existing manually curated records visible without fabricating identities."""
    for merchant in c.execute(
        "SELECT DISTINCT m.*,v.account_id FROM merchants m JOIN conversations v ON v.merchant_id=m.id"
    ).fetchall():
        customer_id = "legacy:" + merchant["account_id"] + ":" + merchant["id"]
        c.execute(
            "INSERT OR IGNORE INTO crm_customers VALUES(?,NULL,?,?,?,?)",
            (
                customer_id,
                merchant["account_id"],
                merchant["name"],
                merchant["do_not_contact"],
                merchant["created_at"],
            ),
        )
        for task in c.execute(
            "SELECT * FROM tasks WHERE merchant_id=?", (merchant["id"],)
        ).fetchall():
            refs = []
            if task["suggestion_id"]:
                suggestion = c.execute(
                    "SELECT payload FROM suggestions WHERE id=?",
                    (task["suggestion_id"],),
                ).fetchone()
                if suggestion:
                    refs = json.loads(suggestion["payload"]).get("evidence", [])
            c.execute(
                "INSERT OR IGNORE INTO crm_actions(id,customer_id,action_key,summary,reason,party,state,due_date,due_text,date_kind,evidence,event_time,locked,version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task["id"],
                    customer_id,
                    "legacy:" + task["id"],
                    task["summary"],
                    "保留原工作台的人工确认事项",
                    task["party"],
                    task["state"],
                    task["due_at"][:10] if task["due_at"] else None,
                    task["due_text"],
                    "explicit",
                    dumps(refs),
                    task["created_at"],
                    1,
                    task["version"],
                    task["created_at"],
                ),
            )
