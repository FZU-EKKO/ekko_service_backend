from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from config.db_config import get_db
from crud import domain
from models.domain import DomainMemberRole
from models.users import Users
from schemas.domain import (
    ChangeDomainMemberRoleRequest,
    DomainInfo,
    DomainInfosPage,
    DomainMemberAliasUpdateRequest,
    DomainMemberInfo,
    DomainMemberSearchInfosRequest,
    DomainMembersInfoPage,
    DomainRequest,
    DomainResearchRequest,
    DomainUpdateRequest,
    KickDomainMemberRequest,
)
from utils.auth import get_current_user
from utils.file_storage import delete_uploaded_file
from utils.pagination import compute_pagination_params
from utils.response import success_response


ekko = APIRouter(prefix="/api/domains", tags=["domains"])


@ekko.post("/create_domain")
async def add_domain(
    _domain: DomainRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    new_domain = await domain.create_domain(db, user.id, _domain)
    if not new_domain:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建域失败，请稍后重试",
        )
    return success_response(
        message="创建域成功",
        data=DomainInfo.model_validate(new_domain),
    )


@ekko.get("/get_domain/{domain_id}")
async def get_domain(domain_id: str, db: AsyncSession = Depends(get_db)):
    current_domain = await domain.select_domain_id(db, domain_id)
    if not current_domain:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="未找到该域")
    return success_response(
        message=f"已找到域 {domain_id}:{current_domain.domain_name}",
        data=DomainInfo.model_validate(current_domain),
    )


@ekko.post("/")
async def select_all_domains(
    domain_inf: DomainResearchRequest,
    _pagination=Depends(compute_pagination_params),
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    total, domain_page_list = await domain.select_domains(
        db=db,
        domain_info=domain_inf,
        _offset=_pagination["offset"],
        _limit=_pagination["limit"],
    )
    return success_response(
        message="查询域成功",
        data=DomainInfosPage(
            total=total,
            domain_infos=[DomainInfo.model_validate(item) for item in domain_page_list],
        ),
    )


@ekko.put("/update_domain")
async def updated_domain(
    domain_update: DomainUpdateRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_domain = await domain.select_domain_id(db, domain_update.id)
    if not current_domain:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"未找到域 {domain_update.id}")
    if current_domain.create_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="你没有权限修改该域")

    previous_avatar = current_domain.avatar
    updated = await domain.update_domain(db, domain_update)
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="域更新失败")
    if updated.avatar != previous_avatar:
        delete_uploaded_file(previous_avatar)

    return success_response(
        message=f"修改域成功 {updated.domain_name}",
        data=DomainInfo.model_validate(updated),
    )


@ekko.delete("/delete_domain/{domain_id}")
async def deleted_domain(
    domain_id: str,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_domain = await domain.select_domain_id(db, domain_id)
    if not current_domain:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="域不存在")
    if current_domain.create_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="你没有权限删除该域")

    delete_uploaded_file(current_domain.avatar)
    deleted = await domain.delete_domain_id(db, domain_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="域不存在")

    return success_response(message="删除成功")


@ekko.get("/join_domain/{domain_id}")
async def join_domain(
    domain_id: str,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_domain = await domain.select_domain_id(db, domain_id)
    if not current_domain:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="该域不存在")

    domain_member = await domain.join_the_domains(
        db=db,
        domain_id=domain_id,
        member_id=user.id,
    )
    if not domain_member:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="禁止重复加入该域")

    return success_response(
        message="加入域成功",
        data=DomainMemberInfo.model_validate(domain_member),
    )


@ekko.get("/leave_domain/{domain_id}")
async def leave_domain(
    domain_id: str,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    left = await domain.out_of_the_domains(
        db=db,
        domain_id=domain_id,
        member_id=user.id,
    )
    if not left:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="该域中没有你的成员记录")
    return success_response(message="退出域成功")


