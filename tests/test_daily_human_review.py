from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api.routes import daily
from backend.data.database import Base, get_db
from backend.data.models.decision import PendingAIAction
from backend.data.models.job import JobRun
from backend.evidence.daily_panel import CARD_TYPES
from backend.ops.run_envelope import build_run_envelope
from backend.research import daily_review as service


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(service, '_now', lambda: datetime(2026, 9, 16, 10, tzinfo=UTC))
    monkeypatch.delenv('MINGCANG_AGENT_MODE', raising=False)
    engine = create_engine(f'sqlite:///{tmp_path / "review.db"}', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    path = tmp_path / 'postmarket_2026-09-16.daily_panel.json'
    coverage = {'workflow': 'm63_daily', 'mode': 'postmarket', 'required_steps': ['m59_panel']}
    envelope = build_run_envelope(run_id='source-run', job_name='m63_postmarket', trigger_source='manual_cli',
                                 as_of='2026-09-16', row_status='success', input_coverage=coverage,
                                 result={'ok': True, 'date': '2026-09-16', 'steps': [{'name': 'm59_panel', 'ok': True}]})
    assert envelope['status'] == 'complete'
    cards = [{'card_type': kind, 'lifecycle': 'stable', 'status': 'ready', 'summary': '研究记录', 'payload': {},
              'run_ref': {'run_id': 'source-run'}} for kind in CARD_TYPES]
    cards[1]['payload']['items'] = [
        {'symbol': '600001', 'name': '合成样本甲', 'recommendation': '等待核实', 'expires_at': '2026-09-16'},
        {'symbol': '600001', 'name': '合成样本甲', 'recommendation': '等待核实', 'expires_at': '2026-09-16'},
    ]
    cards[2]['payload']['items'] = [{'symbol': '600002', 'name': '合成持仓', 'quantity': 100, 'avg_cost': 10}]
    cards[6]['payload']['pending_queue'] = [{'id': 'q-1', 'target': '600003', 'reason': '补充证据', 'status': 'pending'}]
    panel = {'schema_version': 'daily_panel.v1', 'as_of': '2026-09-16', 'ledger_commit_state': 'committed',
             'run_envelope': envelope, 'cards': cards, 'artifact_contract': {'source_job_run_id': 'source-run', 'close_confirmed': True}}
    path.write_text(json.dumps(panel))
    with Session() as db:
        db.add(JobRun(run_id='source-run', job_name='m63_postmarket', trigger_source='manual_cli', as_of='2026-09-16',
                      status='success', started_at=datetime(2026, 9, 16), runtime_version='test', build_commit='test',
                      db_role='primary', input_coverage_json=json.dumps(coverage),
                      output_summary_json=json.dumps({'run_envelope': envelope}), artifact_path=str(path)))
        db.commit()
    app = FastAPI()
    app.include_router(daily.router)
    def get_test_db():
        with Session() as db:
            yield db
    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app) as client:
        yield client, Session, path
    engine.dispose()


def body(item, choice='accepted'):
    return {'as_of': item['panel_as_of'], 'panel_sha256': item['panel_sha256'], 'item_id': item['item_id'],
            'choice': choice, 'rationale': '我已核对原始资料', 'revised_text': '继续等待更新资料' if choice == 'modified' else ''}


def first(client):
    result = client.get('/daily/reviews?as_of=2026-09-16')
    assert result.status_code == 200
    assert result.json()['warning'] is None
    return result.json()['items'][0]


@pytest.mark.parametrize('choice', ['accepted', 'modified', 'rejected'])
def test_review_survives_reload_and_never_executes(environment, monkeypatch, choice):
    client, Session, path = environment
    original = path.read_bytes()
    item = first(client)
    assert len(client.get('/daily/reviews').json()['items']) == 3  # identical candidates dedupe
    response = client.post('/daily/reviews', json=body(item, choice))
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['result']['decision']['choice'] == choice
    assert saved['source']['original']['recommendation'] == '等待核实'
    assert saved['result']['actual_execution'] == 'not_recorded'
    assert saved['can_execute'] is False
    assert client.post('/daily/reviews', json=body(item, choice)).json() == saved
    with Session() as db:
        assert db.query(PendingAIAction).count() == 1
        row = db.query(PendingAIAction).one()
        assert row.status == 'reviewed'
        assert row.executed_at is None
        from backend.api.routes import ai
        monkeypatch.setattr(ai, '_execute_action', lambda *a: pytest.fail('research review executed an action'))
        assert ai.confirm_action(row.action_id, db=db)['status'] == 'reviewed'
    assert first(client)['review'] == saved
    assert path.read_bytes() == original
    changed = body(item, 'rejected' if choice != 'rejected' else 'accepted')
    assert client.post('/daily/reviews', json=changed).status_code == 409


def test_append_outcome_is_versioned_idempotent_and_keeps_original(environment):
    client, _, _ = environment
    saved = client.post('/daily/reviews', json=body(first(client), 'modified')).json()
    url = f"/daily/reviews/{saved['review_id']}/outcomes"
    outcome = {'expected_version': 1, 'observation_id': 'observe-1', 'status': 'inconclusive', 'note': '公告仍不足以核实'}
    updated = client.post(url, json=outcome)
    assert updated.status_code == 200
    assert updated.json()['result']['version'] == 2
    assert updated.json()['source'] == saved['source']
    assert updated.json()['result']['decision'] == saved['result']['decision']
    assert client.post(url, json=outcome).json() == updated.json()
    assert client.post(url, json={**outcome, 'note': 'overwrite'}).status_code == 409
    assert client.post(url, json={**outcome, 'observation_id': 'observe-2'}).status_code == 409
    assert client.get('/daily/reviews').json()['history'][0]['result']['version'] == 2


