"""
app.py
Streamlit entry point for EverTree 3D — Telegram Mini App.

Handles:
    - Telegram WebApp session init (reads initDataUnsafe via a small JS bridge).
    - User registration/login + profile cloning.
    - Referral-link consumption (?startapp=team_<code>).
    - UI tabs: 3D Tree View, Team Status, Tasks, Shop/Shield, Leaderboard.
"""

from __future__ import annotations

import json
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

from components.three_tree import render_tree
from database import (
    ALL_ROLES,
    ROLE_LABELS,
    SHIELD_COST_STARS,
    SHIELD_DURATION_DAYS,
    Role,
    TASK_CYCLE_HOURS,
    check_degradation,
    complete_task,
    create_team,
    get_active_shield,
    get_or_create_user,
    get_session,
    has_active_shield,
    init_db,
    join_team_by_code,
    roles_for_user,
    task_status,
)

st.set_page_config(page_title="EverTree 3D", page_icon="🌳", layout="wide")
init_db()

# --------------------------------------------------------------------------- #
# 1. Pull Telegram WebApp initData into Streamlit via query params
# --------------------------------------------------------------------------- #
# Telegram Mini Apps expose window.Telegram.WebApp.initDataUnsafe on the client.
# We bridge it into Streamlit by writing it into the URL query string once,
# then reading it with st.query_params. This runs once per session.

TG_BRIDGE_JS = """
<script>
(function() {
  try {
    const tg = window.Telegram ? window.Telegram.WebApp : null;
    if (!tg) return;
    tg.ready();
    tg.expand();
    const u = tg.initDataUnsafe && tg.initDataUnsafe.user;
    const startParam = tg.initDataUnsafe && tg.initDataUnsafe.start_param;
    const params = new URLSearchParams(window.parent.location.search);
    let changed = false;
    if (u && !params.get('tg_id')) {
      params.set('tg_id', u.id);
      params.set('tg_first', u.first_name || '');
      params.set('tg_last', u.last_name || '');
      params.set('tg_username', u.username || '');
      params.set('tg_photo', u.photo_url || '');
      changed = true;
    }
    if (startParam && !params.get('startapp')) {
      params.set('startapp', startParam);
      changed = true;
    }
    if (changed) {
      window.parent.location.search = params.toString();
    }
  } catch (e) { console.error('TG bridge error', e); }
})();
</script>
"""
components.html(TG_BRIDGE_JS, height=0)

qp = st.query_params
tg_id = qp.get("tg_id")
tg_first = qp.get("tg_first", "")
tg_last = qp.get("tg_last", "")
tg_username = qp.get("tg_username", "")
tg_photo = qp.get("tg_photo", "")
startapp = qp.get("startapp", "")

# Local/dev fallback so the app is testable outside Telegram.
if not tg_id:
    with st.sidebar:
        st.warning("No Telegram session detected — using dev login.")
        tg_id = st.text_input("Dev Telegram ID", value="000001")
        tg_first = st.text_input("Dev First Name", value="DevPlayer")

db = get_session()
user = get_or_create_user(
    db,
    telegram_id=tg_id,
    first_name=tg_first,
    last_name=tg_last,
    username=tg_username,
    photo_url=tg_photo,
)

# --------------------------------------------------------------------------- #
# 2. Referral link consumption
# --------------------------------------------------------------------------- #
if startapp and startapp.startswith("team_") and not user.team_id:
    joined = join_team_by_code(db, user, startapp)
    if joined:
        st.toast(f"Joined {joined.name}! 🌳", icon="🎉")
    else:
        st.toast("That invite link is invalid or the team is full.", icon="⚠️")

# --------------------------------------------------------------------------- #
# 3. No team yet -> onboarding
# --------------------------------------------------------------------------- #
if not user.team_id:
    st.title("🌳 EverTree 3D")
    st.subheader("Grow a magical tree together with your squad")
    st.write(f"Welcome, **{user.display_name}**!")
    name = st.text_input("Name your Grove", value=f"{user.display_name}'s Grove")
    if st.button("🌱 Start a new Grove", type="primary"):
        team = create_team(db, user, name=name)
        st.rerun()
    st.stop()

team = user.team
tree = team.tree

# --------------------------------------------------------------------------- #
# 4. Degradation check (run on every load)
# --------------------------------------------------------------------------- #
alert = check_degradation(db, team)
if alert:
    st.error(alert)

shield_active = has_active_shield(db, team)
active_shield = get_active_shield(db, team) if shield_active else None
my_roles = roles_for_user(user)

# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
header_l, header_r = st.columns([3, 1])
with header_l:
    st.markdown(f"## 🌳 {team.name}")
    cols = st.columns(4)
    cols[0].metric("Tree Level", tree.level)
    cols[1].metric("Team Size", f"{team.size}/5")
    cols[2].metric("XP", tree.xp)
    cols[3].metric("Shield", "🛡️ Active" if shield_active else "—")
with header_r:
    if user.photo_url:
        st.image(user.photo_url, width=64)
    st.caption(f"**{user.display_name}**")
    if my_roles:
        st.caption(" / ".join(ROLE_LABELS[r] for r in my_roles))

st.divider()

tab_tree, tab_team, tab_tasks, tab_shop, tab_board = st.tabs(
    ["🌳 3D Tree", "👥 Team", "✅ Tasks", "🛒 Shop", "🏆 Leaderboard"]
)

