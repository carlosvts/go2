"""A coleção do Insomnia (`insomnia/go2-api.json`) cobre todas as rotas."""

import json

from scripts.make_insomnia import OUT, _normalize, app_routes, render


def test_colecao_commitada_esta_em_dia() -> None:
    assert OUT.read_text(encoding="utf-8") == render(), (
        "rode `uv run python scripts/make_insomnia.py` e commite o resultado"
    )


def test_toda_rota_http_e_websocket_esta_na_colecao() -> None:
    openapi, websockets = app_routes()
    resources = json.loads(OUT.read_text(encoding="utf-8"))["resources"]
    requests = {
        (r["method"], _normalize(r["url"].removeprefix("{{ _.base_url }}")))
        for r in resources
        if r["_type"] == "request"
    }
    sockets = {
        r["url"].removeprefix("{{ _.ws_url }}")
        for r in resources
        if r["_type"] == "websocket_request"
    }
    expected = {
        (method.upper(), path)
        for path, methods in openapi["paths"].items()
        for method in methods
    }
    assert expected <= requests
    assert set(websockets) == sockets
    assert len(websockets) == 4
