"""Overshared content assessment — port of Get-CROversharedContent.ps1"""
from datetime import datetime
from services.graph_client import graph_get_paged, get_sites_list, get_group_member_count
import config


def _readiness_rating(score: float) -> str:
    if score >= 80:
        return "Ready"
    if score >= 60:
        return "Nearly Ready"
    if score >= 40:
        return "Requires Work"
    return "Not Ready"


def _enumerate_files(token: str, drive_id: str, item_id: str, file_list: list, sample_size: int):
    if sample_size > 0 and len(file_list) >= sample_size:
        return
    uri = (
        f"{config.GRAPH_BASE}/drives/{drive_id}/items/{item_id}/children"
        "?$select=id,name,webUrl,file,folder,lastModifiedDateTime&$top=200"
    )
    try:
        children = graph_get_paged(token, uri)
    except Exception:
        return
    for child in children:
        if child.get("file") is not None:
            file_list.append(child)
            if sample_size > 0 and len(file_list) >= sample_size:
                return
        elif child.get("folder") is not None and child.get("id"):
            _enumerate_files(token, drive_id, child["id"], file_list, sample_size)
            if sample_size > 0 and len(file_list) >= sample_size:
                return


def run(token: str, log, include_onedrive: bool = False, sample_size: int = 100) -> dict:
    oversharing: list[dict] = []
    group_count_cache: dict[str, int] = {}

    def _group_member_count(group_id: str) -> int:
        if group_id not in group_count_cache:
            group_count_cache[group_id] = get_group_member_count(token, group_id)
        return group_count_cache[group_id]

    log("Retrieving SharePoint sites for oversharing analysis via Microsoft Search API...")
    sites = get_sites_list(token)

    if not include_onedrive:
        sites = [s for s in sites if "-my.sharepoint.com/personal/" not in s.get("webUrl", "")]

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
            file_items: list = []
            _enumerate_files(token, drive["id"], "root", file_items, sample_size)

            for item in file_items:
                try:
                    permissions = graph_get_paged(
                        token,
                        f"{config.GRAPH_BASE}/drives/{drive['id']}/items/{item['id']}/permissions?$top=200",
                    )
                except Exception as exc:
                    log(f"[Warning] Skipping permission check for {item.get('webUrl')}. {exc}")
                    continue

                for perm in permissions:
                    link = perm.get("link") or {}
                    if link.get("scope") == "anonymous":
                        oversharing.append({
                            "SiteUrl": site.get("webUrl", ""),
                            "SiteTitle": site.get("displayName", ""),
                            "LibraryName": drive.get("name", ""),
                            "ItemName": item.get("name", ""),
                            "ItemPath": item.get("webUrl", ""),
                            "SharedWith": "Anonymous Link",
                            "MemberType": "Anonymous",
                            "RiskLevel": "Critical",
                            "RiskReason": "Anyone with link can access",
                            "LastModified": item.get("lastModifiedDateTime", ""),
                        })

                    principal_set = []
                    gv2 = perm.get("grantedToV2")
                    if gv2:
                        principal_set.append(gv2)
                    giv2 = perm.get("grantedToIdentitiesV2") or []
                    principal_set.extend(giv2)

                    for principal in principal_set:
                        risk_level = "Low"
                        risk_reason = ""
                        shared_with = "Unknown"
                        member_type = "Unknown"

                        site_group = principal.get("siteGroup") or {}
                        group = principal.get("group") or {}
                        user = principal.get("user") or {}
                        site_user = principal.get("siteUser") or {}

                        if site_group.get("displayName"):
                            name = site_group["displayName"]
                            shared_with = name
                            member_type = "SiteGroup"
                            if "Everyone except external users" in name:
                                risk_level = "High"
                                risk_reason = "Shared with Everyone except external users"
                            elif "Everyone" in name:
                                risk_level = "Critical"
                                risk_reason = "Shared with Everyone group"
                        elif group.get("displayName"):
                            shared_with = group["displayName"]
                            member_type = "SecurityGroup"
                            count = _group_member_count(group.get("id", ""))
                            if count > 500:
                                risk_level = "Medium"
                                risk_reason = f"Shared with large security group ({count} members)"
                        elif user.get("email") or user.get("displayName"):
                            shared_with = user.get("email") or user.get("displayName", "")
                            member_type = "User"
                        elif site_user.get("email") or site_user.get("displayName"):
                            shared_with = site_user.get("email") or site_user.get("displayName", "")
                            member_type = "SiteUser"

                        if risk_level != "Low":
                            oversharing.append({
                                "SiteUrl": site.get("webUrl", ""),
                                "SiteTitle": site.get("displayName", ""),
                                "LibraryName": drive.get("name", ""),
                                "ItemName": item.get("name", ""),
                                "ItemPath": item.get("webUrl", ""),
                                "SharedWith": shared_with,
                                "MemberType": member_type,
                                "RiskLevel": risk_level,
                                "RiskReason": risk_reason,
                                "LastModified": item.get("lastModifiedDateTime", ""),
                            })

    critical = sum(1 for r in oversharing if r["RiskLevel"] == "Critical")
    high = sum(1 for r in oversharing if r["RiskLevel"] == "High")
    medium = sum(1 for r in oversharing if r["RiskLevel"] == "Medium")

    readiness_score = max(0, 100 - critical * 20 - high * 10 - medium * 5)
    rating = _readiness_rating(readiness_score)

    summary = {
        "AssessmentDate": datetime.now().isoformat(),
        "TotalOversharingInstances": len(oversharing),
        "CriticalRisk": critical,
        "HighRisk": high,
        "MediumRisk": medium,
        "ReadinessRating": rating,
    }

    log(f"Overshared content assessment complete. Total={len(oversharing)}, Critical={critical}")

    return {
        "Name": "OversharedContent",
        "Summary": summary,
        "Findings": oversharing,
        "ReadinessScore": readiness_score,
        "ReadinessRating": rating,
    }
