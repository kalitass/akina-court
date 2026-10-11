"""The local experiment changes round trips, not the evidence or citation boundary."""
from pathlib import Path
from types import SimpleNamespace

from core.agents.advocate import AdvocateDeps, get_case_facts, local_batch_evidence
from core.facts.tools import TOOL_SOURCES, facts_for_tool, build_fact_table
from core.schemas import Case


def test_batch_preserves_sources_seen_ids_and_events():
    case = Case.model_validate_json((Path(__file__).resolve().parents[1] / 'data/cases/C-0004.json').read_text())
    table = build_fact_table(case)
    events = []
    deps = AdvocateDeps(side='driver', table=table, emit=lambda *a, **kw: events.append((a, kw)))
    result = get_case_facts(SimpleNamespace(deps=deps), case.case_id)
    expected_seen = set()
    for name in TOOL_SOURCES:
        expected = facts_for_tool(table, name)
        assert result[name]['facts'] == [f.model_dump(include={'id', 'source', 'text'}) for f in expected]
        expected_seen.update(f.id for f in expected)
    assert deps.seen == expected_seen
    assert deps.called == set(TOOL_SOURCES)
    assert len(events) == len(TOOL_SOURCES)
    assert get_case_facts(SimpleNamespace(deps=deps), 'another-case').get('error')
    assert len(events) == len(TOOL_SOURCES)


def test_batch_never_changes_cloud_workflow(monkeypatch):
    monkeypatch.setenv('LOCAL_BATCH_EVIDENCE', '1')
    for provider in ('deepseek', 'tokenhub'):
        monkeypatch.setenv('LLM_PROVIDER', provider)
        assert not local_batch_evidence()
    monkeypatch.setenv('LLM_PROVIDER', 'ollama')
    assert local_batch_evidence()
    monkeypatch.delenv('LOCAL_BATCH_EVIDENCE')
    assert not local_batch_evidence()


def test_compact_context_keeps_read_fact_text_and_never_marks_unread_as_seen():
    from core.agents.advocate import compact_rebuttal_context
    from core.schemas import CaseRecord
    root = Path(__file__).resolve().parents[1]
    case = Case.model_validate_json((root / 'data/cases/C-0004.json').read_text())
    table = build_fact_table(case)
    record = CaseRecord.load(root / 'runs/C-0004.json')
    own = record.briefs['driver']
    deps = AdvocateDeps(side='driver', table=table, emit=lambda *a, **kw: None)
    deps.seen.add(table.facts[0].id)
    before = set(deps.seen)
    prompt = compact_rebuttal_context(deps, own)
    # Isolate the evidence block: briefs can mention facts without making them read.
    import json
    block = prompt.split('verbatim. This is not new evidence:\n', 1)[1].split('\nTools already called:', 1)[0]
    assert json.loads(block) == [table.facts[0].model_dump(include={'id', 'source', 'text'})]
    assert own.model_dump_json() in prompt
    assert deps.seen == before and not deps.called


def test_compact_rebuttal_is_opt_in_and_local_only(monkeypatch):
    from core.agents.advocate import local_compact_rebuttal
    monkeypatch.setenv('LOCAL_COMPACT_REBUTTAL', '1')
    monkeypatch.setenv('LLM_PROVIDER', 'deepseek')
    assert not local_compact_rebuttal()
    monkeypatch.setenv('LLM_PROVIDER', 'ollama')
    assert local_compact_rebuttal()
    monkeypatch.delenv('LOCAL_COMPACT_REBUTTAL')
    assert not local_compact_rebuttal()