@ekko.post("/get_domain_member_infos")
async def get_domain_member_infos(
    domain_member_search_infos: DomainMemberSearchInfosRequest,
    _page=Depends(compute_pagination_params),
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    role_str = domain_member_search_infos.role
    role = None
    if role_str == "owner":
        role = DomainMemberRole.Owner
    elif role_str == "admin":
        role = DomainMemberRole.Admin
    elif role_str == "member":
        role = DomainMemberRole.Member

    total, domain_members = await domain.domain_member_infos_with_users(
        db=db,
        domain_id=domain_member_search_infos.domain_id,
        role=role,
        _offset=_page["offset"],
        _limit=_page["limit"],
    )
    if domain_members is None and total is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="该域不存在或没有成员")

    return success_response(
        message="获取成员信息成功",
        data=DomainMembersInfoPage(
            total=total,
            domain_infos=[
                DomainMemberInfo(
                    domain_id=member.domain_id,
                    member_id=member.member_id,
                    alias=member.alias,
                    join_time=member.join_time,
                    role=member.role,
                    nick_name=current_user.nick_name,
                    avatar=current_user.avatar,
                    email=current_user.email,
                )
                for member, current_user in domain_members
            ],
        ),
    )


@ekko.put("/change_role")
async def change_role(
    change_role_req: ChangeDomainMemberRoleRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_domain = await domain.select_domain_id(db, change_role_req.domain_id)
    if not current_domain:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="该域不存在")
    if user.id != current_domain.create_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="只有域主可以修改成员权限")

    role_map = {
        "owner": DomainMemberRole.Owner,
        "admin": DomainMemberRole.Admin,
        "member": DomainMemberRole.Member,
    }
    current_role = role_map.get(change_role_req.role)
    if current_role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="无效的成员角色")

    changed_res = await domain.change_domain_role(
        db=db,
        domain_id=change_role_req.domain_id,
        member_id=change_role_req.member_id,
        role=current_role,
    )
    if not changed_res:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="目标成员不存在")

    return success_response(
        message="修改成员权限成功",
        data=DomainMemberInfo.model_validate(changed_res),
    )


@ekko.put("/member/alias")
async def update_member_alias(
    req: DomainMemberAliasUpdateRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_member = await domain.select_domain_members(db, req.domain_id, user.id)
    if not current_member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="你不在该域中")

    updated_member = await domain.update_domain_member_alias(
        db=db,
        domain_id=req.domain_id,
        member_id=user.id,
        alias=req.alias,
    )
    if not updated_member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="成员不存在")

    return success_response(
        message="更新域内别名成功",
        data=DomainMemberInfo.model_validate(updated_member),
    )


@ekko.delete("/kick_domain_member")
async def kick_domain_member(
    kick_req: KickDomainMemberRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_domain = await domain.select_domain_id(db, kick_req.domain_id)
    if not current_domain:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="该域不存在")

    _, domain_admins = await domain.domain_member_infos(
        db=db,
        domain_id=kick_req.domain_id,
        role=DomainMemberRole.Admin,
    )
    admin_ids = [member.member_id for member in (domain_admins or [])]

    if user.id != current_domain.create_id and user.id not in admin_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="你没有权限踢出成员")

    kicked = await domain.kick_domain_member(
        db=db,
        domain_id=kick_req.domain_id,
        member_id=kick_req.member_id,
    )
    if not kicked:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="目标成员不存在")

    return success_response(message="踢出成员成功")


@ekko.get("/get_domain_info_by_member_id")
async def get_my_domains(
    p=Depends(compute_pagination_params),
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    total, domains = await domain.select_domains_by_members(
        db=db,
        member_id=user.id,
        _offset=p["offset"],
        _limit=p["limit"],
    )
    return success_response(
        message="查询成功",
        data=DomainInfosPage(
            total=total,
            domain_infos=[DomainInfo.model_validate(item) for item in (domains or [])],
        ),
    )
