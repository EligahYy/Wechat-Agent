"""Readers authorize against persisted manifests, not caller-supplied ref lists."""
import copy
import json
from .contracts import ContextSnapshot,SnapshotError
from ..profiles.contracts import SourceRef

class ContextReader:
    def __init__(self,conn,snapshot:ContextSnapshot):
        snapshot=ContextSnapshot.model_validate(snapshot)
        saved=conn.execute('SELECT manifest_json,payload_json FROM snapshots WHERE account_id=? AND snapshot_id=? AND contact_id=?',
            (snapshot.key.account_id,snapshot.id,snapshot.key.contact_id)).fetchone()
        if saved is None or ContextSnapshot.model_validate_json(saved['manifest_json'])!=snapshot:
            raise SnapshotError('snapshot_not_authorized')
        self._payload=json.loads(saved['payload_json'])
        self._messages={(row['message_id'],row['revision']):row for row in self._payload['messages']}

    def messages(self)->list[dict]:return copy.deepcopy(self._payload['messages'])
    def actors(self)->dict:return copy.deepcopy(self._payload['actors'])
    def conversations(self)->dict:return copy.deepcopy(self._payload['conversations'])

    def manual(self)->dict:return copy.deepcopy(self._payload.get('manual',{'fields':{},'notes':{}}))

    def resolve(self,ref:SourceRef)->dict:
        ref=SourceRef.model_validate(ref)
        row=self._messages.get((ref.message_id,ref.revision))
        if row is None:raise SnapshotError('source_outside_snapshot')
        if ref.attachment_id is not None and ref.attachment_id not in {item['attachment_id'] for item in row['attachments']}:
            raise SnapshotError('attachment_outside_snapshot')
        if ref.locator is not None:raise SnapshotError('attachment_locator_not_processed')
        return copy.deepcopy(row)