# --------------------------------------------------------------------------- #
# Tab: 3D Tree View
# --------------------------------------------------------------------------- #
with tab_tree:
    pest_mode = "pest_mode" in st.session_state and st.session_state.pest_mode
    render_tree(
        level=tree.level,
        stage=tree.stage,
        shield_active=shield_active,
        pest_mode=pest_mode,
        pest_count=max(2, tree.level // 3 + 2),
        height=520,
        key=f"tree_{team.id}_{tree.level}_{pest_mode}",
    )
    if pest_mode:
        st.info("Tap/click the pests crawling on the trunk to clear them 🐛")
        if st.button("✅ I cleared them (confirm)"):
            complete_task(db, team, user, Role.CLEANER)
            st.session_state.pest_mode = False
            st.success("Pests cleared! Tozalovchi task complete.")
            st.rerun()

# --------------------------------------------------------------------------- #
# Tab: Control Panel (role actions)
# --------------------------------------------------------------------------- #
with tab_tasks:
    st.markdown("### Your Role Actions")
    if not my_roles:
        st.info("You'll be assigned a role once more teammates join, or you'll get all 5 roles solo.")
    for role in my_roles:
        status = task_status(db, team, role)
        badge = {"done": "🟢", "warning": "🟡", "missed": "🔴", "pending": "⚪", "shielded": "🛡️"}[status["state"]]
        st.markdown(f"#### {badge} {ROLE_LABELS[role]} — {status['completions']}/{status['required']} this cycle")

        action_label = {
            Role.WATERER: "💧 Water Tree",
            Role.GARDENER: "🪴 Loosen Soil",
            Role.SUNLIGHT: "☀️ Adjust Sunlight",
            Role.CLEANER: "🐛 Clear Pests (open 3D view)",
            Role.NURTURER: "🎵 Send Love",
        }[role]

        col_a, col_b = st.columns([1, 2])
        with col_a:
            if role == Role.CLEANER:
                if st.button(action_label, key=f"act_{role}"):
                    st.session_state.pest_mode = True
                    st.info("Switch to the 🌳 3D Tree tab to squash the pests!")
            else:
                if st.button(action_label, key=f"act_{role}"):
                    complete_task(db, team, user, role)
                    st.success(f"{ROLE_LABELS[role]} task logged!")
                    st.rerun()
        with col_b:
            st.progress(min(1.0, status["completions"] / status["required"]))
    st.caption(
        f"Tasks reset every {TASK_CYCLE_HOURS}h. A 1h warning phase follows, then a missed "
        f"task degrades the tree by 1 level (unless a Magical Shield is active)."
    )

# --------------------------------------------------------------------------- #
# Tab: Team Panel
# --------------------------------------------------------------------------- #
with tab_team:
    st.markdown("### Team Members")
    for member in team.members:
        m_roles = roles_for_user(member)
        role_str = ", ".join(ROLE_LABELS[r] for r in m_roles) if m_roles else "Unassigned"
        cols = st.columns([1, 3, 2])
        with cols[0]:
            if member.photo_url:
                st.image(member.photo_url, width=48)
            else:
                st.write("👤")
        with cols[1]:
            st.write(f"**{member.display_name}**")
            st.caption(role_str)
        with cols[2]:
            states = [task_status(db, team, r)["state"] for r in m_roles] if m_roles else []
            dot = {"done": "🟢", "warning": "🟡", "missed": "🔴", "pending": "⚪", "shielded": "🛡️"}
            st.write(" ".join(dot.get(s, "⚪") for s in states) or "—")

    st.divider()
    st.markdown("### Invite Teammates")
    if team.is_full:
        st.success("Your grove is full (5/5)! 🌳")
    else:
        st.code(team.invite_link, language=None)
        st.caption("Share this link — clicking it auto-joins the team and assigns an open role.")

# --------------------------------------------------------------------------- #
# Tab: Shop (Telegram Stars — Magical Shield)
# --------------------------------------------------------------------------- #
with tab_shop:
    st.markdown("### 🛡️ Magical Shield")
    st.write(
        f"Protects your tree from degradation for **{SHIELD_DURATION_DAYS} days**, "
        f"even if tasks are missed. Costs **{SHIELD_COST_STARS} Telegram Stars**."
    )
    if shield_active and active_shield:
        st.success(f"Shield active until **{active_shield.expires_at.strftime('%Y-%m-%d %H:%M UTC')}**")
    st.markdown(
        "Purchases are completed via the Telegram bot's `/shield` command or the "
        "**Buy Shield** inline button (Telegram Stars invoice), since in-app "
        "Stars payments must be initiated through the Bot API, not the web view."
    )
    if st.button("🔗 Open Bot to Buy Shield"):
        bot_username = "EverTree3DBot"
        st.markdown(f"[Open @{bot_username} to purchase →](https://t.me/{bot_username}?start=shield_{team.id})")

# --------------------------------------------------------------------------- #
# Tab: Leaderboard
# --------------------------------------------------------------------------- #
with tab_board:
    st.markdown("### 🏆 Top Groves")
    from database import Team as TeamModel, TreeState as TreeStateModel

    top = (
        db.query(TeamModel, TreeStateModel)
        .join(TreeStateModel, TreeStateModel.team_id == TeamModel.id)
        .order_by(TreeStateModel.level.desc(), TreeStateModel.xp.desc())
        .limit(20)
        .all()
    )
    for i, (t, ts) in enumerate(top, start=1):
        marker = "👑" if t.id == team.id else f"{i}."
        st.write(f"{marker} **{t.name}** — Level {ts.level} ({ts.xp} XP)")

db.close()
