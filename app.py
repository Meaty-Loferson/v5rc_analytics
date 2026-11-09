import streamlit as st
import pandas as pd
import numpy as np
import os
import requests
from datetime import datetime

st.set_page_config(page_title="V5RC Tournament Intelligence & Community Hub", layout="wide")

# Directory paths for persistent storage
DATA_DIR = "data"
TOURNAMENTS_DIR = os.path.join(DATA_DIR, "tournaments")
BALLOTS_DIR = os.path.join(DATA_DIR, "ballots")
BALLOTS_FILE = os.path.join(BALLOTS_DIR, "ballots.csv")

os.makedirs(TOURNAMENTS_DIR, exist_ok=True)
os.makedirs(BALLOTS_DIR, exist_ok=True)

# ==========================================
# REST API CLIENT (VEX / 3145H AXUM SPEC)
# ==========================================
class VexApiClient:
    def __init__(self):
        # Locked in background; never exposed to user UI
        self.base_url = st.secrets.get("VEX_API_BASE_URL", "https://api.3145h.org/v1").rstrip("/")
        self.api_key = st.secrets.get("VEX_API_KEY", "")
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def _get(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            res = self.session.get(url, params=params or {}, timeout=15)
            res.raise_for_status()
            return res.json()
        except requests.exceptions.ConnectionError:
            raise ConnectionError(f"Could not connect to API server at '{self.base_url}'.")
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"API returned HTTP {res.status_code}")

    def resolve_event(self, event_query: str) -> tuple[str, str]:
        """
        Resolves an Event SKU or numeric ID to (event_identifier, event_name).
        Guarantees that a random first event is never returned by mistake.
        """
        query = str(event_query).strip()
        query_upper = query.upper()

        # 1. Try direct lookup via /events/{id_or_sku}
        try:
            res = self._get(f"/events/{query}")
            data = res.get("data", res) if isinstance(res, dict) else res
            if isinstance(data, dict) and ("id" in data or "sku" in data):
                name = data.get("name", f"Event {query}")
                target_id = str(data.get("id", query))
                return target_id, name
        except Exception:
            pass

        # 2. Search /events collection with strict SKU/code matching
        for param_key in ["sku", "sku[]", "code", "search"]:
            try:
                res = self._get("/events", params={param_key: query})
                items = res.get("data", res) if isinstance(res, dict) else res
                if isinstance(items, list):
                    for ev in items:
                        if isinstance(ev, dict):
                            ev_sku = str(ev.get("sku", "")).strip().upper()
                            ev_code = str(ev.get("code", "")).strip().upper()
                            if query_upper in [ev_sku, ev_code]:
                                return str(ev.get("id", query)), ev.get("name", query)
            except Exception:
                continue

        # 3. Numeric ID direct pass
        if query.isdigit():
            return query, f"Event #{query}"

        # 4. Fallback: pass input directly to sub-endpoints
        return query, query

    def get_event_teams(self, event_id: str | int) -> pd.DataFrame:
        all_teams = []
        page = 1
        while True:
            payload = self._get(f"/events/{event_id}/teams", params={"page": page, "per_page": 100})
            data = payload.get("data", payload) if isinstance(payload, dict) else payload
            if not isinstance(data, list) or not data:
                break
            for t in data:
                all_teams.append({
                    "Team": t.get("number", ""),
                    "Name": t.get("team_name", t.get("name", "")),
                    "Organization": t.get("organization", ""),
                    "City": t.get("location", {}).get("city", "") if isinstance(t.get("location"), dict) else ""
                })
            pagination = payload.get("pagination", {}) if isinstance(payload, dict) else {}
            if page >= pagination.get("total_pages", 1):
                break
            page += 1
        return pd.DataFrame(all_teams)

    def get_event_matches(self, event_id: str | int) -> pd.DataFrame:
        # Pre-fetch registered teams to map internal numeric team IDs (e.g. 78936 -> "11124R")
        id_to_num = {}
        try:
            df_teams_ref = self.get_event_teams(event_id)
            if not df_teams_ref.empty:
                raw_t = self._get(f"/events/{event_id}/teams", params={"per_page": 100})
                t_list = raw_t.get("data", raw_t) if isinstance(raw_t, dict) else raw_t
                if isinstance(t_list, list):
                    for item in t_list:
                        if isinstance(item, dict):
                            t_id = str(item.get("id", ""))
                            t_num = str(item.get("number", item.get("team_name", ""))).strip()
                            if t_id and t_num:
                                id_to_num[t_id] = t_num
        except Exception:
            pass

        def resolve_num(val):
            if val is None:
                return ""
            if isinstance(val, dict):
                inner = val.get("team", val)
                if isinstance(inner, dict):
                    v = inner.get("number") or inner.get("name") or inner.get("id") or ""
                    return id_to_num.get(str(v).strip(), str(v).strip())
                return id_to_num.get(str(inner).strip(), str(inner).strip())
            s = str(val).strip()
            return id_to_num.get(s, s)

        all_matches = []
        page = 1

        while True:
            payload = self._get(f"/events/{event_id}/matches", params={"page": page, "per_page": 100})
            data = payload.get("data", payload) if isinstance(payload, dict) else payload
            if not isinstance(data, list) or not data:
                break

            for m in data:
                if not isinstance(m, dict):
                    continue

                m_name = str(m.get("name") or f"Qualifier #{m.get('matchnum', '')}").strip()
                m_lower = m_name.lower()

                # Filter out elimination bracket matches
                if any(x in m_lower for x in ["round of 16", "quarterfinal", "semifinal", "final", "qf", "sf", "f#"]):
                    continue

                r1, r2, b1, b2 = "", "", "", ""
                r_sc, b_sc = 0.0, 0.0

                # Format A: Nested RobotEvents / Axum alliances
                if "alliances" in m and isinstance(m["alliances"], list):
                    red = next((a for a in m["alliances"] if isinstance(a, dict) and str(a.get("color", "")).lower() == "red"), {})
                    blue = next((a for a in m["alliances"] if isinstance(a, dict) and str(a.get("color", "")).lower() == "blue"), {})

                    r_teams = [resolve_num(t) for t in red.get("teams", []) if resolve_num(t)]
                    b_teams = [resolve_num(t) for t in blue.get("teams", []) if resolve_num(t)]

                    if len(r_teams) >= 2:
                        r1, r2 = r_teams[0], r_teams[1]
                    elif len(r_teams) == 1:
                        r1, r2 = r_teams[0], r_teams[0]

                    if len(b_teams) >= 2:
                        b1, b2 = b_teams[0], b_teams[1]
                    elif len(b_teams) == 1:
                        b1, b2 = b_teams[0], b_teams[0]

                    r_sc = float(red.get("score") or red.get("points") or 0.0)
                    b_sc = float(blue.get("score") or blue.get("points") or 0.0)

                # Format B: Flat keys (e.g. red_1, red_2, blue_1, blue_2 or red1, red2)
                else:
                    r1 = resolve_num(m.get("red_1") or m.get("red1") or m.get("red_team_1"))
                    r2 = resolve_num(m.get("red_2") or m.get("red2") or m.get("red_team_2"))
                    b1 = resolve_num(m.get("blue_1") or m.get("blue1") or m.get("blue_team_1"))
                    b2 = resolve_num(m.get("blue_2") or m.get("blue2") or m.get("blue_team_2"))
                    r_sc = float(m.get("red_score") or m.get("redscore") or m.get("red_points") or 0.0)
                    b_sc = float(m.get("blue_score") or m.get("bluescore") or m.get("blue_points") or 0.0)

                if r1 and b1:
                    if not r2: r2 = r1
                    if not b2: b2 = b1
                    winner = "Red" if r_sc > b_sc else ("Blue" if b_sc > r_sc else "Tie")
                    all_matches.append({
                        "Match": m_name,
                        "Red Team 1": r1,
                        "Red Team 2": r2,
                        "Blue Team 1": b1,
                        "Blue Team 2": b2,
                        "Red Score": r_sc,
                        "Blue Score": b_sc,
                        "Winner": winner
                    })

            pagination = payload.get("pagination", {}) if isinstance(payload, dict) else {}
            if page >= pagination.get("total_pages", 1):
                break
            page += 1

        return pd.DataFrame(all_matches)

    def get_event_rankings(self, event_id: str | int) -> pd.DataFrame:
        payload = self._get(f"/events/{event_id}/rankings")
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        rows = []
        if isinstance(data, list):
            for r in data:
                team_info = r.get("team", {})
                t_num = team_info.get("number", team_info.get("name", r.get("team_number", ""))) if isinstance(team_info, dict) else str(team_info)
                rows.append({
                    "Actual_Rank": r.get("rank"),
                    "Team": str(t_num).strip(),
                    "WP": r.get("wp", 0),
                    "AP": r.get("ap", 0),
                    "SP": r.get("sp", 0),
                    "Wins": r.get("wins", 0),
                    "Losses": r.get("losses", 0),
                    "Ties": r.get("ties", 0)
                })
        return pd.DataFrame(rows)

