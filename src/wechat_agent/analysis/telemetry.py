"""Operation stage totals, measured without retaining source or provider text."""
import json
from time import monotonic

from ..source.repository import transaction


def record_stage(conn, account_id: str, operation_id: str, stage: str, started: float) -> None:
    elapsed_ms = max(0, round((monotonic() - started) * 1000))
    key = f'timing_{stage}_ms'
    with transaction(conn):
        row = conn.execute(
            'SELECT counts_json FROM operations WHERE account_id=? AND id=?',
            (account_id, operation_id),
        ).fetchone()
        if row is None:
            return
        counts = json.loads(row[0])
        counts[key] = counts.get(key, 0) + elapsed_ms
        conn.execute('UPDATE operations SET counts_json=? WHERE account_id=? AND id=?',
                     (json.dumps(counts), account_id, operation_id))
