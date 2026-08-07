import importlib
import os


def test_sitecustomize_sets_reload_stability_environment(monkeypatch):
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.delenv("WATCHFILES_FORCE_POLLING", raising=False)
    monkeypatch.delenv("WATCHFILES_POLL_DELAY_MS", raising=False)

    import sitecustomize

    importlib.reload(sitecustomize)

    assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
    assert os.environ["WATCHFILES_FORCE_POLLING"].lower() == "true"
    assert os.environ["WATCHFILES_POLL_DELAY_MS"] == "1000"