api_client = VexApiClient()

# ==========================================
# SIDEBAR: NAVIGATION
# ==========================================
app_mode = st.sidebar.radio(
    "Navigation:",
    [
        "📊 TM Event Analyzer & Archive", 
        "🗳️ Top 25 Poll & Community Rankings", 
        "🔮 Future Tournament Sandbox"
    ]
)

# ==========================================
# FILE PARSER & CORE ANALYTICAL ENGINE
# ==========================================
def parse_file(file):
    if hasattr(file, "name"):
        fname = file.name.lower()
    else:
        fname = str(file).lower()

    if fname.endswith(".csv"):
        return pd.read_csv(file)
    if fname.endswith(".xlsx"):
        return pd.read_excel(file, engine="openpyxl")
    try:
        return pd.read_excel(file, engine="calamine")
    except Exception:
        try:
            return pd.read_excel(file, engine="xlrd")
        except Exception:
            return pd.read_excel(file)

def parse_manual_overrides(text):
    overrides = {}
    if not text.strip():
        return overrides
    for line in text.strip().split("\n"):
        parts = line.split(":")
        if len(parts) >= 2:
            action = parts[0].strip().lower()
            details = parts[1].strip()
            if action == "tie":
                overrides[details.lower()] = {"winner": "Tie"}
            elif action in ["winner", "dq"]:
                sub = details.split(",")
                if len(sub) == 2:
                    m_key = sub[0].strip().lower()
                    win_val = sub[1].strip().capitalize()
                    if action == "dq":
                        win_val = "Blue" if "red" in win_val.lower() else "Red"
                    overrides[m_key] = {"winner": win_val}
    return overrides

