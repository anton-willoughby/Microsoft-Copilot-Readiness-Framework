"""Microsoft Defender security posture assessment.

Checks Defender for Endpoint / Microsoft 365 Defender exposure signals
that are material to Copilot readiness:
  - Secure Score (overall and identity/device categories)
  - Risky users detected by Identity Protection
  - MFA registration coverage (via Graph)
  - OAuth app risk (apps with broad permissions)

All calls use the Microsoft Graph API where possible so that the existing
delegated token works without additional service principals.
"""
from datetime import datetime
from services.graph_client import graph_get, graph_get_paged


# Secure Score thresholds (percentage of max score)
SCORE_READY = 70
SCORE_NEARLY_READY = 50
SCORE_REQUIRES_WORK = 30


def _rating(score_pct: float, risky_users: int, oauth_risks: int) -> str:
    """Derive an overall readiness rating from Defender signals."""
    if score_pct >= SCORE_READY and risky_users == 0 and oauth_risks == 0:
        return "Ready"
    if score_pct >= SCORE_NEARLY_READY and risky_users <= 5:
        return "Nearly Ready"
    if score_pct >= SCORE_REQUIRES_WORK:
        return "Requires Work"
    return "Not Ready"


def _get_secure_score(token: str, log) -> dict:
    """Fetch the most recent Secure Score snapshot."""
    try:
        data = graph_get(
            token,
            "https://graph.microsoft.com/v1.0/security/secureScores?$top=1",
        )
        scores = data.get("value", [])
        if not scores:
            log("[Warning] Secure Score data not available (may require Defender licence).")
            return {}
        latest = scores[0]
        current = latest.get("currentScore", 0)
        max_score = latest.get("maxScore", 1)
        pct = round((current / max_score) * 100, 1) if max_score else 0

        # Pull category sub-scores (Identity, Device, Apps, Data, Infrastructure)
        categories = {}
        for cat in (latest.get("controlScores") or []):
            cname = cat.get("controlCategory", "")
            if cname and cname not in categories:
                categories[cname] = categories.get(cname, 0) + cat.get("score", 0)

        return {
            "CurrentScore": current,
            "MaxScore": max_score,
            "Percentage": pct,
            "Categories": categories,
            "CreatedDateTime": latest.get("createdDateTime", ""),
        }
    except Exception as exc:
        log(f"[Warning] Could not fetch Secure Score: {exc}")
        return {}


def _get_risky_users(token: str, log) -> list:
    """Fetch users flagged as 'high' or 'medium' risk by Identity Protection."""
    try:
        users = graph_get_paged(
            token,
            "https://graph.microsoft.com/v1.0/identityProtection/riskyUsers"
            "?$filter=riskLevel eq 'high' or riskLevel eq 'medium'"
            "&$select=userDisplayName,userPrincipalName,riskLevel,riskState,riskDetail,riskLastUpdatedDateTime"
            "&$top=100",
        )
        return [
            {
                "DisplayName": u.get("userDisplayName", ""),
                "UPN": u.get("userPrincipalName", ""),
                "RiskLevel": u.get("riskLevel", ""),
                "RiskState": u.get("riskState", ""),
                "RiskDetail": u.get("riskDetail", ""),
                "LastUpdated": u.get("riskLastUpdatedDateTime", ""),
            }
            for u in users
        ]
    except Exception as exc:
        log(f"[Warning] Could not fetch risky users (requires Identity Protection P2): {exc}")
        return []


def _get_mfa_coverage(token: str, log) -> dict:
    """
    Approximate MFA coverage using authenticationMethods registration report.
    Requires Reports.Read.All or equivalent.
    """
    try:
        data = graph_get(
            token,
            "https://graph.microsoft.com/v1.0/reports/authenticationMethods/usersRegisteredByFeature",
        )
        # Response is a userRegistrationFeatureSummary
        registered = {
            f.get("feature"): {
                "Registered": f.get("userCount", 0),
                "Enabled": f.get("userCount", 0),
            }
            for f in (data.get("userRegistrationFeatureSummary") or [])
        }

        total_users = data.get("totalUserCount", 0)
        mfa_registered = next(
            (v["Registered"] for k, v in registered.items() if "mfa" in k.lower()),
            0,
        )
        pct = round((mfa_registered / total_users) * 100, 1) if total_users else 0

        return {
            "TotalUsers": total_users,
            "MFARegistered": mfa_registered,
            "MFACoveragePercent": pct,
            "ByFeature": registered,
        }
    except Exception as exc:
        log(f"[Warning] Could not fetch MFA registration data (requires Reports.Read.All): {exc}")
        return {}


