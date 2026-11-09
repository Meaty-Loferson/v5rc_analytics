import os
import requests
import pandas as pd
import streamlit as st

class VexApiClient:
    def __init__(self, base_url: str = None, api_key: str = None):
        # Read from Streamlit secrets or fallback to env vars / localhost
        self.base_url = (base_url or st.secrets.get("VEX_API_BASE_URL", "http://localhost:3000/v1")).rstrip("/")
        self.api_key = api_key or st.secrets.get("VEX_API_KEY", "")
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def _get(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        res = self.session.get(url, params=params or {}, timeout=10)
        res.raise_for_status()
        return res.json()

    def get_event_teams(self, event_id: str | int) -> pd.DataFrame:
        """Fetches teams registered for an event into a clean DataFrame."""
        all_teams = []
        page = 1
        while True:
            payload = self._get(f"/events/{event_id}/teams", params={"page": page, "per_page": 50})
            data = payload.get("data", [])
            for t in data:
                all_teams.append({
                    "Team": t.get("number", ""),
                    "Name": t.get("team_name", ""),
                    "Organization": t.get("organization", ""),
                    "City": t.get("location", {}).get("city", "")
                })
            
            pagination = payload.get("pagination", {})
            if page >= pagination.get("total_pages", 1):
                break
            page += 1
        return pd.DataFrame(all_teams)

    def get_event_matches(self, event_id: str | int) -> pd.DataFrame:
        """
        Fetches event matches and normalizes directly to the 
        exact column schema required by analyze_tournament().
        """
        all_matches = []
        page = 1
        while True:
            payload = self._get(f"/events/{event_id}/matches", params={"page": page, "per_page": 50})
            data = payload.get("data", [])
            
            for m in data:
                # Filter for qualification round if flagged
                alliances = m.get("alliances", [])
                red = next((a for a in alliances if a.get("color", "").lower() == "red"), {})
                blue = next((a for a in alliances if a.get("color", "").lower() == "blue"), {})
                
                red_teams = [t.get("team", {}).get("name", t.get("number", "")) for t in red.get("teams", [])]
                blue_teams = [t.get("team", {}).get("name", t.get("number", "")) for t in blue.get("teams", [])]
                
                # Standard V5RC 2v2 alliance structure
                if len(red_teams) >= 2 and len(blue_teams) >= 2:
                    r_sc = float(red.get("score", 0.0))
                    b_sc = float(blue.get("score", 0.0))
                    winner = "Red" if r_sc > b_sc else ("Blue" if b_sc > r_sc else "Tie")
                    
                    all_matches.append({
                        "Match": m.get("name", f"Qualifier #{m.get('matchnum', '')}"),
                        "Red Team 1": red_teams[0],
                        "Red Team 2": red_teams[1],
                        "Blue Team 1": blue_teams[0],
                        "Blue Team 2": blue_teams[1],
                        "Red Score": r_sc,
                        "Blue Score": b_sc,
                        "Winner": winner
                    })

            pagination = payload.get("pagination", {})
            if page >= pagination.get("total_pages", 1):
                break
            page += 1

        return pd.DataFrame(all_matches)

    def get_event_rankings(self, event_id: str | int) -> pd.DataFrame:
        """Fetches official standings (resolving AP/AWP/DQ automatically)."""
        payload = self._get(f"/events/{event_id}/rankings")
        rows = []
        for r in payload.get("data", []):
            rows.append({
                "Actual_Rank": r.get("rank"),
                "Team": r.get("team", {}).get("name", r.get("team_number", "")),
                "WP": r.get("wp", 0),
                "AP": r.get("ap", 0),
                "SP": r.get("sp", 0),
                "Wins": r.get("wins", 0),
                "Losses": r.get("losses", 0),
                "Ties": r.get("ties", 0)
            })
        return pd.DataFrame(rows)