def analyze_tournament(df_matches, df_rankings_file=None, overrides_text=""):
    df_matches.columns = [str(c).strip() for c in df_matches.columns]
    match_col = next((c for c in df_matches.columns if "match" in c.lower()), None)
    r1_col = next((c for c in df_matches.columns if "red" in c.lower() and "1" in c.lower()), None)
    r2_col = next((c for c in df_matches.columns if "red" in c.lower() and "2" in c.lower()), None)
    b1_col = next((c for c in df_matches.columns if "blue" in c.lower() and "1" in c.lower()), None)
    b2_col = next((c for c in df_matches.columns if "blue" in c.lower() and "2" in c.lower()), None)
    r_score_col = next((c for c in df_matches.columns if "red" in c.lower() and "score" in c.lower()), None)
    b_score_col = next((c for c in df_matches.columns if "blue" in c.lower() and "score" in c.lower()), None)
    winner_col = next((c for c in df_matches.columns if "winner" in c.lower()), None)

    if not all([match_col, r1_col, r2_col, b1_col, b2_col, r_score_col, b_score_col]):
        st.error(f"Could not map match columns. Detected headers: {list(df_matches.columns)}")
        return None, None

    qual_df = df_matches[df_matches[match_col].astype(str).str.lower().str.contains("qual|q", regex=True)].copy()
    if qual_df.empty:
        qual_df = df_matches.copy()

    qual_df[r_score_col] = pd.to_numeric(qual_df[r_score_col], errors="coerce").fillna(0.0)
    qual_df[b_score_col] = pd.to_numeric(qual_df[b_score_col], errors="coerce").fillna(0.0)
    overrides = parse_manual_overrides(overrides_text)

    raw_teams = set()
    for col in [r1_col, r2_col, b1_col, b2_col]:
        raw_teams.update(qual_df[col].dropna().astype(str).str.strip().unique())
    all_teams = sorted([t for t in raw_teams if t and t.lower() != "nan" and not t.isdigit()])

    df_ranks = None
    if df_rankings_file is not None and not df_rankings_file.empty:
        df_rankings_file.columns = [str(c).strip() for c in df_rankings_file.columns]
        team_rk_col = next((c for c in df_rankings_file.columns if "team" in c.lower()), None)
        rk_col = next((c for c in df_rankings_file.columns if "rank" in c.lower()), None)
        wp_col = next((c for c in df_rankings_file.columns if "wp" in c.lower()), None)
        sp_col = next((c for c in df_rankings_file.columns if "sp" in c.lower()), None)
        if team_rk_col and rk_col:
            df_ranks = df_rankings_file.copy()
            df_ranks["Team"] = df_ranks[team_rk_col].astype(str).str.strip()
            df_ranks["Actual_Rank"] = pd.to_numeric(df_ranks[rk_col], errors="coerce").fillna(99).astype(int)
            if wp_col: df_ranks["WP"] = pd.to_numeric(df_ranks[wp_col], errors="coerce").fillna(0).astype(int)
            if sp_col: df_ranks["SP"] = pd.to_numeric(df_ranks[sp_col], errors="coerce").fillna(0).astype(int)

    if df_ranks is None:
        stats = {t: {"Wins": 0, "Losses": 0, "Ties": 0, "WP": 0, "SP": 0} for t in all_teams}
        for _, row in qual_df.iterrows():
            m_label = str(row[match_col]).strip().lower()
            r_teams = [str(row[r1_col]).strip(), str(row[r2_col]).strip()]
            b_teams = [str(row[b1_col]).strip(), str(row[b2_col]).strip()]
            r_sc = float(row[r_score_col])
            b_sc = float(row[b_score_col])
            w = str(row[winner_col]).strip() if winner_col else ""

            if m_label in overrides:
                w = overrides[m_label]["winner"]
            elif w not in ["Red", "Blue", "Tie"]:
                w = "Red" if r_sc > b_sc else ("Blue" if b_sc > r_sc else "Tie")

            losing_score = int(min(r_sc, b_sc))
            if w == "Red":
                for t in r_teams:
                    if t in stats: stats[t]["Wins"] += 1; stats[t]["WP"] += 2; stats[t]["SP"] += losing_score
                for t in b_teams:
                    if t in stats: stats[t]["Losses"] += 1; stats[t]["SP"] += losing_score
            elif w == "Blue":
                for t in b_teams:
                    if t in stats: stats[t]["Wins"] += 1; stats[t]["WP"] += 2; stats[t]["SP"] += losing_score
                for t in r_teams:
                    if t in stats: stats[t]["Losses"] += 1; stats[t]["SP"] += losing_score
            else:
                for t in r_teams + b_teams:
                    if t in stats: stats[t]["Ties"] += 1; stats[t]["WP"] += 1; stats[t]["SP"] += losing_score

        df_ranks = pd.DataFrame([{"Team": t, **s} for t, s in stats.items()])
        df_ranks = df_ranks.sort_values(by=["WP", "SP"], ascending=[False, False]).reset_index(drop=True)
        df_ranks["Actual_Rank"] = df_ranks.index + 1

    rank_map = {row["Team"]: row["Actual_Rank"] for _, row in df_ranks.iterrows()}
    carry_sums = {t: 0.0 for t in all_teams}
    teammates = {t: [] for t in all_teams}
    opponents = {t: [] for t in all_teams}
    audit_rows = []

    for _, row in qual_df.iterrows():
        m_label = str(row[match_col]).strip()
        r1, r2 = str(row[r1_col]).strip(), str(row[r2_col]).strip()
        b1, b2 = str(row[b1_col]).strip(), str(row[b2_col]).strip()
        r_sc = float(row[r_score_col])
        b_sc = float(row[b_score_col])
        w = str(row[winner_col]).strip() if winner_col else ""

        if m_label.lower() in overrides:
            w = overrides[m_label.lower()]["winner"]
        elif w not in ["Red", "Blue", "Tie"]:
            w = "Red" if r_sc > b_sc else ("Blue" if b_sc > r_sc else "Tie")

        # Red Alliance Calculations
        if r1 in rank_map and r2 in rank_map and b1 in rank_map and b2 in rank_map:
            for t, p in [(r1, r2), (r2, r1)]:
                teammates[t].append(rank_map[p])
                opponents[t].extend([rank_map[b1], rank_map[b2]])
                delta_r = ((rank_map[t] + rank_map[p]) / 2.0) - ((rank_map[b1] + rank_map[b2]) / 2.0)
                base = (rank_map[p] - rank_map[t]) + 2.0 * max(0.0, delta_r)
                if w == "Red":
                    carry = base * 1.0
                elif w == "Tie":
                    carry = base * 0.5
                else:
                    w_m = -0.25 * max(0.0, 1.0 - (r_sc / max(b_sc, 1.0)))
                    carry = -abs(base) * abs(w_m) if base > 0 else base * (1.0 - abs(w_m))
                carry_sums[t] += carry
                audit_rows.append({"Match": m_label, "Team": t, "Alliance": "Red", "Partner": p, "Opponents": f"{b1}, {b2}", "Score": f"{int(r_sc)}-{int(b_sc)}", "Result": "Win" if w=="Red" else ("Tie" if w=="Tie" else "Loss"), "Leverage": round(carry, 2)})

        # Blue Alliance Calculations
        if b1 in rank_map and b2 in rank_map and r1 in rank_map and r2 in rank_map:
            for t, p in [(b1, b2), (b2, b1)]:
                teammates[t].append(rank_map[p])
                opponents[t].extend([rank_map[r1], rank_map[r2]])
                delta_r = ((rank_map[t] + rank_map[p]) / 2.0) - ((rank_map[r1] + rank_map[r2]) / 2.0)
                base = (rank_map[p] - rank_map[t]) + 2.0 * max(0.0, delta_r)
                if w == "Blue":
                    carry = base * 1.0
                elif w == "Tie":
                    carry = base * 0.5
                else:
                    w_m = -0.25 * max(0.0, 1.0 - (b_sc / max(r_sc, 1.0)))
                    carry = -abs(base) * abs(w_m) if base > 0 else base * (1.0 - abs(w_m))
                carry_sums[t] += carry
                audit_rows.append({"Match": m_label, "Team": t, "Alliance": "Blue", "Partner": p, "Opponents": f"{r1}, {r2}", "Score": f"{int(b_sc)}-{int(r_sc)}", "Result": "Win" if w=="Blue" else ("Tie" if w=="Tie" else "Loss"), "Leverage": round(carry, 2)})

    num_teams = len(all_teams)
    median_rank = (num_teams + 1) / 2.0
    c_vals = list(carry_sums.values())
    mu = np.mean(c_vals) if c_vals else 0.0
    sigma = np.std(c_vals, ddof=1) if len(c_vals) > 1 and np.std(c_vals, ddof=1) > 0 else 1.0

    df_ranks["Avg_Teammate_Rank"] = df_ranks["Team"].map(lambda t: round(np.mean(teammates[t]), 2) if t in teammates and teammates[t] else median_rank)
    df_ranks["Avg_Opponent_Rank"] = df_ranks["Team"].map(lambda t: round(np.mean(opponents[t]), 2) if t in opponents and opponents[t] else median_rank)
    df_ranks["Schedule_Advantage"] = np.round(df_ranks["Avg_Opponent_Rank"] - df_ranks["Avg_Teammate_Rank"], 2)
    df_ranks["SOS_Rank"] = df_ranks["Schedule_Advantage"].rank(ascending=True, method="min").astype(int)
    df_ranks["Carry_Factor"] = df_ranks["Team"].map(lambda t: round(50.0 + 50.0 * ((carry_sums.get(t, 0.0) - mu) / (3.0 * sigma)), 1))

    intercept = median_rank + (0.6282 * 50.0)
    std_adv = df_ranks["Schedule_Advantage"].std()
    z_sched = (df_ranks["Schedule_Advantage"] - df_ranks["Schedule_Advantage"].mean()) / (std_adv if std_adv and std_adv > 0 else 1.0)
    exp_rank = -0.6282 * df_ranks["Carry_Factor"] + intercept
    surplus = exp_rank - df_ranks["Actual_Rank"]
    std_surp = surplus.std()
    z_surp = (surplus - surplus.mean()) / (std_surp if std_surp and std_surp > 0 else 1.0)
    comp_z = 0.5 * z_sched + 0.5 * z_surp
    std_comp = comp_z.std()
    df_ranks["Lucky_Factor"] = np.round(50.0 + 50.0 * (comp_z / (3.0 * (std_comp if std_comp and std_comp > 0 else 1.0))), 1)

    col_order = ["Actual_Rank", "Team"]
    for c in ["WP", "AP", "SP", "Wins", "Losses", "Ties"]:
        if c in df_ranks.columns: col_order.append(c)
    col_order += ["Avg_Teammate_Rank", "Avg_Opponent_Rank", "Schedule_Advantage", "SOS_Rank", "Carry_Factor", "Lucky_Factor"]
    
    return df_ranks[[c for c in col_order if c in df_ranks.columns]].sort_values("Actual_Rank").reset_index(drop=True), pd.DataFrame(audit_rows)

