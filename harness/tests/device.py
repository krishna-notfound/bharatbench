"""A tiny scripted fake Android device behind the adb Runner interface."""

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
PKG = "com.example.shop"


def make_xml(texts: list[str], clickables: list[str] | None = None, progress: bool = False) -> str:
    nodes = []
    y = 100
    for t in texts:
        nodes.append(
            f'<node text="{t}" resource-id="" class="android.widget.TextView" content-desc="" '
            f'clickable="false" bounds="[0,{y}][500,{y + 50}]" />'
        )
        y += 60
    for t in clickables or []:
        nodes.append(
            f'<node text="{t}" resource-id="" class="android.widget.Button" content-desc="" '
            f'clickable="true" bounds="[0,{y}][500,{y + 50}]" />'
        )
        y += 60
    if progress:
        nodes.append(
            '<node text="" resource-id="" class="android.widget.ProgressBar" content-desc="" '
            'clickable="false" bounds="[0,1000][100,1100]" />'
        )
    return '<?xml version="1.0"?><hierarchy rotation="0">' + "".join(nodes) + "</hierarchy>"


class FakeDevice:
    """screens: UI xml per state; a tap advances to the next screen (sticks on the last)."""

    def __init__(self, screens: list[str], launcher: str = ".MainActivity", booted: bool = True) -> None:
        self.screens = screens
        self.idx = 0
        self.launcher = launcher
        self.foreground = f"{PKG}/{launcher}"
        self.calls: list[list[str]] = []
        self.fail: dict[str, int] = {}  # substring -> rc
        self.raise_on: dict[str, Exception] = {}
        self.after_kill_screen: str | None = None
        self.booted = booted
        self.installed = False
        self.killed = False
        self.change_after_dumps: int | None = None
        self._dumps = 0

    async def __call__(self, argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
        assert timeout > 0
        self.calls.append(argv)
        joined = " ".join(argv)
        for key, exc in self.raise_on.items():
            if key in joined:
                raise exc
        for key, rc in self.fail.items():
            if key in joined:
                return rc, b"", b"failed"
        rest = argv[3:] if argv[1] == "-s" else argv[1:]
        s = " ".join(rest)
        if argv[1] == "version":
            return 0, b"Android Debug Bridge version 1.0.41", b""
        if argv[1] == "devices":
            return 0, b"List of devices attached\nemulator-5554\tdevice\n", b""
        if s.startswith("install"):
            self.installed = True
            return 0, b"Performing Streamed Install\nSuccess\n", b""
        if s == "get-state":
            return 0, b"device\n", b""
        if "getprop sys.boot_completed" in s:
            return 0, b"1\n" if self.booted else b"\n", b""
        if "getprop ro.build.version.release" in s:
            return 0, b"14\n", b""
        if "exec-out cat /sdcard/ui.xml" in s:
            self._dumps += 1
            if self.change_after_dumps and self._dumps == self.change_after_dumps:
                self.idx = min(self.idx + 1, len(self.screens) - 1)
            return 0, self.screens[self.idx].encode(), b""
        if "exec-out screencap" in s:
            return 0, PNG, b""
        if "ResumedActivity" in s:
            return 0, f"  mResumedActivity: ActivityRecord{{ab u0 {self.foreground} t1}}\n".encode(), b""
        if "resolve-activity" in s:
            return 0, f"priority=0\n  {PKG}/{self.launcher}\n".encode(), b""
        if "am start -W" in s:
            return 0, b"Status: ok\nTotalTime: 777\n", b""
        if "input tap" in s:
            self.idx = min(self.idx + 1, len(self.screens) - 1)
        if "am kill" in s:
            self.killed = True
        if "monkey" in s and self.killed and self.after_kill_screen is not None:
            self.screens = [self.after_kill_screen]
            self.idx = 0
            self.foreground = f"{PKG}/{self.launcher}"
        if "df -k" in s:
            return 0, b"Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/x 6000000 1000000 5000000 17% /data\n", b""
        if "dumpsys meminfo" in s:
            return 0, b" TOTAL PSS:    5555            TOTAL RSS: 1\n", b""
        if "logcat -d" in s:
            return 0, b"11-21 10:00:00.100   500   500 I ActivityManager: Start proc 4242:" + PKG.encode() + b"/u0a1 x\n", b""
        return 0, b"", b""
