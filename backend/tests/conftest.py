import pytest


@pytest.fixture(autouse=True)
def _sin_keys_de_imagen(monkeypatch):
    """Ningún test debe disparar generación real de imágenes por tener las
    keys exportadas en el shell del desarrollador. Los tests que necesitan
    una key la setean explícitamente después (monkeypatch.setenv)."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
