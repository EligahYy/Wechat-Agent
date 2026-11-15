"""Author-only monthly metadata and Beijing day boundaries."""
from datetime import date,datetime,time,timedelta,timezone
from .queries import timeline_sources,message_scope
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
        following=date(first.year+int(first.month==12),first.month%12+1,1)
    except (ValueError,TypeError,OverflowError):raise OperationError('message_month_invalid',422) from None
    where="account_id=? AND sender_id=? AND kind NOT IN ('system','revoke') AND julianday(sent_at) IS NOT NULL"
    params=[account,contact]
    allowed={row['conversation_id'] for row in sources}
    if conversation_id:allowed&={conversation_id}
    if allowed:
        where+=' AND conversation_id IN ('+','.join('?' for _ in allowed)+')';params.extend(sorted(allowed))
    else:where+=' AND 0'
    edges=[]
    for direction in ('DESC','ASC'):
        row=conn.execute("SELECT date(sent_at,'+8 hours') FROM messages WHERE "+where+f' ORDER BY julianday(sent_at) {direction},message_id {direction} LIMIT 1',params).fetchone()
        edges.append(row[0] if row else None)
    start=day_bounds(first.isoformat())[0];end=day_bounds(following.isoformat())[0]
    days={row[0]:row[1] for row in conn.execute("SELECT date(sent_at,'+8 hours') AS day,COUNT(*) FROM messages WHERE "+where+" AND julianday(sent_at)>=julianday(?) AND julianday(sent_at)<julianday(?) GROUP BY day",[*params,start,end]) if row[0]}
    if edges[0] is None:
        # Outgoing-only verified private chats remain reachable without blue dots.
        private=[row for row in sources if row['kind']=='private']
        fallback,values=message_scope(conn,account,contact,sources=private,conversation_id=conversation_id)
        for i,direction in enumerate(('DESC','ASC')):
            row=conn.execute("SELECT date(m.sent_at,'+8 hours') FROM messages m WHERE "+fallback+f' ORDER BY julianday(m.sent_at) {direction},m.message_id {direction} LIMIT 1',values).fetchone()
            edges[i]=row[0] if row else None
    return {'month':month,'days':days,'speech_days':days,'latest_day':edges[0],'earliest_day':edges[1],'sources':sources,'timezone':'Asia/Shanghai'}
