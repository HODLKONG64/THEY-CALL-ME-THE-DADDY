from the_daddy.engine import DaddyEngine
from the_daddy.config import Settings


def test_engine_runs(tmp_path):
    settings = Settings(target_root=tmp_path)
    engine = DaddyEngine(settings)
    result = engine.run()
    assert result is not None
