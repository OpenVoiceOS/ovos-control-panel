"""The transformers page's API."""
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ovos_webui import transformcfg


class BidirectionalBody(BaseModel):
    enable: bool
    #: the languages to translate to and from; ``None`` leaves them unchanged
    secondary_langs: list[str] | None = None
    #: the utterance plugin's flags; ``None`` leaves them at their defaults
    flags: dict[str, bool] | None = None


class ChainStateBody(BaseModel):
    #: plugin name -> on(true)/off(false, kept with ``"active": false``)
    enabled: dict[str, bool] = Field(default_factory=dict)
    #: optional run order; an empty list clears it, ``None`` leaves it untouched
    order: list[str] | None = None


class PluginConfigBody(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class SoxBody(BaseModel):
    enable: bool
    #: SoX effects as {effect: {param: number}}; ``None`` leaves them unchanged
    effects: dict[str, dict[str, float]] | None = None


def routes(r) -> None:
    # ── transformer chains ────────────────────────────────────────────────────
    # The six transformer chains (utterance/metadata/intent/audio/dialog/tts)
    # each live in their own config section. These routes turn plugins on and
    # off, order them, and edit a plugin's own config block — all writes to the
    # user configuration layer, like /api/config. No feature-specific bus message.
    @r.privileged.get("/transformers")
    def api_transformers_get() -> dict[str, Any]:
        return transformcfg.get_chains()

    @r.privileged.post("/transformers/{chain}")
    def api_transformers_set(chain: str, body: ChainStateBody) -> dict[str, Any]:
        try:
            return transformcfg.set_chain_state(chain, body.enabled, body.order,
                                                bus=r.bus())
        except transformcfg.TransformerConfigError as err:
            raise HTTPException(400, str(err)) from None

    @r.privileged.post("/transformers/{chain}/{name}/config")
    def api_transformer_plugin_config(chain: str, name: str,
                                      body: PluginConfigBody) -> dict[str, Any]:
        try:
            return transformcfg.set_plugin_config(chain, name, body.config,
                                                  bus=r.bus())
        except transformcfg.TransformerConfigError as err:
            raise HTTPException(400, str(err)) from None

    # Bidirectional translation is two transformer plugins plus secondary_langs,
    # written together so "talk in language X, hear the answer in X" is one switch.
    @r.privileged.get("/bidirectional")
    def api_bidirectional_get() -> dict[str, Any]:
        return transformcfg.get_bidirectional()

    @r.privileged.post("/bidirectional")
    def api_bidirectional_set(body: BidirectionalBody) -> dict[str, Any]:
        try:
            return transformcfg.set_bidirectional(
                body.enable, body.secondary_langs, body.flags, bus=r.bus())
        except transformcfg.TransformerConfigError as err:
            raise HTTPException(400, str(err)) from None

    # SoX voice tuning: a curated view over the tts transformer that applies
    # sound effects (pitch, tempo, reverb, …) to the synthesized speech.
    @r.privileged.get("/sox")
    def api_sox_get() -> dict[str, Any]:
        return transformcfg.get_sox()

    @r.privileged.post("/sox")
    def api_sox_set(body: SoxBody) -> dict[str, Any]:
        try:
            return transformcfg.set_sox(body.enable, body.effects, bus=r.bus())
        except transformcfg.TransformerConfigError as err:
            raise HTTPException(400, str(err)) from None
