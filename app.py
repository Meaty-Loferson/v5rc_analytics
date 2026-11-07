import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="V5RC Tournament Intelligence & Sandbox", layout="wide")
st.title("🤖 V5RC Event Tracker & Tournament Intelligence Engine")

# ==========================================
# SIDEBAR: APP MODE SELECTION
# ==========================================
app_mode = st.sidebar.radio(
    "Select Operating Mode:",
    ["🔮 Future Tournament Sandbox", "📊 TM Event Analyzer (Past/Live)"]
)

def parse_file(file):
    if file.name.lower().endswith(".csv"):
        return pd.read_csv(file)
    if file.name.lower().endswith(".xlsx"):
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

# ==============================================================================
# MODE 1: FUTURE TOURNAMENT SANDBOX (PREDICTIONS, VALIDATION & ALLIANCE DRAFT)
# ==============================================================================
if app_mode == "🔮 Future Tournament Sandbox":
    st.subheader("🔮 Upcoming Event Predictions & Mock Alliance Selection")
    st.write("Input projected tournament stats below. The integrity engine verifies mathematical tournament legality before populating official tiebreakers and the elimination draft room.")

    col_up1, col_up2, col_up3 = st.columns([2, 1, 1])
    with col_up1:
        uploaded_teams = st.file_uploader(
            "Upload Registered Teams List (.csv or .xlsx)",
            type=["csv", "xlsx", "xls"],
            help="File must contain at least a 'Team' column (and optional 'Team Name' / 'Name')"
        )
    with col_up2:
        st.write("")
        st.write("")
        use_template = st.button("📋 Load Sample 16-Team Roster")
    with col_up3:
        target_matches = st.number_input(
            "Scheduled Matches / Team:",
            min_value=2,
            max_value=12,
            value=6,
            step=1,
            help="Standard V5RC regional qualifications usually schedule 6 matches per team."
        )

    # Initial dataframe setup
    if uploaded_teams is not None:
        df_raw_teams = parse_file(uploaded_teams)
        df_raw_teams.columns = [str(c).strip() for c in df_raw_teams.columns]
        team_col = next((c for c in df_raw_teams.columns if "team" in c.lower() and "name" not in c.lower()), df_raw_teams.columns[0])
        name_col = next((c for c in df_raw_teams.columns if "name" in c.lower()), None)
        
        base_teams = []
        for idx, row in df_raw_teams.iterrows():
            t_num = str(row[team_col]).strip()
            t_name = str(row[name_col]).strip() if name_col else f"Team {t_num}"
            if t_num and t_num.lower() != "nan":
                base_teams.append({
                    "Team": t_num,
                    "Name": t_name,
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

    st.markdown("### ✏️ Step 1: Input / Edit Projected Stats")
    st.caption("Double-click any cell to adjust values. The integrity tracker updates automatically as you type.")

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
            "AWP": st.column_config.NumberColumn("Auton Win Points (AWP)", min_value=0, max_value=target_matches, default=0),
            "AP": st.column_config.NumberColumn("Autonomous Pts (AP)", min_value=0, max_value=300, default=0, step=6),
            "SP": st.column_config.NumberColumn("Strength Pts (SP)", min_value=0, max_value=1000, default=0)
        }
    )

    # ==========================================
    # TOURNAMENT INTEGRITY & VALIDATION CHECKER
    # ==========================================
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
    ap_unit = target_matches * 6  # 36 for 6 matches

    validation_errors = []
    validation_warnings = []

    # 1. Parity Check: Wins must equal Losses
    if tot_wins != tot_losses:
        validation_errors.append(f"❌ **Wins/Losses Imbalance:** Total Wins ({tot_wins}) does not equal Total Losses ({tot_losses}). Net difference: {abs(tot_wins - tot_losses)}.")

    # 2. Evenness Check: Wins and Losses must each be an even number
    if tot_wins % 2 != 0:
        validation_errors.append(f"❌ **Odd Win Count:** Total Wins ({tot_wins}) must be an even number because 2 teams win per 2v2 match.")
    if tot_losses % 2 != 0:
        validation_errors.append(f"❌ **Odd Loss Count:** Total Losses ({tot_losses}) must be an even number because 2 teams lose per 2v2 match.")

    # 3. Ties Check: Ties must be a multiple of 4
    if tot_ties % 4 != 0:
        validation_warnings.append(f"⚠️ **Ties Non-Divisible by 4:** Total Ties across the field is {tot_ties}. Since each tie involves 4 robots, this typically must be a multiple of 4.")

    # 4. AP Divisibility Check (Overall)
    if tot_ap % ap_unit != 0:
        rem_ap = tot_ap % ap_unit
        validation_errors.append(f"❌ **Overall AP Rule Violation:** Total field AP ({tot_ap}) must be a multiple of ({target_matches} matches × 6) = **{ap_unit}**. Off by {rem_ap} AP.")

    # 5. Individual Team Integrity Checks
    bad_ap_teams = []
    bad_match_teams = []
    bad_awp_teams = []

    for _, row in pred_data.iterrows():
        t = str(row["Team"])
        played = row["Wins"] + row["Losses"] + row["Ties"]
        if played != target_matches:
            bad_match_teams.append(f"{t} ({played}/{target_matches})")
        if row["AP"] % 6 != 0:
            bad_ap_teams.append(f"{t} ({row['AP']} AP)")
        if row["AWP"] > target_matches:
            bad_awp_teams.append(f"{t} ({row['AWP']} AWP)")

    if bad_match_teams:
        validation_warnings.append(f"⚠️ **Match Count Discrepancies:** Teams with match totals $\\ne$ {target_matches}: {', '.join(bad_match_teams[:8])}{'...' if len(bad_match_teams) > 8 else ''}.")

    if bad_ap_teams:
        validation_errors.append(f"❌ **Non-Multiple of 6 AP:** Each team's AP must be divisible by 6. Flagged teams: {', '.join(bad_ap_teams[:8])}{'...' if len(bad_ap_teams) > 8 else ''}.")

    if bad_awp_teams:
        validation_errors.append(f"❌ **AWP Exceeds Match Ceiling:** Autonomous Win Points cannot exceed matches played ({target_matches}). Flagged: {', '.join(bad_awp_teams)}.")

    # Render Validation Status Box
    st.markdown("#### 🛡️ Tournament Legality & Integrity Status")
    v_col1, v_col2, v_col3, v_col4 = st.columns(4)
    v_col1.metric("Total Field Wins", tot_wins, f"{'Balanced' if tot_wins == tot_losses else f'Diff: {tot_wins - tot_losses}'}")
    v_col2.metric("Total Field Losses", tot_losses, f"{'Even' if tot_losses % 2 == 0 else 'Odd (Invalid)'}")
    v_col3.metric("Total Field Ties", tot_ties, f"{'Multiple of 4' if tot_ties % 4 == 0 else 'Non-Multiple'}")
    v_col4.metric("Total Field AP", tot_ap, f"{'Valid (Multiple of ' + str(ap_unit) + ')' if tot_ap % ap_unit == 0 else 'Invalid AP Sum'}")

    if not validation_errors and not validation_warnings:
        st.success("✅ **Tournament Math Verified:** All Win/Loss parity, evenness constraints, match limits, and Autonomous Points (AP) multiples pass official V5RC tournament criteria.")
    else:
        for err in validation_errors:
            st.error(err)
        for warn in validation_warnings:
            st.warning(warn)

    # Dynamic WP & Official Ranking Calculation
    pred_data["WP"] = (pred_data["Wins"] * 2) + pred_data["Ties"] + pred_data["AWP"]
    pred_standings = pred_data.sort_values(by=["WP", "AP", "SP"], ascending=[False, False, False]).reset_index(drop=True)
    pred_standings.index = pred_standings.index + 1
    pred_standings.index.name = "Predicted_Rank"
    pred_standings = pred_standings.reset_index()

    st.markdown("### 🏆 Step 2: Official Predicted Leaderboard")
    st.dataframe(
        pred_standings[["Predicted_Rank", "Team", "Name", "Wins", "Losses", "Ties", "WP", "AP", "SP"]],
        use_container_width=True
    )

    st.markdown("---")
    # ==========================================
    # ALLIANCE SELECTION DRAFT ROOM
    # ==========================================
    st.markdown("### 🤝 Step 3: Interactive Alliance Selection Draft Room")
    
    total_avail = len(pred_standings)
    max_alliances = 16 if total_avail >= 32 else (8 if total_avail >= 16 else max(2, total_avail // 2))
    
    col_d1, col_d2 = st.columns([1, 2])
    with col_d1:
        num_alliances = st.selectbox(
            "Number of Elimination Alliances:",
            [8, 16] if total_avail >= 32 else ([8] if total_avail >= 16 else [max_alliances]),
            index=0
        )
        auto_draft = st.checkbox("Auto-Draft highest available seeds", value=False)

    all_teams_list = pred_standings["Team"].tolist()
    available_pool = all_teams_list.copy()

    alliances = []
    
    for a_num in range(1, num_alliances + 1):
        if not available_pool:
            break
        captain = available_pool.pop(0)
        
        if auto_draft:
            partner = available_pool.pop(0) if available_pool else "No Partner Available"
        else:
            partner_options = ["Select Partner..."] + available_pool
            st.markdown(f"#### Alliance #{a_num} Captain: **{captain}**")
            partner_pick = st.selectbox(
                f"Choose partner for Alliance #{a_num} ({captain}):",
                partner_options,
                key=f"alliance_pick_{a_num}"
            )
            if partner_pick != "Select Partner..." and partner_pick in available_pool:
                available_pool.remove(partner_pick)
                partner = partner_pick
            else:
                partner = "(Undrafted)"

        alliances.append({
            "Alliance_Number": a_num,
            "Captain": captain,
            "Partner": partner
        })

    df_alliances = pd.DataFrame(alliances)

    st.markdown("#### 🎯 Elimination Alliances Board")
    st.dataframe(df_alliances, use_container_width=True)

    # Elimination Matchup Pairing
    st.markdown("#### ⚔️ Projected Playoff Bracket Matchups")
    bracket_pairs = []
    half = num_alliances // 2
    for i in range(half):
        seed_top = i + 1
        seed_bot = num_alliances - i
        top_row = df_alliances[df_alliances["Alliance_Number"] == seed_top].iloc[0]
        bot_row = df_alliances[df_alliances["Alliance_Number"] == seed_bot].iloc[0]
        bracket_pairs.append({
            "Match": f"Quarterfinal {i+1}" if num_alliances == 8 else f"Round of 16 - Match {i+1}",
            "High Seed": f"Alliance {seed_top} ({top_row['Captain']} & {top_row['Partner']})",
            "vs": "VS",
            "Low Seed": f"Alliance {seed_bot} ({bot_row['Captain']} & bot_row['Partner'])"
        })
    
    st.dataframe(pd.DataFrame(bracket_pairs), use_container_width=True)

    csv_alliances = df_alliances.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Export Drafted Alliances CSV", data=csv_alliances, file_name="drafted_alliances.csv", mime="text/csv")


# ==============================================================================
# MODE 2: LIVE / PAST TOURNAMENT MANAGER ANALYZER
# ==============================================================================
elif app_mode == "📊 TM Event Analyzer (Past/Live)":
    st.sidebar.header("1. Match Results (Required)")
    uploaded_matches = st.sidebar.file_uploader(
        "Upload TM Match Results (.xlsx, .xls, .csv)", 
        type=["xlsx", "xls", "csv"],
        help="Exported from TM via File -> Export -> Match Results"
    )

    st.sidebar.header("2. Official Rankings (Optional)")
    uploaded_rankings = st.sidebar.file_uploader(
        "Upload TM Rankings (.xlsx, .xls, .csv)", 
        type=["xlsx", "xls", "csv"],
        help="Exported from TM via File -> Export -> Rankings"
    )

    st.sidebar.header("3. Manual Match Overrides")
    manual_overrides = st.sidebar.text_area(
        "Overrides (one per line, optional)",
        placeholder="e.g.\nTie: Qualifier #58\nWinner: Qualifier #12, Blue\nDQ: Qualifier #65, Red",
        help="Forces outcomes if you do not have an official rankings file."
    )

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

        qual_df = df_matches[df_matches[match_col].astype(str).str.startswith("Qualifier")].copy()
        qual_df[r_score_col] = pd.to_numeric(qual_df[r_score_col], errors="coerce").fillna(0.0)
        qual_df[b_score_col] = pd.to_numeric(qual_df[b_score_col], errors="coerce").fillna(0.0)

        overrides = parse_manual_overrides(overrides_text)

        raw_teams = set()
        for col in [r1_col, r2_col, b1_col, b2_col]:
            raw_teams.update(qual_df[col].dropna().astype(str).str.strip().unique())
        all_teams = sorted([t for t in raw_teams if t and t.lower() != "nan" and not t.isdigit()])

        df_ranks = None
        if df_rankings_file is not None:
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

            if r1 in rank_map and r2 in rank_map and b1 in rank_map and b2 in rank_map:
                for t, p in [(r1, r2), (r2, r1)]:
                    teammates[t].append(rank_map[p])
                    opponents[t].extend([rank_map[b1], rank_map[b2]])
                    r_all = (rank_map[t] + rank_map[p]) / 2.0
                    r_opp = (rank_map[b1] + rank_map[b2]) / 2.0
                    delta_r = r_all - r_opp
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

            if b1 in rank_map and b2 in rank_map and r1 in rank_map and r2 in rank_map:
                for t, p in [(b1, b2), (b2, b1)]:
                    teammates[t].append(rank_map[p])
                    opponents[t].extend([rank_map[r1], rank_map[r2]])
                    r_all = (rank_map[t] + rank_map[p]) / 2.0
                    r_opp = (rank_map[r1] + rank_map[r2]) / 2.0
                    delta_r = r_all - r_opp
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

    if uploaded_matches is not None:
        with st.spinner("Processing Tournament Data..."):
            df_m = parse_file(uploaded_matches)
            df_r = parse_file(uploaded_rankings) if uploaded_rankings is not None else None
            df_results, df_audit = analyze_tournament(df_m, df_r, manual_overrides)

        if df_results is not None:
            st.success(f"Processed {len(df_results)} teams successfully.")
            
            c1, c2, c3 = st.columns(3)
            top_carry = df_results.sort_values("Carry_Factor", ascending=False).iloc[0]
            luckiest = df_results.sort_values("Lucky_Factor", ascending=False).iloc[0]
            hardest_sos = df_results.sort_values("SOS_Rank").iloc[0]
            
            c1.metric("Highest Carry Factor", f"{top_carry['Team']} ({top_carry['Carry_Factor']})")
            c2.metric("Luckiest Schedule Draw", f"{luckiest['Team']} ({luckiest['Lucky_Factor']})")
            c3.metric("Hardest Schedule (#1 SOS)", f"{hardest_sos['Team']}")

            st.subheader("Tournament Advanced Metrics Board")
            st.dataframe(df_results, use_container_width=True)

            csv_data = df_results.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Export Clean CSV", data=csv_data, file_name="tournament_analytics.csv", mime="text/csv")
    else:
        st.info("👈 Upload your Tournament Manager Match Results file in the sidebar to begin.")