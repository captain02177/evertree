"""
database.py
SQLAlchemy models and business-logic helpers for EverTree 3D.

Models:
    User        - Telegram-authenticated player
    Team        - Coop squad of 1-5 players, owns exactly one TreeState
    TreeState   - The tree's level / growth / degradation state for a Team
    TaskLog     - Record of each role-task completion (for timers + history)
    ShieldStatus- Active "Magical Shield" purchases (Telegram Stars)

Business logic:
    - Role assignment (1..5 players -> 5 roles, see assign_roles)
    - 6h/7h task-timer + degradation checker (check_degradation)
    - Scaling task-count-per-level (actions_required_for_level)
    - Referral code creation / consumption
    - Shield purchase / effect application
"""

from __future__ import annotations

import enum
import os
import random
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    create_engine,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Session,
    relationship,
    sessionmaker,
)

# --------------------------------------------------------------------------- #
# Engine / Session setup
# --------------------------------------------------------------------------- #

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///evertree3d.db")

# SQLite needs this connect_arg for multi-threaded Streamlit access.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

class Role(str, enum.Enum):
    WATERER = "suvchi"          # Waters the roots
    GARDENER = "bogbon"         # Loosens / fertilizes soil
    SUNLIGHT = "quyoshchi"      # Regulates light/warmth
    CLEANER = "tozalovchi"      # 3D pest clearing
    NURTURER = "parvarishchi"   # Plays soothing music / love

ALL_ROLES = [Role.WATERER, Role.GARDENER, Role.SUNLIGHT, Role.CLEANER, Role.NURTURER]

ROLE_LABELS = {
    Role.WATERER: "Suvchi (Waterer)",
    Role.GARDENER: "Bog'bon (Gardener)",
    Role.SUNLIGHT: "Quyoshchi (Sunlight Controller)",
    Role.CLEANER: "Tozalovchi (Cleaner)",
    Role.NURTURER: "Parvarishchi (Nurturer)",
}

TASK_CYCLE_HOURS = 6          # tasks must be completed every 6h
WARNING_WINDOW_HOURS = 1      # +1h grace ("Warning Phase") before degrade
DEGRADE_DEADLINE_HOURS = TASK_CYCLE_HOURS + WARNING_WINDOW_HOURS  # 7h

SHIELD_COST_STARS = 50
SHIELD_DURATION_DAYS = 10

MAX_TEAM_SIZE = 5
MAX_TREE_LEVEL = 999  # soft cap; stage art caps out at 31+


def actions_required_for_level(level: int) -> int:
    """Scaling difficulty: at level N, each task needs N completions per 6h cycle."""
    return max(1, level)


def stage_for_level(level: int) -> str:
    """Return the visual growth-stage key used by components/three_tree.py."""
    if level <= 0:
        return "seed"
    if level <= 5:
        return "sprout"
    if level <= 15:
        return "golden_pink"
    if level <= 30:
        return "ecosystem"
    return "fairytale"


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String(32), unique=True, nullable=False, index=True)
    first_name = Column(String(128), default="")
    last_name = Column(String(128), default="")
    username = Column(String(128), default="")
    photo_url = Column(String(512), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    role = Column(Enum(Role), nullable=True)

    team = relationship("Team", back_populates="members", foreign_keys=[team_id])

    @property
    def display_name(self) -> str:
        return self.first_name or self.username or f"Player {self.telegram_id}"


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), default="EverTree Squad")
    referral_code = Column(String(16), unique=True, nullable=False, index=True)
    owner_telegram_id = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    members = relationship("User", back_populates="team", foreign_keys=[User.team_id])
    tree = relationship("TreeState", back_populates="team", uselist=False)

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def is_full(self) -> bool:
        return self.size >= MAX_TEAM_SIZE

    @property
    def invite_link(self) -> str:
        bot_username = os.environ.get("BOT_USERNAME", "EverTree3DBot")
        return f"https://t.me/{bot_username}?startapp=team_{self.referral_code}"


class TreeState(Base):
    __tablename__ = "tree_states"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), unique=True, nullable=False)
    level = Column(Integer, default=1)
    xp = Column(Integer, default=0)
    last_degraded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    team = relationship("Team", back_populates="tree")

    @property
    def stage(self) -> str:
        return stage_for_level(self.level)


class TaskLog(Base):
    __tablename__ = "task_logs"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(Enum(Role), nullable=False)
    cycle_start = Column(DateTime, nullable=False)  # start of the current 6h window
    completions = Column(Integer, default=0)
    last_completed_at = Column(DateTime, nullable=True)


