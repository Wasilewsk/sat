"""SAT application object and entry point."""

import wx

from sat import APP_NAME, __version__
from sat.main_frame import MainFrame


class SATApp(wx.App):
    def OnInit(self):
        self.SetAppName(APP_NAME)
        frame = MainFrame()
        frame.Show()
        self.SetTopWindow(frame)
        wx.CallAfter(self._welcome, frame)
        return True

    def _welcome(self, frame):
        from sat.announce import announce
        frame.notebook.SetFocus()
        announce(frame, f"SAT version {__version__} ready. Host: "
                       f"{frame.runner.describe()}. Press F8 for status, "
                       f"F5 to refresh the current tool.")


def main():
    app = SATApp(redirect=False)
    app.MainLoop()


if __name__ == "__main__":
    main()
