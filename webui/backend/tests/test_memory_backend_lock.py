"""Memory-backend lock: the choice freezes once memory has been enabled.

The backend decides the on-disk storage layout, so switching it after storage
went live would orphan whatever is already there. Toggling ``memory_enabled``
itself stays free — only the backend is frozen, and the lock must survive the
user turning memory back off.
"""
import pytest

from app.backends.errors import BadRequest
from app.backends.ms_agent import projects as P
from app.schemas.project import ProjectCreate, ProjectUpdate


@pytest.fixture
def unlocked_project():
    """A project created with memory OFF — backend still switchable."""
    proj = P.create_project(
        ProjectCreate(name="lock-test", memory_enabled=False,
                      memory_backend="file"))
    yield proj
    P.delete_project(proj.id)


def test_backend_unlocked_while_memory_never_enabled(unlocked_project):
    assert unlocked_project.memory_enabled is False
    assert unlocked_project.memory_backend_locked is False

    got = P.update_project(unlocked_project.id,
                           ProjectUpdate(memory_backend="vector"))
    assert got.memory_backend == "vector"
    assert got.memory_backend_locked is False


def test_enabling_memory_locks_the_backend(unlocked_project):
    got = P.update_project(unlocked_project.id,
                           ProjectUpdate(memory_enabled=True))
    assert got.memory_backend_locked is True


def test_lock_survives_disabling_memory_again(unlocked_project):
    """The rule that motivates a sticky flag rather than reading
    ``memory_enabled``: storage exists from the first enable onwards."""
    P.update_project(unlocked_project.id, ProjectUpdate(memory_enabled=True))
    got = P.update_project(unlocked_project.id,
                           ProjectUpdate(memory_enabled=False))
    assert got.memory_enabled is False
    assert got.memory_backend_locked is True


def test_changing_locked_backend_is_rejected(unlocked_project):
    P.update_project(unlocked_project.id, ProjectUpdate(memory_enabled=True))
    with pytest.raises(BadRequest):
        P.update_project(unlocked_project.id,
                         ProjectUpdate(memory_backend="vector"))


def test_resending_same_locked_backend_is_tolerated(unlocked_project):
    """The edit form submits the whole shape; an unchanged value must not 400."""
    P.update_project(unlocked_project.id, ProjectUpdate(memory_enabled=True))
    got = P.update_project(unlocked_project.id,
                           ProjectUpdate(memory_backend="file",
                                         memory_enabled=True))
    assert got.memory_backend == "file"


def test_created_with_memory_on_is_locked_immediately():
    proj = P.create_project(
        ProjectCreate(name="lock-test-on", memory_enabled=True,
                      memory_backend="vector"))
    try:
        assert proj.memory_backend == "vector"
        assert proj.memory_backend_locked is True
        with pytest.raises(BadRequest):
            P.update_project(proj.id, ProjectUpdate(memory_backend="file"))
    finally:
        P.delete_project(proj.id)


def test_project_path_cannot_be_changed_after_creation(unlocked_project):
    """The directory IS the project's identity and holds all of its data; the
    SDK's update() only rewrites the field, nothing moves on disk."""
    with pytest.raises(BadRequest):
        P.update_project(unlocked_project.id,
                         ProjectUpdate(local_path="/tmp/somewhere-else"))


def test_resending_same_project_path_is_tolerated(unlocked_project):
    """The edit form submits the whole shape; an unchanged path must not 400."""
    got = P.update_project(
        unlocked_project.id,
        ProjectUpdate(local_path=unlocked_project.local_path, name="renamed"))
    assert got.name == "renamed"
    assert got.local_path == unlocked_project.local_path
