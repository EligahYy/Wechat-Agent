"""Account-scoped archive reads conceal resources outside the selected account."""
from ..accounts import AccountError, authorize_account
from ..operations.service import OperationError


def authorize_archive(conn, request, account_id):
    try:
        authorize_account(conn,request.app.state.settings,request.app.state.services,account_id)
    except AccountError as error:
        if error.status in (403,409):
            raise OperationError('archive_not_found',404) from None
        raise
