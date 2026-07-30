"""
Quest for the Cortex — Team Scoreboard Dashboard
--------------------------------------------------
Main page: overall team standings (manual entries + quiz points combined).
Quiz Results page: breakdown of each individual quiz.

Everything lives in ONE Google Spreadsheet, across multiple tabs:
  - "Admin Responses"   — manual point entries (Timestamp, Points Awarded,
                            Team, category, Comments)
  - "Quiz Responses 1", "Quiz Responses 2", etc. — one tab per quiz, created
    automatically when each quiz's Google Form is linked to this same
    spreadsheet (Google auto-adds a "Score" column, formatted like "7/10",
    since these Forms are set up as quizzes)

SETUP REQUIRED (one-time):
  1. Create a Google Cloud project, enable the Google Sheets API.
  2. Create a service account, download its JSON key.
  3. Share this spreadsheet with the service account's client_email
     (Viewer access is enough) — once, since everything is one file.
  4. Put the service account JSON into .streamlit/secrets.toml locally
     (see the [gcp_service_account] section), or into Streamlit Cloud's
     "Secrets" settings when deployed. Never commit secrets.toml to a
     public repo.
"""

import re
import traceback

import streamlit as st
import pandas as pd
from streamlit_autorefresh import st_autorefresh
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials

# ============================================================================
# CONFIG — main scoreboard sheet
# ============================================================================

SHEET_ID = "1Cd4SsjJfF0Fq-WYJJz05XDnH0wkzzDWlufYKIhZi6cw"
WORKSHEET_NAME = "Admin Responses"

COL_TIMESTAMP = "Timestamp"
COL_POINTS = "Points Awarded"
COL_TEAM = "Team"
COL_CATEGORY = "category"
COL_COMMENT = "Comments"

TEAM_ORDER = None  # e.g. ["Team A", "Team B", "Team C"], or None to auto-detect
REFRESH_INTERVAL_MS = 45_000

# ============================================================================
# CONFIG — quizzes
# ============================================================================
# Quiz tabs are auto-discovered — any tab in this same spreadsheet named
# "Quiz Responses 1", "Quiz Responses 2", etc. is picked up automatically.
# You do NOT need to edit this file when you add a new quiz each week.
#
# EASY ON/OFF SWITCH: flip this to False any time to exclude quiz points from
# the main scoreboard totals entirely.
INCLUDE_QUIZ_POINTS_IN_MAIN_TOTAL = True

# Column headers expected on every quiz tab (must match exactly).
QUIZ_TEAM_COLUMN = "Team Name"
QUIZ_SCORE_COLUMN = "Score"    # auto-added by Google, formatted like "7/10"
QUIZ_NAME_COLUMN = "Your Name"  # used only to de-duplicate repeat submissions

# Global scoring mode — applies to every quiz, past and future, since there's
# nothing per-quiz to keep in sync. Change any time.
#
#   "participation"   Every respondent's team gets QUIZ_FLAT_POINTS,
#                     regardless of score.
#   "all_or_nothing"  A respondent's team gets QUIZ_FLAT_POINTS only for a
#                     perfect score; otherwise 0.
#   "weighted"        Points scale with how well they did, up to
#                     WEIGHTED_MAX_POINTS for a perfect score.
QUIZ_SCORING_MODE = "participation"

QUIZ_FLAT_POINTS = 1       # used by "participation" and "all_or_nothing" modes
WEIGHTED_MAX_POINTS = 5    # used by "weighted" mode

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
# included, AND must also match however the team is spelled in each quiz's
# team dropdown question. Everything indented under it (display_name,
# emoji, color) is pure decoration and safe to change freely.
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

