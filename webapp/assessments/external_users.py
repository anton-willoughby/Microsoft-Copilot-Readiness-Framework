"""External user access assessment — port of Get-CRExternalUserAccess.ps1"""
import re
from datetime import datetime, timezone
from services.graph_client import graph_get_paged, graph_get, get_sites_list
import config

RISK_RANK = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
PERM_RANK = {"Limited Access": 1, "Read": 2, "Edit": 3, "Design": 4, "Full Control": 5}
CONSUMER_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com"}


def _readiness_rating(score: float) -> str:
    if score >= 80:
        return "Ready"
    if score >= 60:
        return "Nearly Ready"
    if score >= 40:
        return "Requires Work"
    return "Not Ready"


def run(token: str, log) -> dict:
    log("Retrieving guest users from Microsoft Graph...")
    external_users = graph_get_paged(
        token,
        f"{config.GRAPH_BETA}/users?$filter=userType%20eq%20%27Guest%27"
        "&$select=id,displayName,mail,userPrincipalName,createdDateTime,signInActivity,userType&$top=200",
    )
    log(f"Found {len(external_users)} guest users.")

    now = datetime.now(tz=timezone.utc)
    summary_by_id: dict[str, dict] = {}
    email_to_id: dict[str, str] = {}

    for user in external_users:
        email = user.get("mail") or user.get("userPrincipalName", "")
        domain = email.split("@")[-1].lower() if "@" in email else ""
        sign_in = user.get("signInActivity") or {}
        last_dt = sign_in.get("lastSuccessfulSignInDateTime") or sign_in.get("lastSignInDateTime")
        if last_dt:
            try:
                last_ts = datetime.fromisoformat(last_dt.replace("Z", "+00:00"))
                days_inactive = (now - last_ts).days
            except ValueError:
                days_inactive = 999
        else:
            days_inactive = 999

        entry = {
            "Id": user["id"],
            "Email": email,
            "DisplayName": user.get("displayName", ""),
            "LoginName": user.get("userPrincipalName", ""),
            "HighestPermission": "Limited Access",
            "HighestRiskLevel": "Low",
            "TotalSites": 0,
            "DaysSinceLastActivity": days_inactive,
            "SitesAccessed": set(),
            "Domain": domain,
        }
        summary_by_id[user["id"]] = entry
        if email:
            email_to_id[email.lower()] = user["id"]
        upn = user.get("userPrincipalName", "")
        if upn:
            email_to_id[upn.lower()] = user["id"]

    external_user_access = []
    log("Retrieving SharePoint sites via Microsoft Search API...")
    sites = get_sites_list(token)
    log(f"Found {len(sites)} sites to evaluate for guest access.")

    def _resolve_summary_key(grantee: dict) -> str | None:
        g_user = grantee.get("user") or {}
        g_site_user = grantee.get("siteUser") or {}
        principal = g_user or g_site_user
        gid = principal.get("id", "")
        gmail = principal.get("email", "")
        if gid and gid in summary_by_id:
            return gid
        if gmail and gmail.lower() in email_to_id:
            return email_to_id[gmail.lower()]
        return None

    def _risk_for_roles(roles_str: str) -> tuple[str, str, str]:
        """Return (risk_level, perm_label, risk_factor_note)"""
        if re.search(r"owner|fullcontrol", roles_str, re.IGNORECASE):
            return "Critical", "Full Control", "Full control style role"
        if re.search(r"write|edit|manage", roles_str, re.IGNORECASE):
            return "High", "Edit", "Edit or write role"
        return "Low", "Read", ""

    def _process_permission(permission: dict, site: dict, scan_label: str):
        roles_list = permission.get("roles") or []
        roles_str = "; ".join(roles_list) if roles_list else "Read"
        grantee_set = []
        gv2 = permission.get("grantedToV2")
        if gv2:
            grantee_set.append(gv2)
        giv2 = permission.get("grantedToIdentitiesV2") or []
        grantee_set.extend(giv2)

        for grantee in grantee_set:
            key = _resolve_summary_key(grantee)
            if not key:
                continue
            entry = summary_by_id[key]
            risk_level, highest_perm, role_note = _risk_for_roles(roles_str)
            risk_factors = [scan_label]
            if role_note:
                risk_factors.append(role_note)
            if entry["DaysSinceLastActivity"] > 90:
                risk_factors.append(f"No sign-in in {entry['DaysSinceLastActivity']} days")
                if RISK_RANK[risk_level] < RISK_RANK["Medium"]:
                    risk_level = "Medium"
            if entry["Domain"] in CONSUMER_DOMAINS:
                risk_factors.append("Consumer email domain")
                if RISK_RANK[risk_level] < RISK_RANK["Medium"]:
                    risk_level = "Medium"

            record = {
                "ExternalUserEmail": entry["Email"],
                "DisplayName": entry["DisplayName"],
                "LoginName": entry["LoginName"],
                "SiteUrl": site.get("webUrl", ""),
                "SiteTitle": site.get("displayName", ""),
                "Permissions": roles_str,
                "RiskLevel": risk_level,
                "RiskFactors": "; ".join(risk_factors),
                "EmailDomain": entry["Domain"],
                "DaysSinceLastActivity": entry["DaysSinceLastActivity"],
            }
            external_user_access.append(record)
            entry["SitesAccessed"].add(site.get("webUrl", ""))
            entry["TotalSites"] = len(entry["SitesAccessed"])
            if PERM_RANK.get(highest_perm, 0) > PERM_RANK.get(entry["HighestPermission"], 0):
                entry["HighestPermission"] = highest_perm
            if RISK_RANK.get(risk_level, 0) > RISK_RANK.get(entry["HighestRiskLevel"], 0):
                entry["HighestRiskLevel"] = risk_level

    for site in sites:
        site_id = site.get("id", "")
        if not site_id:
            continue
        try:
            drives = graph_get_paged(
                token,
                f"{config.GRAPH_BASE}/sites/{site_id}/drives?$top=200",
            )
        except Exception as exc:
            log(f"[Warning] Skipping drives for {site.get('webUrl')}. {exc}")
            continue

        for drive in drives:
            try:
                root_perms = graph_get_paged(
                    token,
                    f"{config.GRAPH_BASE}/drives/{drive['id']}/root/permissions?$top=200",
                )
            except Exception as exc:
                log(f"[Warning] Skipping root permissions for drive in {site.get('webUrl')}. {exc}")
                continue
            for perm in root_perms:
                _process_permission(perm, site, "Drive root permission (least-privilege scan)")

    # Build per-user summaries
    user_summaries = []
    for entry in summary_by_id.values():
        if entry["TotalSites"] == 0:
            continue
        user_summaries.append({
            "ExternalUserEmail": entry["Email"],
            "DisplayName": entry["DisplayName"],
            "Domain": entry["Domain"],
            "TotalSites": entry["TotalSites"],
            "HighestPermission": entry["HighestPermission"],
            "HighestRiskLevel": entry["HighestRiskLevel"],
            "DaysSinceLastActivity": entry["DaysSinceLastActivity"],
        })

    total_guests = len(external_users)
    critical = sum(1 for r in external_user_access if r["RiskLevel"] == "Critical")
    high = sum(1 for r in external_user_access if r["RiskLevel"] == "High")
    medium = sum(1 for r in external_user_access if r["RiskLevel"] == "Medium")

    readiness_score = max(0, 100 - critical * 20 - high * 10 - medium * 5)
    rating = _readiness_rating(readiness_score)

    summary = {
        "AssessmentDate": datetime.now().isoformat(),
        "TotalGuestUsers": total_guests,
        "GuestsWithSiteAccess": len(user_summaries),
        "CriticalRisk": critical,
        "HighRisk": high,
        "MediumRisk": medium,
        "ReadinessRating": rating,
    }

    log(f"External user access assessment complete. Guests={total_guests}, Critical={critical}")

    return {
        "Name": "ExternalUserAccess",
        "Summary": summary,
        "Findings": external_user_access,
        "HighRiskAccess": [r for r in external_user_access if r["RiskLevel"] in ("Critical", "High")],
        "UserSummaries": user_summaries,
        "ReadinessScore": readiness_score,
        "ReadinessRating": rating,
    }