class ShieldStatus(Base):
    __tablename__ = "shield_statuses"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    purchased_by_telegram_id = Column(String(32), nullable=False)
    stars_paid = Column(Integer, default=SHIELD_COST_STARS)
    starts_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    telegram_payment_charge_id = Column(String(128), nullable=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    return SessionLocal()


# --------------------------------------------------------------------------- #
# Referral codes
# --------------------------------------------------------------------------- #

def _generate_referral_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_team(db: Session, owner: "User", name: Optional[str] = None) -> Team:
    code = _generate_referral_code()
    while db.query(Team).filter_by(referral_code=code).first():
        code = _generate_referral_code()

    team = Team(
        name=name or f"{owner.display_name}'s Grove",
        referral_code=code,
        owner_telegram_id=owner.telegram_id,
    )
    db.add(team)
    db.flush()

    tree = TreeState(team_id=team.id, level=1, xp=0)
    db.add(tree)

    owner.team_id = team.id
    db.flush()
    db.expire(team, ["members"])  # force a fresh load of the members collection

    assign_roles(db, team)
    db.commit()
    return team


def join_team_by_code(db: Session, user: "User", referral_code: str) -> Optional[Team]:
    """Consume a referral link: t.me/Bot?startapp=team_<code>."""
    code = referral_code.replace("team_", "").strip().upper()
    team = db.query(Team).filter_by(referral_code=code).first()
    if not team or team.is_full:
        return None

    user.team_id = team.id
    db.flush()
    db.expire(team, ["members"])  # force a fresh load of the members collection
    assign_roles(db, team)
    db.commit()
    return team


# --------------------------------------------------------------------------- #
# Role assignment
# --------------------------------------------------------------------------- #

def assign_roles(db: Session, team: Team) -> None:
    """
    Re-derive role assignment for a team, per the spec:
      - 1 player  -> gets ALL 5 roles (represented as role=None -> "all roles" in UI)
      - 2-4       -> unassigned roles randomly distributed (players may hold >1 role)
      - 5 players -> exactly 1 role each
    Existing explicit single-role assignments are preserved where possible;
    only unassigned members/roles are shuffled.
    """
    members = list(team.members)
    if not members:
        return

    if len(members) == 1:
        solo = members[0]
        solo.role = None  # None == "holds all 5 roles"
        db.flush()
        return

    # For 2-5 players: assign each member exactly one *primary* role first,
    # ensuring all 5 roles are covered; extras wrap around randomly.
    unassigned_members = [m for m in members if m.role is None]
    taken_roles = {m.role for m in members if m.role is not None}
    free_roles = [r for r in ALL_ROLES if r not in taken_roles]
    random.shuffle(free_roles)
    random.shuffle(unassigned_members)

    pool = list(free_roles)
    for member in unassigned_members:
        if not pool:
            pool = list(ALL_ROLES)
            random.shuffle(pool)
        member.role = pool.pop()

    db.flush()


def roles_for_user(user: "User") -> list[Role]:
    """A solo player (role is None) effectively holds every role."""
    if user.team and user.team.size == 1:
        return list(ALL_ROLES)
    return [user.role] if user.role else []


# --------------------------------------------------------------------------- #
# Task completion + 6h/7h degradation
# --------------------------------------------------------------------------- #

def _current_cycle_start(now: Optional[datetime] = None) -> datetime:
    """Floor 'now' to the start of the current TASK_CYCLE_HOURS-hour window."""
    now = now or datetime.utcnow()
    epoch = datetime(1970, 1, 1)
    hours_since_epoch = int((now - epoch).total_seconds() // 3600)
    floored = hours_since_epoch - (hours_since_epoch % TASK_CYCLE_HOURS)
    return epoch + timedelta(hours=floored)


def get_or_create_task_log(db: Session, team: Team, user: "User", role: Role) -> TaskLog:
    cycle_start = _current_cycle_start()
    log = (
        db.query(TaskLog)
        .filter_by(team_id=team.id, role=role, cycle_start=cycle_start)
        .first()
    )
    if not log:
        log = TaskLog(
            team_id=team.id,
            user_id=user.id,
            role=role,
            cycle_start=cycle_start,
            completions=0,
        )
        db.add(log)
        db.flush()
    return log


def complete_task(db: Session, team: Team, user: "User", role: Role) -> TaskLog:
    """Record one completion of `role`'s task for the current cycle."""
    log = get_or_create_task_log(db, team, user, role)
    log.completions += 1
    log.last_completed_at = datetime.utcnow()
    log.user_id = user.id

    tree = team.tree
    required = actions_required_for_level(tree.level)
    if log.completions >= required:
        tree.xp += 10
    db.commit()
    return log


def task_status(db: Session, team: Team, role: Role) -> dict:
    """
    Returns {'state': 'done'|'warning'|'missed'|'pending', 'completions': int,
             'required': int, 'deadline': datetime}
    for the CURRENT 6h cycle, used to color-code the Team Panel
    (Green = Done, Yellow = Warning, Red = Missed).
    """
    cycle_start = _current_cycle_start()
    now = datetime.utcnow()
    tree = team.tree
    required = actions_required_for_level(tree.level)

    log = (
        db.query(TaskLog)
        .filter_by(team_id=team.id, role=role, cycle_start=cycle_start)
        .first()
    )
    completions = log.completions if log else 0

    warn_at = cycle_start + timedelta(hours=TASK_CYCLE_HOURS)
    deadline = cycle_start + timedelta(hours=DEGRADE_DEADLINE_HOURS)

    if has_active_shield(db, team):
        state = "done" if completions >= required else "shielded"
    elif completions >= required:
        state = "done"
    elif now >= deadline:
        state = "missed"
    elif now >= warn_at:
        state = "warning"
    else:
        state = "pending"

    return {
        "state": state,
        "completions": completions,
        "required": required,
        "cycle_start": cycle_start,
        "warn_at": warn_at,
        "deadline": deadline,
    }


def check_degradation(db: Session, team: Team) -> Optional[str]:
    """
    Call periodically (e.g. on every page load / a background job).
    If the PREVIOUS cycle ended with any role missed and no shield is active,
    degrade the tree by 1 level (min 1) and log an alert.
    Returns an alert message string if a degradation occurred, else None.
    """
    tree = team.tree
    if not tree:
        return None

    if has_active_shield(db, team):
        return None

    now = datetime.utcnow()
    prev_cycle_start = _current_cycle_start(now) - timedelta(hours=TASK_CYCLE_HOURS)
    prev_deadline = prev_cycle_start + timedelta(hours=DEGRADE_DEADLINE_HOURS)

    # Only evaluate once per completed cycle, and only after the 7h deadline passed.
    if now < prev_deadline:
        return None
    if tree.last_degraded_at and tree.last_degraded_at >= prev_cycle_start:
        return None  # already handled this cycle

    failed_roles = []
    for role in ALL_ROLES:
        required = actions_required_for_level(tree.level)
        log = (
            db.query(TaskLog)
            .filter_by(team_id=team.id, role=role, cycle_start=prev_cycle_start)
            .first()
        )
        completions = log.completions if log else 0
        if completions < required:
            failed_roles.append(role)

    if failed_roles:
        tree.level = max(1, tree.level - 1)
        tree.last_degraded_at = now
        db.commit()
        names = ", ".join(ROLE_LABELS[r] for r in failed_roles)
        return f"⚠️ {names} failed their duty! The tree withered to Level {tree.level}."

    tree.last_degraded_at = now
    db.commit()
    return None


# --------------------------------------------------------------------------- #
# Shield ("Magical Shield") - Telegram Stars monetization
# --------------------------------------------------------------------------- #

def has_active_shield(db: Session, team: Team) -> bool:
    now = datetime.utcnow()
    active = (
        db.query(ShieldStatus)
        .filter(ShieldStatus.team_id == team.id, ShieldStatus.expires_at > now)
        .first()
    )
    return active is not None


def get_active_shield(db: Session, team: Team) -> Optional[ShieldStatus]:
    now = datetime.utcnow()
    return (
        db.query(ShieldStatus)
        .filter(ShieldStatus.team_id == team.id, ShieldStatus.expires_at > now)
        .order_by(ShieldStatus.expires_at.desc())
        .first()
    )


def activate_shield(
    db: Session,
    team: Team,
    purchaser_telegram_id: str,
    telegram_payment_charge_id: Optional[str] = None,
    stars_paid: int = SHIELD_COST_STARS,
) -> ShieldStatus:
    """
    Call after a successful Telegram Stars payment
    (bot.py's successful_payment handler) to grant/extend the shield.
    """
    now = datetime.utcnow()
    existing = get_active_shield(db, team)
    start_from = existing.expires_at if existing else now

    shield = ShieldStatus(
        team_id=team.id,
        purchased_by_telegram_id=purchaser_telegram_id,
        stars_paid=stars_paid,
        starts_at=start_from,
        expires_at=start_from + timedelta(days=SHIELD_DURATION_DAYS),
        telegram_payment_charge_id=telegram_payment_charge_id,
    )
    db.add(shield)
    db.commit()
    return shield


# --------------------------------------------------------------------------- #
# User lookup / registration
# --------------------------------------------------------------------------- #

def get_or_create_user(
    db: Session,
    telegram_id: str,
    first_name: str = "",
    last_name: str = "",
    username: str = "",
    photo_url: str = "",
) -> User:
    user = db.query(User).filter_by(telegram_id=str(telegram_id)).first()
    if user:
        # Keep the cloned Telegram profile fresh.
        user.first_name = first_name or user.first_name
        user.last_name = last_name or user.last_name
        user.username = username or user.username
        user.photo_url = photo_url or user.photo_url
        db.commit()
        return user

    user = User(
        telegram_id=str(telegram_id),
        first_name=first_name,
        last_name=last_name,
        username=username,
        photo_url=photo_url,
    )
    db.add(user)
    db.commit()
    return user
