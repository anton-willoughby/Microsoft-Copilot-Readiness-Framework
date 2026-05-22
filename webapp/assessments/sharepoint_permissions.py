"""
sharepoint_permissions.py

Assessment module for SharePoint site and document library permissions.
Follows the same run(token, log) signature as all other assessment modules.
"""

import requests


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

