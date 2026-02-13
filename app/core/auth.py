from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt

from app.core.config import settings

# OAuth2 token endpoint
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")

ALGORITHM = "HS256"


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def authenticate_user(username: str, password: str) -> bool:
    # Simple single-admin authentication. Credentials come from environment/config.
    if username != settings.ADMIN_USERNAME:
        return False
    # Constant-time comparison
    from hmac import compare_digest

    return compare_digest(password, settings.ADMIN_PASSWORD)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    if not settings.AUTH_ENABLED:
        # If auth disabled, return anonymous user
        return "anonymous"

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Only support admin configured in settings for now
    if username != settings.ADMIN_USERNAME:
        raise credentials_exception
    return username


async def login_for_access_token(form_data: OAuth2PasswordRequestForm) -> dict:
    if not settings.AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="Authentication is disabled")

    valid = await authenticate_user(form_data.username, form_data.password)
    if not valid:
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    access_token = create_access_token(data={"sub": form_data.username})
    return {"access_token": access_token, "token_type": "bearer"}
