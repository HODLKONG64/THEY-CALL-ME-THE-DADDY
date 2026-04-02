from the_daddy.memory.repository import MemoryRepository


def test_memory_bootstrap():
    repo = MemoryRepository(None)
    state = repo.state
    assert state.schema_version == "3.0"
