"""NHL team brand colors for card theming."""

from .leagues import PWHL_TEAM_COLORS

TEAM_COLORS: dict[str, dict[str, str]] = {
    "ANA": {"primary": "#111111", "accent": "#FC4C02", "light": "#F5F5F5"},
    "ARI": {"primary": "#8C2633", "accent": "#E2D6B5", "light": "#F8F4EC"},
    "BOS": {"primary": "#111111", "accent": "#FFB81C", "light": "#FFF8E6"},
    "BUF": {"primary": "#002654", "accent": "#FCB514", "light": "#E8EEF8"},
    "CAR": {"primary": "#010101", "accent": "#CC0000", "light": "#F5E8E8"},
    "CBJ": {"primary": "#002654", "accent": "#CE1126", "light": "#E8EEF8"},
    "CGY": {"primary": "#111111", "accent": "#D2001C", "light": "#F5E8EA"},
    "CHI": {"primary": "#CF0A2C", "accent": "#111111", "light": "#F5E8EB"},
    "COL": {"primary": "#6F263D", "accent": "#236192", "light": "#EEE8EC"},
    "DAL": {"primary": "#006847", "accent": "#8F8F8C", "light": "#E8F2EE"},
    "DET": {"primary": "#CE1126", "accent": "#111111", "light": "#F5E8EB"},
    "EDM": {"primary": "#041E42", "accent": "#FF4C00", "light": "#E8EDF5"},
    "FLA": {"primary": "#041E42", "accent": "#C8102E", "light": "#E8EDF5"},
    "LAK": {"primary": "#111111", "accent": "#A2AAAD", "light": "#F0F1F2"},
    "MIN": {"primary": "#154734", "accent": "#DDCBA4", "light": "#E8F0ED"},
    "MTL": {"primary": "#AF1E2D", "accent": "#192168", "light": "#F0E8EA"},
    "NJD": {"primary": "#CE1126", "accent": "#111111", "light": "#F5E8EB"},
    "NSH": {"primary": "#FFB81C", "accent": "#041E42", "light": "#FFF8E6"},
    "NYI": {"primary": "#00539B", "accent": "#F47D30", "light": "#E8F0FA"},
    "NYR": {"primary": "#0038A8", "accent": "#CE1126", "light": "#E8EEFA"},
    "OTT": {"primary": "#C52032", "accent": "#B9975B", "light": "#F5E8EB"},
    "PHI": {"primary": "#F74902", "accent": "#111111", "light": "#FFF0E8"},
    "PIT": {"primary": "#111111", "accent": "#FCB514", "light": "#FFF8E6"},
    "SEA": {"primary": "#001628", "accent": "#99D9D9", "light": "#E8EEF2"},
    "SJS": {"primary": "#006D75", "accent": "#EA7200", "light": "#E8F2F3"},
    "STL": {"primary": "#002F87", "accent": "#FCB514", "light": "#E8EEFA"},
    "TBL": {"primary": "#002868", "accent": "#111111", "light": "#E8EEFA"},
    "TOR": {"primary": "#00205B", "accent": "#FFFFFF", "light": "#E8EEFA"},
    "UTA": {"primary": "#010101", "accent": "#6CACE4", "light": "#EEF6FC"},
    "VAN": {"primary": "#00205B", "accent": "#00843D", "light": "#E8EEFA"},
    "VGK": {"primary": "#333F42", "accent": "#B4975A", "light": "#EEF0F1"},
    "WPG": {"primary": "#041E42", "accent": "#004C97", "light": "#E8EDF5"},
    "WSH": {"primary": "#041E42", "accent": "#C8102E", "light": "#E8EDF5"},
}

