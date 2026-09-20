# -*- coding: utf-8 -*-
"""The chat model configuration, used as DTO layer."""

from pydantic import BaseModel, Field

from ....model import ModelCard


class ListModelsResponse(BaseModel):
    """List the candidate models response."""

    models: list[ModelCard] = Field(description="The candidate models.")
    total: int = Field(description="The total number of candidates.")


class ListModelsRequest(BaseModel):
    """List the candidate models request."""

    provider: str = Field(
        description="The provider type, e.g. openai, dashscope, etc.",
    )
    credential_id: str | None = Field(
        default=None,
        description=(
            "Optional credential id. When given, the credential's own "
            "model list wins over the provider's packaged defaults "
            "(currently only the custom credential type carries one)."
        ),
    )
