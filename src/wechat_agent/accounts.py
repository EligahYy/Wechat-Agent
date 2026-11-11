"""Resolve the application's selected account without contacting WeChat."""

import json

from .source.probe import SourceConfig


class AccountError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


def selected_account(conn, settings, services):
    binding = None
    if settings.source_config:
        try:
            binding = SourceConfig.model_validate(json.loads(settings.source_config.read_text())).expected_account_id
        except (OSError, ValueError, TypeError):
            raise AccountError("account_configuration_invalid", 503) from None
    if services.source is not None:
        if binding and binding != services.source.account_id:
            raise AccountError("account_configuration_mismatch", 503)
        binding = services.source.account_id
    if binding is None:
        rows = conn.execute("SELECT account_id FROM accounts ORDER BY account_id LIMIT 2").fetchall()
        if len(rows) != 1:
            raise AccountError("account_binding_required")
        binding = rows[0][0]
    return binding


def authorize_account(conn, settings, services, account_id):
    if selected_account(conn, settings, services) != account_id:
        raise AccountError("account_scope_forbidden", 403)
