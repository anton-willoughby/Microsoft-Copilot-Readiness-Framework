"""M365 Copilot licensing assessment.

Checks tenant-level license inventory to determine whether Copilot licenses
are purchased and consumed, and whether prerequisite M365 licenses are present.
Uses GET /subscribedSkus — no per-user queries required.
"""
from datetime import datetime
from services.graph_client import graph_get


# SKU part numbers that represent M365 Copilot or Copilot add-ons
COPILOT_SKUS = {
    "MICROSOFT_365_COPILOT",
    "COPILOT_STUDIO_VIRAL",
    "MICROSOFT_COPILOT_STUDIO",
    "POWER_VIRTUAL_AGENTS_D365",
    "POWERVIRTUALAGENTS_VIRAL",
}

# SKU part numbers that are accepted prerequisite licenses for Copilot
PREREQUISITE_SKUS = {
    "SPE_E3",               # Microsoft 365 E3
    "SPE_E5",               # Microsoft 365 E5
    "ENTERPRISEPREMIUM",    # Office 365 E3
    "ENTERPRISEPREMIUM_NOPSTNCONF",
    "O365_BUSINESS_PREMIUM",  # Microsoft 365 Business Premium
    "SPB",                  # Microsoft 365 Business Premium (alt SKU)
    "M365_F1",              # Microsoft 365 F1
    "SPE_F1",               # Microsoft 365 F1 (alt)
    "M365_G3",              # Microsoft 365 G3 (Government)
    "M365_G5",              # Microsoft 365 G5 (Government)
}

# Copilot-adjacent service plans to call out specifically
COPILOT_SERVICE_PLANS = {
    "M365_COPILOT",
    "COPILOT_FOR_MICROSOFT365",
    "MICROSOFT_365_COPILOT",
    "SHAREPOINT_COPILOT",
    "TEAMS_COPILOT",
    "EXCHANGE_COPILOT",
}


def _rating(copilot_consumed: int, copilot_purchased: int, has_prereqs: bool) -> str:
    if copilot_consumed > 0:
        return "Ready"
    if copilot_purchased > 0:
        return "Nearly Ready"
    if has_prereqs:
        return "Requires Work"
    return "Not Ready"


