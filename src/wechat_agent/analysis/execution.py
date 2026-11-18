"""Durable per-operation request quotas, separate from per-unit retry limits."""
from dataclasses import dataclass
import time

from ..model.contracts import ModelCallError


@dataclass(frozen=True)
class ExecutionBudget:
    max_calls: int = 20
    max_elapsed_seconds: int = 600

    def reserve(self, conn, account_id: str, operation_id: str) -> None:
        # Called in the same transaction as model attempt reservation.
        now = time.time()
        conn.execute(
            'INSERT INTO analysis_execution(account_id,operation_id,started_at) VALUES(?,?,?) ON CONFLICT DO NOTHING',
            (account_id, operation_id, now),
        )
        updated = conn.execute(
            '''UPDATE analysis_execution SET requests=requests+1
               WHERE account_id=? AND operation_id=? AND requests<? AND started_at>?''',
            (account_id, operation_id, self.max_calls, now-self.max_elapsed_seconds),
        )
        if not updated.rowcount:
            raise ModelCallError('analysis_budget_paused')
