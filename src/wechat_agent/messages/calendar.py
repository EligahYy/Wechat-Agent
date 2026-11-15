"""Calendar metadata and day boundaries are always Beijing local time."""
from datetime import date,datetime,time,timedelta,timezone
from .queries import timeline_sources
from ..operations.service import OperationError

def day_bounds(value):
    try:
        local=date.fromisoformat(value)
        if local.isoformat()!=value:raise ValueError()
        start=datetime.combine(local,time(),timezone(timedelta(hours=8)))
        return start.isoformat(),(start+timedelta(days=1)).isoformat()
    except (ValueError,TypeError,OverflowError):raise OperationError('message_day_invalid',422) from None

def read_calendar(conn,account,contact,month,conversation_id=None):
    sources=timeline_sources(conn,account,contact,conversation_id)
    try:
        first=date.fromisoformat(month+'-01')
        if first.strftime('%Y-%m')!=month:raise ValueError()
    except (ValueError,TypeError):raise OperationError('message_month_invalid',422) from None
    where="m.account_id=? AND m.kind NOT IN ('system','revoke') AND (m.sender_id=? OR m.conversation_id IN (SELECT conversation_id FROM members WHERE account_id=? AND contact_id=?))"
    params=[account,contact,account,contact]
    if conversation_id:where+=' AND m.conversation_id=?';params.append(conversation_id)
    latest=conn.execute("SELECT MAX(date(m.sent_at,'+8 hours')) FROM messages m WHERE "+where,params).fetchone()[0]
    earliest=conn.execute("SELECT MIN(date(m.sent_at,'+8 hours')) FROM messages m WHERE "+where,params).fetchone()[0]
    days={row[0]:row[1] for row in conn.execute("SELECT date(m.sent_at,'+8 hours') AS day,COUNT(*) FROM messages m WHERE "+where+" AND strftime('%Y-%m',m.sent_at,'+8 hours')=? GROUP BY day",[*params,month]) if row[0]}
    return {'month':month,'days':days,'latest_day':latest,'earliest_day':earliest,'sources':sources,'timezone':'Asia/Shanghai'}
