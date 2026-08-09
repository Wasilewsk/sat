"""Screen-reader friendly announcements.

SAT is designed for blind users, so every action reports back.  There is
no reliable way to force every screen reader to speak at once, so we use
a layered approach:

* The status bar always holds the latest announcement.  Orca (Linux)
  reads status bar changes automatically; NVDA users can press
  Insert+PageDown (desktop layout) to hear it at any time.
* Where the wx build ships accessibility events (Linux/AT-SPI builds),
  we also fire a live-region event so Orca speaks immediately.
* Panels move focus to the control that changed (the unit/container
  list or the output pane), because focus changes are announced by
  NVDA, JAWS and Orca alike.
"""

import wx


def announce(window, text):
    """Announce *text* through the status bar and any available
    accessibility event mechanism.  *window* is any wx window inside
    the main frame."""
    tlw = window.GetTopLevelParent()
    sb = tlw.GetStatusBar()
    if sb is not None:
        sb.SetStatusText(text)
    evt = getattr(wx, "wxEVT_ACCESSIBLE_LIVE_REGION_CHANGED", None) or \
        getattr(wx, "wxEVT_ACCESSIBLE_ALERT", None)
    if evt is not None and hasattr(wx.Accessible, "NotifyEvent"):
        try:
            wx.Accessible.NotifyEvent(evt, window, wx.Accessible(), wx.DefaultPosition)
        except Exception:
            pass  # accessibility events are best-effort
