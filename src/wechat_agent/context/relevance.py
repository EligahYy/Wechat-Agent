"""Deterministic, customer-scoped triage of authorized message revisions."""

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict


RULE_VERSION = 'text-relevance-v2'
FIELDS = {
    'goods.products': r'货品|品名|塑料|服装|配件|收纳盒|电池|纯电|带电|液体|粉末',
    'goods.special_attributes': r'纯电|带电|液体|粉末|磁性|敏感货|危险品',
    'goods.volume': r'货量|体积|多少方|几箱|\d\s*(?:方|箱|件|托|公斤|千克|吨|kg\b|cbm\b|m³|m3\b)',
    'logistics.origins': r'起运|始发|从.{1,10}(?:发货|出发|提货)',
    'logistics.destinations': r'目的地|发往|到仓|德国|法国|英国|西班牙|荷兰|波兰|欧洲',
    'logistics.warehouse_postcode': r'邮编|仓库|海外仓|FBA\b',
    'logistics.transport': r'卡航|空运|海运|铁路|快递|汽运|拼柜|整柜',
    'logistics.clearance_tax': r'清关|含税|包税|税号|VAT\b|DDP\b|关税',
    'logistics.timing': r'时效|到货|预计.{0,8}到|\d\s*(?:天内|工作日)|催件',
    'logistics.price': r'报价|询价|运费|价格|费率|\d\s*(?:元|欧元|美金|rmb\b|eur\b|usd\b)',
    'logistics.pickup_lastmile': r'提货|派送|入仓|自提|上门取',
    'communication.summary': r'确认|暂缓|取消|改成|延后|先别|先不|按原|不要发|换成',
    'shipments': r'已发|发车|出境|放行|卸货|签收|妥投|备货|单号|运单|柜号|这票|这批',
}
PATTERNS = [(field, re.compile(pattern, re.I)) for field, pattern in FIELDS.items()]
NOISE = re.compile(r'(?:早上好|早安|晚安|你好|您好|节日快乐|哈哈+|\[表情\]|[👍😂🙂🙏❤❤️]+)[!！。\s]*')
CHANGE = re.compile(r'改成|改为|换成|先别|先不|取消|已发|签收|暂缓|放行|卸货|延后')
ATTACHMENT_KINDS = {'image', 'video', 'voice', 'file', 'attachment', 'link', 'forward'}


class RelevanceEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    message_id: str
    revision: int
    level: Literal['high', 'medium', 'low']
    field_paths: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    needs_review: bool = False
    usable: bool = False


class RelevanceManifest(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule_version: str = RULE_VERSION
    entries: tuple[RelevanceEntry, ...]


def reviewable(entry: RelevanceEntry) -> bool:
    return (
        entry.level == 'medium' and entry.usable and entry.needs_review
        and ('business_change_review' in entry.reason_codes
             or any(path != 'communication.summary' for path in entry.field_paths))
    )


def has_review_gap(entry: RelevanceEntry) -> bool:
    return reviewable(entry) or any(
        code in {'revocation_review', 'ambiguous_recipients', 'attachment_unprocessed'}
        for code in entry.reason_codes
    )


def classify_messages(snapshot, rows, actors, conversations, *, known_batches=(), reviewed_refs=()):
    contact = snapshot.key.contact_id
    results = {}
    known_numbers = {
        str(number) for batch in known_batches for number in batch.get('numbers', ())
        if len(str(number)) >= 5
    }
    names = {}
    for identifier, actor in actors.items():
        if name := actor.get('name'):
            names.setdefault(name, set()).add(identifier)
    examined = set(reviewed_refs)
    for row in rows:
        identifier, revision = row['message_id'], row['revision']
        body = unicodedata.normalize('NFKC', row['body']).strip()
        sender = row['sender_id']
        room = row['conversation_id']
        parent = results.get(row.get('reply_to'))
        if parent is not None and parent[0] != room:
            parent = None
        prior = parent[1] if parent else None
        fields = tuple(field for field, pattern in PATTERNS if pattern.search(body))
        matched_batch = any(part in known_numbers for part in re.findall(r'\b[A-Za-z0-9-]{5,}\b', body))
        mentions = set().union(*(names.get(name, set()) for name in re.findall(r'@([^\s，,。:：]+)', body)))
        known_customer = sender == contact or conversations.get(room, {}).get('kind') == 'private'
        linked = prior is not None and prior.usable
        if linked and CHANGE.search(body):
            fields = tuple(sorted(set(fields) | set(prior.field_paths)))
        attributable = known_customer or linked or mentions == {contact} or matched_batch
        # An explicit other recipient takes precedence over a nearby conversation or number.
        other_recipients = {person for person in mentions - {contact}
                            if actors.get(person, {}).get('role') == 'merchant'}
        mixed_recipients = bool(other_recipients) and contact in mentions
        other_customer = bool(other_recipients) or (
            sender != contact and actors.get(sender, {}).get('role') == 'merchant'
        )
        local = dict(message_id=identifier, revision=revision, field_paths=fields)
        active = row.get('author_state') == 'active'
        kind = row['kind']
        if kind == 'revoke':
            entry = RelevanceEntry(**local, level='medium', needs_review=True,
                                   reason_codes=('revocation_review',))
        elif kind == 'system':
            entry = RelevanceEntry(**local, level='low', reason_codes=('system_event',))
        elif mixed_recipients:
            entry = RelevanceEntry(**local, level='medium', needs_review=True, reason_codes=('ambiguous_recipients',))
        elif other_customer:
            entry = RelevanceEntry(**local, level='low', reason_codes=('other_customer',))
        elif row.get('attachments') or kind in ATTACHMENT_KINDS:
            if kind in {'text', 'quote'} and active and attributable and fields:
                entry = RelevanceEntry(**local, level='high', needs_review=True, usable=True,
                                       reason_codes=('field_match', 'attachment_unprocessed'))
            else:
                entry = RelevanceEntry(**local, level='medium', needs_review=True,
                                       reason_codes=('attachment_unprocessed',))
        elif active and attributable and (identifier, revision) in examined:
            entry = RelevanceEntry(**local, level='high', usable=True, reason_codes=('reviewed',))
        elif active and attributable and (fields or matched_batch) and (
            fields != ('communication.summary',) or CHANGE.search(body) and linked
        ):
            entry = RelevanceEntry(**local, level='high', usable=True,
                                   dependencies=(prior.message_id,) if linked else (),
                                   reason_codes=('linked_reply',) if linked else ('field_match',))
        elif NOISE.fullmatch(body) and not linked:
            entry = RelevanceEntry(**local, level='low', reason_codes=('greeting_or_reaction',))
        else:
            business_change = bool(active and attributable and CHANGE.search(body))
            entry = RelevanceEntry(**local, level='medium', usable=active and attributable,
                                   dependencies=(prior.message_id,) if linked else (),
                                   reason_codes=('business_change_review',) if business_change else ('context_required',),
                                   needs_review=business_change or any(path != 'communication.summary' for path in fields))
        results[identifier] = (room, entry)
    return RelevanceManifest(entries=tuple(entry for _, entry in results.values()))
