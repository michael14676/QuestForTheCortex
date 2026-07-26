"""
Team Scoreboard Dashboard
--------------------------
Reads score entries from a private Google Sheet (via a Google service account)
and displays:
  - A bar chart comparing total points across teams
  - Beneath the chart, each team's most recent scoring entry
    (category as subtitle, comment as the detail text)

SETUP REQUIRED (one-time):
  1. Create a Google Cloud project, enable the Google Sheets API.
  2. Create a service account, download its JSON key.
  3. Share your Google Sheet with the service account's client_email
     (Viewer access is enough).
  4. Put the service account JSON into .streamlit/secrets.toml locally
     (see the [gcp_service_account] section below), or into Streamlit
     Cloud's "Secrets" settings when deployed. Never commit secrets.toml
     to a public repo.

Expected columns in the "Form Responses 1" sheet:
  Timestamp | Points Awarded | Team | category | Comments
"""

import streamlit as st
import pandas as pd
from streamlit_autorefresh import st_autorefresh
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials

# ----------------------------------------------------------------------------
# CONFIG — edit these to match your setup
# ----------------------------------------------------------------------------

# The ID from your Sheet's URL:
# https://docs.google.com/spreadsheets/d/THIS_PART_IS_THE_ID/edit
SHEET_ID = "1Cd4SsjJfF0Fq-WYJJz05XDnH0wkzzDWlufYKIhZi6cw"

# The exact tab name your form responses land on
WORKSHEET_NAME = "Sheet1"

# Column names exactly as they appear in your Sheet
COL_TIMESTAMP = "Timestamp"
COL_POINTS = "Points Awarded"
COL_TEAM = "Team"
COL_CATEGORY = "category"
COL_COMMENT = "Comments"

# Fix team names/order here if you want a consistent order in the chart
TEAM_ORDER = None  # e.g. ["Team A", "Team B", "Team C"], or None to auto-detect

# Auto-refresh interval in milliseconds (45 seconds)
REFRESH_INTERVAL_MS = 45_000

# ============================================================================
# 🎨  DECORATION — EDIT THIS SECTION TO CUSTOMIZE 🎨
# ============================================================================
# Everything below is just text, emojis, and colors — no logic. Change
# anything between quotes and save the file to update the dashboard.
#
# Colors use hex codes, e.g. "#E9A319". Pick one visually at
# https://htmlcolorcodes.com and paste the code shown there.
# Emojis: copy/paste one from https://emojipedia.org
#
# ⚠️ IMPORTANT: the key on the left of each team entry below (e.g.
# "Ryan and the Pryon Lyons") MUST exactly match how that team's name is
# spelled in the "Team" column of the Google Sheet — capitalization
# included. Everything indented under it (display_name, emoji, color) is
# pure decoration and safe to change freely.
# ============================================================================

PAGE_TITLE = "🗺️ Quest for the Cortex"
PAGE_SUBTITLE = "A Chronicle of Trials, Triumphs, and the Path to Mastery"

TEAM_DISPLAY = {
    "Ryan and the Pryon Lyons": {
        "display_name": "Ryan and the Pryon Lyons",
        "emoji": "🦁",
        "color": "#B8860B",  # antique gold
    },
    "Basal Ganglia Baddies": {
        "display_name": "Basal Ganglia Baddies",
        "emoji": "🧠",
        "color": "#5D3A9B",  # deep royal violet
    },
    "Mad Cowz": {
        "display_name": "Mad Cowz",
        "emoji": "🐄",
        "color": "#A32020",  # oxblood red
    },
}

# Rank titles unlocked as a team's total points climb. Add, remove, rename,
# or rebalance thresholds freely — just keep the list sorted by threshold.
RANK_TITLES = [
    (0, "Apprentice of the Mind"),
    (10, "Journeyman Healer"),
    (25, "Adept of the Cortex"),
    (50, "Master Neuromancer"),
    (100, "Grandmaster of the Realm"),
]


def rank_for(points: float) -> str:
    """Return the highest rank title earned for a given point total."""
    title = RANK_TITLES[0][1]
    for threshold, name in RANK_TITLES:
        if points >= threshold:
            title = name
    return title


