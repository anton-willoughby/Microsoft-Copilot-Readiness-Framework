import os
import tempfile

# Well-known Microsoft Graph Command Line Tools public client
GRAPH_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"

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

# Flask
SECRET_KEY = os.environ.get("FLASK_SECRET", os.urandom(32))
SESSION_TYPE = "filesystem"
SESSION_FILE_DIR = os.path.join(tempfile.gettempdir(), "cr_flask_sessions")
SESSION_PERMANENT = False
