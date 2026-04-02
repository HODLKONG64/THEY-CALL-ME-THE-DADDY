from the_daddy.config import Settings
from the_daddy.memory.r2_store import R2Store
from the_daddy.memory.repository import MemoryRepository
from the_daddy.models import VettingDecision


def test_reputation_updates_without_r2(tmp_path):
    settings = Settings(
        target_root=tmp_path,
        local_state_dir=tmp_path / "local",
        r2_endpoint_url="",
        r2_access_key_id="",
        r2_secret_access_key="",
        r2_bucket="",
    )
    repo = MemoryRepository(R2Store(settings))
    decision = VettingDecision(
        accepted=True,
        route="safe",
        reason="fine",
        risk="low",
        reputation_delta=7,
        notes=[],
    )
    rep = repo.update_reputation("agent-x", decision)
    assert rep.trust_score == 57
    assert rep.accepted_count == 1
