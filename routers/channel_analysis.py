from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from config.db_config import get_db
from crud import channel, domain
from models.users import Users
from schemas.channel_analysis import ChannelAnalysisRequest, ChannelAnalysisResponse
from utils.auth import get_current_user
from utils.channel_analyzer import analyze_channel_conversation
from utils.response import success_response


ekko = APIRouter(prefix="/api/channels", tags=["channel_analysis"])


async def _assert_channel_access(db: AsyncSession, *, channel_id: int, user_id: str):
    current_channel = await channel.select_channel_id(db, channel_id)
    if not current_channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Channel does not exist")

    member = await domain.select_domain_members(db, current_channel.domain_id, user_id)
    if not member:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You are not a member of this domain")

    return current_channel


@ekko.post("/{channel_id}/analyze")
async def analyze_channel(
    channel_id: int,
    req: ChannelAnalysisRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_channel_access(db, channel_id=channel_id, user_id=user.id)

    try:
        result = await analyze_channel_conversation(
            db=db,
            channel_id=channel_id,
            prompt=req.prompt,
            start_time=req.start_time,
            end_time=req.end_time,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return success_response(
        message="Channel analyzed",
        data=ChannelAnalysisResponse(**result),
    )
