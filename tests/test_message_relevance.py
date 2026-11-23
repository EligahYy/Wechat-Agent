from types import SimpleNamespace

from wechat_agent.source.contracts import ContactKey


def classify(rows, **kwargs):
    from wechat_agent.context.relevance import classify_messages
    snapshot = SimpleNamespace(key=ContactKey(account_id='a', contact_id='merchant'))
    actors = {'merchant': {'name': '甲'}, 'other': {'name': '乙', 'role': 'merchant'}}
    return classify_messages(snapshot, rows, actors, {'room': {'kind': 'group'}}, **kwargs).entries


def row(identifier, body, sender='merchant', reply=None, kind='text'):
    return dict(message_id=identifier, revision=1, body=body, sender_id=sender,
                conversation_id='room', reply_to=reply, kind=kind, author_state='active')


def test_two_customers_and_cross_month_correction():
    result = classify([
        row('first', '这票 15 方'),
        row('change', '改成 12，先别发', reply='first'),
        row('other', '发德国，报价 15 元', sender='other'),
        row('unknown', '报价 15 元', sender='provider'),
    ])
    assert [entry.level for entry in result] == ['high', 'high', 'low', 'medium']
    assert result[-1].needs_review
    assert result[1].dependencies == ('first',)


def test_noise_unusual_business_and_attachment_only():
    rows = [row('hello', '早上好'), row('ambiguous', '按上次那个'), row('number', '1234567'),
            row('attachment', '[图片]', kind='image')]
    result = classify(rows)
    assert result == classify(rows)
    assert [entry.level for entry in result] == ['low', 'medium', 'medium', 'medium']
    assert result[-1].needs_review


def test_reply_with_explicit_mixed_recipients_is_not_evidence():
    result = classify([
        row('first', '这票 15 方'),
        row('reply', '@甲 @乙 报价 15 元', sender='provider', reply='first'),
    ])
    assert result[1].level == 'medium' and result[1].needs_review and not result[1].usable
