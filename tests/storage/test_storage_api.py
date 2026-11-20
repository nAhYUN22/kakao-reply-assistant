from fastapi.testclient import TestClient

from kakaoreply.api import create_app
from kakaoreply.crypto import DataCipher
from kakaoreply.engine import Engine
from kakaoreply.storage import Journal


def test_encrypted_api_delete_preserves_audit_and_auth(tmp_path):
    engine = Engine(Journal(str(tmp_path / 'a.sqlite'), cipher=DataCipher(b'k' * 32, 'synthetic')))
    with TestClient(create_app(engine=engine), base_url='http://127.0.0.1:8765') as client:
        assert client.get('/api/storage').status_code == 401
        token = client.get('/api/session').json()['token']
        client.headers['X-Session-Token'] = token
        assert client.get('/api/storage').json() == {'schema_version': 2, 'body_storage': 'aead', 'raw_retention_days': 7}
        client.post('/api/simulator/start', json={'mode': 'auto'})
        client.post('/api/simulator/messages', json={'text': '합성', 'origin': 'partner'})
        state = client.post('/api/simulator/advance', json={'seconds': 600}).json()
        job_id = state['jobs'][0]['job_id']
        route = f'/api/jobs/{job_id}/body'
        assert client.get(f'/api/jobs/{job_id}').json()['reply_text']
        assert client.delete(route, headers={'Origin': 'https://untrusted.invalid'}).status_code == 403
        assert client.delete(route, headers={'X-Session-Token': 'wrong'}).status_code == 401
        result = client.delete(route)
        assert result.status_code == 200
        assert result.json()['simulated_send_count'] == 1
        assert client.get(f'/api/jobs/{job_id}').json()['reply_text'] is None
        assert len(engine.journal.attempts()) == 1
        assert 'text' not in engine.transport.attempts[0]
        assert client.delete('/api/jobs/missing/body').status_code == 404


def test_locked_body_read_stops_runtime_without_leaking_error(tmp_path):
    locked = False
    def key_check():
        if locked:
            raise RuntimeError('SYNTHETIC_SECRET_BACKEND_ERROR')
    journal = Journal(str(tmp_path / 'a.sqlite'), cipher=DataCipher(b'k' * 32, 'synthetic'), key_check=key_check)
    engine = Engine(journal)
    with TestClient(create_app(engine=engine), base_url='http://127.0.0.1:8765') as client:
        client.headers['X-Session-Token'] = client.get('/api/session').json()['token']
        client.post('/api/simulator/start', json={'mode': 'auto'})
        client.post('/api/simulator/messages', json={'text': '합성', 'origin': 'partner'})
        state = client.post('/api/simulator/advance', json={'seconds': 600}).json()
        locked = True
        result = client.get('/api/jobs/' + state['jobs'][0]['job_id'])
        assert result.status_code == 409
        assert result.json() == {'detail': 'OPERATION_REJECTED'}
        assert client.get('/api/state').json()['mode'] == 'off'
