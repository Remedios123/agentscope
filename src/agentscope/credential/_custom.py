# -*- coding: utf-8 -*-
"""The custom OpenAI-compatible credential."""
from typing import ClassVar, Literal, Type, TYPE_CHECKING

from pydantic import ConfigDict, Field, SecretStr, field_validator

from ._base import CredentialBase

if TYPE_CHECKING:
    from ..model import ChatModelBase, ModelCard


class SelfConfiguredModelsMixin(CredentialBase):  # pylint: disable=W0223
    """Adds a user-configured model list to a credential.

    Unlike built-in providers — whose candidate models come from the
    YAML cards packaged with each model class — credentials mixing this
    in carry their model list on the credential itself (one
    ``model_id | display name`` pair per line), so an arbitrary
    third-party gateway or self-hosted deployment can be wired up
    without touching code. The model router serves the instance list
    when a request names a ``credential_id``; with no packaged defaults
    of its own, the type lists nothing without one.

    The parameter controls shown for each model mirror the chat model
    class returned by :meth:`get_chat_model_class`, minus
    :attr:`unsupported_parameters`.
    """

    context_size: int = Field(
        default=128000,
        title="Context Size",
        description="The context window advertised for every model below.",
        gt=0,
    )
    """The context size advertised for the configured models."""

    models_text: str = Field(
        default="",
        title="Models",
        description=(
            "One model per line: ``model_id | display name`` — the "
            "display name is optional and defaults to the id. These are "
            "the only models offered under this credential."
        ),
        json_schema_extra={"format": "model-list"},
    )
    """The user-configured model list, one ``id | label`` pair per line.

    Stored as line text (human-readable, round-trips through every
    config surface); the UI edits it through a structured row editor
    rather than a raw textarea.
    """

    unsupported_parameters: ClassVar[tuple[str, ...]] = ()
    """Parameter names hidden from the model cards (unsupported by the
    endpoint this credential targets)."""

    @field_validator("models_text")
    @classmethod
    def _strip_lines(cls, v: str) -> str:
        """Normalize blank space around entries; keep line structure."""
        return "\n".join(line.strip() for line in v.splitlines()).strip()

    @classmethod
    def list_models(cls) -> list["ModelCard"]:
        """No packaged defaults — this type has no static card directory.

        The candidate models live on each credential instance (see
        :meth:`list_models_for`). Without a credential there is nothing
        sensible to list, so this returns empty rather than leaking
        another provider's packaged cards.
        """
        return []

    def list_models_for(self) -> list["ModelCard"] | None:
        """This credential's configured models are the list."""
        return self.list_model_cards()

    def list_model_cards(self) -> list["ModelCard"]:
        """Build a model card per configured line.

        Returns:
            `list[ModelCard]`: One card per non-empty line, in order.
        """
        from ..model import ModelCard

        model_cls = self.get_chat_model_class()
        base_schema = model_cls.Parameters.model_json_schema()
        properties = {
            key: schema
            for key, schema in base_schema.get("properties", {}).items()
            if key not in self.unsupported_parameters
        }
        parameter_schema: dict = {
            "type": "object",
            "properties": properties,
            "required": base_schema.get("required", []),
        }

        cards: list[ModelCard] = []
        for line in self.models_text.splitlines():
            name, _, label = line.partition("|")
            name = name.strip()
            if not name:
                continue
            cards.append(
                ModelCard(
                    name=name,
                    label=(label.strip() or name),
                    status="active",
                    context_size=self.context_size,
                    output_size=16384,
                    parameter_schema=parameter_schema,
                    parameters_overrides={},
                ),
            )
        return cards


class CustomCredential(SelfConfiguredModelsMixin, CredentialBase):
    """A user-defined OpenAI-compatible endpoint carrying its own model
    list.

    Consumed by :class:`~agentscope.model._openai_chat.OpenAIChatModel`,
    which reads ``api_key`` / ``organization`` / ``base_url`` off the
    credential object it is handed.
    """

    model_config = ConfigDict(
        title="Custom (OpenAI-Compatible)",
    )

    type: Literal["custom_credential"] = "custom_credential"
    """The credential type."""

    api_key: SecretStr = Field(
        description="The API key for the endpoint.",
    )
    """The API key."""

    base_url: str = Field(
        description=(
            "The OpenAI-compatible base URL "
            "(e.g. ``https://gw.example.com/v1``)."
        ),
    )
    """The endpoint base URL."""

    @classmethod
    def get_chat_model_class(cls) -> Type["ChatModelBase"]:
        """Return the OpenAI chat model class (the endpoint is
        OpenAI-compatible)."""
        from ..model import OpenAIChatModel

        return OpenAIChatModel
