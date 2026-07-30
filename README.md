# Quest for the Cortex — Team Scoreboard Dashboard

A live-updating dashboard for tracking team points across a neurology residency's "Quest for the Cortex" challenge, built with [Streamlit](https://streamlit.io) and a single Google Spreadsheet as the data source. Admins log points directly, quizzes feed in automatically, and the dashboard reflects new entries live.

## What it does

- Bar chart comparing total points across teams (manual points + quiz points combined)
- Ranked standings with a crown for the current leader
- "Quest Log" showing each team's most recent manually-logged entry (category + comment)
- A rank/title per team based on their point total
- "Quiz Completion" showing how many people on each team have completed the most recent quiz (e.g. `7/10 completed`)
- Auto-refreshes on a timer, plus a manual refresh button

## How the data is structured

Everything lives in **one Google Spreadsheet**, across multiple tabs:

| Tab name | Purpose |
|---|---|
| `Admin Responses` | Manually-logged points: Timestamp, Points Awarded, Team, category, Comments |
| `Quiz Responses 1`, `Quiz Responses 2`, ... | One tab per quiz, auto-created when each quiz's Google Form (set up as a quiz, linked to this same spreadsheet) collects responses |

**Quiz tabs are auto-discovered.** The app looks for any tab named exactly `Quiz Responses <number>` and automatically includes it — you do **not** need to edit `app.py` or make a commit every time you add a new quiz. Just create the quiz, name its tab correctly, and it shows up.

Each quiz tab is expected to have these columns (exact spelling matters):
- `Timestamp` (added automatically by Google Forms)
- `Team Name` — a dropdown question you add to the quiz Form
- `Score` — added automatically by Google whenever the linked Form is set up as a quiz (formatted like `7/10`)
- `Your Name` — used to detect and de-duplicate repeat submissions (keeps their highest-scoring attempt for points, and counts them only once for completion rate) and to count unique completions
- Any number of other question columns — these are ignored by the dashboard entirely

## Quiz scoring

One global scoring mode applies to every quiz (set in `app.py`). Currently set to:

- **`participation`** — every respondent's team earns `QUIZ_FLAT_POINTS` (currently **1 point**) just for completing the quiz, regardless of score

Two other modes are built in and can be switched to any time by changing `QUIZ_SCORING_MODE`:
- **`all_or_nothing`** — a team earns `QUIZ_FLAT_POINTS` only if that person got a perfect score; otherwise 0
- **`weighted`** — points scale with how well they did, up to `WEIGHTED_MAX_POINTS` for a perfect score

Change the mode or point values any time near the top of `app.py` — it applies retroactively to every quiz automatically, since there's nothing to keep in sync per-quiz.

Whether quiz points count toward the main scoreboard totals at all is a single on/off switch: `INCLUDE_QUIZ_POINTS_IN_MAIN_TOTAL`.

## Quiz completion tracking

The **Quiz Completion** section shows, for the **most recently created quiz tab only**, how many unique people per team have completed it — e.g. `7/10 completed`.

- The denominator (team size) comes from `TEAM_SIZE` near the top of `app.py` — currently a placeholder of `10` for every team. Update each team's number individually once rosters are finalized.
- "Most recent" is determined by the highest number in the `Quiz Responses <n>` tab name, not by timestamp — so tabs should be numbered in the order quizzes are created.
- A team with zero completions on the latest quiz still shows correctly (e.g. `0/10`) rather than disappearing.

## Files in this project

| File | Purpose |
|---|---|
| `app.py` | The whole dashboard — config, data loading, scoring logic, decoration/theming |
| `requirements.txt` | Python packages needed to run the app |
| `.streamlit/secrets.toml` | Your private Google service account credentials (never share or commit this) |

---

## One-time setup

### 1. Create the spreadsheet + Admin Responses form

