from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from config.db_config import get_db
from config.livekit_config import livekit_is_configured
from crud import channel, domain
from models.channel import ChannelType
from models.domain import DomainMemberRole
from models.users import Users
from schemas.channel import (
    ChannelCreateRequest,
    ChannelInfo,
    ChannelInfosPage,
    ChannelJoinRequest,
    ChannelLeaveRequest,
    ChannelMemberInfo,
    ChannelMemberStateUpdateRequest,
    ChannelMembersPage,
    ChannelUpdateRequest,
    LiveKitJoinResponse,
)
from utils.auth import get_current_user
from utils.livekit import build_room_name, get_livekit_connection_info
from utils.pagination import compute_pagination_params
from utils.response import success_response


ekko = APIRouter(prefix="/api/channels", tags=["channels"])


def _parse_channel_type(channel_type: str) -> ChannelType:
    value = channel_type.lower()
    mapping = {
        "voice": ChannelType.Voice,
        "text": ChannelType.Text,
        "both": ChannelType.Both,
    }
    parsed = mapping.get(value)
    if parsed is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="无效的频道类型")
    return parsed


async def _get_domain_member_role(db: AsyncSession, domain_id: str, member_id: str):
    member = await domain.select_domain_members(db, domain_id, member_id)
    if not member:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="你不是该域成员")
    return member.role


@ekko.post("/create_channel")
async def create_channel(
    req: ChannelCreateRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_domain = await domain.select_domain_id(db, req.domain_id)
    if not current_domain:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="域不存在")

    role = await _get_domain_member_role(db, req.domain_id, user.id)
    if role not in (DomainMemberRole.Owner, DomainMemberRole.Admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="只有域主或管理员可以创建频道")

    created = await channel.create_channel(
        db,
        domain_id=req.domain_id,
        create_id=user.id,
        channel_name=req.channel_name,
        description=req.description,
        max_capacity=req.max_capacity,
        channel_type=_parse_channel_type(req.channel_type),
    )
    return success_response(
        message="创建频道成功",
        data=ChannelInfo.model_validate(created),
    )


@ekko.get("/get_channel/{channel_id}")
async def get_channel(channel_id: int, db: AsyncSession = Depends(get_db)):
    current_channel = await channel.select_channel_id(db, channel_id)
    if not current_channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="频道不存在")
    return success_response(
        message="查询频道成功",
        data=ChannelInfo.model_validate(current_channel),
    )


@ekko.get("/list_by_domain/{domain_id}")
async def list_channels_by_domain(
    domain_id: str,
    _pagination=Depends(compute_pagination_params),
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_domain_member_role(db, domain_id, user.id)
    total, rows = await channel.select_channels_by_domain(
        db,
        domain_id,
        offset=_pagination["offset"],
        limit=_pagination["limit"],
    )
    return success_response(
        message="查询频道列表成功",
        data=ChannelInfosPage(
            total=total,
            channel_infos=[ChannelInfo.model_validate(item) for item in rows],
        ),
    )


@ekko.put("/update_channel")
async def update_channel(
    req: ChannelUpdateRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_channel = await channel.select_channel_id(db, req.id)
    if not current_channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="频道不存在")

    role = await _get_domain_member_role(db, current_channel.domain_id, user.id)
    if user.id != current_channel.create_id and role not in (DomainMemberRole.Owner, DomainMemberRole.Admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="你没有权限修改该频道")

    payload = req.model_dump(exclude_unset=True, exclude_none=True)
    payload.pop("id", None)
    if "channel_type" in payload:
        payload["channel_type"] = _parse_channel_type(payload["channel_type"])
    updated = await channel.update_channel(db, req.id, payload)
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="频道不存在")

    return success_response(
        message="更新频道成功",
        data=ChannelInfo.model_validate(updated),
    )


