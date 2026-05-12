"""Microsoft Graph API client with automatic paging."""
import requests
import config


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def graph_get_paged(token: str, uri: str) -> list:
    """Fetch all pages from a Graph endpoint and return a flat list of items."""
    results = []
    next_uri = uri
    while next_uri:
        resp = requests.get(next_uri, headers=_headers(token))
        resp.raise_for_status()
        data = resp.json()
        if "value" in data:
            results.extend(data["value"])
            next_uri = data.get("@odata.nextLink")
        else:
            results.append(data)
            next_uri = None
    return results


def graph_post(token: str, uri: str, body: dict) -> dict:
    """POST to a Graph endpoint and return the JSON response."""
    resp = requests.post(
        uri,
        headers={**_headers(token), "Content-Type": "application/json"},
        json=body,
    )
    resp.raise_for_status()
    return resp.json()


def graph_get(token: str, uri: str, headers: dict | None = None) -> dict:
    """GET a single Graph resource."""
    h = _headers(token)
    if headers:
        h.update(headers)
    resp = requests.get(uri, headers=h)
    resp.raise_for_status()
    return resp.json()


def get_sites_list(token: str, page_size: int = 500) -> list:
    """
    Enumerate SharePoint sites via POST /search/query (delegated Sites.Read.All).
    Falls back to root + subsites if Search API returns nothing.
    """
    all_sites = []
    from_offset = 0
    more = True

    while more:
        body = {
            "requests": [
                {
                    "entityTypes": ["site"],
                    "query": {"queryString": "*"},
                    "from": from_offset,
                    "size": page_size,
                    "fields": [
                        "id", "name", "displayName", "webUrl",
                        "description", "createdDateTime", "lastModifiedDateTime",
                    ],
                }
            ]
        }
        try:
            data = graph_post(token, "https://graph.microsoft.com/v1.0/search/query", body)
        except Exception:
            break

        container = None
        for result in data.get("value", []):
            containers = result.get("hitsContainers", [])
            if containers:
                container = containers[0]
                break

        if not container:
            break

        hits = container.get("hits", [])
        for hit in hits:
            resource = hit.get("resource")
            if resource:
                if not resource.get("id") and hit.get("hitId"):
                    resource["id"] = hit["hitId"]
                all_sites.append(resource)

        more = container.get("moreResultsAvailable", False)
        from_offset += page_size
        if not hits:
            break

    if not all_sites:
        try:
            root = graph_get(token, f"{config.GRAPH_BASE}/sites/root")
            if root:
                all_sites.append(root)
                sub = graph_get_paged(token, f"{config.GRAPH_BASE}/sites/{root['id']}/sites")
                all_sites.extend(sub)
        except Exception:
            pass

    return all_sites


def get_group_member_count(token: str, group_id: str) -> int:
    try:
        data = graph_get(
            token,
            f"{config.GRAPH_BASE}/groups/{group_id}/members/$count",
            headers={"ConsistencyLevel": "eventual"},
        )
        return int(data) if isinstance(data, (int, str)) else 0
    except Exception:
        return 0
