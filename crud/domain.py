from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.domain import DomainMemberRole, DomainMembers, Domains
from models.users import Users
from schemas.domain import DomainRequest, DomainResearchRequest, DomainUpdateRequest
from utils import random_string


async def get_default_member_alias(db: AsyncSession, member_id: str) -> str | None:
    result = await db.execute(select(Users.nick_name).where(Users.id == member_id))
    return result.scalar_one_or_none()


async def create_domain(
    db: AsyncSession,
    _create_id: str,
    domain: DomainRequest,
):
    unique_domain_id = ""
    max_iter = 1000
    _iter = 0
    while _iter < max_iter:
        _iter += 1
        unique_domain_id = random_string.gen_random_string(8, False)
        if unique_domain_id[0] == "0":
            continue
        query = select(Domains).where(Domains.id == unique_domain_id)
        result = await db.execute(query)
        if result.first() is None:
            break
    if _iter >= max_iter:
        return None

    new_domain = Domains(
        id=unique_domain_id,
        create_id=_create_id,
        **domain.model_dump(exclude_unset=True, exclude_none=True),
    )
    db.add(new_domain)
    await db.commit()
    await db.refresh(new_domain)

    domain_member = DomainMembers(
        domain_id=unique_domain_id,
        member_id=_create_id,
        alias=await get_default_member_alias(db, _create_id),
        role=DomainMemberRole.Owner,
    )
    db.add(domain_member)
    await db.commit()
    await db.refresh(domain_member)
    return new_domain


