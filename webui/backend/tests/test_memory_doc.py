"""File-backend memory as ONE markdown document.

With ``memory_backend="file"`` memory is a single MEMORY.md that the agent
reads, so the UI previews/edits it as a document rather than as separate items.
The document and item APIs are two views of the SAME store. The vector backend
has no such file and must reject the document API.
"""
import asyncio

import pytest

from app.backends.errors import BadRequest
from app.backends.ms_agent import memory as M
from app.backends.ms_agent import projects as P
from app.schemas.memory import MemoryDocUpdate, MemoryItemCreate
from app.schemas.project import ProjectCreate


@pytest.fixture
def file_project():
    proj = P.create_project(
        ProjectCreate(name="doc-test", memory_enabled=True,
                      memory_backend="file"))
    yield proj
    P.delete_project(proj.id)


@pytest.fixture
def vector_project():
    proj = P.create_project(
        ProjectCreate(name="doc-test-vec", memory_enabled=True,
                      memory_backend="vector"))
    yield proj
    P.delete_project(proj.id)


def test_empty_document_on_a_fresh_project(file_project):
    assert M.get_doc(file_project.id).content == ""


def test_document_roundtrip(file_project):
    md = "# Project memory\n\n- prefers Chinese\n- keep it short\n"
    saved = M.put_doc(file_project.id, MemoryDocUpdate(content=md))
    assert "prefers Chinese" in saved.content
    assert M.get_doc(file_project.id).content == saved.content


def test_document_and_items_share_one_store(file_project):
    """An item added the old way shows up in the document, and document lines
    show up as items — they are the same MEMORY.md."""
    M.create_item(file_project.id, MemoryItemCreate(content="likes brevity"))
    assert "likes brevity" in M.get_doc(file_project.id).content

    M.put_doc(file_project.id, MemoryDocUpdate(content="- written as a doc\n"))
    contents = [i.content for i in asyncio.run(M.list_items(file_project.id))]
    assert "- written as a doc" in contents


def test_clearing_the_document_is_allowed(file_project):
    M.put_doc(file_project.id, MemoryDocUpdate(content="- something\n"))
    assert M.put_doc(file_project.id, MemoryDocUpdate(content="")).content == ""


def test_document_api_rejects_vector_backend(vector_project):
    with pytest.raises(BadRequest):
        M.get_doc(vector_project.id)
    with pytest.raises(BadRequest):
        M.put_doc(vector_project.id, MemoryDocUpdate(content="x"))


def test_vector_memories_are_read_only_apart_from_deletion(vector_project):
    """Vector entries come from the agent's fact extraction during conversation,
    so the UI only offers removal — creating/editing by hand is refused."""
    from app.schemas.memory import MemoryItemCreate, MemoryItemUpdate

    with pytest.raises(BadRequest):
        M.create_item(vector_project.id, MemoryItemCreate(content="manual note"))
    with pytest.raises(BadRequest):
        M.update_item(vector_project.id, "mem_whatever",
                      MemoryItemUpdate(content="edited"))


def test_file_memories_stay_writable(file_project):
    """The file backend is the editable one — the guard must not leak to it."""
    from app.schemas.memory import MemoryItemCreate

    item = M.create_item(file_project.id, MemoryItemCreate(content="a note"))
    assert item.content == "a note"
