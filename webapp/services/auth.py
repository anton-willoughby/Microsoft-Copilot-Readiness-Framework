"""MSAL interactive browser authentication for the Copilot Readiness web app."""
import msal
import config


def get_msal_app() -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        client_id=config.GRAPH_CLIENT_ID,
        authority=config.GRAPH_AUTHORITY,
    )


def acquire_token_interactive() -> dict:
    """Open Microsoft interactive sign-in and return an MSAL token response."""
    app = get_msal_app()
    result = app.acquire_token_interactive(
        scopes=config.GRAPH_SCOPES,
        prompt="select_account",
    )
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", str(result)))
    return result


def reacquire_token_for_consent() -> dict:
    """Force a fresh interactive sign-in with explicit consent prompt.

    Use this when a cached token is missing required scopes — the user sees
    the Microsoft consent screen for any scope not yet approved.
    """
    app = get_msal_app()
    result = app.acquire_token_interactive(
        scopes=config.GRAPH_SCOPES,
        prompt="consent",
    )
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", str(result)))
    return result


def check_missing_scopes(token_result: dict) -> list[str]:
    """Return scopes from GRAPH_SCOPES that were NOT included in the token response.

    MSAL returns granted scopes in ``token_result["scope"]`` as a space-separated
    string.  We compare normalised lower-case short names so that URL-form scopes
    (``https://graph.microsoft.com/Foo.Bar``) are handled correctly.
    """
    raw = token_result.get("scope", "")
    granted = {s.lower().split("/")[-1] for s in raw.split() if s}
    missing = [s for s in config.GRAPH_SCOPES if s.lower() not in granted]
    return missing


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
