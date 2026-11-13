"""Fail closed outside the macOS Keychain; never fall back to plaintext files."""
import sys
from .contracts import ModelCallError

class CredentialStore:
    def _backend(self):
        if sys.platform!='darwin':raise ModelCallError('credential_store_unsupported')
        from keyring.backends.macOS import Keyring
        return Keyring()
    def get(self,ref:str)->str:
        try:value=self._backend().get_password('Wechat-Agent',ref)
        except Exception:raise ModelCallError('credential_unavailable') from None
        if not value:raise ModelCallError('credential_missing')
        return value
    def set(self,ref:str,value:str)->None:
        if not value.strip():raise ModelCallError('credential_empty')
        try:self._backend().set_password('Wechat-Agent',ref,value)
        except Exception:raise ModelCallError('credential_unavailable') from None
