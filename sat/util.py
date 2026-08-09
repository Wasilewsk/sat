"""Small helpers shared by the panels."""

import threading

import wx


def run_in_thread(fn, on_done, on_error=None):
    """Run *fn* in a worker thread.

    The result is delivered to *on_done* and any exception to *on_error*
    (or a message box) on the wx main thread, so the UI never blocks.
    """
    def worker():
        try:
            result = fn()
        except Exception as exc:  # deliver everything to the UI thread
            if on_error is not None:
                wx.CallAfter(on_error, exc)
            else:
                wx.CallAfter(_default_error, exc)
        else:
            wx.CallAfter(on_done, result)

    threading.Thread(target=worker, daemon=True).start()


def _default_error(exc):
    wx.MessageBox(f"An error occurred:\n{exc}", "SAT Error",
                  wx.OK | wx.ICON_ERROR)