async def select_domain_id(db: AsyncSession, domain_id: str):
    query = select(Domains).where(Domains.id == domain_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def update_domain(db: AsyncSession, domain_update: DomainUpdateRequest):
    query = (
        update(Domains)
        .where(Domains.id == domain_update.id)
        .values(**domain_update.model_dump(exclude_unset=True))
    )
    update_result = await db.execute(query)
    if update_result.rowcount == 0:
        return None
    await db.commit()
    return await select_domain_id(db, domain_update.id)


async def delete_domain_id(db: AsyncSession, domain_id: str):
    current_domain = await select_domain_id(db, domain_id)
    if current_domain is None:
        return False
    await db.delete(current_domain)
    await db.commit()
    return True


async def select_domains(
    db: AsyncSession,
    domain_info: DomainResearchRequest,
    _offset: int | None = None,
    _limit: int | None = None,
):
    search_conditions: list[ColumnElement[bool]] = [Domains.is_public == True]
    or_conditions = []
    if domain_info.id is not None:
        or_conditions.append(Domains.id == domain_info.id)
    if domain_info.domain_name is not None:
        or_conditions.append(Domains.domain_name.like(f"%{domain_info.domain_name}%"))
    if domain_info.description is not None:
        or_conditions.append(Domains.description.like(f"%{domain_info.description}%"))
    if or_conditions:
        search_conditions.append(or_(*or_conditions))

    total_query = select(func.count(Domains.id)).where(and_(*search_conditions))
    total_result = await db.execute(total_query)
    total = total_result.scalar()

    query = select(Domains).where(and_(*search_conditions))
    if _offset is not None:
        query = query.offset(_offset)
    if _limit is not None:
        query = query.limit(_limit)
    result = await db.execute(query)
    return total, result.scalars().all()


async def select_domain_members(db: AsyncSession, domain_id: str, member_id: str):
    query = select(DomainMembers).where(
        (DomainMembers.domain_id == domain_id) & (DomainMembers.member_id == member_id)
    )
    result = await db.execute(query)
    return result.scalars().first()


async def join_the_domains(db: AsyncSession, domain_id: str, member_id: str):
    if await select_domain_members(db, domain_id, member_id):
        return None
    domain_member = DomainMembers(
        domain_id=domain_id,
        member_id=member_id,
        alias=await get_default_member_alias(db, member_id),
    )
    db.add(domain_member)
    await db.commit()
    await db.refresh(domain_member)
    return domain_member


async def out_of_the_domains(db: AsyncSession, domain_id: str, member_id: str):
    domain_member = await select_domain_members(db, domain_id, member_id)
    if domain_member is None:
        return False
    await db.delete(domain_member)
    await db.commit()
    return True


async def domain_member_infos(
    db: AsyncSession,
    domain_id: str,
    role: DomainMemberRole | None = None,
    _offset: int | None = None,
    _limit: int | None = None,
):
    query = select(DomainMembers).where(DomainMembers.domain_id == domain_id)
    domain_member_result = await db.execute(query)
    domain_members = domain_member_result.scalars().all()
    if not domain_members:
        return None, None

    search_conditions: list[ColumnElement[bool]] = [DomainMembers.domain_id == domain_id]
    if role is not None:
        search_conditions.append(DomainMembers.role == role)

    total_query = select(func.count(DomainMembers.member_id)).where(and_(*search_conditions))
    total_result = await db.execute(total_query)
    total = total_result.scalar()

    query = select(DomainMembers).where(and_(*search_conditions))
    if _offset is not None:
        query = query.offset(_offset)
    if _limit is not None:
        query = query.limit(_limit)
    result_list = await db.execute(query)
    return total, result_list.scalars().all()


async def domain_member_infos_with_users(
    db: AsyncSession,
    domain_id: str,
    role: DomainMemberRole | None = None,
    _offset: int | None = None,
    _limit: int | None = None,
):
    search_conditions: list[ColumnElement[bool]] = [DomainMembers.domain_id == domain_id]
    if role is not None:
        search_conditions.append(DomainMembers.role == role)

    total_query = select(func.count(DomainMembers.member_id)).where(and_(*search_conditions))
    total_result = await db.execute(total_query)
    total = total_result.scalar() or 0

    query = (
        select(DomainMembers, Users)
        .join(Users, Users.id == DomainMembers.member_id)
        .where(and_(*search_conditions))
        .order_by(DomainMembers.join_time.asc())
    )
    if _offset is not None:
        query = query.offset(_offset)
    if _limit is not None:
        query = query.limit(_limit)

    result = await db.execute(query)
    rows = result.all()
    return total, rows


async def change_domain_role(
    db: AsyncSession,
    domain_id: str,
    member_id: str,
    role: DomainMemberRole = DomainMemberRole.Member,
):
    query = select(DomainMembers).where(
        (DomainMembers.domain_id == domain_id) & (DomainMembers.member_id == member_id)
    )
    result = await db.execute(query)
    domain_member = result.scalar_one_or_none()
    if not domain_member:
        return None
    domain_member.role = role
    await db.commit()
    await db.refresh(domain_member)
    return domain_member


async def update_domain_member_alias(db: AsyncSession, domain_id: str, member_id: str, alias: str | None):
    query = select(DomainMembers).where(
        (DomainMembers.domain_id == domain_id) & (DomainMembers.member_id == member_id)
    )
    result = await db.execute(query)
    domain_member = result.scalar_one_or_none()
    if not domain_member:
        return None
    domain_member.alias = alias
    await db.commit()
    await db.refresh(domain_member)
    return domain_member


async def kick_domain_member(db: AsyncSession, domain_id: str, member_id: str):
    query = select(DomainMembers).where(
        (DomainMembers.domain_id == domain_id) & (DomainMembers.member_id == member_id)
    )
    result = await db.execute(query)
    domain_member = result.scalar_one_or_none()
    if not domain_member:
        return False
    await db.delete(domain_member)
    await db.commit()
    return True


async def select_domains_by_members(
    db: AsyncSession,
    member_id: str,
    _offset: int | None = None,
    _limit: int | None = None,
):
    query = select(DomainMembers).where(DomainMembers.member_id == member_id)
    result = await db.execute(query)
    domain_members = result.scalars().all()
    domain_ids = [item.domain_id for item in domain_members]
    if not domain_ids:
        return 0, []

    total_query = select(func.count(Domains.id)).where(Domains.id.in_(domain_ids))
    total_result = await db.execute(total_query)
    total = total_result.scalar()

    query = select(Domains).where(Domains.id.in_(domain_ids))
    if _offset is not None:
        query = query.offset(_offset)
    if _limit is not None:
        query = query.limit(_limit)
    result = await db.execute(query)
    return total, result.scalars().all()
