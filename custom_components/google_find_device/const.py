"""Constants for Google Find My Device integration."""

DOMAIN = "google_find_device"

CONF_EMAIL = "email"
CONF_APP_PASSWORD = "app_password"
CONF_POLL_INTERVAL = "poll_interval"

DEFAULT_POLL_INTERVAL = 300  # 5 minutes

PLATFORMS = ["device_tracker", "button"]

# Google API endpoints
NOVA_API_BASE = "https://android.googleapis.com/nova"
NOVA_LIST_DEVICES = f"{NOVA_API_BASE}/nbe_list_devices"
NOVA_EXECUTE_ACTION = f"{NOVA_API_BASE}/nbe_execute_action"

# GCM endpoints (NOT Firebase - these still work)
GCM_CHECKIN_URL = "https://android.clients.google.com/checkin"
GCM_REGISTER_URL = "https://android.clients.google.com/c2dm/register3"

# Google Find My Device app credentials
ADM_PACKAGE = "com.google.android.apps.adm"
ADM_SENDER_ID = "289722593072"
ADM_CERT_SHA1 = "38918a453d07199354f8b19af05ec6562ced5788"
GMS_PACKAGE = "com.google.android.gms"
GMS_CERT_SHA1 = "38918a453d07199354f8b19af05ec6562ced5788"
ADM_SERVICE = "oauth2:https://www.googleapis.com/auth/android_device_manager"

# Nova API headers
NOVA_HEADERS_BASE = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept-Language": "en-US",
    "User-Agent": "fmd/20006320; gzip",
}
