from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fishrag_api.api.dependencies import CurrentUser, get_current_user, get_session, require_roles
from fishrag_api.core.security import create_access_token, hash_password, verify_password
from fishrag_api.db.models import User, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])

RoleLiteral = Literal["admin", "reviewer", "member"]
DbSession = Annotated[AsyncSession, Depends(get_session)]
AdminUser = Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN.value))]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


class RegisterUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    role: RoleLiteral = "member"

    model_config = ConfigDict(extra="forbid")


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    model_config = ConfigDict(extra="forbid")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    request: RegisterUserRequest,
    session: DbSession,
    _: AdminUser,
) -> UserResponse:
    existing = await session.scalar(select(User).where(User.email == request.email.lower()))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists.")

    user = User(
        email=request.email.lower(),
        password_hash=hash_password(request.password),
        full_name=request.full_name,
        role=request.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserResponse.model_validate(user, from_attributes=True)


@router.post("/token", response_model=TokenResponse)
async def login(request: LoginRequest, session: DbSession) -> TokenResponse:
    user = await session.scalar(select(User).where(User.email == request.email.lower()))
    if (
        user is None
        or not user.is_active
        or not verify_password(request.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    return TokenResponse(access_token=create_access_token(subject=user.id, role=user.role))


@router.get("/me", response_model=CurrentUser)
async def read_me(user: CurrentUserDep) -> CurrentUser:
    return user
