import enum
from datetime import datetime

from sqlalchemy import BIGINT, CHAR, JSON, DateTime, Enum, ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base
from models.channel import Channels
from models.users import Users


class TranscriptSessionStatus(enum.Enum):
    Active = "active"
    Processing = "processing"
    Completed = "completed"
    Failed = "failed"


class TranscriptSessions(Base):
    __tablename__ = "transcript_sessions"
    __table_args__ = (
        ForeignKeyConstraint(["channel_id"], [Channels.id], name="fk_transcript_session_channel"),
        ForeignKeyConstraint(["started_by"], [Users.id], name="fk_transcript_session_user"),
        Index("idx_transcript_session_channel", "channel_id"),
        Index("idx_transcript_session_status", "status"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True, comment="Transcript session ID")
    channel_id: Mapped[int] = mapped_column(BIGINT, nullable=False, comment="Channel ID")
    started_by: Mapped[str] = mapped_column(CHAR(7), nullable=False, comment="Session owner user ID")
    status: Mapped[TranscriptSessionStatus] = mapped_column(
        Enum(TranscriptSessionStatus, values_callable=lambda items: [item.value for item in items]),
        default=TranscriptSessionStatus.Active,
        comment="Transcript session status",
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="Session start time")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="Session end time")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Last processing error")


class TranscriptSegments(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_transcript_segment"),
        ForeignKeyConstraint(["session_id"], [TranscriptSessions.id], name="fk_transcript_segment_session"),
        ForeignKeyConstraint(["user_id"], [Users.id], name="fk_transcript_segment_user"),
        Index("idx_transcript_segment_session", "session_id"),
        Index("idx_transcript_segment_user", "user_id"),
        Index("idx_transcript_segment_seq", "session_id", "seq_no"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True, comment="Transcript segment ID")
    session_id: Mapped[int] = mapped_column(BIGINT, nullable=False, comment="Transcript session ID")
    user_id: Mapped[str] = mapped_column(CHAR(7), nullable=False, comment="Speaker user ID")
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="Per-session sequence number")
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, comment="Segment start timestamp in ms")
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, comment="Segment end timestamp in ms")
    text: Mapped[str] = mapped_column(Text, nullable=False, comment="Transcript text")
    is_final: Mapped[bool] = mapped_column(default=True, comment="Whether the segment is finalized")
    words: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True, comment="Word-level timestamps")
