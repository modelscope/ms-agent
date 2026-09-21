# Copyright (c) ModelScope Contributors. All rights reserved.
"""Cache rollback in ``history_mode='overwrite'``.

In overwrite mode ``DefaultMemory.add()`` drops every cached block from the
first one whose hash no longer matches the incoming history. When the very
first block mismatches -- a new conversation reusing the same store, or a
history that was edited/cleared -- the whole cache is rolled back, and
deleting the last remaining entry must leave the instance in the same state a
fresh store has, instead of raising.
"""
import asyncio
from omegaconf import OmegaConf

from ms_agent.llm.utils import Message
from ms_agent.memory.default_memory import DefaultMemory


class _FakeMem0:
    """Stands in for the mem0 client: what is under test is DefaultMemory's
    own cache bookkeeping, not fact extraction or the vector store."""

    def add(self, messages, **kwargs):
        return {'results': []}

    def get_all(self, **kwargs):
        return {'results': []}

    def delete(self, memory_id=None, **kwargs):
        pass


def _build(path, monkeypatch):
    monkeypatch.setattr(DefaultMemory, '_init_memory_obj',
                        lambda self: _FakeMem0())
    config = OmegaConf.create({
        'output_dir': str(path),
        'memory': {
            'default_memory': {
                'user_id': 'u1',
                'path': str(path),
                'history_mode': 'overwrite',
            }
        },
    })
    return DefaultMemory(config)


def _turn(question, answer):
    return [
        Message(role='user', content=question),
        Message(role='assistant', content=answer),
    ]


def test_overwrite_rollback_of_every_cached_block(tmp_path, monkeypatch):
    """A second session on the same store opens with a different first turn,
    so every cached block is rolled back before the new one is added."""

    async def _run():
        first = _build(tmp_path, monkeypatch)
        await first.add(_turn('My name is Alice.', 'Hi Alice.'))
        assert list(first.cache_messages) == [0]
        assert first.max_msg_id == 0

        second = _build(tmp_path, monkeypatch)
        assert list(second.cache_messages) == [0]
        await second.add(_turn('What is the capital of France?', 'Paris.'))
        assert list(second.cache_messages) == [0]
        assert second.max_msg_id == 0

    asyncio.run(_run())


def test_overwrite_rollback_empties_the_cache(tmp_path, monkeypatch):
    """Nothing is re-added, so the cache ends up empty and ``max_msg_id``
    falls back to the sentinel ``load_cache()`` uses for an empty store."""

    async def _run():
        memory = _build(tmp_path, monkeypatch)
        await memory.add(_turn('My name is Alice.', 'Hi Alice.'))
        await memory.add([])
        assert memory.cache_messages == {}
        assert memory.max_msg_id == -1

        # The next block is numbered from 0 again, as on a fresh store.
        await memory.add(_turn('Capital of France?', 'Paris.'))
        assert list(memory.cache_messages) == [0]

    asyncio.run(_run())