def display_for(team_raw_name: str) -> dict:
    """Look up display info for a team; fall back gracefully if not configured."""
    if team_raw_name in TEAM_DISPLAY:
        return TEAM_DISPLAY[team_raw_name]
    return {"display_name": team_raw_name, "emoji": "", "color": "#999999"}


# ----------------------------------------------------------------------------
# PAGE SETUP
# ----------------------------------------------------------------------------

st.set_page_config(page_title="Quest for the Cortex", page_icon="🗺️", layout="centered")
st_autorefresh(interval=REFRESH_INTERVAL_MS, key="auto_refresh")

# --- Fantasy/parchment theming ---------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=EB+Garamond:ital@0;1&display=swap');

    .stApp {
        background: #F3E5C3;
        background-image:
            radial-gradient(circle at 20% 20%, rgba(139,109,58,0.06) 0%, transparent 40%),
            radial-gradient(circle at 80% 80%, rgba(139,109,58,0.06) 0%, transparent 40%);
    }

    h1, h2, h3, .quest-heading {
        font-family: 'Cinzel', serif !important;
        color: #4A3624 !important;
        text-shadow: 1px 1px 0px rgba(201,162,39,0.35);
    }

    p, .stMarkdown, .stCaption, div[data-testid="stCaptionContainer"] {
        font-family: 'EB Garamond', serif;
        color: #4A3624;
    }

    div[data-testid="stCaptionContainer"] {
        font-style: italic;
        font-size: 1.05rem;
    }

    .quest-card {
        background: rgba(255, 253, 245, 0.55);
        border: 1px solid rgba(139,109,58,0.35);
        border-radius: 10px;
        padding: 0.9rem 1rem;
        margin-bottom: 0.5rem;
    }

    .quest-divider {
        border: none;
        border-top: 2px solid #C9A227;
        margin: 1.2rem 0;
        opacity: 0.6;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title(PAGE_TITLE)
if PAGE_SUBTITLE:
    st.caption(PAGE_SUBTITLE)

# Manual refresh button (auto-refresh covers most cases, but nice to have)
if st.button("🔄 Refresh now"):
    st.cache_data.clear()


# ----------------------------------------------------------------------------
# DATA LOADING
# ----------------------------------------------------------------------------

def load_data(sheet_id: str, worksheet_name: str) -> pd.DataFrame:
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(sheet_id)
    worksheet = sheet.worksheet(worksheet_name)
    records = worksheet.get_all_records()  # list of dicts, keyed by header row
    df = pd.DataFrame(records)

    df[COL_TIMESTAMP] = pd.to_datetime(df[COL_TIMESTAMP], errors="coerce")
    df[COL_POINTS] = pd.to_numeric(df[COL_POINTS], errors="coerce")
    df = df.dropna(subset=[COL_TEAM, COL_POINTS])
    return df


import traceback

try:
    data = load_data(SHEET_ID, WORKSHEET_NAME)
except Exception as e:
    st.error(
        "Couldn't load the sheet. Check that:\n"
        "- SHEET_ID and WORKSHEET_NAME are correct\n"
        "- The sheet is shared with your service account's client_email (Viewer access)\n"
        "- st.secrets['gcp_service_account'] is set up correctly"
    )
    with st.expander("Technical details (for debugging)"):
        st.code(traceback.format_exc())
    st.stop()

if data.empty:
    st.info("No score entries yet. Once your Google Form gets responses, "
             "they'll show up here automatically.")
    st.stop()


# ----------------------------------------------------------------------------
# TOTALS + CHART
# ----------------------------------------------------------------------------

totals = data.groupby(COL_TEAM)[COL_POINTS].sum().reset_index()

if TEAM_ORDER:
    totals[COL_TEAM] = pd.Categorical(totals[COL_TEAM], categories=TEAM_ORDER, ordered=True)
    totals = totals.sort_values(COL_TEAM)
else:
    totals = totals.sort_values(COL_POINTS, ascending=False)

totals["Display Name"] = totals[COL_TEAM].apply(lambda t: display_for(t)["display_name"])
color_map = {display_for(t)["display_name"]: display_for(t)["color"] for t in totals[COL_TEAM]}

fig = px.bar(
    totals,
    x="Display Name",
    y=COL_POINTS,
    color="Display Name",
    color_discrete_map=color_map,
    text=COL_POINTS,
    labels={COL_POINTS: "Total Points", "Display Name": "Team"},
)
fig.update_traces(textposition="outside")
fig.update_layout(
    showlegend=False,
    yaxis_title="Quest Points",
    xaxis_title=None,
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(255,253,245,0.4)",
    font=dict(family="EB Garamond, serif", color="#4A3624", size=14),
    title_font=dict(family="Cinzel, serif"),
)
fig.update_xaxes(gridcolor="rgba(139,109,58,0.15)")
fig.update_yaxes(gridcolor="rgba(139,109,58,0.15)")

st.plotly_chart(fig, use_container_width=True)


# ----------------------------------------------------------------------------
# STANDINGS / RANKING
# ----------------------------------------------------------------------------

st.markdown("<h3 class='quest-heading'>🏅 Standings</h3>", unsafe_allow_html=True)

ranking = data.groupby(COL_TEAM)[COL_POINTS].sum().reset_index()
ranking = ranking.sort_values(COL_POINTS, ascending=False).reset_index(drop=True)

RANK_ICONS = ["👑", "🥈", "🥉"]  # 1st gets a crown instead of a medal

rank_cols = st.columns(len(ranking))
for i, col in enumerate(rank_cols):
    team = ranking.loc[i, COL_TEAM]
    points_val = ranking.loc[i, COL_POINTS]
    info = display_for(team)
    icon = RANK_ICONS[i] if i < len(RANK_ICONS) else f"#{i + 1}"

    with col:
        st.markdown(
            f"<div class='quest-card' style='text-align:center;'>"
            f"<div style='font-size:1.6rem;'>{icon}</div>"
            f"<div style='font-family:Cinzel, serif; font-weight:700; color:{info['color']};'>"
            f"{info['emoji']} {info['display_name']}</div>"
            f"<div style='font-size:0.9rem; color:#8B6D3A;'>{points_val:g} pts</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


# ----------------------------------------------------------------------------
# MOST RECENT ENTRY PER TEAM
# ----------------------------------------------------------------------------

st.markdown("<h3 class='quest-heading'>📜 Quest Log</h3>", unsafe_allow_html=True)

teams = TEAM_ORDER if TEAM_ORDER else totals[COL_TEAM].tolist()
cols = st.columns(len(teams))

for col, team in zip(cols, teams):
    team_rows = data[data[COL_TEAM] == team].sort_values(COL_TIMESTAMP, ascending=False)
    info = display_for(team)
    team_total = totals.loc[totals[COL_TEAM] == team, COL_POINTS]
    points_so_far = float(team_total.iloc[0]) if not team_total.empty else 0.0
    rank = rank_for(points_so_far)

    with col:
        latest = team_rows.iloc[0] if not team_rows.empty else None
        category = latest.get(COL_CATEGORY, "") if latest is not None else ""
        comment = latest.get(COL_COMMENT, "") if latest is not None else ""
        comment_html = (
            comment if pd.notna(comment) and str(comment).strip() else "<em>No comment</em>"
        )
        category_html = f"<em>{category}</em>" if category else ""
        body = (
            f"<div class='quest-card'>"
            f"<div style='font-family:Cinzel, serif; font-size:1.3rem; font-weight:700; color:{info['color']};'>"
            f"{info['emoji']} {info['display_name']}</div>"
            f"<div style='font-size:0.85rem; letter-spacing:0.03em; text-transform:uppercase; "
            f"color:#8B6D3A; margin-bottom:0.4rem;'>{rank}</div>"
        )
        if team_rows.empty:
            body += "<div>No entries yet</div></div>"
        else:
            body += f"{category_html}<div>{comment_html}</div></div>"
        st.markdown(body, unsafe_allow_html=True)

st.markdown("<hr class='quest-divider'>", unsafe_allow_html=True)
st.caption(
    f"Auto-refreshes every {REFRESH_INTERVAL_MS // 1000} seconds • "
    f"Last loaded: {pd.Timestamp.now().strftime('%I:%M:%S %p')}"
)