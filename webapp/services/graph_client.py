"""Microsoft Graph API client with automatic paging."""
import time
import requests
import config


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _retry_delay_seconds(resp: requests.Response | None, attempt: int) -> float:
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
    return config.GRAPH_REQUEST_RETRY_BACKOFF_SECONDS * (2 ** attempt)


def _request_json(
    method: str,
    uri: str,
    token: str,
    *,
    headers: dict | None = None,
    json_body: dict | None = None,
):
    req_headers = _headers(token)
    if headers:
        req_headers.update(headers)

    last_exc: Exception | None = None
    for attempt in range(config.GRAPH_REQUEST_MAX_RETRIES + 1):
        resp = None
        try:
            resp = requests.request(
                method,
                uri,
                headers=req_headers,
                json=json_body,
                timeout=config.GRAPH_REQUEST_TIMEOUT_SECONDS,
            )
            if resp.status_code in (429, 503, 504):
                if attempt >= config.GRAPH_REQUEST_MAX_RETRIES:
                    resp.raise_for_status()
                time.sleep(_retry_delay_seconds(resp, attempt))
                continue

            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            if attempt >= config.GRAPH_REQUEST_MAX_RETRIES:
                raise
            time.sleep(_retry_delay_seconds(resp, attempt))
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt >= config.GRAPH_REQUEST_MAX_RETRIES:
                raise
            time.sleep(_retry_delay_seconds(resp, attempt))

    if last_exc:
        raise last_exc
    raise RuntimeError("Graph request failed unexpectedly")


def graph_get_paged(token: str, uri: str) -> list:
    """Fetch all pages from a Graph endpoint and return a flat list of items."""
    results = []
    next_uri = uri
    page_count = 0
    while next_uri:
        page_count += 1
        if page_count > config.GRAPH_PAGED_MAX_PAGES:
            raise RuntimeError(
                f"Graph paging exceeded maximum page limit ({config.GRAPH_PAGED_MAX_PAGES}) for URI: {uri}"
            )

        data = _request_json("GET", next_uri, token)
        if "value" in data:
            results.extend(data["value"])
            next_uri = data.get("@odata.nextLink")
        else:
            results.append(data)
            next_uri = None
    return results


def graph_post(token: str, uri: str, body: dict) -> dict:
    """POST to a Graph endpoint and return the JSON response."""
    return _request_json(
        "POST",
        uri,
        token,
        headers={"Content-Type": "application/json"},
        json_body=body,
    )


def graph_get(token: str, uri: str, headers: dict | None = None) -> dict:
    """GET a single Graph resource."""
    return _request_json("GET", uri, token, headers=headers)


def get_sites_list(token: str, page_size: int = 500) -> list:
    """
    Enumerate SharePoint sites via POST /search/query (delegated Sites.Read.All).
    Falls back to root + subsites if Search API returns nothing.
    """
    all_sites = []
    seen_site_ids: set[str] = set()
    from_offset = 0
    more = True
    search_pages = 0

    while more:
        search_pages += 1
        if search_pages > config.GRAPH_PAGED_MAX_PAGES:
            break

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
                site_id = resource.get("id") or resource.get("webUrl") or ""
                if site_id and site_id not in seen_site_ids:
                    seen_site_ids.add(site_id)
                    all_sites.append(resource)

        more = container.get("moreResultsAvailable", False)
        from_offset += page_size
        if not hits:
            break

    if not all_sites:
        try:
            root = graph_get(token, f"{config.GRAPH_BASE}/sites/root")
            if root:
                root_id = root.get("id") or root.get("webUrl") or ""
                if root_id and root_id not in seen_site_ids:
                    seen_site_ids.add(root_id)
                    all_sites.append(root)
                sub = graph_get_paged(token, f"{config.GRAPH_BASE}/sites/{root['id']}/sites")
                for site in sub:
                    site_id = site.get("id") or site.get("webUrl") or ""
                    if site_id and site_id not in seen_site_ids:
                        seen_site_ids.add(site_id)
                        all_sites.append(site)
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
