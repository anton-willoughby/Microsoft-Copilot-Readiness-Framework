import os
import tempfile

# Well-known Microsoft Graph Command Line Tools public client.
# This keeps the consultant workflow simple: no client-created app registration is required.
GRAPH_CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID", "14d82eec-204b-4c2f-b7e8-296a70dab67e")

GRAPH_AUTHORITY = "https://login.microsoftonline.com/common"

GRAPH_SCOPES = [
    "Policy.Read.All",
    "Directory.Read.All",
    "User.Read.All",
    "AuditLog.Read.All",
    "Sites.Read.All",
    "Files.Read.All",
]

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_BETA  = "https://graph.microsoft.com/beta"

# Graph request safety controls
GRAPH_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("GRAPH_REQUEST_TIMEOUT_SECONDS", "30"))
GRAPH_REQUEST_MAX_RETRIES = int(os.environ.get("GRAPH_REQUEST_MAX_RETRIES", "4"))
GRAPH_REQUEST_RETRY_BACKOFF_SECONDS = float(os.environ.get("GRAPH_REQUEST_RETRY_BACKOFF_SECONDS", "1.5"))
GRAPH_PAGED_MAX_PAGES = int(os.environ.get("GRAPH_PAGED_MAX_PAGES", "500"))

# Overshared content assessment safeguards
OVERSHARED_MAX_RUNTIME_SECONDS = int(os.environ.get("OVERSHARED_MAX_RUNTIME_SECONDS", "900"))
OVERSHARED_PROGRESS_INTERVAL_SITES = int(os.environ.get("OVERSHARED_PROGRESS_INTERVAL_SITES", "5"))

# Flask
SECRET_KEY = os.environ.get("FLASK_SECRET", os.urandom(32))
SESSION_TYPE = "filesystem"
SESSION_FILE_DIR = os.path.join(tempfile.gettempdir(), "cr_flask_sessions")
SESSION_PERMANENT = False