CHL_TEAM_COLORS: dict[str, dict[str, str]] = {
    "EVERETT SILVERTIPS": {"primary": "#043927", "accent": "#C5A059", "light": "#E8F2EE"},
    "EVERETT": {"primary": "#043927", "accent": "#C5A059", "light": "#E8F2EE"},
    "REGINA PATS": {"primary": "#00205B", "accent": "#CC0000", "light": "#E8EEFA"},
    "REGINA": {"primary": "#00205B", "accent": "#CC0000", "light": "#E8EEFA"},
    "LONDON KNIGHTS": {"primary": "#00482B", "accent": "#FFB81C", "light": "#E8F2EE"},
    "LONDON": {"primary": "#00482B", "accent": "#FFB81C", "light": "#E8F2EE"},
    "SAGINAW SPIRIT": {"primary": "#002B49", "accent": "#D11242", "light": "#E8EDF5"},
    "SAGINAW": {"primary": "#002B49", "accent": "#D11242", "light": "#E8EDF5"},
    "MEDICINE HAT TIGERS": {"primary": "#111111", "accent": "#FF6600", "light": "#F5F5F5"},
    "MEDICINE HAT": {"primary": "#111111", "accent": "#FF6600", "light": "#F5F5F5"},
    "PRINCE ALBERT RAIDERS": {"primary": "#004B33", "accent": "#C5A059", "light": "#E8F2EE"},
    "BRANDON WHEAT KINGS": {"primary": "#111111", "accent": "#FFB81C", "light": "#FFF8E6"},
    "MOOSE JAW WARRIORS": {"primary": "#CC0000", "accent": "#111111", "light": "#F5E8E8"},
    "SPOKANE CHIEFS": {"primary": "#CC0000", "accent": "#002B49", "light": "#F5E8E8"},
    "TRI-CITY AMERICANS": {"primary": "#002B49", "accent": "#CC0000", "light": "#E8EDF5"},
    "KELOWNA ROCKETS": {"primary": "#005A60", "accent": "#CC0000", "light": "#E8F2F3"},
    "KAMLOOPS BLAZERS": {"primary": "#002B49", "accent": "#FF4500", "light": "#E8EDF5"},
    "VANCOUVER GIANTS": {"primary": "#111111", "accent": "#C5A059", "light": "#F5F5F5"},
    "PRINCE GEORGE COUGARS": {"primary": "#CC0000", "accent": "#111111", "light": "#F5E8E8"},
    "VICTORIA ROYALS": {"primary": "#002B49", "accent": "#8F8F8C", "light": "#E8EDF5"},
    "EDMONTON OIL KINGS": {"primary": "#CC0000", "accent": "#FFB81C", "light": "#F5E8E8"},
    "CALGARY HITMEN": {"primary": "#CC0000", "accent": "#005A60", "light": "#F5E8E8"},
    "RED DEER REBELS": {"primary": "#111111", "accent": "#CC0000", "light": "#F5F5F5"},
    "SWIFT CURRENT BRONCOS": {"primary": "#002B49", "accent": "#008080", "light": "#E8EDF5"},
    "LETHBRIDGE HURRICANES": {"primary": "#CC0000", "accent": "#002B49", "light": "#F5E8E8"},
    "WENATCHEE WILD": {"primary": "#002B49", "accent": "#CC0000", "light": "#E8EDF5"},
    # NCAA / USHL clubs (undrafted prospect branding)
    "UNIV. OF MICHIGAN": {"primary": "#00274C", "accent": "#FFCB05", "light": "#E8EEF5"},
    "UNIVERSITY OF MICHIGAN": {"primary": "#00274C", "accent": "#FFCB05", "light": "#E8EEF5"},
    "MICHIGAN": {"primary": "#00274C", "accent": "#FFCB05", "light": "#E8EEF5"},
    "PENN STATE": {"primary": "#041E42", "accent": "#FFFFFF", "light": "#E8EDF5"},
    "PENN STATE NITTANY LIONS": {"primary": "#041E42", "accent": "#FFFFFF", "light": "#E8EDF5"},
}

DEFAULT = {"primary": "#0f172a", "accent": "#3b82f6", "light": "#f1f5f9"}


def get_team_colors(team: str, *, league: str | None = None) -> dict[str, str]:
    tri = team.upper().strip()
    if (league or "nhl").lower() == "pwhl":
        return PWHL_TEAM_COLORS.get(tri, DEFAULT)
    if tri in TEAM_COLORS:
        return TEAM_COLORS[tri]
    if tri in CHL_TEAM_COLORS:
        return CHL_TEAM_COLORS[tri]
    for k, v in CHL_TEAM_COLORS.items():
        if k in tri or tri in k:
            return v
    return DEFAULT