@pytest.mark.parametrize('failure', ['pending', 'wrong_run', 'changed_bytes', 'unknown_item', 'incomplete_cards'])
def test_unbound_or_changed_evidence_cannot_be_accepted(environment, failure):
    client, Session, path = environment
    request = body(first(client))
    panel = json.loads(path.read_text())
    if failure == 'pending':
        panel['ledger_commit_state'] = 'pending'
    elif failure == 'wrong_run':
        panel['run_envelope']['run_id'] = 'different'
    elif failure == 'incomplete_cards':
        panel['cards'].pop()
    elif failure == 'changed_bytes':
        panel['cards'][1]['payload']['items'][0]['recommendation'] = '新建议'
    else:
        request['item_id'] = 'f' * 64
    path.write_text(json.dumps(panel))
    assert client.post('/daily/reviews', json=request).status_code in (404, 409)
    with Session() as db:
        assert db.query(PendingAIAction).count() == 0


def test_expired_evidence_can_only_be_rejected_and_pending_task_is_not_completed(environment):
    client, _, path = environment
    panel = json.loads(path.read_text())
    for item in panel['cards'][1]['payload']['items']:
        item['expires_at'] = '2026-09-15'
    path.write_text(json.dumps(panel))
    item = first(client)
    assert item['validity'] == 'expired'
    assert client.post('/daily/reviews', json=body(item)).status_code == 409
    assert client.post('/daily/reviews', json=body(item, 'rejected')).status_code == 200
    queue = client.get('/daily/reviews').json()['items'][2]
    saved = client.post('/daily/reviews', json=body(queue)).json()
    assert saved['source']['original']['status'] == 'pending'
    assert saved['result']['queue_task_completed'] is False


def test_remote_guard_and_extra_trade_fields_fail_before_writing(environment, monkeypatch):
    client, Session, _ = environment
    request = body(first(client))
    assert client.post('/daily/reviews', json={**request, 'position_pct': 20}).status_code == 422
    monkeypatch.setenv('MINGCANG_AGENT_MODE', 'remote')
    monkeypatch.setenv('MINGCANG_AGENT_API_KEY', 'test-key')
    monkeypatch.setenv('MINGCANG_AGENT_REMOTE_WRITE_ENABLED', 'true')
    monkeypatch.setenv('MINGCANG_AGENT_REMOTE_WRITE_ACTIONS', 'watchlist.add')
    assert client.post('/daily/reviews', json=request).status_code == 401
    assert client.post('/daily/reviews', json=request, headers={'x-mingcang-agent-api-key': 'test-key'}).status_code == 403
    with Session() as db:
        assert db.query(PendingAIAction).count() == 0
    url = '/daily/reviews/daily-review:' + request['item_id'] + '/outcomes'
    observation = {'expected_version': 1, 'observation_id': 'guard-check', 'status': 'inconclusive', 'note': '测试'}
    assert client.post(url, json=observation).status_code == 401
    assert client.post(url, json=observation, headers={'x-mingcang-agent-api-key': 'test-key'}).status_code == 403


def test_concurrent_same_choice_records_once(environment):
    client, Session, _ = environment
    request = body(first(client))
    def save(_):
        with Session() as db:
            return service.record_review(db, **request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert results[0]['review_id'] == results[1]['review_id']
    with Session() as db:
        assert db.query(PendingAIAction).count() == 1


def test_concurrent_outcomes_cannot_overwrite_each_other(environment):
    client, Session, _ = environment
    saved = client.post('/daily/reviews', json=body(first(client))).json()
    def observe(index):
        with Session() as db:
            try:
                return service.record_outcome(db, review_id=saved['review_id'], expected_version=1,
                                              observation_id=f'observe-{index}', status='inconclusive', note=f'观察 {index}')
            except service.ReviewError as exc:
                return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(observe, range(2)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 'review_version_conflict_reload_required' in results
    latest = client.get('/daily/reviews').json()['history'][0]
    assert len(latest['result']['outcomes']) == 1
    assert latest['result']['version'] == 2
    assert latest['result']['decision'] == saved['result']['decision']


def test_review_queue_separates_old_current_and_undated_without_writes(environment):
    client, Session, path = environment
    panel = json.loads(path.read_text())
    panel['cards'][6]['payload']['pending_queue'] = [
        {'target': '600003', 'created_at': '2026-07-05', 'reason': '旧资料'},
        {'target': '600004', 'created_at': '2026-09-16T09:00:00+08:00', 'reason': '本期资料'},
        {'target': '600005', 'created_at': 'invalid', 'reason': '日期不明'},
        {'target': '600006', 'created_at': '2026-09-17', 'reason': '未来日期'},
    ]
    path.write_text(json.dumps(panel))
    before = path.read_bytes()
    result = client.get('/daily/reviews?as_of=2026-09-16').json()
    by_subject = {item['subject']: item for item in result['items']}
    assert by_subject['600003']['source_scope'] == 'historical'
    assert by_subject['600004']['source_scope'] == 'current'
    assert by_subject['600005']['source_scope'] == 'unverified'
    assert by_subject['600006']['source_scope'] == 'unverified'
    assert result['summary'] == {'current': 3, 'historical': 1, 'unverified': 2,
                                  'recorded_choices': 0, 'with_observations': 0,
                                  'independently_verified_outcomes': None}
    assert path.read_bytes() == before
    with Session() as db:
        assert db.query(PendingAIAction).count() == 0
    saved = client.post('/daily/reviews', json=body(by_subject['600004'])).json()
    assert saved['result']['queue_task_completed'] is False
    updated = client.get('/daily/reviews').json()['summary']
    assert updated['recorded_choices'] == 1
    assert updated['with_observations'] == 0
