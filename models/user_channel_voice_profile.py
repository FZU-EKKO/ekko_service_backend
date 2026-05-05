from sqlalchemy import BIGINT, CHAR, DOUBLE, ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base
from models.channel import Channels
from models.users import Users


class UserChannelVoiceProfile(Base):
    __tablename__ = "user_channel_voice_profile"
    __table_args__ = (
        PrimaryKeyConstraint("channel_id", "user_id", name="pk_user_channel_voice_profile"),
        ForeignKeyConstraint(["channel_id"], [Channels.id], name="fk_voice_profile_channel"),
        ForeignKeyConstraint(["user_id"], [Users.id], name="fk_voice_profile_user"),
        Index("idx_voice_profile_user", "user_id"),
        Index("idx_voice_profile_baseline_count", "baseline_sentence_count"),
    )

    channel_id: Mapped[int] = mapped_column(BIGINT, nullable=False, comment="Channel ID")
    user_id: Mapped[str] = mapped_column(CHAR(7), nullable=False, comment="User ID")
    historical_avg_amplitude: Mapped[float] = mapped_column(
        DOUBLE,
        default=0,
        nullable=False,
        comment="Historical average of sentence average amplitudes",
    )
    historical_avg_frequency: Mapped[float] = mapped_column(
        DOUBLE,
        default=0,
        nullable=False,
        comment="Historical average of sentence average frequencies",
    )
    total_sentence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="Total spoken sentences")
    baseline_sentence_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Sentence count used in historical baseline, capped at 500",
    )
