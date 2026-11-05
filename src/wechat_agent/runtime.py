"""One local start command owns collection, resumable archive and model worker."""

import fcntl
import os
import threading
import time
from datetime import UTC, datetime

from .analysis import run_once
from .archive import discover, import_history, register
from .collector import Collector
from .crm import schedule


class Runtime:
    def __init__(self, db, source_factory=Collector):
        self.db = db
        self.source_factory = source_factory
        self.stop = threading.Event()
        self.threads = []
        self.lock = None

    def start(self):
        self.lock = os.open(
            self.db.settings.data_dir / "runtime.lock", os.O_CREAT | os.O_RDWR, 0o600
        )
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.lock)
            self.lock = None
            raise RuntimeError(
                "此数据目录的后台已运行，请停止旧 start/serve 后再启动"
            ) from None
        for target in (self.collect, self.analyze):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=2)
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None

    def collect(self):
        discovered = 0
        while not self.stop.is_set():
            source = None
            try:
                if not self.db.settings.source_account:
                    self.db.heartbeat("collector", "awaiting_account")
                    self.stop.wait(5)
                    continue
                source = self.source_factory(self.db)
                if time.monotonic() - discovered > 300:
                    register(
                        self.db,
                        discover(source),
                        int(datetime.now(UTC).timestamp()),
                        preserve_paused=True,
                    )
                    discovered = time.monotonic()
                source.tick()
                import_history(self.db, source, delay=0, max_pages=1, stop=self.stop)
                self.db.heartbeat("collector", "running")
            except Exception as exc:
                # Never expose credential-bearing HTTP strings or message bodies.
                self.db.heartbeat("collector", "error:" + type(exc).__name__)
            finally:
                if source:
                    source.client.close()
            self.stop.wait(10)

    def analyze(self):
        while not self.stop.is_set():
            try:
                policy = self.db.rows(
                    "SELECT enabled FROM crm_policies WHERE account_id=?",
                    (self.db.settings.source_account,),
                )
                if not policy or not policy[0]["enabled"]:
                    self.db.heartbeat("worker", "awaiting_authorization")
                    self.stop.wait(5)
                    continue
                with self.db.tx() as c:
                    from .db import now

                    c.execute(
                        "UPDATE jobs SET status='queued',attempts=0 WHERE status='blocked_budget' AND available_at<=?",
                        (now(),),
                    )
                schedule(self.db)
                worked = run_once(self.db)
                if not worked:
                    self.db.heartbeat("worker", "idle")
                self.stop.wait(0.2 if worked else 5)
            except Exception as exc:
                self.db.heartbeat("worker", "error:" + type(exc).__name__)
                self.stop.wait(5)
