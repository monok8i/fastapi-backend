import secrets  # noqa: I001
from datetime import datetime, timedelta
from typing import Any, Union

import jwt
from fastapi import HTTPException
from passlib.context import CryptContext
from pydantic import EmailStr

from .user import UserService
from ..core.settings import config
from ..models import User
from ..schemas import RefreshSessionCreate, Token
from ..utils import UnitOfWork
from ..utils.exceptions import (
    InvalidCredentialsException,
    InvalidTokenException,
    TokenExpiredException,
)
from ..utils.security import verify_password
from ..utils.specification import RefreshTokenSpecification, UserIDSpecification

hash_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthenticationService:
    @classmethod
    def encode_jwt_token(
        cls,
        subject: Union[str, Any],
        private_key: str = config.Authentication().JWT_PRIVATE_PATH.read_text(),
        algorithm: str = config.Authentication().ALGORITHM,
        *,
        expires: timedelta | None = None,
    ) -> str:
        """
        Encodes a JWT token.

        Args:
            subject (Union[str, Any]): The subject of the token.
            private_key (str): The path to the private key file.
            algorithm (str): The algorithm to use for encoding the token.
            expires (timedelta, optional): The expiration time of the token. If not provided, the expiration time will be set to the default value specified in the configuration file.

        Returns:
            str: The encoded JWT token.
        """
        if expires:
            expire = datetime.utcnow() + expires  # noqa: DTZ003
        else:
            expire = datetime.utcnow() + timedelta(  # noqa: DTZ003
                minutes=float(config.Authentication().ACCESS_TOKEN_EXPIRE_MINUTES)
            )

        payload = {
            "sub": subject,
            "iat": datetime.utcnow(),  # noqa: DTZ003
            "exp": expire,
        }

        return jwt.encode(payload, private_key, algorithm)

    @classmethod
    def decode_jwt_token(
        cls,
        token: str,
        public_key: str = config.Authentication().JWT_PUBLIC_PATH.read_text(),
        algorithm: str = config.Authentication().ALGORITHM,
    ) -> Any:
        """
        Decodes a JWT token.

        Args:
            token (str): The JWT token to be decoded.
            public_key (str): The path to the public key file.
            algorithm (str): The algorithm used to encode the token.

        Returns:
            Any: The decoded payload of the JWT token.
        """
        return jwt.decode(token, public_key, algorithms=[algorithm])

    @classmethod
    def _generate_refresh_token(cls, lenght: int = 64) -> str:
        """
        Generates a random refresh token.

        Args:
            lenght (int, optional): The length of the refresh token. Defaults to 64.

        Returns:
            str: The generated refresh token.
        """
        return secrets.token_urlsafe(lenght)

    @classmethod
    async def create_token(cls, uow: UnitOfWork, user_id: int) -> Token:
        """
        Creates a new access and refresh token for the given user.

        Args:
            uow (UnitOfWork): The active unit of work.
            user_id (int): The ID of the user for whom the tokens are being created.

        Returns:
            Token: The newly created access and refresh tokens.
        """
        access_token = cls.encode_jwt_token(user_id)
        refresh_token = cls._generate_refresh_token()

        async with uow:
            await uow.refresh_session.create(
                create_schema=RefreshSessionCreate(
                    refresh_token=refresh_token,
                    expires_in=timedelta(
                        days=float(config.Authentication().REFRESH_TOKEN_EXPIRE_DAYS)
                    ).total_seconds(),
                    user_id=user_id,
                )
            )

            await uow.commit()

        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=config.Authentication().TOKEN_TYPE,
        )

    @classmethod
    async def refresh_token(
        cls, uow: UnitOfWork, refresh_token: str
    ) -> Token | HTTPException:
        """
        Refreshes an access token using a refresh token.

        Args:
            uow (UnitOfWork): The active unit of work.
            refresh_token (str): The refresh token used to refresh the access token.

        Returns:
            Token | HTTPException: The refreshed access token or an HTTP exception if the refresh token is invalid or expired.
        """
        spec = RefreshTokenSpecification(refresh_token=refresh_token)

        async with uow:
            refresh_session = await uow.refresh_session.get(spec=spec)

            if not refresh_session:
                raise InvalidTokenException

            if datetime.utcnow() > refresh_session.created_at + timedelta(  # noqa: DTZ003
                seconds=refresh_session.expires_in
            ):
                await uow.refresh_session.delete(spec=spec)
                raise TokenExpiredException

            user = await uow.user.get(
                spec=UserIDSpecification(id=refresh_session.user_id)
            )
            if not user:
                raise InvalidTokenException

            await uow.commit()

        access_token = cls.encode_jwt_token(user.id)

        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=config.Authentication().TOKEN_TYPE,
        )

    @classmethod
    async def authenticate_user(
        cls, uow: UnitOfWork, *, email: EmailStr, password: str
    ) -> User | InvalidCredentialsException:
        """
        Authenticates a user using their email and password.

        Args:
            uow (UnitOfWork): The active unit of work.
            email (EmailStr): The email of the user.
            password (str): The password of the user.

        Returns:
            User | InvalidCredentialsException: The authenticated user or an exception if the credentials are invalid.
        """
        user = await UserService.get_by_email(uow, email=email)

        if not user:
            raise InvalidCredentialsException

        if not verify_password(
            user_password=password,
            hashed_password=user.hashed_password,
        ):
            raise InvalidCredentialsException

        return user

    @classmethod
    async def logout(cls, uow: UnitOfWork, refresh_token: str) -> None:
        """
        Logs out the user by deleting the refresh session associated with the given refresh token.

        Args:
            uow (UnitOfWork): The active unit of work.
            refresh_token (str): The refresh token used to authenticate the user.

        Raises:
            InvalidTokenException: If the refresh token is invalid.
            TokenExpiredException: If the refresh token has expired.
        """
        spec = RefreshTokenSpecification(refresh_token=refresh_token)

        async with uow:
            refresh_session = await uow.refresh_session.get(spec=spec)

            if not refresh_session:
                raise InvalidTokenException

            if datetime.utcnow() > refresh_session.created_at + timedelta(  # noqa: DTZ003
                seconds=refresh_session.expires_in
            ):
                await uow.refresh_session.delete(spec=spec)
                raise TokenExpiredException

            await uow.commit()