def _get_oauth_app_risks(token: str, log) -> list:
    """
    Identify OAuth service principals with overly broad Graph API permissions
    (application-level permissions that include Mail, Files, or all-user scopes).
    """
    HIGH_RISK_PERMS = {
        "Mail.ReadWrite", "Mail.Send", "Files.ReadWrite.All",
        "Sites.FullControl.All", "User.ReadWrite.All",
        "RoleManagement.ReadWrite.Directory", "Directory.ReadWrite.All",
    }
    risky_apps = []
    try:
        # Fetch service principals (OAuth apps registered/consented in tenant)
        sps = graph_get_paged(
            token,
            "https://graph.microsoft.com/v1.0/servicePrincipals"
            "?$select=displayName,appId,publisherName,appRoles,oauth2PermissionScopes"
            "&$top=100",
        )
        for sp in sps:
            name = sp.get("displayName", "")
            app_id = sp.get("appId", "")
            # Check app roles (application permissions)
            risky = [
                r.get("value", "")
                for r in (sp.get("appRoles") or [])
                if r.get("value", "") in HIGH_RISK_PERMS and r.get("isEnabled")
            ]
            if risky:
                risky_apps.append({
                    "AppName": name,
                    "AppId": app_id,
                    "Publisher": sp.get("publisherName", ""),
                    "RiskyPermissions": ", ".join(risky),
                })
        return risky_apps[:50]
    except Exception as exc:
        log(f"[Warning] Could not fetch OAuth app data: {exc}")
        return []


