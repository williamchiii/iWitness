"""Authenticated user profile endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import Principal, get_current_principal


router = APIRouter()


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str | None
    avatar_url: str | None


@router.get("/me", response_model=UserResponse)
def get_me(principal: Principal = Depends(get_current_principal)) -> UserResponse:
    """Return profile fields from the verified access token."""

    if not principal.email:
        raise HTTPException(status_code=401, detail="Authenticated user email is missing")
    return UserResponse(
        id=principal.id,
        email=principal.email,
        display_name=principal.display_name,
        avatar_url=principal.avatar_url,
    )
