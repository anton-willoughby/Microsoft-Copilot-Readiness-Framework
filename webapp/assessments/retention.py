"""Retention labels & policies assessment — Graph-based port of Get-CRRetentionAssessment.ps1.

Note: The original PowerShell implementation queries the Security & Compliance PowerShell
module (Get-ComplianceTag, Get-RetentionCompliancePolicy). Those cmdlets have no direct REST API
equivalent. This port uses the Microsoft Graph compliance/retention endpoints (beta) which
provide equivalent data via delegated access.
"""
from datetime import datetime
from services.graph_client import graph_get_paged
import config

BETA = config.GRAPH_BETA


def _readiness_rating(score: float) -> str:
    if score >= 80:
        return "Ready"
    if score >= 60:
        return "Nearly Ready"
    if score >= 40:
        return "Requires Work"
    return "Not Ready"


def run(token: str, log) -> dict:
    # ── Retention labels ─────────────────────────────────────────────────────────
    log("Retrieving retention labels from Microsoft Graph (beta)...")
    try:
        raw_labels = graph_get_paged(
            token,
            f"{BETA}/security/labels/retentionLabels?$top=200",
        )
    except Exception as exc:
        log(f"[Warning] Could not retrieve retention labels via Graph beta. {exc}")
        raw_labels = []

    label_inventory = [
        {
            "LabelName": lbl.get("displayName", ""),
            "RetentionAction": lbl.get("retentionAction", ""),
            "RetentionDuration": str(lbl.get("retentionDuration", {}).get("days", "") if isinstance(lbl.get("retentionDuration"), dict) else lbl.get("retentionDuration", "")),
            "IsRecordLabel": lbl.get("isRecordLabel", False),
            "BehaviorDuringRetentionPeriod": lbl.get("behaviorDuringRetentionPeriod", ""),
        }
        for lbl in raw_labels
    ]

    # ── Retention policies ───────────────────────────────────────────────────────
    log("Retrieving retention policies from Microsoft Graph (beta)...")
    try:
        raw_policies = graph_get_paged(
            token,
            f"{BETA}/security/cases/retentionPolicies?$top=200",
        )
    except Exception as exc:
        log(f"[Warning] Could not retrieve retention policies via Graph beta. {exc}")
        raw_policies = []

    active_sp = active_od = active_ex = active_teams = False
    policies_with_delete = keep_only = delete_only = keep_and_delete = 0
    policy_findings = []

    for pol in raw_policies:
        name = pol.get("displayName") or pol.get("name") or "<Unnamed Policy>"
        is_enabled = pol.get("isEnabled", True)
        locations = pol.get("locations") or []
        location_names = {loc.get("name", "").lower() for loc in locations}

        sp_configured = any("sharepoint" in n for n in location_names)
        od_configured = any("onedrive" in n for n in location_names)
        ex_configured = any("exchange" in n for n in location_names)
        teams_configured = any("teams" in n for n in location_names)

        if is_enabled:
            if sp_configured:
                active_sp = True
            if od_configured:
                active_od = True
            if ex_configured:
                active_ex = True
            if teams_configured:
                active_teams = True

        action = pol.get("retentionAction", "NotSpecified")
        if is_enabled and "delete" in action.lower():
            policies_with_delete += 1

        if action == "KeepAndDelete":
            lifecycle = "RetainThenDelete"
            if is_enabled:
                keep_and_delete += 1
        elif action == "Delete":
            lifecycle = "DeleteOnly"
            if is_enabled:
                delete_only += 1
        elif action == "Keep":
            lifecycle = "RetainOnly"
            if is_enabled:
                keep_only += 1
        else:
            lifecycle = "NotSpecified"

        workloads = (
            (["SharePoint"] if sp_configured else [])
            + (["OneDrive"] if od_configured else [])
            + (["Exchange"] if ex_configured else [])
            + (["Teams"] if teams_configured else [])
        )

        duration_raw = pol.get("retentionDuration") or {}
        duration = str(duration_raw.get("days", "")) if isinstance(duration_raw, dict) else str(duration_raw)

        policy_findings.append({
            "PolicyName": name,
            "EnabledStatus": "Enabled" if is_enabled else "Disabled",
            "WorkloadsCovered": "; ".join(workloads) if workloads else "None",
            "RetentionAction": action,
            "RetentionDuration": duration,
            "LifecycleMode": lifecycle,
        })

    readiness_score = 0
    if active_sp:
        readiness_score += 25
    if active_od:
        readiness_score += 20
    if active_ex:
        readiness_score += 20
    if active_teams:
        readiness_score += 15
    if policies_with_delete > 0:
        readiness_score += 20

    workloads_covered = (
        (["SharePoint"] if active_sp else [])
        + (["OneDrive"] if active_od else [])
        + (["Exchange"] if active_ex else [])
        + (["Teams"] if active_teams else [])
    )

    if keep_and_delete > 0 or delete_only > 0:
        data_lifecycle = "Retention and deletion actions configured"
    elif keep_only > 0:
        data_lifecycle = "Retention-only actions configured"
    else:
        data_lifecycle = "No explicit retention actions detected"

    active_policies = sum(1 for p in policy_findings if p["EnabledStatus"] == "Enabled")
    rating = _readiness_rating(readiness_score)

    summary = {
        "AssessmentDate": datetime.now().isoformat(),
        "TotalRetentionLabels": len(label_inventory),
        "TotalPolicies": len(policy_findings),
        "TotalActivePolicies": active_policies,
        "WorkloadsCovered": ", ".join(workloads_covered) if workloads_covered else "None",
        "PoliciesWithDeleteAction": policies_with_delete,
        "KeepOnlyPolicies": keep_only,
        "DeleteOnlyPolicies": delete_only,
        "KeepAndDeletePolicies": keep_and_delete,
        "DataLifecyclePosture": data_lifecycle,
        "ReadinessRating": rating,
    }

    log(f"Retention assessment complete. ActivePolicies={active_policies}, Labels={len(label_inventory)}, Score={readiness_score}")

    return {
        "Name": "RetentionLabels",
        "Summary": summary,
        "Findings": policy_findings,
        "LabelInventory": label_inventory,
        "ReadinessScore": readiness_score,
        "ReadinessRating": rating,
    }
