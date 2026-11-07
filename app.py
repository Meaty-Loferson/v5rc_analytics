import streamlit as st
import pandas as pd
import numpy as np
import os
import re
from datetime import datetime

st.set_page_config(page_title="V5RC Tournament Intelligence & Community Hub", layout="wide")

# Directory Configuration
DATA_DIR = "data"
TOURNAMENTS_DIR = os.path.join(DATA_DIR, "tournaments")
BALLOTS_DIR = os.path.join(DATA_DIR, "ballots")
BALLOTS_FILE = os.path.join(BALLOTS_DIR, "ballots.csv")

os.makedirs(TOURNAMENTS_DIR, exist_ok=True)
os.makedirs(BALLOTS_DIR, exist_ok=True)

# Navigation
app_mode = st.sidebar.radio(
    "Navigation:",
    [
        "TM Event Analyzer & Archive",
        "Top 25 Poll & Community Rankings",
        "Future Tournament Sandbox"
    ]
)

# ==========================================
# FILE INGESTION & DATA PARSING
# ==========================================
def parse_file(file):
    """
    Auto-detects file type using magic bytes and encoding scans so that
    renamed .xlsx files (.xlsx -> .csv) or legacy .xls files parse seamlessly.
    """
    if file is None:
        return None

    # Check for empty file
    if isinstance(file, str) and os.path.exists(file):
        if os.path.getsize(file) == 0:
            st.warning(f"File '{os.path.basename(file)}' is empty (0 bytes).")
            return None

    # Read leading bytes to inspect binary signatures
    header_bytes = b""
    try:
        if isinstance(file, str):
            with open(file, "rb") as f:
                header_bytes = f.read(8)
        elif hasattr(file, "read"):
            header_bytes = file.read(8)
            file.seek(0)
    except Exception:
        pass

    # 1. Zip-compressed Office Open XML (.xlsx)
    if header_bytes.startswith(b"PK\x03\x04"):
        try:
            if hasattr(file, "seek"):
                file.seek(0)
            return pd.read_excel(file, engine="openpyxl")
        except Exception:
            return pd.read_excel(file)

    # 2. Legacy OLE Compound Document (.xls)
    if header_bytes.startswith(b"\xd0\xcf\x11\xe0"):
        for eng in ["calamine", "xlrd"]:
            try:
                if hasattr(file, "seek"):
                    file.seek(0)
                return pd.read_excel(file, engine=eng)
            except Exception:
                continue
        return pd.read_excel(file)

    # 3. Plain text / CSV with encoding fallbacks
    for enc in ["utf-8", "utf-8-sig", "cp1252", "latin1", "utf-16"]:
        try:
            if hasattr(file, "seek"):
                file.seek(0)
            return pd.read_csv(file, encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        except pd.errors.EmptyDataError:
            return None
        except Exception:
            break

    # 4. Final fallback
    try:
        if hasattr(file, "seek"):
            file.seek(0)
        return pd.read_excel(file)
    except Exception as e:
        filename = file if isinstance(file, str) else getattr(file, "name", "unknown")
        st.error(f"Could not parse '{filename}': {str(e)}")
        return None

def clean_team_token(token):
    """
    Extracts clean team string and flags DQ tags (e.g. '2011B (DQ)' or '11124X*').
    """
    raw = str(token).strip()
    is_dq = bool(re.search(r'\bDQ\b|\(DQ\)', raw, re.IGNORECASE))
    clean_team = re.sub(r'[\(\[\{]?\bDQ\b[\)\]\}]?|\*', '', raw, flags=re.IGNORECASE).strip()
    return clean_team, is_dq

def parse_manual_overrides(text):
    overrides = {"match_winner": {}, "team_dq": set(), "alliance_dq": {}}
    if not text.strip():
        return overrides

    for line in text.strip().split("\n"):
        parts = line.split(":")
        if len(parts) >= 2:
            action = parts[0].strip().lower()
            details = parts[1].strip()

            if action == "tie":
                overrides["match_winner"][details.lower()] = "Tie"
            elif action == "winner":
                sub = details.split(",")
                if len(sub) == 2:
                    overrides["match_winner"][sub[0].strip().lower()] = sub[1].strip().capitalize()
            elif action == "dq":
                sub = details.split(",")
                if len(sub) == 2:
                    m_key = sub[0].strip().lower()
                    target = sub[1].strip()
                    target_lower = target.lower()

                    if target_lower in ["red", "blue"]:
                        overrides["alliance_dq"].setdefault(m_key, set()).add(target.capitalize())
                    elif target_lower in ["red 1", "red1"]:
                        overrides["team_dq"].add((m_key, "red1"))
                    elif target_lower in ["red 2", "red2"]:
                        overrides["team_dq"].add((m_key, "red2"))
                    elif target_lower in ["blue 1", "blue1"]:
                        overrides["team_dq"].add((m_key, "blue1"))
                    elif target_lower in ["blue 2", "blue2"]:
                        overrides["team_dq"].add((m_key, "blue2"))
                    else:
                        overrides["team_dq"].add((m_key, target.upper()))
    return overrides

def get_available_events():
    if not os.path.exists(TOURNAMENTS_DIR):
        return []
    files = os.listdir(TOURNAMENTS_DIR)
    events = set()
    for f in files:
        if f.endswith((".csv", ".xlsx", ".xls")):
            base_name = f.rsplit(".", 1)[0]
            for suffix in ["_matches", "_rankings", "-matches", "-rankings", "_results"]:
                if base_name.endswith(suffix):
                    base_name = base_name[:-len(suffix)]
                    break
            events.add(base_name)
    return sorted(list(events))

def load_preloaded_event_files(event_prefix):
    matches_file = None
    rankings_file = None

    if not os.path.exists(TOURNAMENTS_DIR):
        st.sidebar.error("Tournaments directory 'data/tournaments/' not found.")
        return None, None

    all_files = os.listdir(TOURNAMENTS_DIR)
    matching_files = [f for f in all_files if f.lower().startswith(event_prefix.lower())]

    for f in matching_files:
        full_path = os.path.join(TOURNAMENTS_DIR, f)
        lower_name = f.lower()

        if any(k in lower_name for k in ["rank", "standing"]):
            rankings_file = full_path
        elif any(k in lower_name for k in ["match", "qual", "result", "schedule"]):
            matches_file = full_path
        elif not matches_file:
            matches_file = full_path

    with st.sidebar.expander("🔍 Loaded File Diagnostics", expanded=False):
        st.write(f"**Prefix:** `{event_prefix}`")
        st.write(f"**Matches File:** `{os.path.basename(matches_file) if matches_file else 'None Found'}`")
        st.write(f"**Rankings File:** `{os.path.basename(rankings_file) if rankings_file else 'None Found'}`")
        st.write("**Folder Files:**", all_files)

    df_m = parse_file(matches_file) if matches_file else None
    df_r = parse_file(rankings_file) if rankings_file else None
    return df_m, df_r

def load_all_archived_teams():
    events = get_available_events()
    all_records = []
    for ev in events:
        _, df_r = load_preloaded_event_files(ev)
        if df_r is not None and "Team" in df_r.columns:
            df_r["Tournament"] = ev
            all_records.append(df_r)
        else:
            path = os.path.join(TOURNAMENTS_DIR, f"{ev}.csv")
            if os.path.exists(path):
                try:
                    df = pd.read_csv(path)
                    if "Team" in df.columns:
                        df["Tournament"] = ev
                        all_records.append(df)
                except Exception:
                    continue
    if all_records:
        return pd.concat(all_records, ignore_index=True)
    return pd.DataFrame()

# ==========================================
# CORE ANALYTICS & AUTO-RECONCILIATION
# ==========================================
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
        st.error(f"Could not map columns: {list(df_matches.columns)}")
        return None, None

    qual_df = df_matches[df_matches[match_col].astype(str).str.startswith("Qualifier")].copy()
    qual_df[r_score_col] = pd.to_numeric(qual_df[r_score_col], errors="coerce").fillna(0.0)
    qual_df[b_score_col] = pd.to_numeric(qual_df[b_score_col], errors="coerce").fillna(0.0)

    raw_teams = set()
    for col in [r1_col, r2_col, b1_col, b2_col]:
        for val in qual_df[col].dropna():
            team_clean, _ = clean_team_token(val)
            if team_clean and team_clean.lower() != "nan" and not team_clean.isdigit():
                raw_teams.add(team_clean)

    all_teams = sorted(list(raw_teams))
    overrides = parse_manual_overrides(overrides_text)
    match_dqs = set()
    auto_detected_dqs = []
    scoring_anomalies = []

    # 1. Ingest Official TM Rankings
    df_ranks = None
    official_data = {}
    if df_rankings_file is not None:
        df_rankings_file.columns = [str(c).strip() for c in df_rankings_file.columns]
        team_rk_col = next((c for c in df_rankings_file.columns if "team" in c.lower()), None)
        rk_col = next((c for c in df_rankings_file.columns if "rank" in c.lower()), None)
        wp_col = next((c for c in df_rankings_file.columns if "wp" in c.lower()), None)
        ap_col = next((c for c in df_rankings_file.columns if "ap" in c.lower()), None)
        sp_col = next((c for c in df_rankings_file.columns if "sp" in c.lower()), None)
        wins_col = next((c for c in df_rankings_file.columns if "win" in c.lower() and "point" not in c.lower()), None)
        loss_col = next((c for c in df_rankings_file.columns if "loss" in c.lower()), None)
        ties_col = next((c for c in df_rankings_file.columns if "tie" in c.lower()), None)

        if team_rk_col and rk_col:
            df_ranks = df_rankings_file.copy()
            df_ranks["Team"] = df_ranks[team_rk_col].astype(str).map(lambda x: clean_team_token(x)[0])
            df_ranks["Actual_Rank"] = pd.to_numeric(df_ranks[rk_col], errors="coerce").fillna(99).astype(int)
            if wp_col: df_ranks["WP"] = pd.to_numeric(df_ranks[wp_col], errors="coerce").fillna(0).astype(int)
            if ap_col: df_ranks["AP"] = pd.to_numeric(df_ranks[ap_col], errors="coerce").fillna(0).astype(int)
            if sp_col: df_ranks["SP"] = pd.to_numeric(df_ranks[sp_col], errors="coerce").fillna(0).astype(int)
            if wins_col: df_ranks["Wins"] = pd.to_numeric(df_ranks[wins_col], errors="coerce").fillna(0).astype(int)
            if loss_col: df_ranks["Losses"] = pd.to_numeric(df_ranks[loss_col], errors="coerce").fillna(0).astype(int)
            if ties_col: df_ranks["Ties"] = pd.to_numeric(df_ranks[ties_col], errors="coerce").fillna(0).astype(int)

            # Auto-calculate AWP: AWP = WP - (2 * Wins + Ties)
            if all(k in df_ranks.columns for k in ["WP", "Wins", "Ties"]):
                df_ranks["AWP"] = (df_ranks["WP"] - (2 * df_ranks["Wins"] + df_ranks["Ties"])).clip(lower=0)

            for _, r in df_ranks.iterrows():
                official_data[r["Team"]] = r.to_dict()

    # 2. Pre-scan matches: log tags, score-winner flips, and per-team match list
    team_match_history = {t: [] for t in all_teams}
    for _, row in qual_df.iterrows():
        m_label = str(row[match_col]).strip()
        m_key = m_label.lower()
        r1, r1_dq = clean_team_token(row[r1_col]); r2, r2_dq = clean_team_token(row[r2_col])
        b1, b1_dq = clean_team_token(row[b1_col]); b2, b2_dq = clean_team_token(row[b2_col])
        r_sc = float(row[r_score_col]); b_sc = float(row[b_score_col])
        w = str(row[winner_col]).strip() if winner_col else ""

        for t, is_dq in [(r1, r1_dq), (r2, r2_dq), (b1, b1_dq), (b2, b2_dq)]:
            if is_dq:
                match_dqs.add((m_key, t))
                auto_detected_dqs.append(f"{m_label}: Team **{t}** marked as DQ in match export.")

        if w == "Red" and b_sc > r_sc:
            scoring_anomalies.append(f"{m_label}: Winner is Red despite score being Blue {int(b_sc)} - Red {int(r_sc)}.")
        elif w == "Blue" and r_sc > b_sc:
            scoring_anomalies.append(f"{m_label}: Winner is Blue despite score being Red {int(r_sc)} - Blue {int(b_sc)}.")

        if m_key in overrides["match_winner"]:
            w_eff = overrides["match_winner"][m_key]
        elif w in ["Red", "Blue", "Tie"]:
            w_eff = w
        else:
            w_eff = "Red" if r_sc > b_sc else ("Blue" if b_sc > r_sc else "Tie")

        losing_sc = int(min(r_sc, b_sc))
        for t, alliance, partner in [(r1, "Red", r2), (r2, "Red", r1), (b1, "Blue", b2), (b2, "Blue", b1)]:
            res = "Win" if w_eff == alliance else ("Tie" if w_eff == "Tie" else "Loss")
            team_match_history[t].append({
                "match": m_label, "match_key": m_key, "partner": partner,
                "alliance": alliance, "result": res, "losing_score": losing_sc
            })

    # 3. Cross-Reconciliation DQ Detection Engine
    if official_data:
        for t in all_teams:
            if t not in official_data:
                continue
            off_wins = official_data[t].get("Wins")
            off_sp = official_data[t].get("SP")

            # Team DQ on a match their alliance won
            calc_wins = sum(1 for m in team_match_history[t] if m["result"] == "Win")
            if off_wins is not None and calc_wins > off_wins:
                wins_to_remove = calc_wins - off_wins
                for m in team_match_history[t]:
                    if wins_to_remove <= 0:
                        break
                    p = m["partner"]
                    p_off_wins = official_data.get(p, {}).get("Wins")
                    p_calc_wins = sum(1 for pm in team_match_history[p] if pm["result"] == "Win")
                    if p_off_wins == p_calc_wins:
                        match_dqs.add((m["match_key"], t))
                        auto_detected_dqs.append(f"Auto-Reconciled: Team **{t}** DQ detected in **{m['match']}** (Partner {p} kept win).")
                        wins_to_remove -= 1

            # Team DQ on a match their alliance lost (0 SP granted)
            calc_sp = sum(m["losing_score"] for m in team_match_history[t])
            if off_sp is not None and calc_sp > off_sp:
                sp_deficit = calc_sp - off_sp
                for m in team_match_history[t]:
                    if m["result"] == "Loss" and m["losing_score"] == sp_deficit and (m["match_key"], t) not in match_dqs:
                        match_dqs.add((m["match_key"], t))
                        auto_detected_dqs.append(f"Auto-Reconciled: Team **{t}** DQ detected on loss in **{m['match']}** ({sp_deficit} SP zeroed out).")
                        break

    # 4. Map Manual Overrides
    for t_ident, t_clean in [("red1", r1_col), ("red2", r2_col), ("blue1", b1_col), ("blue2", b2_col)]:
        pass

    # 5. Build official matrix honoring V5RC Rule GG6
    stats = {t: {"Wins": 0, "Losses": 0, "Ties": 0, "WP": 0, "SP": 0} for t in all_teams}
    for _, row in qual_df.iterrows():
        m_label = str(row[match_col]).strip(); m_key = m_label.lower()
        r1, _ = clean_team_token(row[r1_col]); r2, _ = clean_team_token(row[r2_col])
        b1, _ = clean_team_token(row[b1_col]); b2, _ = clean_team_token(row[b2_col])
        r_sc = float(row[r_score_col]); b_sc = float(row[b_score_col])
        losing_sc = int(min(r_sc, b_sc))

        w = str(row[winner_col]).strip() if winner_col else ""
        if m_key in overrides["match_winner"]:
            w_eff = overrides["match_winner"][m_key]
        elif w in ["Red", "Blue", "Tie"]:
            w_eff = w
        else:
            w_eff = "Red" if r_sc > b_sc else ("Blue" if b_sc > r_sc else "Tie")

        # Red Alliance
        for t in [r1, r2]:
            if (m_key, t) in match_dqs:
                stats[t]["Losses"] += 1
            elif w_eff == "Red":
                stats[t]["Wins"] += 1; stats[t]["WP"] += 2; stats[t]["SP"] += losing_sc
            elif w_eff == "Tie":
                stats[t]["Ties"] += 1; stats[t]["WP"] += 1; stats[t]["SP"] += losing_sc
            else:
                stats[t]["Losses"] += 1; stats[t]["SP"] += losing_sc

        # Blue Alliance
        for t in [b1, b2]:
            if (m_key, t) in match_dqs:
                stats[t]["Losses"] += 1
            elif w_eff == "Blue":
                stats[t]["Wins"] += 1; stats[t]["WP"] += 2; stats[t]["SP"] += losing_sc
            elif w_eff == "Tie":
                stats[t]["Ties"] += 1; stats[t]["WP"] += 1; stats[t]["SP"] += losing_sc
            else:
                stats[t]["Losses"] += 1; stats[t]["SP"] += losing_sc

    if df_ranks is None:
        df_ranks = pd.DataFrame([{"Team": t, **s} for t, s in stats.items()])
        df_ranks = df_ranks.sort_values(by=["WP", "SP"], ascending=[False, False]).reset_index(drop=True)
        df_ranks["Actual_Rank"] = df_ranks.index + 1

    rank_map = {row["Team"]: row["Actual_Rank"] for _, row in df_ranks.iterrows()}

    # 6. Schedule Gauntlet & Individual Leverage
    carry_sums = {t: 0.0 for t in all_teams}
    teammates = {t: [] for t in all_teams}
    opponents = {t: [] for t in all_teams}
    audit_rows = []

    for _, row in qual_df.iterrows():
        m_label = str(row[match_col]).strip(); m_key = m_label.lower()
        r1, _ = clean_team_token(row[r1_col]); r2, _ = clean_team_token(row[r2_col])
        b1, _ = clean_team_token(row[b1_col]); b2, _ = clean_team_token(row[b2_col])
        r_sc = float(row[r_score_col]); b_sc = float(row[b_score_col])

        w = str(row[winner_col]).strip() if winner_col else ""
        if m_key in overrides["match_winner"]:
            w_eff = overrides["match_winner"][m_key]
        elif w in ["Red", "Blue", "Tie"]:
            w_eff = w
        else:
            w_eff = "Red" if r_sc > b_sc else ("Blue" if b_sc > r_sc else "Tie")

        # Red Alliance Leverage
        if all(t in rank_map for t in [r1, r2, b1, b2]):
            for t, p in [(r1, r2), (r2, r1)]:
                teammates[t].append(rank_map[p])
                opponents[t].extend([rank_map[b1], rank_map[b2]])
                delta_r = ((rank_map[t] + rank_map[p]) / 2.0) - ((rank_map[b1] + rank_map[b2]) / 2.0)
                base = (rank_map[p] - rank_map[t]) + 2.0 * max(0.0, delta_r)

                if (m_key, t) in match_dqs:
                    carry = -abs(base) if base > 0 else base
                    res_str = "DQ"
                elif w_eff == "Red":
                    carry = base * 1.0; res_str = "Win"
                elif w_eff == "Tie":
                    carry = base * 0.5; res_str = "Tie"
                else:
                    w_m = -0.25 * max(0.0, 1.0 - (r_sc / max(b_sc, 1.0)))
                    carry = -abs(base) * abs(w_m) if base > 0 else base * (1.0 - abs(w_m))
                    res_str = "Loss"

                carry_sums[t] += carry
                audit_rows.append({
                    "Match": m_label, "Team": t, "Alliance": "Red", "Partner": p,
                    "Opponents": f"{b1}, {b2}", "Score": f"{int(r_sc)}-{int(b_sc)}",
                    "Result": res_str, "Match_Leverage": round(carry, 2)
                })

        # Blue Alliance Leverage
        if all(t in rank_map for t in [r1, r2, b1, b2]):
            for t, p in [(b1, b2), (b2, b1)]:
                teammates[t].append(rank_map[p])
                opponents[t].extend([rank_map[r1], rank_map[r2]])
                delta_r = ((rank_map[t] + rank_map[p]) / 2.0) - ((rank_map[r1] + rank_map[r2]) / 2.0)
                base = (rank_map[p] - rank_map[t]) + 2.0 * max(0.0, delta_r)

                if (m_key, t) in match_dqs:
                    carry = -abs(base) if base > 0 else base
                    res_str = "DQ"
                elif w_eff == "Blue":
                    carry = base * 1.0; res_str = "Win"
                elif w_eff == "Tie":
                    carry = base * 0.5; res_str = "Tie"
                else:
                    w_m = -0.25 * max(0.0, 1.0 - (b_sc / max(r_sc, 1.0)))
                    carry = -abs(base) * abs(w_m) if base > 0 else base * (1.0 - abs(w_m))
                    res_str = "Loss"

                carry_sums[t] += carry
                audit_rows.append({
                    "Match": m_label, "Team": t, "Alliance": "Blue", "Partner": p,
                    "Opponents": f"{r1}, {r2}", "Score": f"{int(b_sc)}-{int(r_sc)}",
                    "Result": res_str, "Match_Leverage": round(carry, 2)
                })

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

    # Dynamic Expected Rank and Lucky Factor
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

    if auto_detected_dqs:
        with st.expander("🚨 Auto-Detected Disqualifications (Cross-Reconciled)", expanded=True):
            for alert in auto_detected_dqs:
                st.write(alert)

    if scoring_anomalies:
        with st.expander("⚖️ Score vs. Winner Overrides (Ref Decisions)", expanded=False):
            for alert in scoring_anomalies:
                st.write(alert)

    col_order = ["Actual_Rank", "Team"]
    for c in ["WP", "AP", "SP", "AWP", "Wins", "Losses", "Ties"]:
        if c in df_ranks.columns: col_order.append(c)
    col_order += ["Avg_Teammate_Rank", "Avg_Opponent_Rank", "Schedule_Advantage", "SOS_Rank", "Carry_Factor", "Lucky_Factor"]

    df_final = df_ranks[[c for c in col_order if c in df_ranks.columns]].sort_values("Actual_Rank").reset_index(drop=True)
    df_audit = pd.DataFrame(audit_rows)
    return df_final, df_audit

# ==========================================
# MODE 1: TM EVENT ANALYZER & ARCHIVE
# ==========================================
if app_mode == "TM Event Analyzer & Archive":
    st.subheader("Tournament Manager Results, Analytics & Archival")

    st.sidebar.header("📁 Load Saved Tournament")
    available_events = get_available_events()
    selected_event = st.sidebar.selectbox(
        "Choose Archived Tournament:",
        ["-- Upload New Event Below --"] + available_events
    )

    st.sidebar.header("📤 Or Upload New Tournament")
    uploaded_matches = st.sidebar.file_uploader("1. Match Results (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])
    uploaded_rankings = st.sidebar.file_uploader("2. TM Rankings (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])
    manual_overrides = st.sidebar.text_area(
        "3. Overrides (Optional)",
        placeholder="e.g.\nDQ: Qualifier #12, 2011B\nTie: Qualifier #58\nWinner: Qualifier #65, Blue"
    )

    df_m = None
    df_r = None

    if selected_event != "-- Upload New Event Below --":
        df_m, df_r = load_preloaded_event_files(selected_event)
        if df_m is not None:
            st.sidebar.success(f"Loaded match data for **{selected_event}**")
        if df_r is not None:
            st.sidebar.success("Found & linked official TM Rankings!")
        else:
            st.sidebar.info("Running standalone on match score tallies.")
    elif uploaded_matches is not None:
        df_m = parse_file(uploaded_matches)
        df_r = parse_file(uploaded_rankings) if uploaded_rankings is not None else None

    if df_m is not None:
        df_results, df_audit = analyze_tournament(df_m, df_r, manual_overrides)

        if df_results is not None:
            c1, c2, c3, c4 = st.columns(4)
            top_carry = df_results.sort_values("Carry_Factor", ascending=False).iloc[0]
            luckiest = df_results.sort_values("Lucky_Factor", ascending=False).iloc[0]
            hardest_sos = df_results.sort_values("SOS_Rank").iloc[0]
            unluckiest = df_results.sort_values("Lucky_Factor").iloc[0]

            c1.metric("Highest Carry Factor", f"{top_carry['Team']} ({top_carry['Carry_Factor']})")
            c2.metric("Hardest Schedule (#1 SOS)", f"{hardest_sos['Team']}")
            c3.metric("Luckiest Schedule Draw", f"{luckiest['Team']} ({luckiest['Lucky_Factor']})")
            c4.metric("Most Suppressed / Tough Luck", f"{unluckiest['Team']} ({unluckiest['Lucky_Factor']})")

            st.subheader("Tournament Advanced Metrics Board")
            st.dataframe(df_results, use_container_width=True)

            b_col1, b_col2 = st.columns([1, 1])
            with b_col1:
                csv_data = df_results.to_csv(index=False).encode("utf-8")
                st.download_button("📥 Export Clean CSV", data=csv_data, file_name="tournament_analytics.csv", mime="text/csv")
            with b_col2:
                if selected_event == "-- Upload New Event Below --":
                    event_name = st.text_input("Archive Event Name (e.g., 2026-10-31_Marion_Harding):", value=f"Event_{datetime.now().strftime('%Y%m%d')}")
                    if st.button("💾 Save Event to Tournament Archive"):
                        save_path = os.path.join(TOURNAMENTS_DIR, f"{event_name.strip()}.csv")
                        df_results.to_csv(save_path, index=False)
                        st.success(f"Saved event to archive as {event_name.strip()}.csv!")
                        st.rerun()

            if df_audit is not None and not df_audit.empty:
                st.markdown("---")
                st.subheader("🔍 Single-Team Match Audit")
                team_list = df_results["Team"].tolist()
                sel_team = st.selectbox("Inspect Match Log for Team:", team_list)
                team_matches = df_audit[df_audit["Team"] == sel_team].reset_index(drop=True)
                st.dataframe(team_matches[["Match", "Alliance", "Partner", "Opponents", "Score", "Result", "Match_Leverage"]], use_container_width=True)
    else:
        st.info("👈 Upload your Tournament Manager files or choose a preloaded tournament from the sidebar.")

# ==========================================
# MODE 2: TOP 25 COMMUNITY VOTING & CONSENSUS
# ==========================================
elif app_mode == "Top 25 Poll & Community Rankings":
    st.subheader("🏆 V5RC Community Top 25 Power Rankings Portal")
    st.write("Submit official ballots using aggregated tournament resumes, or inspect community consensus standings.")

    tab_ballot, tab_consensus, tab_dossier = st.tabs(["🗳️ Submit Top 25 Ballot", "📊 Consensus Power Rankings", "📁 Team Dossiers"])
    df_global = load_all_archived_teams()
    known_teams = sorted(df_global["Team"].unique().tolist()) if not df_global.empty else []

    with tab_ballot:
        st.markdown("### Official Top 25 Ballot")
        voter_name = st.text_input("Voter Name / Handle:", placeholder="e.g., BuckeyeScout / Coach Smith")
        affiliation = st.text_input("Voter Affiliation / Region (Optional):", placeholder="e.g., Ohio / Team 2011")
        st.caption("Select your ranked 1 to 25 teams. Each choice must be a unique team.")

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
            st.error(f"❌ Duplicate teams selected: {', '.join(duplicates)}. Each rank must be unique.")
        elif len(picked_teams) < 25:
            st.warning(f"⚠️ Ballot incomplete: {len(picked_teams)} of 25 teams selected.")

        if st.button("Submit Top 25 Ballot", disabled=submit_disabled):
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

            st.success("🎉 Ballot submitted and factored into consensus rankings!")
            st.rerun()

    with tab_consensus:
        st.markdown("### Community Consensus Top 25 Leaderboard")
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

            with st.expander("👁️ View All Submitted Ballots"):
                st.dataframe(df_ballots, use_container_width=True)
        else:
            st.info("No ballots submitted yet. Be the first to submit a ballot in the 'Submit Top 25 Ballot' tab!")

    with tab_dossier:
        st.markdown("### Season Team Dossiers & Performance History")
        if not df_global.empty:
            inspect_team = st.selectbox("Select Team to Inspect:", known_teams)
            team_records = df_global[df_global["Team"] == inspect_team]

            t_c1, t_c2, t_c3, t_c4 = st.columns(4)
            t_c1.metric("Events Attended", len(team_records))
            t_c2.metric("Best Finish", f"#{int(team_records['Actual_Rank'].min())}")
            t_c3.metric("Avg Finish", f"#{team_records['Actual_Rank'].mean():.1f}")
            if "Carry_Factor" in team_records.columns:
                t_c4.metric("Mean Carry Factor", f"{team_records['Carry_Factor'].mean():.1f}")

            display_cols = [c for c in ["Tournament", "Actual_Rank", "WP", "AP", "SP", "Carry_Factor", "SOS_Rank", "Lucky_Factor"] if c in team_records.columns]
            st.dataframe(team_records[display_cols].reset_index(drop=True), use_container_width=True)
        else:
            st.info("No tournament archives found. Save an analyzed tournament in Mode 1 to build season team profiles.")

# ==========================================
# MODE 3: FUTURE TOURNAMENT SANDBOX
# ==========================================
elif app_mode == "Future Tournament Sandbox":
    st.subheader("Upcoming Event Predictions, Validation & Mock Alliance Selection")
    st.write("Input projected tournament stats below. The integrity engine verifies mathematical tournament legality before generating brackets.")

    col_up1, col_up2, col_up3 = st.columns([2, 1, 1])
    with col_up1:
        uploaded_teams = st.file_uploader("Upload Registered Teams List (.csv or .xlsx)", type=["csv", "xlsx", "xls"])
    with col_up2:
        st.write("")
        st.write("")
        use_template = st.button("Load Sample 16-Team Roster")
    with col_up3:
        target_matches = st.number_input("Scheduled Matches / Team:", min_value=2, max_value=12, value=6, step=1)

    if uploaded_teams is not None:
        df_raw_teams = parse_file(uploaded_teams)
        df_raw_teams.columns = [str(c).strip() for c in df_raw_teams.columns]
        team_col = next((c for c in df_raw_teams.columns if "team" in c.lower() and "name" not in c.lower()), df_raw_teams.columns[0])
        name_col = next((c for c in df_raw_teams.columns if "name" in c.lower()), None)

        base_teams = []
        for _, row in df_raw_teams.iterrows():
            t_num = str(row[team_col]).strip()
            t_name = str(row[name_col]).strip() if name_col else f"Team {t_num}"
            if t_num and t_num.lower() != "nan":
                base_teams.append({
                    "Team": t_num, "Name": t_name,
                    "Wins": int(row.get("Wins", target_matches // 2)),
                    "Losses": int(row.get("Losses", target_matches // 2)),
                    "Ties": int(row.get("Ties", 0)),
                    "AWP": int(row.get("AWP", 0)),
                    "AP": int(row.get("AP", 24)),
                    "SP": int(row.get("SP", 120))
                })
        initial_df = pd.DataFrame(base_teams)
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

    st.markdown("### Step 1: Input / Edit Projected Stats")
    edited_df = st.data_editor(
        initial_df,
        num_rows="dynamic",
        use_container_width=True,
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

    validation_errors = []
    validation_warnings = []

    if tot_wins != tot_losses:
        validation_errors.append(f"❌ **Wins/Losses Imbalance:** Total Wins ({tot_wins}) does not equal Total Losses ({tot_losses}).")
    if tot_wins % 2 != 0:
        validation_errors.append(f"❌ **Odd Win Count:** Total Wins ({tot_wins}) must be an even number.")
    if tot_losses % 2 != 0:
        validation_errors.append(f"❌ **Odd Loss Count:** Total Losses ({tot_losses}) must be an even number.")
    if tot_ties % 4 != 0:
        validation_warnings.append(f"⚠️ **Ties Non-Divisible by 4:** Total Ties across the field is {tot_ties} (since each tie awards 4 team ties).")
    if tot_ap % ap_unit != 0:
        validation_errors.append(f"❌ **Overall AP Rule Violation:** Total field AP ({tot_ap}) must be a multiple of ({target_matches} matches × 6 = {ap_unit}).")

    st.markdown("#### Tournament Legality Status")
    v_col1, v_col2, v_col3, v_col4 = st.columns(4)
    v_col1.metric("Total Field Wins", tot_wins, f"{'Balanced' if tot_wins == tot_losses else f'Diff: {tot_wins - tot_losses}'}")
    v_col2.metric("Total Field Losses", tot_losses, f"{'Even' if tot_losses % 2 == 0 else 'Odd (Invalid)'}")
    v_col3.metric("Total Field Ties", tot_ties, f"{'Multiple of 4' if tot_ties % 4 == 0 else 'Non-Multiple'}")
    v_col4.metric("Total Field AP", tot_ap, f"{'Valid' if tot_ap % ap_unit == 0 else 'Invalid Multiple'}")

    if not validation_errors and not validation_warnings:
        st.success("✅ **Tournament Math Verified:** All parity, evenness, and AP multiples constraints pass.")
    else:
        for err in validation_errors:
            st.error(err)
        for warn in validation_warnings:
            st.warning(warn)

    pred_data["WP"] = (pred_data["Wins"] * 2) + pred_data["Ties"] + pred_data["AWP"]
    pred_standings = pred_data.sort_values(by=["WP", "AP", "SP"], ascending=[False, False, False]).reset_index(drop=True)
    pred_standings.index = pred_standings.index + 1
    pred_standings.index.name = "Predicted_Rank"
    pred_standings = pred_standings.reset_index()

    st.markdown("### Step 2: Predicted Official Leaderboard")
    st.dataframe(pred_standings[["Predicted_Rank", "Team", "Name", "Wins", "Losses", "Ties", "WP", "AP", "SP"]], use_container_width=True)

    st.markdown("---")
    st.markdown("### Step 3: Interactive Alliance Selection Draft Room")
    all_teams_list = pred_standings["Team"].tolist()
    available_pool = all_teams_list.copy()

    col_d1, col_d2 = st.columns([1, 2])
    with col_d1:
        max_possible = 16 if len(all_teams_list) >= 32 else (8 if len(all_teams_list) >= 16 else max(2, len(all_teams_list) // 2))
        num_alliances = st.selectbox("Number of Alliances:", [8, 16] if len(all_teams_list) >= 32 else ([8] if len(all_teams_list) >= 16 else [max_possible]), index=0)
        auto_draft = st.checkbox("Auto-Draft highest remaining seeds", value=False)

    alliances = []
    for a_num in range(1, num_alliances + 1):
        if not available_pool:
            break
        captain = available_pool.pop(0)
        if auto_draft:
            partner = available_pool.pop(0) if available_pool else "(None)"
        else:
            partner_options = ["Select Partner..."] + available_pool
            partner_pick = st.selectbox(f"Alliance #{a_num} Captain: {captain}", partner_options, key=f"draft_{a_num}")
            if partner_pick != "Select Partner..." and partner_pick in available_pool:
                available_pool.remove(partner_pick)
                partner = partner_pick
            else:
                partner = "(Undrafted)"

        alliances.append({"Alliance": a_num, "Captain": captain, "Partner": partner})

    df_alliances = pd.DataFrame(alliances)
    st.markdown("#### Drafted Elimination Alliances")
    st.dataframe(df_alliances, use_container_width=True)

    st.markdown("#### Projected Playoff Bracket Matchups")
    bracket_pairs = []
    half = num_alliances // 2
    for i in range(half):
        seed_top = i + 1
        seed_bot = num_alliances - i
        top_row = df_alliances[df_alliances["Alliance"] == seed_top].iloc[0]
        bot_row = df_alliances[df_alliances["Alliance"] == seed_bot].iloc[0]
        bracket_pairs.append({
            "Match": f"Quarterfinal {i+1}" if num_alliances == 8 else f"Round of 16 Match {i+1}",
            "High Seed": f"Alliance {seed_top} ({top_row['Captain']} & {top_row['Partner']})",
            "vs": "VS",
            "Low Seed": f"Alliance {seed_bot} ({bot_row['Captain']} & bot_row['Partner'])"
        })
    st.dataframe(pd.DataFrame(bracket_pairs), use_container_width=True)

    csv_alliances = df_alliances.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Export Drafted Alliances CSV", data=csv_alliances, file_name="drafted_alliances.csv", mime="text/csv")