1. Create a Google Form for admin point entries with fields matching: **Points Awarded**, **Team**, **category**, **Comments**.
2. Link it to a Google Sheet, and rename the responses tab to **`Admin Responses`**.
3. Note the **Sheet ID** (the long string in the Sheet's URL between `/d/` and `/edit`).

### 2. Set up each quiz (repeat this every time you add one)

1. Create the quiz as a Google Form, in **quiz mode**, and include a **"Team Name"** dropdown question matching your team names exactly.
2. Under the Form's response destination, choose **"Select existing spreadsheet"** and pick the same spreadsheet from step 1 — this creates a new tab in it (rather than a whole new file).
3. Rename that new tab to **`Quiz Responses <n>`** — `Quiz Responses 1` for the first quiz, `Quiz Responses 2` for the next, and so on.
4. That's it — no code changes needed. The dashboard will pick it up automatically on its next refresh, including in the Quiz Completion section.

### 3. Enable the Google Sheets API (free)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a project (any name).
2. Go to **APIs & Services → Library**, search **Google Sheets API**, and click **Enable**.
   - This has a generous free quota — no billing account is required for this use case.

### 4. Create a service account (so the app can read the spreadsheet privately)

1. **APIs & Services → Credentials → Create Credentials → Service account**.
2. Give it any name, skip optional role assignment.
3. Open the new service account → **Keys → Add Key → Create new key → JSON**. This downloads a `.json` credentials file — keep it private.
4. Copy the `client_email` value out of that JSON (looks like `something@project-id.iam.gserviceaccount.com`).
5. In your spreadsheet, click **Share**, paste that email in, and give it **Viewer** access.
   - You only need to do this **once** for the whole spreadsheet — since all quiz tabs live in the same file, new quiz tabs are automatically covered by this same share.

### 5. Set up `secrets.toml`

Create a folder named `.streamlit` next to `app.py`, and inside it a file named `secrets.toml`. Fill it in using your downloaded JSON's values, converting JSON syntax to TOML syntax:

```toml
[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@your-project-id.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
universe_domain = "googleapis.com"
```

### 6. Update the config values in `app.py`

Near the top of `app.py`, set:

```python
SHEET_ID = "your-sheet-id-here"
WORKSHEET_NAME = "Admin Responses"

COL_TIMESTAMP = "Timestamp"
COL_POINTS = "Points Awarded"
COL_TEAM = "Team"
COL_CATEGORY = "category"
COL_COMMENT = "Comments"
```

These must match your Admin Responses tab's column headers **exactly**, including capitalization.

---

## Running it locally

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the app:

```bash
python -m streamlit run app.py
```

---

## Deploying so others can access it

**Streamlit Community Cloud (free):**

1. Push this project to a GitHub repo (keep `secrets.toml` out of it — see `.gitignore` note above).
2. Go to [share.streamlit.io](https://share.streamlit.io), connect your GitHub repo, and deploy, setting the main file to `app.py`.
3. Under **Advanced settings** during deploy (or **Settings → Secrets** afterward), paste the same contents that are in your local `secrets.toml`.

**Embedding in Google Sites:**

1. Get your deployed app's URL and add `?embed=true` to the end.
2. In Google Sites: **Insert → Embed → By URL**, paste that link in.
3. Test on a couple of different browsers/devices — embedding has occasionally had quirks on some mobile browsers.

---

## Customizing

Everything editable without touching the data logic lives in the **`🎨 DECORATION`** section near the top of `app.py`:

- `PAGE_TITLE` / `PAGE_SUBTITLE` — header text
- `TEAM_DISPLAY` — one entry per team: the key (left side) must match the Admin Responses "Team" column AND every quiz's "Team Name" column exactly; `display_name`, `emoji`, and `color` underneath are freely editable
- `TEAM_SIZE` — roster size per team, used as the denominator in Quiz Completion
- `RANK_TITLES` — the point thresholds and titles teams unlock as they earn points; edit the numbers/text to rebalance

Colors are hex codes — pick one visually at [htmlcolorcodes.com](https://htmlcolorcodes.com). Emojis can be copied from [emojipedia.org](https://emojipedia.org).

The overall fantasy/parchment look (fonts, background, card styling) lives in the `apply_theme()` function — safe to tweak colors there too if you want a different palette.

---

## Cost

Everything here is free:
- Google Forms/Sheets: free
- Google Sheets API: free tier, no billing account needed for this scale of usage
- Streamlit Community Cloud: free tier is sufficient for an internal tool with under 50 users

---

## Possible future additions

Ideas discussed but not yet built:
- A live link/button to the Google Forms directly on the dashboard
- Crest-style icons per team instead of plain emoji
- A shared milestone/progress bar across all teams
- Google Form access restricted to your organization's domain accounts (native Google Forms setting, under Settings → Responses)
- Per-quiz (rather than global) scoring mode, if you later want different quizzes scored differently