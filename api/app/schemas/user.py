import uuid

from fastapi_users import schemas

from shared.models.enums import UserRole


class UserRead(schemas.BaseUser[uuid.UUID]):
    role: UserRole
    credit_balance: int


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass
