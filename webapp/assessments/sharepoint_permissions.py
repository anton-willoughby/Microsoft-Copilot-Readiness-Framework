"""sharepoint_permissions.py

Audits SharePoint site and document-library permissions.

Site-level permissions are derived from the backing M365 unified group
(owners + members).  This approach works with delegated auth and
Directory.Read.All, unlike GET /sites/{id}/permissions which returns
OAuth app grants and requires application-level permissions.

Communication sites and classic sites that have no backing M365 group
are flagged so the assessor knows manual review may be needed.

Library-level permissions show unique (non-inherited) sharing links and
direct grants on each document library root, using Sites.Read.All +
Files.Read.All which are standard delegated scopes.
"""

import requests
from services.graph_client import graph_get_paged

_TIMEOUT = 30


def _build_group_site_map(token: str, log) -> dict:
    """Pre-fetch all unified M365 groups and return a dict keyed by
    lower-case SharePoint site URL → group object.

    One bulk request replaces per-site group lookups.
    """
    group_map: dict = {}
    try:
        groups = graph_get_paged(
            token,
            "https://graph.microsoft.com/v1.0/groups"
            "?$filter=groupTypes/any(c:c eq 'Unified')"
            "&$select=id,displayName,mail,sharepointSiteUrl",
        )
        for g in groups:
            url = (g.get("sharepointSiteUrl") or "").rstrip("/").lower()
            if url:
                group_map[url] = g
        log(f"Mapped {len(group_map)} M365 group-connected site(s).")
    except Exception as exc:
        log(f"[Warning] Could not pre-fetch M365 groups: {exc}")
    return group_map


def _get_group_members(token: str, group_id: str, log) -> list:
    """Return owners and members of an M365 group as a permissions list."""
    headers = {"Authorization": f"Bearer {token}"}
    perms = []
    for role, url in (
        (
            "Owner",
            f"https://graph.microsoft.com/v1.0/groups/{group_id}/owners"
            "?$select=displayName,mail&$top=20",
        ),
        (
            "Member",
            f"https://graph.microsoft.com/v1.0/groups/{group_id}/members"
            "?$select=displayName,mail&$top=25",
        ),
    ):
        try:
            resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
            resp.raise_for_status()
            for user in resp.json().get("value", []):
                name = user.get("displayName") or user.get("mail") or "Unknown"
                perms.append({"user": name, "roles": [role]})
        except requests.exceptions.RequestException as exc:
            log(f"[Warning] Could not fetch {role}s for group {group_id}: {exc}")
    return perms


def _get_library_permissions(drive_id: str, headers: dict) -> list:
    """Return unique (non-inherited) permissions on a document library root.

    Inherited permissions are omitted — they are already captured at site
    level via group membership.  We surface sharing links (anonymous,
    organisation-wide) and any direct grants that break inheritance.
    """
    try:
        resp = requests.get(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/permissions",
            headers=headers,
            timeout=_TIMEOUT,
        )
        if resp.status_code in (403, 404):
            return []
        resp.raise_for_status()
        out = []
        for perm in resp.json().get("value", []):
            if perm.get("inheritedFrom"):
                continue  # skip — shown at site level already
            link = perm.get("link", {})
            if link:
                scope = link.get("scope", "")
                link_type = link.get("type", "read")
                if scope in ("anonymous", "organization", "users"):
                    out.append({
                        "user": f"[Sharing Link — {scope} / {link_type}]",
                        "roles": [link_type],
                    })
                continue
            identity = (
                perm.get("grantedToV2", {}).get("siteUser")
                or perm.get("grantedToV2", {}).get("user")
                or perm.get("grantedTo", {}).get("user")
                or {}
            )
            name = identity.get("displayName") or identity.get("email") or ""
            roles = perm.get("roles", [])
            if name and roles:
                out.append({"user": name, "roles": roles})
        return out
    except requests.exceptions.RequestException:
        return []