def run(token: str, log) -> dict:
    log("Retrieving M365 license SKUs from Microsoft Graph...")

    skus_data = graph_get(
        token,
        "https://graph.microsoft.com/v1.0/subscribedSkus?$select=skuPartNumber,skuId,consumedUnits,prepaidUnits,capabilityStatus,servicePlans",
    )
    skus = skus_data.get("value", []) if skus_data else []
    log(f"Found {len(skus)} license SKU(s) in tenant.")

    copilot_licenses = []
    prerequisite_licenses = []
    other_licenses = []
    recommendations = []

    total_copilot_purchased = 0
    total_copilot_consumed = 0
    has_prerequisites = False

    for sku in skus:
        part_number = sku.get("skuPartNumber", "")
        purchased = (sku.get("prepaidUnits") or {}).get("enabled", 0)
        consumed = sku.get("consumedUnits", 0)
        available = purchased - consumed
        status = sku.get("capabilityStatus", "Unknown")

        service_plan_names = [
            p.get("servicePlanName", "")
            for p in (sku.get("servicePlans") or [])
        ]

        # Identify Copilot-specific service plans present in this SKU
        copilot_plans_in_sku = [
            p for p in service_plan_names
            if p.upper() in {s.upper() for s in COPILOT_SERVICE_PLANS}
        ]

        entry = {
            "SkuPartNumber": part_number,
            "SkuId": sku.get("skuId", ""),
            "Purchased": purchased,
            "Consumed": consumed,
            "Available": available,
            "Status": status,
            "CopilotServicePlans": ", ".join(copilot_plans_in_sku) if copilot_plans_in_sku else "None",
        }

        if part_number.upper() in {s.upper() for s in COPILOT_SKUS} or copilot_plans_in_sku:
            copilot_licenses.append(entry)
            total_copilot_purchased += purchased
            total_copilot_consumed += consumed

            if consumed == 0 and purchased > 0:
                recommendations.append({
                    "Priority": "High",
                    "Status": "Warning",
                    "Area": "Licensing",
                    "Observation": f"{part_number}: {purchased} licenses purchased but 0 assigned to users.",
                    "Recommendation": "Assign Copilot licenses to intended users to activate the service.",
                })
            elif available < 0:
                recommendations.append({
                    "Priority": "High",
                    "Status": "Warning",
                    "Area": "Licensing",
                    "Observation": f"{part_number}: Over-consumed — {consumed} assigned but only {purchased} purchased.",
                    "Recommendation": "Purchase additional Copilot licenses to cover all assigned users.",
                })

        elif part_number.upper() in {s.upper() for s in PREREQUISITE_SKUS}:
            has_prerequisites = True
            prerequisite_licenses.append(entry)
        else:
            other_licenses.append(entry)

    # Generate recommendations for missing Copilot licenses
    if total_copilot_purchased == 0:
        if has_prerequisites:
            recommendations.append({
                "Priority": "High",
                "Status": "Not Configured",
                "Area": "Licensing",
                "Observation": "Prerequisite M365 licenses are present but no Microsoft 365 Copilot licenses were found.",
                "Recommendation": "Purchase Microsoft 365 Copilot add-on licenses for intended users.",
            })
        else:
            recommendations.append({
                "Priority": "High",
                "Status": "Not Configured",
                "Area": "Licensing",
                "Observation": "No Microsoft 365 Copilot licenses or qualifying prerequisite licenses found in the tenant.",
                "Recommendation": "Purchase qualifying M365 E3/E5/Business Premium licenses, then add Microsoft 365 Copilot licenses.",
            })

    if total_copilot_consumed > 0 and not has_prerequisites:
        recommendations.append({
            "Priority": "Medium",
            "Status": "Warning",
            "Area": "Licensing",
            "Observation": "Copilot licenses are assigned, but no standard prerequisite licenses (E3/E5/Business Premium) were detected.",
            "Recommendation": "Verify all Copilot-licensed users also hold a qualifying base M365 license.",
        })

    if total_copilot_consumed > 0:
        recommendations.append({
            "Priority": "Low",
            "Status": "Compliant",
            "Area": "Licensing",
            "Observation": f"{total_copilot_consumed} Copilot license(s) are actively assigned to users.",
            "Recommendation": "Monitor consumption regularly and align license counts with user growth.",
        })

    rating = _rating(total_copilot_consumed, total_copilot_purchased, has_prerequisites)
    # Score: 100 if consumed > 0; 60 if purchased but not consumed; 30 if prereqs only; 0 otherwise
    score_map = {"Ready": 100, "Nearly Ready": 60, "Requires Work": 30, "Not Ready": 0}
    score = score_map[rating]

    summary = {
        "AssessmentDate": datetime.now().isoformat(),
        "TotalSkus": len(skus),
        "CopilotLicensesPurchased": total_copilot_purchased,
        "CopilotLicensesConsumed": total_copilot_consumed,
        "CopilotLicensesAvailable": total_copilot_purchased - total_copilot_consumed,
        "HasPrerequisiteLicenses": has_prerequisites,
        "ReadinessRating": rating,
    }

    log(
        f"Licensing assessment complete. Copilot purchased={total_copilot_purchased}, "
        f"consumed={total_copilot_consumed}, rating={rating}"
    )

    return {
        "Name": "M365Licensing",
        "Summary": summary,
        "Findings": copilot_licenses + prerequisite_licenses,
        "AllSkus": skus,
        "Recommendations": recommendations,
        "ReadinessScore": score,
        "ReadinessRating": rating,
    }
