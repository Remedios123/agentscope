# -*- coding: utf-8 -*-
"""The model router."""

from fastapi import APIRouter, Depends, HTTPException, status

from .._service import ResourceAccessService
from ..deps import get_current_user_id, get_resource_access_service
from ._schema import ListModelsResponse, ListModelsRequest
from ...credential import CredentialFactory

model_router = APIRouter(
    prefix="/model",
    tags=["model"],
    responses={404: {"description": "Not found"}},
)


@model_router.get(
    "/",
    response_model=ListModelsResponse,
    summary="List all candidate models under the given credential type",
)
async def list_models(
    body: ListModelsRequest = Depends(),
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> ListModelsResponse:
    """Return all candidate models under the given credential type.

    When ``credential_id`` is given, the credential must be visible to
    the caller (owned or shared) and its own model list — if the
    credential type carries one — wins over the packaged defaults.

    Args:
        body (ListModelsRequest): The request body.
        user_id (`str`): Injected authenticated user ID.
        access (ResourceAccessService): Injected access service.

    Returns:
        `ListModelsResponse`: The response body.
    """
    credential_cls = CredentialFactory.get_credential_class(body.provider)
    if credential_cls is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{body.provider}' not found.",
        )

    if body.credential_id:
        credential_record = await access.resolve_credential(
            user_id,
            body.credential_id,
        )
        credential = CredentialFactory.from_dict(credential_record.data)
        if credential.type != body.provider:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Credential '{body.credential_id}' is of type "
                    f"'{credential.type}', not '{body.provider}'."
                ),
            )
        models = credential.list_models_for()
        if models is None:
            models = credential_cls.list_models()
    else:
        models = credential_cls.list_models()

    return ListModelsResponse(models=models, total=len(models))
