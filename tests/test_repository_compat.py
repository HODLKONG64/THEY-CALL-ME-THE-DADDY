from the_daddy.memory.repository import DaddyMemoryState, MEMORY_SCHEMA_VERSION, MemoryRepository


def test_repository_exports_compat_symbols():
    state = DaddyMemoryState()
    assert state.schema_version == MEMORY_SCHEMA_VERSION

    repo = MemoryRepository()
    assert repo.state.schema_version == MEMORY_SCHEMA_VERSION
    assert len(repo.fingerprint("abc")) == 64