def run(token: str, log) -> dict:
    log("Starting Defender Security Posture assessment...")

    secure_score = _get_secure_score(token, log)
    score_pct = secure_score.get("Percentage", 0)
    log(f"Secure Score: {secure_score.get('CurrentScore', 'N/A')} / {secure_score.get('MaxScore', 'N/A')} ({score_pct}%)")

    log("Fetching risky users from Identity Protection...")
    risky_users = _get_risky_users(token, log)
    log(f"Risky users (High/Medium): {len(risky_users)}")

    log("Fetching MFA registration coverage...")
    mfa_coverage = _get_mfa_coverage(token, log)
    if mfa_coverage:
        log(f"MFA coverage: {mfa_coverage.get('MFACoveragePercent', 'N/A')}% ({mfa_coverage.get('MFARegistered', 0)} / {mfa_coverage.get('TotalUsers', 0)} users)")

    log("Checking OAuth app permissions for overly broad access...")
    oauth_risks = _get_oauth_app_risks(token, log)
    log(f"OAuth apps with broad permissions: {len(oauth_risks)}")

    # Build recommendations
    recommendations = []

    if not secure_score:
        recommendations.append({
            "Priority": "Medium",
            "Status": "Not Configured",
            "Area": "Security",
            "Observation": "Microsoft Secure Score data is unavailable.",
            "Recommendation": "Ensure Microsoft Defender for Microsoft 365 is licensed and provisioned.",
        })
    elif score_pct < SCORE_REQUIRES_WORK:
        recommendations.append({
            "Priority": "High",
            "Status": "Warning",
            "Area": "Security",
            "Observation": f"Microsoft Secure Score is critically low at {score_pct}% of the achievable maximum.",
            "Recommendation": "Review and act on the top recommended actions in the Microsoft Secure Score portal before enabling Copilot broadly.",
        })
    elif score_pct < SCORE_READY:
        recommendations.append({
            "Priority": "Medium",
            "Status": "Warning",
            "Area": "Security",
            "Observation": f"Microsoft Secure Score is {score_pct}%, below the recommended 70% threshold.",
            "Recommendation": "Prioritise outstanding Secure Score improvement actions, particularly in Identity and Device categories.",
        })
    else:
        recommendations.append({
            "Priority": "Low",
            "Status": "Compliant",
            "Area": "Security",
            "Observation": f"Microsoft Secure Score is {score_pct}%, above the recommended threshold.",
            "Recommendation": "Continue monitoring the Secure Score and maintain improvement momentum.",
        })

    if len(risky_users) > 10:
        recommendations.append({
            "Priority": "High",
            "Status": "Warning",
            "Area": "Identity",
            "Observation": f"{len(risky_users)} users are flagged as High or Medium risk by Entra Identity Protection.",
            "Recommendation": "Remediate risky users before enabling Copilot — compromised accounts can exfiltrate data via AI-generated summaries.",
        })
    elif len(risky_users) > 0:
        recommendations.append({
            "Priority": "Medium",
            "Status": "Warning",
            "Area": "Identity",
            "Observation": f"{len(risky_users)} user(s) flagged as High or Medium risk by Identity Protection.",
            "Recommendation": "Review and remediate risky users listed in this report.",
        })
    else:
        recommendations.append({
            "Priority": "Low",
            "Status": "Compliant",
            "Area": "Identity",
            "Observation": "No High or Medium risk users detected by Identity Protection.",
            "Recommendation": "Continue monitoring and ensure Identity Protection policies are enforced.",
        })

    if mfa_coverage:
        mfa_pct = mfa_coverage.get("MFACoveragePercent", 0)
        if mfa_pct < 80:
            recommendations.append({
                "Priority": "High",
                "Status": "Warning",
                "Area": "Identity",
                "Observation": f"Only {mfa_pct}% of users have registered MFA. Low MFA coverage significantly increases breach risk.",
                "Recommendation": "Use Conditional Access and Entra ID registration campaigns to drive MFA adoption to 95%+ before Copilot rollout.",
            })
        elif mfa_pct < 95:
            recommendations.append({
                "Priority": "Medium",
                "Status": "Warning",
                "Area": "Identity",
                "Observation": f"{mfa_pct}% MFA coverage — good but not comprehensive.",
                "Recommendation": "Target 95%+ MFA registration before a broad Copilot deployment.",
            })
        else:
            recommendations.append({
                "Priority": "Low",
                "Status": "Compliant",
                "Area": "Identity",
                "Observation": f"Strong MFA coverage at {mfa_pct}%.",
                "Recommendation": "Maintain MFA enforcement and review exemptions periodically.",
            })

    if oauth_risks:
        recommendations.append({
            "Priority": "High" if len(oauth_risks) > 5 else "Medium",
            "Status": "Warning",
            "Area": "Security",
            "Observation": f"{len(oauth_risks)} OAuth application(s) have overly broad permissions (e.g., Mail.Send, Files.ReadWrite.All). These pose a data exfiltration risk when Copilot is enabled.",
            "Recommendation": "Review and reduce permissions for OAuth apps. Remove apps not in active use. Copilot can surface data accessible to any connected app.",
        })

    # Score: weighted blend of Secure Score %, penalised by risky users and OAuth risks
    risky_penalty = min(30, len(risky_users) * 3)
    oauth_penalty = min(20, len(oauth_risks) * 2)
    raw_score = max(0, score_pct - risky_penalty - oauth_penalty) if score_pct else 0
    readiness_score = round(raw_score, 1)
    rating = _rating(score_pct, len(risky_users), len(oauth_risks))

    summary = {
        "AssessmentDate": datetime.now().isoformat(),
        "SecureScorePercent": score_pct,
        "SecureScoreCurrent": secure_score.get("CurrentScore", "N/A"),
        "SecureScoreMax": secure_score.get("MaxScore", "N/A"),
        "RiskyUsersHighMedium": len(risky_users),
        "MFACoveragePercent": mfa_coverage.get("MFACoveragePercent", "N/A"),
        "OAuthAppsWithBroadPermissions": len(oauth_risks),
        "ReadinessRating": rating,
    }

    log(f"Defender assessment complete. Score={readiness_score}, Rating={rating}")

    return {
        "Name": "DefenderPosture",
        "Summary": summary,
        "SecureScore": secure_score,
        "RiskyUsers": risky_users,
        "MFACoverage": mfa_coverage,
        "OAuthRisks": oauth_risks,
        "Recommendations": recommendations,
        "ReadinessScore": readiness_score,
        "ReadinessRating": rating,
    }
