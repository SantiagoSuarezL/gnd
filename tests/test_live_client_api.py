"""Tests unitarios de `diagnostics/riot/live_client_api`.

No tocan red real. Inyecto un `HttpClient` falso que devuelve tuplas
(status, body) prefabricadas. Cubre:

- 200 + JSON valido -> dict parseado correctamente.
- 200 + JSON malformado -> None (no lanza).
- 200 + JSON que no es objeto (lista, numero) -> None.
- 404 / 503 / otros status -> None (no hay partida o endpoint caido).
- Excepcion de red/cert (URLError, SSLError) -> None.
- is_game_active()=True cuando hay partida activa; False en caso contrario.
- verify=False se propaga al cliente (comportamiento del cert self-signed).
"""

from __future__ import annotations

import json

from gnd.diagnostics.riot.live_client_api import LiveClientApi


class _FakeHttpClient:
    """HttpClient falso: devuelve respuesta prefabricada o lanza."""

    def __init__(
        self,
        status: int = 200,
        body: str = "{}",
        exc: type[Exception] | None = None,
    ) -> None:
        self._status = status
        self._body = body
        self._exc = exc
        self.last_call: dict | None = None

    def get(self, url: str, *, verify: bool, timeout_s: float) -> tuple[int, str]:
        self.last_call = {
            "url": url,
            "verify": verify,
            "timeout_s": timeout_s,
        }
        if self._exc is not None:
            raise self._exc("fake raise del cliente HTTP")
        return (self._status, self._body)


class _ConnectionError(Exception):
    """Emula urllib.error.URLError."""


# ---------------------------------------------------------------------------
# fetch_active_player
# ---------------------------------------------------------------------------


class TestFetchActivePlayer:
    def test_200_json_valido_devuelve_dict(self) -> None:
        body = json.dumps({"championName": "Aatrox", "team": 100})
        api = LiveClientApi(http_client=_FakeHttpClient(200, body))
        data = api.fetch_active_player()
        assert data == {"championName": "Aatrox", "team": 100}

    def test_200_json_vacio_devuelve_dict_vacio(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(200, "{}"))
        data = api.fetch_active_player()
        assert data == {}

    def test_200_json_malformado_devuelve_none(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(200, "not json"))
        data = api.fetch_active_player()
        assert data is None

    def test_200_json_no_objeto_lista_devuelve_none(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(200, "[1,2,3]"))
        data = api.fetch_active_player()
        assert data is None

    def test_200_json_no_objeto_numero_devuelve_none(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(200, "42"))
        data = api.fetch_active_player()
        assert data is None

    def test_200_json_no_objeto_string_devuelve_none(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(200, '"hello"'))
        data = api.fetch_active_player()
        assert data is None

    def test_404_devuelve_none(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(404, "not found"))
        data = api.fetch_active_player()
        assert data is None

    def test_503_devuelve_none(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(503, "server err"))
        data = api.fetch_active_player()
        assert data is None

    def test_500_devuelve_none(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(500, "boom"))
        data = api.fetch_active_player()
        assert data is None

    def test_excepcion_de_red_devuelve_none(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(exc=_ConnectionError))
        data = api.fetch_active_player()
        assert data is None

    def test_excepcion_generica_devuelve_none(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(exc=RuntimeError))
        data = api.fetch_active_player()
        assert data is None


# ---------------------------------------------------------------------------
# is_game_active
# ---------------------------------------------------------------------------


class TestIsGameActive:
    def test_200_json_valido_es_active(self) -> None:
        body = json.dumps({"championName": "Aatrox"})
        api = LiveClientApi(http_client=_FakeHttpClient(200, body))
        assert api.is_game_active() is True

    def test_404_no_es_active(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(404, ""))
        assert api.is_game_active() is False

    def test_503_no_es_active(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(503, ""))
        assert api.is_game_active() is False

    def test_excepcion_no_es_active(self) -> None:
        api = LiveClientApi(http_client=_FakeHttpClient(exc=_ConnectionError))
        assert api.is_game_active() is False

    def test_json_malformado_no_es_active(self) -> None:
        # 200 pero JSON invalido: tecnicohay respuesta pero no un game
        api = LiveClientApi(http_client=_FakeHttpClient(200, "not json"))
        assert api.is_game_active() is False


# ---------------------------------------------------------------------------
# Parametros que llegan al cliente (verify=False obligatorio)
# ---------------------------------------------------------------------------


class TestHttpClientParams:
    def test_verify_false_se_propaga_al_cliente_cert_self_signed(self) -> None:
        # Riot usa cert self-signed en 127.0.0.1:2999 — el caller debe
        # forzar verify=False.
        client = _FakeHttpClient(200, "{}")
        api = LiveClientApi(http_client=client)
        api.fetch_active_player()
        assert client.last_call is not None
        assert client.last_call["verify"] is False

    def test_timeout_se_propaga(self) -> None:
        client = _FakeHttpClient(200, "{}")
        api = LiveClientApi(http_client=client, timeout_s=0.5)
        api.fetch_active_player()
        assert client.last_call is not None
        assert client.last_call["timeout_s"] == 0.5

    def test_url_se_propaga(self) -> None:
        client = _FakeHttpClient(200, "{}")
        api = LiveClientApi(
            http_client=client,
            url="https://127.0.0.1:2999/liveclientdata/activeplayer",
        )
        api.fetch_active_player()
        assert client.last_call is not None
        assert (
            client.last_call["url"]
            == "https://127.0.0.1:2999/liveclientdata/activeplayer"
        )

    def test_url_custom_se_respeta(self) -> None:
        # Por si Riot cambia el puerto en el futuro.
        client = _FakeHttpClient(200, "{}")
        api = LiveClientApi(http_client=client, url="https://127.0.0.1:3000/x")
        api.fetch_active_player()
        assert client.last_call["url"] == "https://127.0.0.1:3000/x"
