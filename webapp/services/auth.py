"""MSAL device-code authentication for the Copilot Readiness web app."""
import msal
import config


def get_msal_app() -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        client_id=config.GRAPH_CLIENT_ID,
        authority=config.GRAPH_AUTHORITY,
    )


def start_device_flow() -> dict:
    """Initiate device-code flow. Returns the flow dict containing user_code, verification_uri, etc."""
    app = get_msal_app()
    flow = app.initiate_device_flow(scopes=config.GRAPH_SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Failed to initiate device flow: {flow.get('error_description', flow)}")
    return flow


def acquire_token_by_device_flow(flow: dict) -> dict:
    """Poll for token completion. Returns MSAL token response dict or raises on failure."""
    app = get_msal_app()
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", str(result)))
    return result


def get_cached_token(account_info: dict | None) -> str | None:
    """Try to silently refresh a cached token. Returns access_token string or None."""
    if not account_info:
        return None
    app = get_msal_app()
    accounts = app.get_accounts(username=account_info.get("username"))
    if not accounts:
        return None
    result = app.acquire_token_silent(scopes=config.GRAPH_SCOPES, account=accounts[0])
    if result and "access_token" in result:
        return result["access_token"]
    return None
