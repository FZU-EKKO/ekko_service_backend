import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.users import UserToken, Users
from schemas.users import UpdateUsersRequest
from utils import random_string, security


async def select_user_email(db: AsyncSession, email: str):
    query = select(Users).where(Users.email == email)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def select_user_id(db: AsyncSession, user_id: str):
    stmt = select(Users).where(Users.id == user_id)
    user = await db.execute(stmt)
    return user.scalar_one_or_none()


async def create_user(db: AsyncSession, user_data):
    unique_user_id = ""
    max_iter = 10000
    current_iter = 0
    while current_iter < max_iter:
        current_iter += 1
        unique_user_id = random_string.gen_random_string(7, False)
        if unique_user_id[0] == "0":
            continue
        query = select(Users).where(Users.id == unique_user_id)
        result = await db.execute(query)
        if not result.first():
            break
    if current_iter >= max_iter:
        return None

    hash_pwd = security.get_hash_password(user_data.pwd)
    user = Users(
        id=unique_user_id,
        email=user_data.email,
        pwd=hash_pwd,
        nick_name=user_data.nick_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def create_token(db: AsyncSession, user_id: str):
    token = str(uuid.uuid4())
    expires_at = datetime.now() + timedelta(days=7)
    query = select(UserToken).where(UserToken.user_id == user_id)
    result = await db.execute(query)
    user_token = result.scalar_one_or_none()

    if user_token:
        user_token.token = token
        user_token.expires_at = expires_at
    else:
        user_token = UserToken(user_id=user_id, token=token, expires_at=expires_at)
        db.add(user_token)

    await db.commit()
    return token


async def authenticate_user(db: AsyncSession, email: str, password: str):
    user = await select_user_email(db, email)
    if not user:
        return None
    if not security.verify_password(password, user.pwd):
        return None
    return user


async def get_user_by_token(db: AsyncSession, token: str):
    query = select(UserToken).where(UserToken.token == token)
    result = await db.execute(query)
    db_token = result.scalar_one_or_none()
    if not db_token or db_token.expires_at < datetime.now():
        return None
    query = select(Users).where(Users.id == db_token.user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def update_user(db: AsyncSession, user_id: str, user: UpdateUsersRequest):
    payload = user.model_dump(exclude_unset=True)
    if "pwd" in payload:
        payload["pwd"] = security.get_hash_password(payload["pwd"])

    query = update(Users).where(Users.id == user_id).values(**payload)
    result = await db.execute(query)
    await db.commit()
    if result.rowcount == 0:
        return None
    return await select_user_id(db, user_id)


async def change_password(db: AsyncSession, user: Users, new_password: str):
    user.pwd = security.get_hash_password(new_password)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return True


async def find_password_email(db: AsyncSession, user: Users, password: str):
    user.pwd = security.get_hash_password(password)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
