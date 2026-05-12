"""Sensitivity label coverage assessment — port of Get-CRLabelCoverage.ps1"""
import os
import re
from datetime import datetime
from services.graph_client import graph_get_paged, get_sites_list
import config


def _readiness_rating(score: float) -> str:
    if score >= 80:
        return "Ready"
    if score >= 60:
        return "Nearly Ready"
    if score >= 40:
        return "Requires Work"
    return "Not Ready"


SENSITIVE_PATTERN = re.compile(
    r"confidential|secret|internal|restricted|private|ssn|financ|payroll|hr|contract",
    re.IGNORECASE,
)


def _enumerate_files(token: str, drive_id: str, item_id: str, file_list: list, sample_size: int):
    if sample_size > 0 and len(file_list) >= sample_size:
        return
    uri = (
        f"{config.GRAPH_BETA}/drives/{drive_id}/items/{item_id}/children"
        "?$select=id,name,webUrl,file,folder,createdDateTime,lastModifiedDateTime,lastModifiedBy,sensitivityLabel&$top=200"
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


def run(token: str, log, include_onedrive: bool = False, sample_size: int = 0) -> dict:
    total_docs = 0
    labeled_docs = 0
    label_distribution: dict[str, int] = {}
    unlabeled_sensitive = []
    coverage_details = []

    log("Retrieving SharePoint sites via Microsoft Search API...")
    sites = get_sites_list(token)

    if not include_onedrive:
        sites = [s for s in sites if "-my.sharepoint.com/personal/" not in s.get("webUrl", "")]

    log(f"Scanning {len(sites)} sites for label coverage.")

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
            log(f"Scanning drive '{drive.get('name')}' in site '{site.get('displayName')}'.")
            file_items: list = []
            _enumerate_files(token, drive["id"], "root", file_items, sample_size)

            for item in file_items:
                total_docs += 1
                sensitivity = item.get("sensitivityLabel") or {}
                label_id = sensitivity.get("id", "")
                has_label = bool(label_id)
                label_name = label_id if has_label else "None"

                ext = os.path.splitext(item.get("name", ""))[1].lstrip(".")
                auto_labeled = False
                if has_label:
                    labeled_docs += 1
                    label_distribution[label_name] = label_distribution.get(label_name, 0) + 1
                    mod_by = item.get("lastModifiedBy") or {}
                    auto_labeled = bool(mod_by.get("application")) or not bool(mod_by.get("user"))

                detail = {
                    "SiteUrl": site.get("webUrl", ""),
                    "LibraryName": drive.get("name", ""),
                    "FileName": item.get("name", ""),
                    "FilePath": item.get("webUrl", ""),
                    "FileType": ext,
                    "HasLabel": has_label,
                    "LabelName": label_name,
                    "AutoLabeled": auto_labeled,
                    "FileCreated": item.get("createdDateTime", ""),
                    "FileModified": item.get("lastModifiedDateTime", ""),
                }
                coverage_details.append(detail)

                if not has_label and SENSITIVE_PATTERN.search(item.get("name", "")):
                    unlabeled_sensitive.append({
                        "SiteUrl": site.get("webUrl", ""),
                        "LibraryName": drive.get("name", ""),
                        "FileName": item.get("name", ""),
                        "FilePath": item.get("webUrl", ""),
                        "SensitiveIndicators": "Sensitive filename indicator",
                        "FileCreated": item.get("createdDateTime", ""),
                        "FileModified": item.get("lastModifiedDateTime", ""),
                    })

    label_pct = round(labeled_docs / total_docs * 100, 2) if total_docs > 0 else 0.0
    auto_count = sum(1 for d in coverage_details if d["AutoLabeled"])
    auto_pct = round(auto_count / labeled_docs * 100, 2) if labeled_docs > 0 else 0.0

    label_dist_report = sorted(
        [
            {
                "LabelName": k,
                "DocumentCount": v,
                "Percentage": round(v / labeled_docs * 100, 2) if labeled_docs > 0 else 0,
            }
            for k, v in label_distribution.items()
        ],
        key=lambda x: x["DocumentCount"],
        reverse=True,
    )

    rating = _readiness_rating(label_pct)

    summary = {
        "AssessmentDate": datetime.now().isoformat(),
        "TotalDocumentsScanned": total_docs,
        "LabeledDocuments": labeled_docs,
        "UnlabeledDocuments": total_docs - labeled_docs,
        "LabelCoveragePercent": label_pct,
        "AutoLabeledDocuments": auto_count,
        "AutoLabelPercent": auto_pct,
        "UniqueLabelTypes": len(label_distribution),
        "UnlabeledSensitiveContent": len(unlabeled_sensitive),
        "ReadinessRating": rating,
    }

    log(f"Label coverage assessment complete. Documents={total_docs}, Coverage={label_pct}%")

    return {
        "Name": "LabelCoverage",
        "Summary": summary,
        "Findings": coverage_details,
        "LabelDistribution": label_dist_report,
        "UnlabeledSensitive": unlabeled_sensitive,
        "ReadinessScore": label_pct,
        "ReadinessRating": rating,
    }