def run(token: str, log) -> dict:
    """Run the SharePoint Permissions assessment.

    Returns site list with M365 group membership (site-level) and unique
    library sharing permissions (library-level).
    """
    log("Starting SharePoint Permissions assessment...")
    headers = {"Authorization": f"Bearer {token}"}

    # Pre-fetch group→site map (one request instead of N)
    group_map = _build_group_site_map(token, log)

    log("Fetching all SharePoint sites...")
    try:
        resp = requests.get(
            "https://graph.microsoft.com/v1.0/sites?search=*",
            headers=headers,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        sites = resp.json().get("value", [])
    except requests.exceptions.RequestException as exc:
        log(f"[Error] Failed to fetch sites: {exc}")
        return {
            "Name": "SharePointPermissions",
            "ReadinessScore": 0,
            "ReadinessRating": "Not Ready",
            "Summary": {"Error": str(exc)},
            "Findings": [],
            "sites": [],
        }

    log(f"Found {len(sites)} site(s). Processing permissions...")
    sites_data = []
    broad_sharing_count = 0

    for site in sites:
        site_id = site.get("id")
        site_name = site.get("displayName") or site.get("name") or site_id
        site_url = (site.get("webUrl") or "").rstrip("/")
        log(f"Processing site: {site_name}")

        # Resolve backing M365 group
        group = group_map.get(site_url.lower())
        if group:
            site_permissions = _get_group_members(token, group["id"], log)
        else:
            site_permissions = [{
                "user": "(No M365 group — Communication or classic site)",
                "roles": ["N/A"],
            }]

        site_entry = {
            "name": site_name,
            "url": site_url,
            "permissions": site_permissions,
            "libraries": [],
        }

        # Enumerate document libraries and their unique permissions
        try:
            lib_resp = requests.get(
                f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
                headers=headers,
                timeout=_TIMEOUT,
            )
            lib_resp.raise_for_status()
            for library in lib_resp.json().get("value", []):
                if library.get("driveType") != "documentLibrary":
                    continue
                lib_id = library.get("id")
                lib_name = library.get("name", lib_id)
                lib_perms = _get_library_permissions(lib_id, headers)

                # Track broad sharing links for scoring
                if any("anonymous" in p.get("user", "") or "organization" in p.get("user", "") for p in lib_perms):
                    broad_sharing_count += 1

                site_entry["libraries"].append({
                    "name": lib_name,
                    "permissions": lib_perms,
                })
        except requests.exceptions.RequestException as exc:
            log(f"[Warning] Could not fetch libraries for {site_name}: {exc}")

        sites_data.append(site_entry)

    total = len(sites_data)
    score_pct = max(0.0, 100.0 - (broad_sharing_count / max(total, 1)) * 100) if total else 50.0
    score = round(score_pct, 1)
    if score >= 80:
        rating = "Ready"
    elif score >= 60:
        rating = "Nearly Ready"
    elif score >= 40:
        rating = "Requires Work"
    else:
        rating = "Not Ready"

    log(
        f"SharePoint Permissions assessment complete. "
        f"Sites={total}, LibsWithBroadSharing={broad_sharing_count}, Score={score}"
    )
    return {
        "Name": "SharePointPermissions",
        "Summary": {
            "TotalSites": total,
            "LibrariesWithBroadSharing": broad_sharing_count,
        },
        "Findings": [],
        "ReadinessScore": score,
        "ReadinessRating": rating,
        "sites": sites_data,
    }



def _get_permissions(url: str, headers: dict, log) -> list:
    """Fetch and normalise permissions from a Graph API permissions endpoint."""
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        raw = response.json().get("value", [])
        processed = []
        for perm in raw:
            # grantedToV2 is preferred; fall back to grantedTo
            identity = (
                perm.get("grantedToV2", {}).get("siteUser")
                or perm.get("grantedToV2", {}).get("user")
                or perm.get("grantedTo", {}).get("user")
                or {}
            )
            display_name = identity.get("displayName") or identity.get("email") or "Unknown"
            roles = perm.get("roles", [])
            processed.append({"user": display_name, "roles": roles})
        return processed
    except requests.exceptions.RequestException as exc:
        log(f"[Warning] Could not fetch permissions from {url}: {exc}")
        return []


def run(token: str, log) -> dict:
    """
    Run the SharePoint permissions assessment.

    Args:
        token (str): A valid Microsoft Graph bearer token.
        log (callable): A logging function that accepts a single string message.

    Returns:
        dict: Assessment results containing sites, their permissions, and library permissions.
    """
    log("Starting SharePoint Permissions assessment...")
    headers = {"Authorization": f"Bearer {token}"}
    sites_data = []

    log("Fetching all SharePoint sites...")
    try:
        response = requests.get(
            "https://graph.microsoft.com/v1.0/sites?search=*",
            headers=headers,
        )
        response.raise_for_status()
        sites = response.json().get("value", [])
        log(f"Found {len(sites)} site(s). Processing permissions...")

        for site in sites:
            site_id = site.get("id")
            site_name = site.get("displayName") or site.get("name") or site_id
            log(f"Processing site: {site_name}")

            site_entry = {
                "name": site_name,
                "url": site.get("webUrl", ""),
                "permissions": _get_permissions(
                    f"https://graph.microsoft.com/v1.0/sites/{site_id}/permissions",
                    headers,
                    log,
                ),
                "libraries": [],
            }

            # Fetch document libraries for this site
            try:
                lib_resp = requests.get(
                    f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
                    headers=headers,
                )
                lib_resp.raise_for_status()
                for library in lib_resp.json().get("value", []):
                    if library.get("driveType") != "documentLibrary":
                        continue
                    lib_id = library.get("id")
                    lib_name = library.get("name", lib_id)
                    log(f"  Library: {lib_name}")
                    site_entry["libraries"].append({
                        "name": lib_name,
                        "permissions": _get_permissions(
                            f"https://graph.microsoft.com/v1.0/drives/{lib_id}/root/permissions",
                            headers,
                            log,
                        ),
                    })
            except requests.exceptions.RequestException as exc:
                log(f"[Warning] Could not fetch libraries for {site_name}: {exc}")

            sites_data.append(site_entry)

    except requests.exceptions.RequestException as exc:
        log(f"[Error] Failed to fetch sites: {exc}")
        return {"sites": [], "error": str(exc)}

    log("SharePoint Permissions assessment complete.")
    return {"sites": sites_data}