def get_archived_tournaments():
    valid_exts = (".csv", ".xlsx", ".xls")
    if not os.path.exists(TOURNAMENTS_DIR):
        return []
    return sorted([f for f in os.listdir(TOURNAMENTS_DIR) if f.lower().endswith(valid_exts)])

def load_tournament_file(filepath):
    df = parse_file(filepath)
    df.columns = [str(c).strip() for c in df.columns]
    is_raw_match = any("match" in c.lower() for c in df.columns) and any("red" in c.lower() for c in df.columns)
    if is_raw_match:
        df_analyzed, _ = analyze_tournament(df)
        return df_analyzed
    return df

def load_all_archived_teams():
    all_files = get_archived_tournaments()
    all_records = []
    for f in all_files:
        path = os.path.join(TOURNAMENTS_DIR, f)
        try:
            df = load_tournament_file(path)
            if df is not None and "Team" in df.columns:
                df = df.copy()
                df["Tournament"] = os.path.splitext(f)[0]
                all_records.append(df)
        except Exception:
            continue
    return pd.concat(all_records, ignore_index=True) if all_records else pd.DataFrame()

# ==============================================================================
# MODE 1: TM EVENT ANALYZER & ARCHIVE (API + UPLOAD + PERSISTENCE)
# ==============================================================================
if app_mode == "📊 TM Event Analyzer & Archive":
    st.subheader("📊 Tournament Manager Results, Analytics & Archival")

    if "df_results" not in st.session_state:
        st.session_state["df_results"] = None
    if "df_audit" not in st.session_state:
        st.session_state["df_audit"] = None
    if "loaded_source_label" not in st.session_state:
        st.session_state["loaded_source_label"] = ""

    st.sidebar.header("📥 Ingestion Method")
    ingest_source = st.sidebar.radio(
        "Select Source:", 
        ["API Sync (Instant)", "File Upload (.xlsx/.xls/.csv)", "Load From Archive"],
        index=0
    )

    if ingest_source == "API Sync (Instant)":
        st.sidebar.markdown("### ⚡ Live VEX API Sync")
        api_event_input = st.sidebar.text_input("Event SKU or ID:", placeholder="e.g. RE-V5RC-26-4758")

        if st.sidebar.button("⚡ Fetch & Analyze Event"):
            if api_event_input.strip():
                with st.spinner("Connecting to live tournament database..."):
                    try:
                        target_id, event_title = api_client.resolve_event(api_event_input.strip())
                        st.sidebar.success(f"Connected: **{event_title}**")
                        
                        df_m = api_client.get_event_matches(target_id)
                        
                        if df_m.empty:
                            st.sidebar.warning(f"⚠️ **{event_title}** has no qualification matches published in the API yet.")
                            df_t = api_client.get_event_teams(target_id)
                            if not df_t.empty:
                                st.sidebar.info(f"💡 Found **{len(df_t)} registered teams** for this event. You can load this roster into the Sandbox.")
                        else:
                            try:
                                df_r = api_client.get_event_rankings(target_id)
                            except Exception:
                                df_r = None
                                
                            res, audit = analyze_tournament(df_m, df_r)
                            st.session_state["df_results"] = res
                            st.session_state["df_audit"] = audit
                            st.session_state["loaded_source_label"] = f"{event_title} ({target_id})"
                            st.rerun()
                    except Exception as e:
                        st.sidebar.error(f"Sync Failed: {str(e)}")
            else:
                st.sidebar.warning("Please enter a valid Event SKU or ID.")

    elif ingest_source == "Load From Archive":
        st.sidebar.markdown("### 📁 Archive Presets")
        archived_files = get_archived_tournaments()
        if archived_files:
            selected_archive = st.sidebar.selectbox("Choose Saved Tournament:", ["-- Select Event --"] + archived_files)
            if selected_archive != "-- Select Event --":
                if st.sidebar.button("📂 Load Selected Event"):
                    archive_path = os.path.join(TOURNAMENTS_DIR, selected_archive)
                    with st.spinner(f"Loading {selected_archive}..."):
                        st.session_state["df_results"] = load_tournament_file(archive_path)
                        st.session_state["loaded_source_label"] = selected_archive
                        st.session_state["df_audit"] = None
                        st.rerun()
        else:
            st.sidebar.info("No archives found in `data/tournaments/`.")

    else:
        st.sidebar.markdown("### 📤 File Uploads")
        uploaded_matches = st.sidebar.file_uploader("1. Match Results (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])
        uploaded_rankings = st.sidebar.file_uploader("2. TM Rankings (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])
        manual_overrides = st.sidebar.text_area("3. Overrides (Optional)", placeholder="e.g.\nTie: Qualifier #58\nDQ: Qualifier #12, Red")
        
        if uploaded_matches is not None:
            if st.sidebar.button("🚀 Analyze Uploaded Files"):
                with st.spinner("Processing Tournament Data..."):
                    df_m = parse_file(uploaded_matches)
                    df_r = parse_file(uploaded_rankings) if uploaded_rankings is not None else None
                    res, audit = analyze_tournament(df_m, df_r, manual_overrides)
                    st.session_state["df_results"] = res
                    st.session_state["df_audit"] = audit
                    st.session_state["loaded_source_label"] = uploaded_matches.name
                    st.rerun()

    # Main Dashboard Display
    df_results = st.session_state["df_results"]

    if df_results is not None:
        st.info(f"📍 Displaying active tournament: **{st.session_state['loaded_source_label']}**")
        
        c1, c2, c3 = st.columns(3)
        top_carry = df_results.sort_values("Carry_Factor", ascending=False).iloc[0]
        luckiest = df_results.sort_values("Lucky_Factor", ascending=False).iloc[0]
        hardest_sos = df_results.sort_values("SOS_Rank").iloc[0]
        
        c1.metric("Highest Carry Factor", f"{top_carry['Team']} ({top_carry['Carry_Factor']})")
        c2.metric("Luckiest Schedule Draw", f"{luckiest['Team']} ({luckiest['Lucky_Factor']})")
        c3.metric("Hardest Schedule (#1 SOS)", f"{hardest_sos['Team']}")

        st.subheader("Tournament Advanced Metrics Board")
        st.dataframe(df_results, use_container_width=True)

        b_col1, b_col2 = st.columns([1, 1])
        with b_col1:
            csv_data = df_results.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Export Clean CSV", data=csv_data, file_name="tournament_analytics.csv", mime="text/csv")
        with b_col2:
            event_name = st.text_input("Save As Archive Name:", value=f"Event_{datetime.now().strftime('%Y%m%d_%H%M')}")
            if st.button("💾 Save Event to Tournament Archive"):
                save_path = os.path.join(TOURNAMENTS_DIR, f"{event_name.strip()}.csv")
                df_results.to_csv(save_path, index=False)
                st.success(f"Saved event to archive as `{event_name.strip()}.csv`!")
                st.rerun()
    else:
        st.markdown("---")
        st.markdown("### 👈 Get Started by Loading Tournament Data")
        st.write("Choose one of the three options from the sidebar to populate the analytics board:")
        
        col_card1, col_card2, col_card3 = st.columns(3)
        with col_card1:
            st.markdown("#### ⚡ Live API Sync")
            st.caption("Enter a V5RC Event SKU or numeric ID to stream match schedules and rankings directly.")
        with col_card2:
            st.markdown("#### 📤 File Upload")
            st.caption("Upload your raw Tournament Manager qualification match export (`.xlsx`, `.xls`, or `.csv`). Official rankings are optional.")
        with col_card3:
            st.markdown("#### 📁 Archive Presets")
            st.caption("Load any tournament previously saved or committed into the repository's `data/tournaments/` folder.")

# ==============================================================================
# MODE 2: TOP 25 COMMUNITY VOTING & CONSENSUS POLL
# ==============================================================================
elif app_mode == "🗳️ Top 25 Poll & Community Rankings":
    st.subheader("🗳️ V5RC Community Top 25 Power Rankings Portal")
    st.write("Submit your Top 25 ballot using aggregated tournament resumes, or inspect the live community consensus leaderboard.")

    tab_ballot, tab_consensus, tab_dossier = st.tabs(["✍️ Submit Top 25 Ballot", "🏆 Consensus Power Rankings", "🔎 Team Season Resumes"])

    df_global = load_all_archived_teams()
    known_teams = sorted(df_global["Team"].unique().tolist()) if not df_global.empty else []

    with tab_ballot:
        st.markdown("### 📋 Official Top 25 Ballot")
        voter_name = st.text_input("Voter Name / Handle:", placeholder="e.g. BuckeyeScout / Coach Smith")
        affiliation = st.text_input("Voter Affiliation / Region (Optional):", placeholder="e.g. Ohio / Team 2011")
        st.caption("Select your ranked 1 to 25 teams. Each team must be unique.")

        ballot_choices = {}
        cols = st.columns(2)
        for r in range(1, 26):
            target_col = cols[0] if r <= 13 else cols[1]
            with target_col:
                if known_teams:
                    options = ["-- Select Team --"] + known_teams
                    val = st.selectbox(f"#{r} Rank", options, key=f"poll_rank_{r}")
                    if val != "-- Select Team --":
                        ballot_choices[r] = val
                else:
                    val = st.text_input(f"#{r} Rank Team #", key=f"poll_rank_{r}")
                    if val.strip():
                        ballot_choices[r] = val.strip().upper()

        picked_teams = list(ballot_choices.values())
        duplicates = [t for t in set(picked_teams) if picked_teams.count(t) > 1]
        submit_disabled = bool(duplicates) or (len(picked_teams) < 25) or (not voter_name.strip())

        if duplicates:
            st.error(f"❌ Duplicate teams selected: {', '.join(duplicates)}. Each rank must be a unique team.")
        elif len(picked_teams) < 25:
            st.warning(f"⚠️ Ballot incomplete: {len(picked_teams)} of 25 teams selected.")

        if st.button("📤 Submit Top 25 Ballot", disabled=submit_disabled):
            new_ballot = {
                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Voter": voter_name.strip(),
                "Affiliation": affiliation.strip()
            }
            for rank_num, team_val in ballot_choices.items():
                new_ballot[f"Rank_{rank_num}"] = team_val

            df_new = pd.DataFrame([new_ballot])
            if os.path.exists(BALLOTS_FILE):
                df_new.to_csv(BALLOTS_FILE, mode="a", header=False, index=False)
            else:
                df_new.to_csv(BALLOTS_FILE, index=False)

            st.success("✅ Ballot submitted successfully and factored into the consensus rankings!")
            st.rerun()

    with tab_consensus:
        st.markdown("### 🏆 Community Consensus Top 25 Leaderboard")
        st.caption("Borda Count Scoring: #1 = 25 pts, #2 = 24 pts, down to #25 = 1 pt.")

        if os.path.exists(BALLOTS_FILE) and os.path.getsize(BALLOTS_FILE) > 0:
            df_ballots = pd.read_csv(BALLOTS_FILE)
            st.metric("Total Ballots Submitted", len(df_ballots))

            borda_scores = {}
            ballot_counts = {}
            ranks_list = {}

            for _, row in df_ballots.iterrows():
                for r in range(1, 26):
                    col_name = f"Rank_{r}"
                    if col_name in row and pd.notna(row[col_name]):
                        t = str(row[col_name]).strip()
                        pts = 26 - r
                        borda_scores[t] = borda_scores.get(t, 0) + pts
                        ballot_counts[t] = ballot_counts.get(t, 0) + 1
                        ranks_list.setdefault(t, []).append(r)

            consensus_rows = []
            for t, total_pts in borda_scores.items():
                consensus_rows.append({
                    "Team": t,
                    "Total_Points": total_pts,
                    "Ballots_Appeared": ballot_counts[t],
                    "Avg_Rank": round(np.mean(ranks_list[t]), 1),
                    "Best_Rank": min(ranks_list[t])
                })

            df_consensus = pd.DataFrame(consensus_rows)
            df_consensus = df_consensus.sort_values(by=["Total_Points", "Ballots_Appeared", "Avg_Rank"], ascending=[False, False, True]).reset_index(drop=True)
            df_consensus.index = df_consensus.index + 1
            df_consensus.index.name = "Consensus_Rank"
            df_consensus = df_consensus.reset_index()

            st.dataframe(df_consensus.head(25), use_container_width=True)

            with st.expander("🗳️ View All Submitted Ballots"):
                st.dataframe(df_ballots, use_container_width=True)
        else:
            st.info("No ballots submitted yet. Submit the first ballot in the 'Submit Top 25 Ballot' tab!")

    with tab_dossier:
        st.markdown("### 🔎 Season Team Dossiers & Performance History")
        if not df_global.empty:
            inspect_team = st.selectbox("Select Team to Inspect:", known_teams)
            team_records = df_global[df_global["Team"] == inspect_team]

            t_c1, t_c2, t_c3, t_c4 = st.columns(4)
            t_c1.metric("Events Attended", len(team_records))
            t_c2.metric("Best Finish", f"#{int(team_records['Actual_Rank'].min())}")
            t_c3.metric("Avg Finish", f"#{team_records['Actual_Rank'].mean():.1f}")
            if "Carry_Factor" in team_records.columns:
                t_c4.metric("Mean Carry Factor", f"{team_records['Carry_Factor'].mean():.1f}")

            st.markdown("#### Tournament History Breakdown")
            display_cols = [c for c in ["Tournament", "Actual_Rank", "WP", "AP", "SP", "Carry_Factor", "SOS_Rank", "Lucky_Factor"] if c in team_records.columns]
            st.dataframe(team_records[display_cols].reset_index(drop=True), use_container_width=True)
        else:
            st.info("No tournament archives found. Add `.xls`, `.xlsx`, or `.csv` files to `data/tournaments/` or save an event in Mode 1.")

# ==============================================================================
# MODE 3: FUTURE TOURNAMENT SANDBOX (API TEAM ROSTER LOAD)
# ==============================================================================
elif app_mode == "🔮 Future Tournament Sandbox":
    st.subheader("🔮 Upcoming Event Predictions & Alliance Draft Room")
    target_matches = st.sidebar.number_input("Scheduled Matches / Team:", min_value=2, max_value=12, value=6, step=1)
    
    col_sb1, col_sb2 = st.columns([1, 1])
    with col_sb1:
        use_template = st.button("📋 Load Sample 16-Team Roster")
    with col_sb2:
        api_sandbox_event = st.text_input("Or Pull Registered Roster via API Event SKU/ID:")
        pull_roster_btn = st.button("⚡ Fetch Team List")

    if pull_roster_btn and api_sandbox_event.strip():
        try:
            target_id, _ = api_client.resolve_event(api_sandbox_event.strip())
            df_fetched_teams = api_client.get_event_teams(target_id)
            if not df_fetched_teams.empty:
                initial_df = pd.DataFrame([{
                    "Team": r["Team"], "Name": r["Name"],
                    "Wins": target_matches // 2, "Losses": target_matches // 2, "Ties": 0,
                    "AWP": 0, "AP": 24, "SP": 120
                } for _, r in df_fetched_teams.iterrows()])
                st.success(f"Fetched {len(initial_df)} registered teams via API!")
            else:
                st.warning("No registered teams found for that event.")
                initial_df = pd.DataFrame([("Team A", "Alpha", 4, 2, 0, 1, 36, 150)], columns=["Team", "Name", "Wins", "Losses", "Ties", "AWP", "AP", "SP"])
        except Exception as e:
            st.error(f"API Fetch Error: {str(e)}")
            initial_df = pd.DataFrame([("Team A", "Alpha", 4, 2, 0, 1, 36, 150)], columns=["Team", "Name", "Wins", "Losses", "Ties", "AWP", "AP", "SP"])
    elif use_template:
        sample_teams = [
            ("6978K", "Dysfunctional", 6, 0, 0, 1, 48, 140),
            ("2011G", "Godspeed", 6, 0, 0, 1, 36, 205),
            ("11124S", "Solstice", 6, 0, 0, 1, 36, 183),
            ("2011F", "FaZe Clan", 5, 0, 1, 1, 60, 312),
            ("7316X", "Xcalibur", 5, 1, 0, 1, 66, 313),
            ("7316D", "Drop Test", 5, 1, 0, 1, 66, 145),
            ("6978P", "Panic!", 5, 1, 0, 1, 54, 233),
            ("2011B", "BlastOff", 5, 1, 0, 1, 48, 165),
            ("2011A", "Apex", 5, 1, 0, 1, 36, 163),
            ("2011D", "Defiance", 5, 1, 0, 1, 36, 162),
            ("68561Z", "ZigZag", 4, 2, 0, 1, 72, 194),
            ("2011S", "Sandwich Mafia", 4, 2, 0, 1, 66, 117),
            ("11124R", "T-Rex Push-Ups", 4, 2, 0, 1, 60, 136),
            ("44691F", "Fierce Functionality", 4, 2, 0, 1, 36, 211),
            ("64165A", "Spirit Driven", 4, 2, 0, 1, 36, 124),
            ("44691B", "Spare Change", 4, 2, 0, 1, 30, 180),
        ]
        initial_df = pd.DataFrame(sample_teams, columns=["Team", "Name", "Wins", "Losses", "Ties", "AWP", "AP", "SP"])
    else:
        default_teams = [
            ("Team A", "Alpha", 4, 2, 0, 1, 36, 150),
            ("Team B", "Bravo", 3, 3, 0, 1, 30, 130),
            ("Team C", "Charlie", 3, 3, 0, 0, 24, 110),
            ("Team D", "Delta", 2, 4, 0, 0, 18, 90)
        ]
        initial_df = pd.DataFrame(default_teams, columns=["Team", "Name", "Wins", "Losses", "Ties", "AWP", "AP", "SP"])

    edited_df = st.data_editor(
        initial_df, num_rows="dynamic", use_container_width=True,
        column_config={
            "Team": st.column_config.TextColumn("Team #", required=True),
            "Name": st.column_config.TextColumn("Team Name"),
            "Wins": st.column_config.NumberColumn("Wins", min_value=0, max_value=20, default=0),
            "Losses": st.column_config.NumberColumn("Losses", min_value=0, max_value=20, default=0),
            "Ties": st.column_config.NumberColumn("Ties", min_value=0, max_value=10, default=0),
            "AWP": st.column_config.NumberColumn("AWP", min_value=0, max_value=target_matches, default=0),
            "AP": st.column_config.NumberColumn("AP", min_value=0, max_value=300, default=0, step=6),
            "SP": st.column_config.NumberColumn("SP", min_value=0, max_value=1000, default=0)
        }
    )

    pred_data = edited_df.copy()
    pred_data["Wins"] = pd.to_numeric(pred_data["Wins"], errors="coerce").fillna(0).astype(int)
    pred_data["Losses"] = pd.to_numeric(pred_data["Losses"], errors="coerce").fillna(0).astype(int)
    pred_data["Ties"] = pd.to_numeric(pred_data["Ties"], errors="coerce").fillna(0).astype(int)
    pred_data["AWP"] = pd.to_numeric(pred_data["AWP"], errors="coerce").fillna(0).astype(int)
    pred_data["AP"] = pd.to_numeric(pred_data["AP"], errors="coerce").fillna(0).astype(int)
    pred_data["SP"] = pd.to_numeric(pred_data["SP"], errors="coerce").fillna(0).astype(int)

    tot_wins = int(pred_data["Wins"].sum())
    tot_losses = int(pred_data["Losses"].sum())
    tot_ties = int(pred_data["Ties"].sum())
    tot_ap = int(pred_data["AP"].sum())
    ap_unit = target_matches * 6

    # Validation Checks
    validation_errors = []
    if tot_wins != tot_losses:
        validation_errors.append(f"❌ **Wins/Losses Imbalance:** Total Wins ({tot_wins}) does not equal Total Losses ({tot_losses}).")
    if tot_wins % 2 != 0:
        validation_errors.append(f"❌ **Odd Win Count:** Total Wins ({tot_wins}) must be an even number.")
    if tot_losses % 2 != 0:
        validation_errors.append(f"❌ **Odd Loss Count:** Total Losses ({tot_losses}) must be an even number.")
    if tot_ap % ap_unit != 0:
        validation_errors.append(f"❌ **AP Divisibility Error:** Total AP ({tot_ap}) must be a multiple of ({target_matches} × 6) = **{ap_unit}**.")

    for err in validation_errors:
        st.error(err)
    if not validation_errors:
        st.success("✅ Tournament Math Verified: All parity and AP multiples pass.")

    pred_data["WP"] = (pred_data["Wins"] * 2) + pred_data["Ties"] + pred_data["AWP"]
    pred_standings = pred_data.sort_values(by=["WP", "AP", "SP"], ascending=[False, False, False]).reset_index(drop=True)
    pred_standings.index = pred_standings.index + 1
    pred_standings.index.name = "Predicted_Rank"
    pred_standings = pred_standings.reset_index()

    st.markdown("### 🏆 Predicted Leaderboard")
    st.dataframe(pred_standings[["Predicted_Rank", "Team", "Name", "Wins", "Losses", "Ties", "WP", "AP", "SP"]], use_container_width=True)

    # Alliance Selection Draft Room
    st.markdown("### 🤝 Interactive Alliance Selection Draft Room")
    all_teams_list = pred_standings["Team"].tolist()
    available_pool = all_teams_list.copy()

    col_d1, col_d2 = st.columns([1, 2])
    with col_d1:
        num_alliances = st.selectbox("Number of Alliances:", [8, 16] if len(all_teams_list) >= 32 else [8 if len(all_teams_list) >= 16 else max(2, len(all_teams_list)//2)])
        auto_draft = st.checkbox("Auto-Draft highest remaining seeds", value=False)

    alliances = []
    for a_num in range(1, num_alliances + 1):
        if not available_pool: break
        captain = available_pool.pop(0)
        if auto_draft:
            partner = available_pool.pop(0) if available_pool else "(None)"
        else:
            partner_options = ["Select Partner..."] + available_pool
            st.markdown(f"**Alliance #{a_num} Captain: `{captain}`**")
            partner_pick = st.selectbox(f"Partner for Alliance #{a_num}:", partner_options, key=f"draft_{a_num}")
            if partner_pick != "Select Partner..." and partner_pick in available_pool:
                available_pool.remove(partner_pick)
                partner = partner_pick
            else:
                partner = "(Undrafted)"

        alliances.append({"Alliance": a_num, "Captain": captain, "Partner": partner})

    df_alliances = pd.DataFrame(alliances)
    st.dataframe(df_alliances, use_container_width=True)