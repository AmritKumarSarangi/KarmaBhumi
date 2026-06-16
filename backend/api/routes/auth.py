"""
api/routes/auth.py – JWT authentication endpoints.

POST /api/auth/register  – create account → JWT
POST /api/auth/login     – verify creds → JWT + user info
GET  /api/auth/me        – current user (requires JWT)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.database import get_db
from db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    initial_balance: float = Field(default=100_000.0, ge=0)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    email: str
    is_admin: bool
    balance: float


class UserResponse(BaseModel):
    user_id: str
    email: str
    is_admin: bool
    balance: float
    created_at: datetime


# ── Helpers ───────────────────────────────────────────────────────────────────


def _hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def _verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


def _create_token(user_id: str, email: str, is_admin: bool) -> tuple[str, int]:
    expire_minutes = settings.JWT_EXPIRE_MINUTES
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload = {
        "sub": user_id,
        "email": email,
        "is_admin": is_admin,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, expire_minutes * 60


# ── Dependency: current user ──────────────────────────────────────────────────


async def get_current_user(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> User:
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from jose import JWTError

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except Exception:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


# ── FastAPI dependency using Bearer header ─────────────────────────────────────


from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return await get_current_user(credentials.credentials, db)


async def require_admin(current_user: User = Depends(require_auth)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def verify_token(token: str) -> str | None:
    """Return user_id if token is valid, else None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except Exception:
        return None


_verify_token = verify_token


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    user = User(
        id=str(uuid.uuid4()),
        email=body.email,
        hashed_password=_hash_password(body.password),
        balance=body.initial_balance,
        is_admin=False,
    )
    db.add(user)
    await db.flush()

    token, expires_in = _create_token(user.id, user.email, user.is_admin)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        balance=user.balance,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not _verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    token, expires_in = _create_token(user.id, user.email, user.is_admin)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        balance=user.balance,
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(require_auth)) -> UserResponse:
    return UserResponse(
        user_id=current_user.id,
        email=current_user.email,
        is_admin=current_user.is_admin,
        balance=current_user.balance,
        created_at=current_user.created_at,
    )
