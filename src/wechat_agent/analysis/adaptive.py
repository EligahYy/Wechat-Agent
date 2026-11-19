"""Small persistent workload feedback, pinned once for each archive window."""
from dataclasses import dataclass, replace

from ..source.repository import transaction


EXTRACT_MATERIAL_PHASE = "extract-material-v1"


@dataclass(frozen=True)
class WorkPolicy:
    target: int = 24_000
    low_load_streak: int = 0

    def observe(self, status: str, elapsed_ms: int, completion: int | None, reserved: int):
        if status in {'model_timeout', 'output_truncated'}:
            return WorkPolicy(max(8_000, self.target // 2))
        if status != 'succeeded':
            return self
        if completion is not None and elapsed_ms < 60_000 and completion * 2 < reserved:
            if self.low_load_streak >= 1:
                return WorkPolicy(min(48_000, self.target * 5 // 4))
            return replace(self, low_load_streak=self.low_load_streak + 1)
        return replace(self, low_load_streak=0)


def pinned_target(conn, account, contact, config_version, conversation, window, phase='extract'):
    with transaction(conn):
        feedback = conn.execute(
            'SELECT target FROM analysis_workload_feedback WHERE account_id=? AND config_version=? AND phase=?',
            (account, config_version, phase),
        ).fetchone()
        conn.execute(
            '''INSERT INTO analysis_workload_plans VALUES(?,?,?,?,?,?,?)
               ON CONFLICT DO NOTHING''',
            (account, contact, config_version, conversation, window, phase,
             feedback[0] if feedback else WorkPolicy.target),
        )
        return conn.execute(
            '''SELECT target FROM analysis_workload_plans WHERE account_id=? AND contact_id=?
               AND config_version=? AND conversation_id=? AND window_key=? AND phase=?''',
            (account, contact, config_version, conversation, window, phase),
        ).fetchone()[0]


def observe_attempt(conn, account, config_version, phase, status, elapsed_ms, usage, reserved):
    previous = conn.execute(
        'SELECT target,low_load_streak FROM analysis_workload_feedback WHERE account_id=? AND config_version=? AND phase=?',
        (account, config_version, phase),
    ).fetchone()
    policy = WorkPolicy(*previous) if previous else WorkPolicy()
    next_policy = policy.observe(status, elapsed_ms, usage.get('completion_tokens'), reserved)
    if next_policy == policy:
        return
    conn.execute(
        '''INSERT INTO analysis_workload_feedback VALUES(?,?,?,?,?)
           ON CONFLICT(account_id,config_version,phase) DO UPDATE SET
           target=excluded.target, low_load_streak=excluded.low_load_streak''',
        (account, config_version, phase, next_policy.target, next_policy.low_load_streak),
    )
