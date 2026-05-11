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
    )

    channel_id: Mapped[int] = mapped_column(BIGINT, nullable=False, comment="Channel ID")
    user_id: Mapped[str] = mapped_column(CHAR(7), nullable=False, comment="User ID")
    baseline_avg_amplitude: Mapped[float] = mapped_column(
        DOUBLE,
        default=0,
        nullable=False,
        comment="Baseline average amplitude from the first N utterances",
    )
    baseline_avg_frequency: Mapped[float] = mapped_column(
        DOUBLE,
        default=0,
        nullable=False,
        comment="Baseline average peak rate from the first N utterances",
    )
    baseline_avg_char_rate: Mapped[float] = mapped_column(
        DOUBLE,
        default=0,
        nullable=False,
        comment="Baseline average transcript char rate from the first N utterances",
    )
    baseline_sample_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="How many utterances have been folded into the baseline",
    )