@ekko.delete("/delete_channel/{channel_id}")
async def delete_channel(
    channel_id: int,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_channel = await channel.select_channel_id(db, channel_id)
    if not current_channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="频道不存在")

    role = await _get_domain_member_role(db, current_channel.domain_id, user.id)
    if user.id != current_channel.create_id and role not in (DomainMemberRole.Owner, DomainMemberRole.Admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="你没有权限删除该频道")

    deleted = await channel.delete_channel(db, channel_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="频道不存在")
    return success_response(message="删除频道成功")


@ekko.post("/join")
async def join_channel(
    req: ChannelJoinRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_channel = await channel.select_channel_id(db, req.channel_id)
    if not current_channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="频道不存在")

    await _get_domain_member_role(db, current_channel.domain_id, user.id)
    if current_channel.current_voice_count >= current_channel.max_capacity:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="频道已满")

    member = await channel.join_channel(db, channel=current_channel, member_id=user.id)
    if not member:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="你已经在该频道中")

    return success_response(
        message="加入频道成功",
        data=ChannelMemberInfo.model_validate(member),
    )


@ekko.post("/leave")
async def leave_channel(
    req: ChannelLeaveRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_channel = await channel.select_channel_id(db, req.channel_id)
    if not current_channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="频道不存在")

    left = await channel.leave_channel(db, channel=current_channel, member_id=user.id)
    if not left:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="你不在该频道中")
    return success_response(message="离开频道成功")


@ekko.put("/member/state")
async def update_channel_member_state(
    req: ChannelMemberStateUpdateRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_channel = await channel.select_channel_id(db, req.channel_id)
    if not current_channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="频道不存在")

    await _get_domain_member_role(db, current_channel.domain_id, user.id)

    updated_member = await channel.update_channel_member_state(
        db,
        channel_id=req.channel_id,
        member_id=user.id,
        microphone_state=req.microphone_state,
        speaker_state=req.speaker_state,
    )
    if not updated_member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="你不在该频道中")

    return success_response(
        message="更新频道成员音频状态成功",
        data=ChannelMemberInfo.model_validate(updated_member),
    )


@ekko.get("/members/{channel_id}")
async def get_channel_members(
    channel_id: int,
    _pagination=Depends(compute_pagination_params),
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_channel = await channel.select_channel_id(db, channel_id)
    if not current_channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="频道不存在")

    await _get_domain_member_role(db, current_channel.domain_id, user.id)
    total, rows = await channel.select_channel_members(
        db,
        channel_id,
        offset=_pagination["offset"],
        limit=_pagination["limit"],
    )
    return success_response(
        message="查询频道成员成功",
        data=ChannelMembersPage(
            total=total,
            channel_members=[ChannelMemberInfo.model_validate(item) for item in rows],
        ),
    )


@ekko.post("/livekit/token")
async def get_livekit_token(
    req: ChannelJoinRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_channel = await channel.select_channel_id(db, req.channel_id)
    if not current_channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="频道不存在")
    if current_channel.channel_type == ChannelType.Text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="文本频道不支持语音通话")

    await _get_domain_member_role(db, current_channel.domain_id, user.id)

    existing_member = await channel.select_channel_member(db, req.channel_id, user.id)
    if not existing_member:
        if current_channel.current_voice_count >= current_channel.max_capacity:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="频道已满")
        existing_member = await channel.join_channel(db, channel=current_channel, member_id=user.id)
        if not existing_member:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="加入频道失败")

    if not livekit_is_configured():
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LiveKit 未配置，请设置 EKKO_LIVEKIT_URL、EKKO_LIVEKIT_API_KEY、EKKO_LIVEKIT_API_SECRET",
        )

    connection_info = get_livekit_connection_info(
        identity=user.id,
        room_name=build_room_name(current_channel.domain_id, current_channel.id),
        participant_name=user.nick_name,
    )
    return success_response(
        message="获取 LiveKit token 成功",
        data=LiveKitJoinResponse(**connection_info),
    )
