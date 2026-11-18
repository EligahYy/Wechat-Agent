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
        self.snapshot=snapshot
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

    def restrict(self, rows):
        """A validated excerpt view preserves the frozen snapshot authority."""
        visible = {}
        for row in rows:
            key = (row['message_id'], row['revision'])
            original = self._messages.get(key)
            if original is None:
                raise SnapshotError('source_outside_snapshot')
            span = row.get('body_fragment')
            if span is None:
                visible[key] = [original['body']]
                continue
            start, end = span['start'], span['end']
            if not 0 <= start <= end <= len(original['body']):
                raise SnapshotError('source_fragment_invalid')
            visible.setdefault(key, []).append(original['body'][start:end])
        view = copy.copy(self)
        view._messages = {key: {**self._messages[key], 'body': '\n'.join(parts)} for key, parts in visible.items()}
        view._payload = {**self._payload, 'messages': list(view._messages.values())}
        return view
