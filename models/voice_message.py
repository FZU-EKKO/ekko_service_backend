from sqlalchemy import BIGINT, BOOLEAN, CHAR, DOUBLE, ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint, Text, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base
from models.channel import Channels
from models.users import Users


class VoiceMessages(Base):
    __tablename__ = "voice_messages"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_voice_message"),
        ForeignKeyConstraint(["channel_id"], [Channels.id], name="fk_voice_message_channel"),
        ForeignKeyConstraint(["user_id"], [Users.id], name="fk_voice_message_user"),
        Index("idx_voice_message_channel_created", "channel_id", "created_at"),
        Index("idx_voice_message_user_created", "user_id", "created_at"),
        Index("idx_voice_message_client_id", "client_message_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True, comment="Voice message ID")
    channel_id: Mapped[int] = mapped_column(BIGINT, nullable=False, comment="Channel ID")
    user_id: Mapped[str] = mapped_column(CHAR(7), nullable=False, comment="Sender user ID")
    client_message_id: Mapped[str | None] = mapped_column(
        VARCHAR(64),
        nullable=True,
        comment="Client-generated message ID for deduplication",
    )
    audio_path: Mapped[str] = mapped_column(Text, nullable=False, comment="Stored audio path")
    audio_duration_ms: Mapped[int] = mapped_column(Integer, default=0, comment="Audio duration in milliseconds")
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Optional transcript text")
    avg_amplitude: Mapped[float | None] = mapped_column(
        DOUBLE,
        nullable=True,
        comment="Average absolute amplitude of the utterance waveform",
    )
    avg_frequency: Mapped[float | None] = mapped_column(
        DOUBLE,
        nullable=True,
        comment="Speech-rate proxy as envelope peak count per second",
    )
    avg_char_rate: Mapped[float | None] = mapped_column(
        DOUBLE,
        nullable=True,
        comment="Speech-rate feature as transcript characters per second",
    )
    is_excited: Mapped[bool] = mapped_column(BOOLEAN, default=False, comment="Whether the utterance is excited")
    transcription_status: Mapped[str] = mapped_column(
        VARCHAR(20),
        default="pending",
        nullable=False,
        comment="Asynchronous transcription status",
    )
