# Google Find My Device - Home Assistant Integration

Custom integration for Home Assistant that allows you to **locate** and **ring** your Google devices directly from your smart home dashboard.

## Features

- **Device Tracking** - See your devices on the HA map with GPS coordinates
- **Ring Device** - Make your phone/tablet ring at full volume
- **Stop Sound** - Stop the ringing remotely
- **Locate Device** - Request a fresh GPS location update
- **Multi-device support** - Track Android phones, tablets, and Spot trackers
- **Auto-refresh** - Configurable polling interval (60-3600 seconds)

## How It Works

This integration connects to Google's **Nova API** (the same backend used by Google Find My Device) using:

1. **GCM Checkin** (old Google Cloud Messaging protocol - stable and not blocked)
2. **gpsoauth** for secure token exchange
3. **Protobuf** encoding/decoding for Nova API communication

> **Key difference from other integrations:** We use GCM Checkin instead of Firebase Installations, which Google has been blocking since 2025.

## Installation

### Manual Installation

1. Copy the `custom_components/google_find_device/` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

### HACS (Custom Repository)

1. Open HACS in Home Assistant
2. Click the 3 dots menu → **Custom repositories**
3. Add `https://github.com/DiraSmart/google-find-ha-dira` as **Integration**
4. Search for "Google Find My Device" and install
5. Restart Home Assistant

## Configuration

### Prerequisites

You need a **Google App Password** (not your regular password):

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Navigate to **Security** → **2-Step Verification** → **App passwords**
3. Generate a new app password and save it

### Setup in Home Assistant

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **"Google Find My Device"**
3. Enter your Google email and the App Password
4. Set the polling interval (default: 300 seconds / 5 minutes)

## Entities Created

For each device found, the integration creates:

| Entity | Type | Description |
|--------|------|-------------|
| `device_tracker.google_find_<id>` | Device Tracker | GPS location on the map |
| `button.google_find_<id>_ring` | Button | Ring the device |
| `button.google_find_<id>_stop_sound` | Button | Stop ringing |
| `button.google_find_<id>_locate` | Button | Request fresh location |

## Troubleshooting

### "Invalid credentials" error
- Make sure you're using an **App Password**, not your regular Google password
- Verify 2-Step Verification is enabled on your Google account
- Try generating a new App Password

### Devices appear but no location
- Location data from Google's Nova API may be encrypted (E2EE)
- The integration will show coordinates when available
- Press the **Locate** button to request a fresh position

### Ring command doesn't work
- The device must be online and connected to the internet
- Some devices may not support remote ring

## Technical Details

### Authentication Flow

```
GCM Checkin → android_id + security_token
     ↓
GCM Register → gcm_token (for push responses)
     ↓
gpsoauth Master Login → master_token
     ↓
gpsoauth OAuth → ADM Bearer Token
     ↓
Nova API calls (list devices, ring, locate)
```

### API Endpoints

- **GCM Checkin:** `android.clients.google.com/checkin`
- **GCM Register:** `android.clients.google.com/c2dm/register3`
- **List Devices:** `android.googleapis.com/nova/nbe_list_devices`
- **Execute Action:** `android.googleapis.com/nova/nbe_execute_action`

## License

MIT License

## Credits

- Built by [DiraSmart](https://github.com/DiraSmart)
- Inspired by [GoogleFindMy-HA](https://github.com/BSkando/GoogleFindMy-HA)
