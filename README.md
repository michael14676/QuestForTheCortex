# Quest for the Cortex — Team Scoreboard Dashboard

A live-updating dashboard for tracking team points, built with [Streamlit](https://streamlit.io) and a Google Sheet as the data source. Team members submit points via a Google Form, and the dashboard reflects new entries automatically.

## What it does

- Reads score entries from a Google Sheet (populated by a Google Form)
- Shows a bar chart comparing total points across teams
- Shows a ranked standings list with a crown for the current leader
- Shows each team's most recent entry ("Quest Log") with category and comment
- Shows a rank/title per team based on their point total
- Auto-refreshes on a timer, plus a manual refresh button

## Files in this project

| File | Purpose |
|---|---|
| `app.py` | The whole dashboard — data loading, chart, standings, decoration/theming, everything |
| `requirements.txt` | Python packages needed to run the app |
| `.streamlit/secrets.toml` | Your private Google service account credentials (never share or commit this) |

---

## One-time setup

### 1. Create the Google Form + Sheet

1. Create a Google Form with fields matching: **Points Awarded**, **Team**, **category**, **Comments** (Google Forms adds a **Timestamp** column automatically to the linked Sheet).
2. Link the Form to a Google Sheet (Responses tab → the green Sheets icon).
3. Note the **Sheet ID** (the long string in the Sheet's URL between `/d/` and `/edit`) and the **exact tab name** the responses land on (e.g. `Sheet1` or `Form Responses 1`).

### 2. Enable the Google Sheets API (free)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a project (any name).
2. Go to **APIs & Services → Library**, search **Google Sheets API**, and click **Enable**.
   - This has a generous free quota — no billing account is required for this use case.

### 3. Create a service account (so the app can read the Sheet privately)

1. **APIs & Services → Credentials → Create Credentials → Service account**.
2. Give it any name, skip optional role assignment.
3. Open the new service account → **Keys → Add Key → Create new key → JSON**. This downloads a `.json` credentials file — keep it private.
4. Copy the `client_email` value out of that JSON (looks like `something@project-id.iam.gserviceaccount.com`).
5. In your Google Sheet, click **Share**, paste that email in, and give it **Viewer** access.

### 4. Set up `secrets.toml`

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

### 5. Update the config values in `app.py`

Near the top of `app.py`, set:

```python
SHEET_ID = "your-sheet-id-here"
WORKSHEET_NAME = "your-tab-name-here"

COL_TIMESTAMP = "Timestamp"
COL_POINTS = "Points Awarded"
COL_TEAM = "Team"
COL_CATEGORY = "category"
COL_COMMENT = "Comments"
```

The `COL_*` values must match your Sheet's column headers **exactly**, including capitalization.

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
2. Go to [share.streamlit.io](https://share.streamlit.io), connect your GitHub repo, and deploy.
3. In your deployed app's **Settings → Secrets**, paste the same contents that are in your local `secrets.toml`.

**Embedding in Google Sites:**

1. Get your deployed app's URL and add `?embed=true` to the end.
2. In Google Sites: **Insert → Embed → By URL**, paste that link in.
3. Test on a couple of different browsers/devices — embedding has occasionally had quirks on some mobile browsers.

---

## Customizing

Everything editable without touching the data logic lives in the **`🎨 DECORATION`** section near the top of `app.py`:

- `PAGE_TITLE` / `PAGE_SUBTITLE` — header text
- `TEAM_DISPLAY` — one entry per team: the key (left side) must match the Sheet's "Team" column exactly; `display_name`, `emoji`, and `color` underneath are freely editable
- `RANK_TITLES` — the point thresholds and titles teams unlock as they earn points; edit the numbers/text to rebalance

Colors are hex codes — pick one visually at [htmlcolorcodes.com](https://htmlcolorcodes.com). Emojis can be copied from [emojipedia.org](https://emojipedia.org).

The overall fantasy/parchment look (fonts, background, card styling) lives in the CSS block right after `st.set_page_config(...)` — safe to tweak colors there too if you want a different palette.

---

## Possible future additions

Ideas discussed but not yet built:
- A live link/button to the Google Form directly on the dashboard
- Crest-style icons per team instead of plain emoji
- A shared milestone/progress bar across all teams
- Google Form access restricted to your organization's domain accounts (native Google Forms setting, under Settings → Responses)
