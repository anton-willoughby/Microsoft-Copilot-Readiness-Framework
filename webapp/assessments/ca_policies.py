"""Conditional Access policy assessment — port of Get-CRCAPolicyAssessment.ps1"""
import math
from datetime import datetime
from services.graph_client import graph_get_paged

COPILOT_APP_IDS = {
    "0ec893e0-5785-4de6-99da-4ed124e5296c",
    "b1831b8b-e4f8-41f4-99d9-b0d8e0e5a4b5",
    "00000003-0000-0000-c000-000000000000",
}


def _readiness_rating(issues_count: int, mfa_count: int) -> str:
    if issues_count == 0 and mfa_count >= 1:
        return "Ready"
    if issues_count <= 2:
        return "Nearly Ready"
    if issues_count <= 5:
        return "Requires Work"
    return "Not Ready"


def run(token: str, log, check_copilot_apps: bool = True) -> dict:
    log("Retrieving Conditional Access policies from Microsoft Graph...")
    policies = graph_get_paged(
        token,
        "https://graph.microsoft.com/v1.0/identity/conditionalAccess/policies?$top=200",
    )

    policy_analysis = []
    compatibility_issues = []

    for policy in policies:
        conditions = policy.get("conditions", {}) or {}
        users = conditions.get("users", {}) or {}
        apps = conditions.get("applications", {}) or {}
        grant = policy.get("grantControls") or {}
        session = policy.get("sessionControls") or {}

        applies_to = ""
        if "All" in users.get("includeUsers", []):
            applies_to = "All Users"
        elif users.get("includeUsers"):
            applies_to = "Specific Users"

        built_in = grant.get("builtInControls", []) or []
        requires_mfa = "mfa" in built_in
        requires_compliant = "compliantDevice" in built_in
        requires_hybrid = "domainJoinedDevice" in built_in
        requires_pw_change = "passwordChange" in built_in

        # Session controls
        session_list = []
        sif = None
        aer = session.get("applicationEnforcedRestrictions") or {}
        if aer.get("isEnabled"):
            session_list.append("App Enforced Restrictions")
        cas = session.get("cloudAppSecurity") or {}
        if cas.get("isEnabled"):
            session_list.append("Cloud App Security Session Control")
        sif = session.get("signInFrequency") or {}
        if sif.get("isEnabled"):
            session_list.append(f"Sign-in Frequency: {sif.get('value')} {sif.get('type')}")
        pb = session.get("persistentBrowser") or {}
        if pb.get("isEnabled"):
            session_list.append(f"Persistent Browser: {pb.get('mode')}")

        # Copilot blocking check
        blocks_copilot = False
        if check_copilot_apps and "block" in built_in:
            inc_apps = apps.get("includeApplications", []) or []
            exc_apps = set(apps.get("excludeApplications", []) or [])
            if "All" in inc_apps and not COPILOT_APP_IDS.intersection(exc_apps):
                blocks_copilot = True

        # Compatibility scoring
        score = 100
        issues = []
        recommendations = []
        state = policy.get("state", "")

        if blocks_copilot:
            score -= 100
            issues.append("Policy blocks all apps without Copilot exclusion.")
            recommendations.append("Exclude Copilot app IDs from this blocking policy.")

        if not requires_mfa and state == "enabled" and applies_to == "All Users":
            score -= 20
            issues.append("No MFA requirement for users in scope.")
            recommendations.append("Require MFA for Copilot access.")

        if not requires_compliant and state == "enabled" and applies_to == "All Users":
            score -= 10
            issues.append("No compliant device requirement for users in scope.")
            recommendations.append("Consider compliant device enforcement for Copilot access.")

        if sif.get("isEnabled") and isinstance(sif.get("value"), (int, float)) and sif["value"] < 4:
            score -= 15
            issues.append("Frequent sign-in requirement may degrade Copilot experience.")
            recommendations.append("Review sign-in frequency for Copilot workflows.")

        compat_score = max(0, score)

        inc_apps_display = (
            "All Apps"
            if "All" in (apps.get("includeApplications") or [])
            else "; ".join(apps.get("includeApplications") or [])
        )

        entry = {
            "PolicyName": policy.get("displayName", ""),
            "PolicyId": policy.get("id", ""),
            "State": state,
            "CreatedDateTime": policy.get("createdDateTime", ""),
            "ModifiedDateTime": policy.get("modifiedDateTime", ""),
            "AppliesTo": applies_to,
            "IncludeUsers": "; ".join(users.get("includeUsers") or []),
            "ExcludeUsers": "; ".join(users.get("excludeUsers") or []),
            "IncludeGroups": "; ".join(users.get("includeGroups") or []),
            "ExcludeGroups": "; ".join(users.get("excludeGroups") or []),
            "IncludeApplications": inc_apps_display,
            "ExcludeApplications": "; ".join(apps.get("excludeApplications") or []),
            "UserRiskLevels": ", ".join(conditions.get("userRiskLevels") or []),
            "SignInRiskLevels": ", ".join(conditions.get("signInRiskLevels") or []),
            "Platforms": ", ".join((conditions.get("platforms") or {}).get("includePlatforms") or []),
            "ClientAppTypes": ", ".join(conditions.get("clientAppTypes") or []),
            "GrantControlOperator": grant.get("operator", ""),
            "GrantControls": ", ".join(built_in),
            "RequiresMFA": requires_mfa,
            "RequiresCompliantDevice": requires_compliant,
            "RequiresHybridJoin": requires_hybrid,
            "RequiresPasswordChange": requires_pw_change,
            "SessionControls": "; ".join(session_list),
            "BlocksCopilotApps": blocks_copilot,
            "CopilotCompatibilityScore": compat_score,
            "CompatibilityIssues": "; ".join(issues),
            "Recommendations": "; ".join(recommendations),
        }

        policy_analysis.append(entry)
        if compat_score < 80:
            compatibility_issues.append(entry)

    total = len(policy_analysis)
    enabled = sum(1 for p in policy_analysis if p["State"] == "enabled")
    with_mfa = sum(1 for p in policy_analysis if p["State"] == "enabled" and p["RequiresMFA"])
    with_device = sum(1 for p in policy_analysis if p["State"] == "enabled" and p["RequiresCompliantDevice"])
    blocking = sum(1 for p in policy_analysis if p["State"] == "enabled" and "block" in p["GrantControls"])
    issues_count = len(compatibility_issues)
    avg_score = round(
        sum(p["CopilotCompatibilityScore"] for p in policy_analysis) / total, 2
    ) if total > 0 else 0

    rating = _readiness_rating(issues_count, with_mfa)

    summary = {
        "AssessmentDate": datetime.now().isoformat(),
        "TotalPolicies": total,
        "EnabledPolicies": enabled,
        "PoliciesWithMFA": with_mfa,
        "PoliciesWithDeviceCompliance": with_device,
        "BlockingPolicies": blocking,
        "CompatibilityIssues": issues_count,
        "AverageCopilotCompatibilityScore": avg_score,
        "ReadinessRating": rating,
    }

    log(f"CA assessment complete. Policies={total}, Issues={issues_count}, Score={avg_score}")

    return {
        "Name": "CAPolicies",
        "Summary": summary,
        "Findings": policy_analysis,
        "ReadinessScore": avg_score,
        "ReadinessRating": rating,
    }
