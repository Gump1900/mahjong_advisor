import json
from pathlib import Path

from scripts.live_tricks import TrickBook, TricksPlayer
from src.players.deliberation import Deliberation
from tests.test_decision_guard import waiting_position
from tests.test_table_decision import proposal
from src.players.table_decision import TABLE_PROTOCOL
from tests.test_simulation import fake_client


def test_contextual_book_is_explicit_and_uses_same_guard_and_one_request():
    book=TrickBook(Path('data/knowledge/experience.md').read_text())
    assert list(book.cards)==[f'T{i:02d}' for i in range(1,25)]
    obs=waiting_position();frame=proposal(obs)
    client,calls=fake_client([json.dumps(frame)])
    bot=TricksPlayer(provider='deepseek',client=client,model='fake',book=book)
    original=bot.knowledge
    bot.choose(obs)
    assert len(calls)==1 and bot.knowledge==original
    assert '### T08' in calls[0]['system'] and '### T11' in calls[0]['system']
    trace=bot.last_validation['tool_trace'][0]
    assert trace['document_sha256']==book.sha256 and 1<=len(trace['selected_ids'])<=6
    assert bot.last_validation['grounding_protocol']==TABLE_PROTOCOL
    assert 'initial_wall' not in calls[0]['messages'][0]['content']