# Number of people on each team — used as the denominator for quiz
# completion rate (e.g. "7/10 completed"). Placeholder values for now;
# update each once rosters are finalized.
TEAM_SIZE = {
    "Ryan and the Pryon Lyons": 10,
    "Basal Ganglia Baddies": 10,
    "Mad Cowz": 10,
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


# ============================================================================
# SHARED GOOGLE SHEETS PLUMBING
# ============================================================================

@st.cache_resource
def get_gspread_client():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    return gspread.authorize(creds)


def load_sheet_df(sheet_id: str, worksheet_name: str) -> pd.DataFrame:
    """Generic loader: any Sheet ID + tab name -> DataFrame of its rows."""
    client = get_gspread_client()
    sheet = client.open_by_key(sheet_id)
    worksheet = sheet.worksheet(worksheet_name)
    records = worksheet.get_all_records()
    return pd.DataFrame(records)


@st.cache_data(ttl=30)
def load_main_data(sheet_id: str, worksheet_name: str) -> pd.DataFrame:
    df = load_sheet_df(sheet_id, worksheet_name)
    df[COL_TIMESTAMP] = pd.to_datetime(df[COL_TIMESTAMP], errors="coerce")
    df[COL_POINTS] = pd.to_numeric(df[COL_POINTS], errors="coerce")
    df = df.dropna(subset=[COL_TEAM, COL_POINTS])
    return df


QUIZ_TAB_PATTERN = re.compile(r"^Quiz Responses (\d+)$")


@st.cache_data(ttl=30)
def discover_quiz_worksheets(sheet_id: str) -> list:
    """Find every tab matching 'Quiz Responses <number>', sorted in order."""
    client = get_gspread_client()
    sheet = client.open_by_key(sheet_id)
    found = []
    for ws in sheet.worksheets():
        m = QUIZ_TAB_PATTERN.match(ws.title)
        if m:
            found.append((int(m.group(1)), ws.title))
    found.sort(key=lambda pair: pair[0])
    return [title for _, title in found]


def quiz_display_name(tab_name: str) -> str:
    m = QUIZ_TAB_PATTERN.match(tab_name)
    return f"Quiz {m.group(1)}" if m else tab_name


@st.cache_data(ttl=30)
def load_quiz_team_points(worksheet_name: str) -> pd.DataFrame:
    """Load one quiz tab and compute points earned per team, using the
    global QUIZ_SCORING_MODE. De-duplicates repeat submissions from the
    same person, keeping only their highest-scoring attempt.

    Returns a DataFrame with columns: Team, Points.
    """
    df = load_sheet_df(SHEET_ID, worksheet_name)

    df = df.dropna(subset=[QUIZ_TEAM_COLUMN])
    df = df[df[QUIZ_TEAM_COLUMN].astype(str).str.strip() != ""]

    # Google's "Score" column looks like "7/10" — split into achieved/possible.
    parts = df[QUIZ_SCORE_COLUMN].astype(str).str.split("/", expand=True)
    df["_achieved"] = pd.to_numeric(parts[0], errors="coerce")
    df["_possible"] = pd.to_numeric(parts[1], errors="coerce") if parts.shape[1] > 1 else None
    df["_pct"] = df["_achieved"] / df["_possible"]

    # De-duplicate: if the same person submitted more than once, keep only
    # their highest-scoring attempt.
    if QUIZ_NAME_COLUMN in df.columns:
        df = df.sort_values("_pct", ascending=False)
        df = df.drop_duplicates(subset=[QUIZ_NAME_COLUMN], keep="first")

    if QUIZ_SCORING_MODE == "participation":
        df["_points"] = QUIZ_FLAT_POINTS

    elif QUIZ_SCORING_MODE == "all_or_nothing":
        is_perfect = df["_achieved"].notna() & df["_possible"].notna() & (df["_achieved"] == df["_possible"])
        df["_points"] = is_perfect.map({True: QUIZ_FLAT_POINTS, False: 0})

    elif QUIZ_SCORING_MODE == "weighted":
        df["_points"] = (df["_pct"].fillna(0) * WEIGHTED_MAX_POINTS).round(1)

    else:
        raise ValueError(f"Unknown QUIZ_SCORING_MODE: {QUIZ_SCORING_MODE!r}")

    grouped = df.groupby(QUIZ_TEAM_COLUMN)["_points"].sum().reset_index()
    grouped.columns = [COL_TEAM, COL_POINTS]
    return grouped


def get_all_quiz_points():
    """Combine points across every discovered quiz tab.

    Returns (team_totals_dict, list_of_(quiz_display_name, per_team_df_or_None, error_or_None)).
    """
    team_totals = {}
    per_quiz_results = []

    try:
        quiz_tabs = discover_quiz_worksheets(SHEET_ID)
    except Exception as e:
        return team_totals, [("Quiz discovery", None, str(e))]

    for tab_name in quiz_tabs:
        display_name = quiz_display_name(tab_name)
        try:
            quiz_points = load_quiz_team_points(tab_name)
            for _, row in quiz_points.iterrows():
                team_totals[row[COL_TEAM]] = team_totals.get(row[COL_TEAM], 0) + row[COL_POINTS]
            per_quiz_results.append((display_name, quiz_points, None))
        except Exception as e:
            per_quiz_results.append((display_name, None, str(e)))

    return team_totals, per_quiz_results


@st.cache_data(ttl=30)
def load_quiz_completion_counts(worksheet_name: str) -> pd.DataFrame:
    """Load one quiz tab and count unique completions per team, de-duplicating
    repeat submissions from the same person.

    Returns a DataFrame with columns: Team, Completed.
    """
    df = load_sheet_df(SHEET_ID, worksheet_name)
    df = df.dropna(subset=[QUIZ_TEAM_COLUMN])
    df = df[df[QUIZ_TEAM_COLUMN].astype(str).str.strip() != ""]

    if QUIZ_NAME_COLUMN in df.columns:
        df = df.drop_duplicates(subset=[QUIZ_NAME_COLUMN], keep="first")

    counts = df.groupby(QUIZ_TEAM_COLUMN).size().reset_index(name="Completed")
    counts.columns = [COL_TEAM, "Completed"]
    return counts


def get_latest_quiz_completion():
    """Return (quiz_display_name, completion_df) for the most recently
    created quiz tab, or (None, None) if no quiz tabs exist yet."""
    try:
        quiz_tabs = discover_quiz_worksheets(SHEET_ID)
    except Exception:
        return None, None
    if not quiz_tabs:
        return None, None

    latest_tab = quiz_tabs[-1]
    try:
        completion_df = load_quiz_completion_counts(latest_tab)
    except Exception:
        return quiz_display_name(latest_tab), None
    return quiz_display_name(latest_tab), completion_df


# ============================================================================
# SHARED THEMING (applies to every page)
# ============================================================================

def apply_theme():
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


# ============================================================================
# MAIN SCOREBOARD PAGE
# ============================================================================

def page_main():
    st_autorefresh(interval=REFRESH_INTERVAL_MS, key="auto_refresh")
    apply_theme()

    st.title(PAGE_TITLE)
    if PAGE_SUBTITLE:
        st.caption(PAGE_SUBTITLE)

    if st.button("🔄 Refresh now"):
        st.cache_data.clear()

    try:
        data = load_main_data(SHEET_ID, WORKSHEET_NAME)
    except Exception:
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

    # --- Combine manual points with quiz points (if enabled) ---------------
    totals = data.groupby(COL_TEAM)[COL_POINTS].sum().reset_index()

    if INCLUDE_QUIZ_POINTS_IN_MAIN_TOTAL:
        quiz_totals, _ = get_all_quiz_points()
        if quiz_totals:
            totals = totals.set_index(COL_TEAM)
            for team, pts in quiz_totals.items():
                if team in totals.index:
                    totals.loc[team, COL_POINTS] += pts
                else:
                    totals.loc[team, COL_POINTS] = pts
            totals = totals.reset_index()

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

    # --- Standings -----------------------------------------------------------
    st.markdown("<h3 class='quest-heading'>🏅 Standings</h3>", unsafe_allow_html=True)

    ranking = totals[[COL_TEAM, COL_POINTS]].sort_values(COL_POINTS, ascending=False).reset_index(drop=True)
    RANK_ICONS = ["👑", "🥈", "🥉"]

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

    # --- Quest Log (manual entries only — quizzes don't have comments) ------
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

    # --- Quiz Completion (most recent quiz only) -----------------------------
    st.markdown("<h3 class='quest-heading'>📋 Quiz Completion</h3>", unsafe_allow_html=True)

    quiz_name, completion_df = get_latest_quiz_completion()

    if quiz_name is None:
        st.caption("No quizzes yet.")
    else:
        st.caption(f"Most recent: {quiz_name}")

        completion_map = {}
        if completion_df is not None:
            completion_map = dict(zip(completion_df[COL_TEAM], completion_df["Completed"]))

        completion_teams = TEAM_ORDER if TEAM_ORDER else list(TEAM_DISPLAY.keys())
        comp_cols = st.columns(len(completion_teams))

        for col, team_raw in zip(comp_cols, completion_teams):
            info = display_for(team_raw)
            completed = completion_map.get(team_raw, 0)
            size = TEAM_SIZE.get(team_raw, 10)
            with col:
                st.markdown(
                    f"<div class='quest-card' style='text-align:center;'>"
                    f"<div style='font-family:Cinzel, serif; font-weight:700; color:{info['color']};'>"
                    f"{info['emoji']} {info['display_name']}</div>"
                    f"<div style='font-size:0.95rem; color:#8B6D3A;'>{completed}/{size} completed</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    st.markdown("<hr class='quest-divider'>", unsafe_allow_html=True)
    note = "Quiz points are included in totals above." if INCLUDE_QUIZ_POINTS_IN_MAIN_TOTAL else ""
    st.caption(
        f"Auto-refreshes every {REFRESH_INTERVAL_MS // 1000} seconds • "
        f"Last loaded: {pd.Timestamp.now().strftime('%I:%M:%S %p')}"
        + (f" • {note}" if note else "")
    )


# ============================================================================
# ENTRYPOINT
# ============================================================================

st.set_page_config(page_title="Quest for the Cortex", page_icon="🗺️", layout="centered")
page_main()