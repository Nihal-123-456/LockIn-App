"""
LockIn - a self-discipline PC lock for Windows 10/11.

What it does
------------
* Lock your PC right now for a duration (e.g. 3 hours).
* Lock your PC for a time period (e.g. today 14:00 - 15:00, overnight works too).
* Weekly schedules (e.g. every Sunday 14:00 - 15:00), any days, overnight OK.
* While locked, an unclosable full-screen shield covers all monitors:
    - blocks Win key, Alt+Tab, Alt+Esc, Alt+F4, Ctrl+Esc, Ctrl+Shift+Esc,
      Alt+Space, and the 5x-Shift Sticky Keys prompt (low-level keyboard hook)
    - re-asserts itself after you sign back in (e.g. after Win+L / Ctrl+Alt+Del)
    - shows a live countdown + rotating motivational quotes
* NO ESCAPE MODE: there is no password and no cancel button. The timer must
  finish. (You chose this. Recovery in an emergency: boot Safe Mode, see README.)
* Starts with Windows into the system tray (optional, recommended).

Requirements: Windows 10/11, Python 3.9+ (with tkinter), pystray + Pillow
(pip install -r requirements.txt). Everything else is pure standard library.

Run:  double-click LockIn.pyw   (or: pythonw LockIn.pyw)
"""

import json
import os
import random
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, time as dtime

# --------------------------------------------------------------------------
# Platform / constants
# --------------------------------------------------------------------------
IS_WINDOWS = (sys.platform == "win32")

APP_NAME = "LockIn"
MIN_LOCK_MINUTES = 5
CLOCK_GUARD_SLACK = 90  # seconds of legitimate clock wobble (NTP, leap seconds) tolerated

if IS_WINDOWS:
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
else:
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".lockin")

CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_PATH = os.path.join(CONFIG_DIR, "lockin.log")
SHOW_FLAG_PATH = os.path.join(CONFIG_DIR, "show_ui.flag")


def resource_path(name):
    """Path to a file shipped next to the script (or inside a PyInstaller bundle)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, name)
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        here = os.getcwd()
    return os.path.join(here, name)


ICON_PATH = resource_path("app.ico")

DAY_NAMES = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
DAY_ORDER = [0, 1, 2, 3, 4, 5, 6]

QUOTES = [
    "Small disciplines, repeated daily, become big results.",
    "You planned this lock for a reason. Trust that decision.",
    "One focused hour beats four distracted ones.",
    "The work you are avoiding is usually the work that matters.",
    "Future you is watching. Make them proud.",
    "Attention is the currency of achievement. Spend it well.",
    "You do not need more time - you need fewer distractions.",
    "Discipline is choosing what you want most over what you want now.",
    "Deep focus is a superpower. This is your training ground.",
    "Protect your attention like it is money - because it is.",
    "Progress loves the person who shows up.",
    "Stay on this side of 'just one quick check'.",
]

DEFAULT_CONFIG = {
    "enabled": True,          # master switch; set false in config.json to disable LockIn
    "motivational": True,     # rotating quotes on the lock screen
    "custom_message": "",     # if set, shown instead of quotes
    "start_with_windows": False,
    "schedules": [],          # {"days":[0..6], "start":"HH:MM", "end":"HH:MM", "enabled":bool}
    "one_time": [],           # {"start":"YYYY-MM-DDTHH:MM", "end":"YYYY-MM-DDTHH:MM"}
}


def log(msg):
    """Append to log file, keep it small, never raise."""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 200000:
            os.truncate(LOG_PATH, 0)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(msg) + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------
# Parsing / formatting helpers
# --------------------------------------------------------------------------
def parse_hm(s):
    """'14:00' -> (14, 0); returns None if invalid."""
    try:
        parts = str(s).strip().split(":")
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return (h, m)
    except Exception:
        pass
    return None


def parse_time_flexible(s):
    """Accepts 14:00, 14.00, 2:00 pm, 2pm, and bare hours ('2' -> 14:00 pm,
    '0' -> 00:00, '14' -> 14:00) -> (h, m) or None."""
    s = ("" if s is None else str(s)).strip().lower().replace(" ", "")
    for fmt in ("%H:%M", "%H.%M", "%I:%M%p", "%I%p"):
        try:
            dt = datetime.strptime(s, fmt)
            return (dt.hour, dt.minute)
        except ValueError:
            continue
    if s.isdigit():
        h = int(s)
        if h == 0:
            return (0, 0)
        if h <= 11:
            return (h + 12, 0)  # a bare 1-11 defaults to afternoon: '2' -> 14:00
        if h <= 23:
            return (h, 0)
    return None


def parse_date_flexible(s):
    """Accepts YYYY-MM-DD (slashes = M/D/Y, dots/dashes = D.M.Y), 'today',
    'tomorrow' -> date or None."""
    s = ("" if s is None else str(s)).strip().lower()
    today = datetime.now().date()
    if s in ("today", "tonight"):
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    # slashes are read month-first (US style); dots and dashes day-first (EU style)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def format_seconds(secs):
    """3725 -> '1h 02m 05s'; 65 -> '1m 05s'; 45 -> '45s'."""
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dh %02dm %02ds" % (h, m, s)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s


def iso_min(dt):
    return dt.isoformat(timespec="minutes")


def _end_delta(hm):
    """Timedelta for an end time; 00:00 counts as 24:00 (midnight of the next day)."""
    h, m = hm
    if h == 0 and m == 0:
        return timedelta(hours=24)
    return timedelta(hours=h, minutes=m)


# --------------------------------------------------------------------------
# Scheduler (pure logic, testable on any OS)
# --------------------------------------------------------------------------
def is_active_now(now, cfg):
    """True if a lock window (one-time or weekly schedule) covers `now`."""
    if not cfg.get("enabled", True):
        return False
    for ot in cfg.get("one_time", []):
        try:
            s = datetime.fromisoformat(ot["start"])
            e = datetime.fromisoformat(ot["end"])
        except Exception:
            continue
        if s <= now < e:
            return True
    dow = now.weekday()  # Mon=0 .. Sun=6
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    t = now - midnight
    for sc in cfg.get("schedules", []):
        if not sc.get("enabled", True):
            continue
        st = parse_hm(sc.get("start", ""))
        en = parse_hm(sc.get("end", ""))
        if st is None or en is None:
            continue
        days = sc.get("days", [])
        st_d = timedelta(hours=st[0], minutes=st[1])
        en_d = _end_delta(en)
        if st_d == en_d:
            continue  # zero-length window
        if st_d < en_d:
            # same-day window [start, end)
            if dow in days and st_d <= t < en_d:
                return True
        else:
            # overnight window: start day [start..24:00) and next day [00:00, end)
            if dow in days and t >= st_d:
                return True
            if ((dow - 1) % 7) in days and t < en_d:
                return True
    return False


def active_until(now, cfg):
    """If a lock is active at `now`, return when it ends (max end covering now)."""
    best = None

    def better(dt):
        nonlocal best
        if best is None or dt > best:
            best = dt

    for ot in cfg.get("one_time", []):
        try:
            s = datetime.fromisoformat(ot["start"])
            e = datetime.fromisoformat(ot["end"])
        except Exception:
            continue
        if s <= now < e:
            better(e)
    dow = now.weekday()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    t = now - midnight
    for sc in cfg.get("schedules", []):
        if not sc.get("enabled", True):
            continue
        st = parse_hm(sc.get("start", ""))
        en = parse_hm(sc.get("end", ""))
        if st is None or en is None:
            continue
        days = sc.get("days", [])
        st_d = timedelta(hours=st[0], minutes=st[1])
        en_d = _end_delta(en)
        if st_d == en_d:
            continue
        if st_d < en_d:
            if dow in days and st_d <= t < en_d:
                better(midnight + en_d)
        else:
            if dow in days and t >= st_d:
                better(midnight + timedelta(days=1) + en_d)
            if ((dow - 1) % 7) in days and t < en_d:
                better(midnight + en_d)
    return best


def next_lock_start(now, cfg):
    """Next future lock start (one-time or weekly), or None."""
    if not cfg.get("enabled", True):
        return None
    best = None

    def better(dt):
        nonlocal best
        if best is None or dt < best:
            best = dt

    for ot in cfg.get("one_time", []):
        try:
            s = datetime.fromisoformat(ot["start"])
        except Exception:
            continue
        if s > now:
            better(s)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(0, 8):
        day = midnight + timedelta(days=d)
        dow = day.weekday()
        for sc in cfg.get("schedules", []):
            if not sc.get("enabled", True):
                continue
            st = parse_hm(sc.get("start", ""))
            en = parse_hm(sc.get("end", ""))
            if st is None or en is None:
                continue
            if dow not in sc.get("days", []):
                continue
            cand = day + timedelta(hours=st[0], minutes=st[1])
            if cand <= now:
                continue
            better(cand)
    return best


# --------------------------------------------------------------------------
# Config load / save
# --------------------------------------------------------------------------
def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update(data)
    except FileNotFoundError:
        pass
    except Exception as e:
        log("config load failed: %r" % (e,))

    # sanitize
    cfg["enabled"] = bool(cfg.get("enabled", True))
    cfg["motivational"] = bool(cfg.get("motivational", True))
    cfg["custom_message"] = str(cfg.get("custom_message", "") or "")
    cfg["start_with_windows"] = bool(cfg.get("start_with_windows", False))

    clean_sch = []
    for s in cfg.get("schedules", []):
        try:
            days = sorted(set(int(d) for d in s.get("days", []) if 0 <= int(d) <= 6))
            st = parse_hm(s.get("start", ""))
            en = parse_hm(s.get("end", ""))
            if not days or st is None or en is None:
                continue
            clean_sch.append({"days": days, "start": "%02d:%02d" % st,
                              "end": "%02d:%02d" % en,
                              "enabled": bool(s.get("enabled", True))})
        except Exception:
            continue
    cfg["schedules"] = clean_sch

    now = datetime.now()
    keep_ot = []
    for ot in cfg.get("one_time", []):
        try:
            s = datetime.fromisoformat(ot["start"])
            e = datetime.fromisoformat(ot["end"])
            if e > now and e > s:
                keep_ot.append({"start": iso_min(s), "end": iso_min(e)})
        except Exception:
            continue
    cfg["one_time"] = keep_ot
    return cfg


def save_config(cfg):
    """Purge expired one-time locks, then write atomically."""
    now = datetime.now()
    keep = []
    for ot in cfg.get("one_time", []):
        try:
            if datetime.fromisoformat(ot["end"]) > now:
                keep.append(ot)
        except Exception:
            continue
    cfg["one_time"] = keep
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except Exception as e:
        log("save_config failed: %r" % (e,))


# --------------------------------------------------------------------------
# Windows API layer (guarded so the logic part imports on any OS)
# --------------------------------------------------------------------------
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    import winreg

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # ---- low-level keyboard hook types ----
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
    WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
    WM_QUIT = 0x0012
    VK_TAB, VK_MENU, VK_CONTROL, VK_SHIFT = 0x09, 0x12, 0x11, 0x10
    VK_ESCAPE, VK_F4, VK_SPACE = 0x1B, 0x73, 0x20
    VK_LWIN, VK_RWIN = 0x5B, 0x5C
    LLKHF_ALTDOWN = 0x20
    ERROR_ALREADY_EXISTS = 183
    SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
    SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

    LRESULT = ctypes.c_ssize_t
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD),
                    ("scanCode", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_void_p)]

    # ---- prototype definitions (correct 64-bit signatures) ----
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = ctypes.c_void_p
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    user32.CallNextHookEx.restype = LRESULT
    user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = ctypes.c_void_p

    _MUTEX_HANDLE = None

    def get_virtual_screen():
        """(x, y, w, h) of the whole virtual desktop (all monitors)."""
        try:
            x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
            if w > 0 and h > 0:
                return int(x), int(y), int(w), int(h)
        except Exception:
            pass
        return 0, 0, 1920, 1080

    def is_workstation_locked():
        """True if the Windows session is on the secure/lock desktop."""
        try:
            h = user32.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS
            if h:
                user32.CloseDesktop(h)
                return False
            return True
        except Exception:
            return False

    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def get_pythonw():
        exe = sys.executable
        if getattr(sys, "frozen", False):
            return '"' + exe + '"'
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        return '"' + (pyw if os.path.exists(pyw) else exe) + '"'

    def script_path_quoted():
        if getattr(sys, "frozen", False):
            return '"' + sys.executable + '"'
        return '"' + os.path.abspath(__file__) + '"'

    def get_start_with_windows():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
                v, _ = winreg.QueryValueEx(k, APP_NAME)
                return bool(v)
        except Exception:
            return False

    def set_start_with_windows(enable):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enable:
                val = "%s %s --hidden" % (get_pythonw(), script_path_quoted())
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, val)
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass

    def acquire_single_instance():
        """False if another LockIn instance is already running."""
        global _MUTEX_HANDLE
        try:
            # "Global\\" covers every session: fast user switching / RDP included
            h = kernel32.CreateMutexW(None, False, "Global\\LockIn_SingleInstance_Mutex")
            err = ctypes.get_last_error()
            if not h:
                return True  # fail-open: allow to run
            _MUTEX_HANDLE = h
            return err != ERROR_ALREADY_EXISTS
        except Exception:
            return True

    def windows_message_box(text, flags=0x40):
        try:
            user32.MessageBoxW(None, text, APP_NAME, flags)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Low-level keyboard hook (blocks escape combos while a lock is active)
# --------------------------------------------------------------------------
class KeyboardHook:
    """WH_KEYBOARD_LL hook on a dedicated thread with its own message pump."""

    def __init__(self):
        self.blocking = False
        self._hook = None
        self._proc = None
        self._thread = None
        self._tid = 0
        self._ready = threading.Event()

    def start(self):
        if not IS_WINDOWS or self._thread is not None:
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="LockIn-KbdHook", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def stop(self):
        if self._thread is None:
            return
        self.blocking = False
        try:
            if self._tid:
                for _ in range(20):
                    if user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0):
                        break
                    time.sleep(0.05)
            self._thread.join(2)
        except Exception as e:
            log("hook stop: %r" % (e,))
        self._thread = None
        self._tid = 0

    def restart(self):
        """Install a fresh hook per lock. LL hooks can be silently dropped by
        Windows (e.g. after resume when the callback is slow), so a new lock
        gets a new hook instead of a stale one."""
        try:
            self.stop()
        except Exception:
            pass
        self.start()

    def reset_shift_counter(self):
        """Forget any half-finished 5x-Shift sequence from the previous lock."""
        KeyboardHook._shift_count = 0
        KeyboardHook._shift_t0 = 0.0

    def _run(self):
        try:
            self._tid = kernel32.GetCurrentThreadId()
            self._proc = HOOKPROC(self._cb)
            self._hook = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        finally:
            self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._hook:
                try:
                    user32.UnhookWindowsHookEx(self._hook)
                except Exception:
                    pass
                self._hook = None

    def _cb(self, ncode, wparam, lparam):
        try:
            if (ncode == 0 and self.blocking and
                    wparam in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP)):
                info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if self._should_block(info, wparam):
                    return 1
        except Exception:
            pass
        return user32.CallNextHookEx(self._hook, ncode, wparam, lparam)

    @staticmethod
    def _async_down(vk):
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    @classmethod
    def _should_block(cls, info, wparam):
        vk = info.vkCode
        is_down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
        if vk in (VK_LWIN, VK_RWIN):
            return True  # block press AND release so the Start menu never opens
        if not is_down:
            return False
        alt = cls._async_down(VK_MENU) or bool(info.flags & LLKHF_ALTDOWN)
        ctrl = cls._async_down(VK_CONTROL)
        if vk == VK_TAB and alt:
            return True                 # Alt+Tab
        if vk == VK_ESCAPE and (alt or ctrl):
            return True                 # Alt+Esc / Ctrl+Esc / Ctrl+Shift+Esc
        if vk == VK_F4 and alt:
            return True                 # Alt+F4
        if vk == VK_SPACE and alt:
            return True                 # Alt+Space window menu
        if vk == VK_SHIFT:
            # suppress the 5x-Shift Sticky Keys prompt
            now = time.time()
            if now - cls._shift_t0 > 3.0:
                cls._shift_count = 0
                cls._shift_t0 = now
            cls._shift_count += 1
            if cls._shift_count >= 5:
                cls._shift_count = 0
                return True
        return False


KeyboardHook._shift_count = 0
KeyboardHook._shift_t0 = 0.0


# --------------------------------------------------------------------------
# GUI (tkinter). Guarded so the pure-logic part imports fine without tkinter.
# --------------------------------------------------------------------------
try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    _HAS_TK = True
except Exception:
    tk = None
    _HAS_TK = False

_BaseTop = tk.Toplevel if _HAS_TK else object


def pick_message(cfg):
    custom = (cfg.get("custom_message") or "").strip()
    if custom:
        return custom
    if cfg.get("motivational", True):
        return random.choice(QUOTES)
    return ""


if _HAS_TK:

    class LockOverlay(_BaseTop):
        """Full-screen, unclosable, topmost shield shown while a lock is active."""

        def __init__(self, master, end_dt, cfg):
            super().__init__(master)
            self.end_dt = end_dt
            self._custom = (cfg.get("custom_message") or "").strip()
            self._quote_bucket = 0
            self._n = 0
            self._red = False
            self._until_text = None

            self.configure(bg="#000000")
            self.overrideredirect(True)
            try:
                self.attributes("-topmost", True)
            except Exception:
                pass
            try:
                if ICON_PATH and os.path.exists(ICON_PATH):
                    self.iconbitmap(ICON_PATH)
            except Exception:
                pass

            self._apply_geometry()

            self.lbl_cap = tk.Label(self, text="TIME REMAINING",
                                    font=("Segoe UI", 11), fg="#9A9A9A", bg="#000000")
            self.lbl_time = tk.Label(self, text="",
                                     font=("Segoe UI", 46, "bold"), fg="#FFFFFF", bg="#000000")
            self.lbl_until = tk.Label(self, text="",
                                      font=("Segoe UI", 12), fg="#BFBFBF", bg="#000000")
            self.lbl_msg = tk.Label(self, text=pick_message(cfg),
                                    font=("Segoe UI", 15, "italic"),
                                    fg="#E4E4E4", bg="#000000",
                                    wraplength=760, justify="center")
            self.lbl_brand = tk.Label(
                self,
                text="LockIn focus shield is active - your PC unlocks when the timer ends.",
                font=("Segoe UI", 9), fg="#6A6A6A", bg="#000000")

            self.lbl_cap.place(relx=0.5, rely=0.36, anchor="center")
            self.lbl_time.place(relx=0.5, rely=0.45, anchor="center")
            self.lbl_until.place(relx=0.5, rely=0.54, anchor="center")
            self.lbl_msg.place(relx=0.5, rely=0.74, anchor="center")
            self.lbl_brand.place(relx=0.5, rely=0.95, anchor="center")

            self.protocol("WM_DELETE_WINDOW", lambda: None)   # cannot be closed
            self.bind("<FocusOut>", self._on_focus_out)
            self.lift()
            self.focus_force()
            self.tick(datetime.now())

        def _apply_geometry(self):
            if IS_WINDOWS:
                x, y, w, h = get_virtual_screen()
            else:
                x, y = 0, 0
                try:
                    w, h = self.master.winfo_screenwidth(), self.master.winfo_screenheight()
                except Exception:
                    w, h = 1920, 1080
            try:
                self.geometry("%dx%d%+d%+d" % (w, h, x, y))
                self.attributes("-topmost", True)
                self.lift()
            except Exception:
                pass

        def refresh_geometry(self):
            self._apply_geometry()

        def _on_focus_out(self, event=None):
            try:
                self.after(150, self.reassert)
            except Exception:
                pass

        def reassert(self):
            """Win the fight for the screen after alt-tabbing away / session unlock."""
            try:
                self.attributes("-topmost", True)
                self.lift()
                if IS_WINDOWS and not is_workstation_locked():
                    self.focus_force()
            except Exception:
                pass

        def tick(self, now):
            try:
                secs = max(0, int((self.end_dt - now).total_seconds()))
                self.lbl_time.config(text=format_seconds(secs))
                if secs <= 60 and not self._red:
                    self._red = True
                    self.lbl_time.config(fg="#FF6B6B")
                if self.end_dt.date() != now.date():
                    fmt = "%a %d %b, %H:%M"   # overnight / multi-day lock
                else:
                    fmt = "%H:%M"
                ut = "Your PC unlocks at %s" % self.end_dt.strftime(fmt)
                if ut != self._until_text:
                    self._until_text = ut
                    self.lbl_until.config(text=ut)
                if not self._custom:
                    bucket = secs // 600
                    if bucket != self._quote_bucket:
                        self._quote_bucket = bucket
                        self.lbl_msg.config(text=random.choice(QUOTES))
                self._n += 1
                if self._n % 30 == 0:
                    self._apply_geometry()
            except Exception:
                log("overlay tick error:\n" + traceback.format_exc())

    class ScheduleDialog(_BaseTop):
        """Add/edit one weekly schedule."""

        def __init__(self, master, item=None):
            super().__init__(master)
            self.title("Weekly schedule")
            self.resizable(False, False)
            try:
                self.transient(master)
            except Exception:
                pass
            self.result = None

            frm = ttk.Frame(self, padding=14)
            frm.pack(fill="both", expand=True)

            ttk.Label(frm, text="Lock on these days:").pack(anchor="w")
            daysf = ttk.Frame(frm)
            daysf.pack(anchor="w", pady=(4, 10))
            self.day_vars = []
            for i in DAY_ORDER:
                v = tk.BooleanVar(value=(item is not None and i in item.get("days", [])))
                cb = ttk.Checkbutton(daysf, text=DAY_NAMES[i], variable=v)
                cb.pack(side="left", padx=4)
                self.day_vars.append((i, v))

            row = ttk.Frame(frm)
            row.pack(fill="x")
            ttk.Label(row, text="From:").pack(side="left")
            self.en_start = ttk.Entry(row, width=9)
            self.en_start.insert(0, item["start"] if item else "14:00")
            self.en_start.pack(side="left", padx=(4, 0))
            ttk.Label(row, text="To:").pack(side="left", padx=(14, 0))
            self.en_end = ttk.Entry(row, width=9)
            self.en_end.insert(0, item["end"] if item else "15:00")
            self.en_end.pack(side="left", padx=(4, 0))

            ttk.Label(frm, foreground="#555555",
                      text="Time format: 14:00 or 2:00 pm (a bare hour like '2' means 2 pm). "
                           "If 'To' is earlier than 'From', "
                           "the lock runs overnight.").pack(anchor="w", pady=(10, 0))

            btnf = ttk.Frame(frm)
            btnf.pack(pady=(14, 0))
            ttk.Button(btnf, text="OK", command=self.on_ok).pack(side="left", padx=6)
            ttk.Button(btnf, text="Cancel", command=self.destroy).pack(side="left", padx=6)

            self.bind("<Return>", lambda e: self.on_ok())
            self.bind("<Escape>", lambda e: self.destroy())
            self.grab_set()

        def on_ok(self):
            days = [i for (i, v) in self.day_vars if v.get()]
            if not days:
                messagebox.showerror(APP_NAME, "Pick at least one day.", parent=self)
                return
            st = parse_time_flexible(self.en_start.get())
            en = parse_time_flexible(self.en_end.get())
            if st is None or en is None:
                messagebox.showerror(APP_NAME, "Invalid time. Use 14:00 or 2:00 pm.", parent=self)
                return
            st_m = st[0] * 60 + st[1]
            en_m = en[0] * 60 + en[1]
            if en_m == 0:
                en_m = 24 * 60  # 00:00 end == midnight
            if st_m == en_m:
                messagebox.showerror(APP_NAME, "Start and end time cannot be the same.", parent=self)
                return
            self.result = {"days": days, "start": "%02d:%02d" % st,
                           "end": "%02d:%02d" % en, "enabled": True}
            self.destroy()

    class SettingsWindow(_BaseTop):
        """Main control panel."""

        def __init__(self, app):
            self.app = app
            super().__init__(app.root)
            self.title("LockIn - PC Lock & Focus Shield")
            self.geometry("680x720")
            self.minsize(620, 560)
            try:
                if ICON_PATH and os.path.exists(ICON_PATH):
                    self.iconbitmap(ICON_PATH)
            except Exception:
                pass

            outer = ttk.Frame(self, padding=10)
            outer.pack(fill="both", expand=True)

            head = ttk.Frame(outer)
            head.pack(fill="x", pady=(0, 8))
            ttk.Label(head, text="LockIn", font=("Segoe UI", 18, "bold")).pack(side="left")
            ttk.Label(head, text="  self-discipline lock for Windows",
                      font=("Segoe UI", 10)).pack(side="left", pady=(8, 0))

            # ---- 1. quick duration lock ----
            g1 = ttk.LabelFrame(outer, text=" 1. Lock right now (duration) ", padding=10)
            g1.pack(fill="x", pady=6)
            row1 = ttk.Frame(g1)
            row1.pack(fill="x")
            ttk.Label(row1, text="Hours:").pack(side="left")
            self.sp_hours = ttk.Spinbox(row1, from_=0, to=72, width=5)
            self.sp_hours.set(0)
            self.sp_hours.pack(side="left", padx=(4, 12))
            ttk.Label(row1, text="Minutes:").pack(side="left")
            self.sp_mins = ttk.Spinbox(row1, from_=0, to=59, increment=5, width=5)
            self.sp_mins.set(30)
            self.sp_mins.pack(side="left", padx=4)
            ttk.Button(row1, text="Lock now", command=self.on_lock_now).pack(side="left", padx=(16, 0))
            rowp = ttk.Frame(g1)
            rowp.pack(fill="x", pady=(8, 0))
            ttk.Label(rowp, text="Presets:").pack(side="left")
            for label, mins in (("30 min", 30), ("1 h", 60), ("2 h", 120),
                                ("3 h", 180), ("4 h", 240)):
                ttk.Button(rowp, text=label, width=7,
                           command=lambda m=mins: self.set_preset(m)).pack(side="left", padx=3)
            ttk.Label(g1, foreground="#B33900",
                      text="Minimum 5 minutes. NO ESCAPE: once the shield is up it stays until "
                           "the timer ends. Plan your breaks first!").pack(anchor="w", pady=(8, 0))

            # ---- 2. period lock ----
            g2 = ttk.LabelFrame(outer, text=" 2. Lock for a time period ", padding=10)
            g2.pack(fill="x", pady=6)
            row2 = ttk.Frame(g2)
            row2.pack(fill="x")
            ttk.Label(row2, text="Date:").pack(side="left")
            self.en_date = ttk.Entry(row2, width=12)
            self.en_date.insert(0, datetime.now().strftime("%Y-%m-%d"))
            self.en_date.pack(side="left", padx=(4, 10))
            ttk.Label(row2, text="From:").pack(side="left")
            self.en_start2 = ttk.Entry(row2, width=9)
            self.en_start2.insert(0, "14:00")
            self.en_start2.pack(side="left", padx=(4, 10))
            ttk.Label(row2, text="To:").pack(side="left")
            self.en_end2 = ttk.Entry(row2, width=9)
            self.en_end2.insert(0, "15:00")
            self.en_end2.pack(side="left", padx=4)
            ttk.Button(row2, text="Schedule lock",
                       command=self.on_schedule_period).pack(side="left", padx=(16, 0))
            ttk.Label(g2, foreground="#555555",
                      text="Date: YYYY-MM-DD, 'today' or 'tomorrow' (slashes = M/D/Y, "
                           "dots or dashes = D.M.Y). Times: 14:00 or 2:00 pm ('2' = 2 pm). "
                           "'To' earlier than 'From' runs overnight.").pack(anchor="w", pady=(8, 0))

            # ---- 3. weekly schedule ----
            g3 = ttk.LabelFrame(outer, text=" 3. Weekly schedule (repeats every week) ", padding=10)
            g3.pack(fill="x", pady=6)
            cols = ("days", "start", "end", "on")
            self.tree = ttk.Treeview(g3, columns=cols, show="headings", height=4)
            self.tree.heading("days", text="Days")
            self.tree.heading("start", text="From")
            self.tree.heading("end", text="To")
            self.tree.heading("on", text="Active")
            self.tree.column("days", width=320)
            self.tree.column("start", width=80, anchor="center")
            self.tree.column("end", width=80, anchor="center")
            self.tree.column("on", width=70, anchor="center")
            self.tree.pack(fill="x")
            rowb = ttk.Frame(g3)
            rowb.pack(fill="x", pady=(6, 0))
            ttk.Button(rowb, text="Add...", command=self.on_add_sched).pack(side="left", padx=3)
            ttk.Button(rowb, text="Edit...", command=self.on_edit_sched).pack(side="left", padx=3)
            ttk.Button(rowb, text="Remove", command=self.on_remove_sched).pack(side="left", padx=3)
            ttk.Button(rowb, text="Enable / Disable",
                       command=self.on_toggle_sched).pack(side="left", padx=3)

            # ---- 4. one-time list ----
            g4 = ttk.LabelFrame(outer, text=" Pending one-time locks ", padding=10)
            g4.pack(fill="x", pady=6)
            self.lb_ontime = tk.Listbox(g4, height=4)
            self.lb_ontime.pack(fill="x")
            ttk.Button(g4, text="Remove selected",
                       command=self.on_remove_ontime).pack(anchor="w", pady=(6, 0))

            # ---- 5. preferences ----
            g5 = ttk.LabelFrame(outer, text=" Preferences ", padding=10)
            g5.pack(fill="x", pady=6)
            self.var_autostart = tk.BooleanVar(value=(get_start_with_windows() if IS_WINDOWS
                                                      else False))
            ttk.Checkbutton(g5, text="Start LockIn automatically when Windows starts (recommended)",
                            variable=self.var_autostart,
                            command=self.on_toggle_autostart).pack(anchor="w")
            self.var_quotes = tk.BooleanVar(value=bool(self.app.cfg.get("motivational", True)))
            ttk.Checkbutton(g5, text="Show rotating motivational quotes on the lock screen",
                            variable=self.var_quotes,
                            command=self.on_pref_change).pack(anchor="w")
            rowm = ttk.Frame(g5)
            rowm.pack(fill="x", pady=(6, 0))
            ttk.Label(rowm, text="Custom lock-screen message:").pack(side="left")
            self.en_msg = ttk.Entry(rowm)
            self.en_msg.insert(0, self.app.cfg.get("custom_message", ""))
            self.en_msg.pack(side="left", padx=8, fill="x", expand=True)
            ttk.Button(rowm, text="Apply", command=self.on_msg_apply).pack(side="left")

            # ---- 6. status ----
            self.lbl_status = tk.Label(outer, text="", font=("Segoe UI", 11, "bold"),
                                       fg="#0A6B0A", bg=self.cget("background")
                                       if hasattr(self, "cget") else "SystemButtonFace",
                                       anchor="w")
            self.lbl_status.pack(fill="x", pady=(10, 0))
            ttk.Label(outer, foreground="#777777",
                      text="Closing this window keeps LockIn running in the tray. "
                           "Use the tray icon -> Exit to quit.").pack(anchor="w", pady=(2, 0))

            self.refresh_lists()
            self.update_status(self.app.status_text(datetime.now()),
                               is_active_now(datetime.now(), self.app.cfg))
            self.protocol("WM_DELETE_WINDOW", self.destroy)

        # ---------- helpers ----------
        def set_preset(self, mins):
            self.sp_hours.set(str(mins // 60))
            self.sp_mins.set(str(mins % 60))

        def _selected_sched_index(self):
            sel = self.tree.selection()
            if not sel:
                messagebox.showinfo(APP_NAME, "Select a schedule row first.", parent=self)
                return None
            return int(sel[0])

        # ---------- actions ----------
        def on_lock_now(self):
            try:
                h = int(float(self.sp_hours.get()))
                m = int(float(self.sp_mins.get()))
                if h < 0 or m < 0 or m > 59 or h > 72:
                    raise ValueError
            except Exception:
                messagebox.showerror(APP_NAME, "Enter valid hours (0-72) and minutes (0-59).",
                                     parent=self)
                return
            self.app.lock_now_minutes(h * 60 + m, parent=self)

        def on_schedule_period(self):
            self.app.schedule_period(self.en_date.get(), self.en_start2.get(),
                                     self.en_end2.get(), parent=self)

        def on_add_sched(self):
            dlg = ScheduleDialog(self)
            self.wait_window(dlg)
            if getattr(dlg, "result", None):
                self.app.cfg["schedules"].append(dlg.result)
                self.app.save_and_recheck()
                self.refresh_lists()

        def on_edit_sched(self):
            idx = self._selected_sched_index()
            if idx is None:
                return
            item = self.app.cfg["schedules"][idx]
            if self.app.item_covers_now("schedules", item):
                messagebox.showerror(
                    APP_NAME,
                    "This schedule's lock is active right now and cannot be edited.",
                    parent=self)
                return
            dlg = ScheduleDialog(self, item)
            self.wait_window(dlg)
            r = getattr(dlg, "result", None)
            if r:
                r["enabled"] = item.get("enabled", True)
                self.app.cfg["schedules"][idx] = r
                self.app.save_and_recheck()
                self.refresh_lists()

        def on_remove_sched(self):
            idx = self._selected_sched_index()
            if idx is None:
                return
            if self.app.item_covers_now("schedules", self.app.cfg["schedules"][idx]):
                messagebox.showerror(
                    APP_NAME,
                    "This schedule's lock is active right now and cannot be removed.",
                    parent=self)
                return
            del self.app.cfg["schedules"][idx]
            self.app.save_and_recheck()
            self.refresh_lists()

        def on_toggle_sched(self):
            idx = self._selected_sched_index()
            if idx is None:
                return
            item = self.app.cfg["schedules"][idx]
            if item.get("enabled", True) and self.app.item_covers_now("schedules", item):
                messagebox.showerror(
                    APP_NAME,
                    "Cannot disable a schedule while its lock is active.",
                    parent=self)
                return
            item["enabled"] = not item.get("enabled", True)
            self.app.save_and_recheck()
            self.refresh_lists()

        def on_remove_ontime(self):
            sel = self.lb_ontime.curselection()
            if not sel:
                messagebox.showinfo(APP_NAME, "Select a pending lock first.", parent=self)
                return
            ot = self.app.cfg["one_time"][sel[0]]
            if self.app.item_covers_now("one_time", ot):
                messagebox.showerror(
                    APP_NAME,
                    "This lock is running right now and cannot be removed.\n"
                    "Wait for the timer to end.",
                    parent=self)
                return
            del self.app.cfg["one_time"][sel[0]]
            self.app.save_and_recheck()
            self.refresh_lists()

        def on_toggle_autostart(self):
            self.app.set_autostart(bool(self.var_autostart.get()), parent=self)

        def on_pref_change(self):
            self.app.cfg["motivational"] = bool(self.var_quotes.get())
            self.app.save_config_only()

        def on_msg_apply(self):
            self.app.cfg["custom_message"] = self.en_msg.get().strip()
            self.app.save_config_only()
            messagebox.showinfo(APP_NAME, "Saved.", parent=self)

        # ---------- refresh ----------
        def refresh_lists(self):
            try:
                for i in self.tree.get_children():
                    self.tree.delete(i)
                for idx, s in enumerate(self.app.cfg.get("schedules", [])):
                    days = ", ".join(DAY_NAMES.get(d, "?") for d in sorted(s.get("days", [])))
                    on = "Yes" if s.get("enabled", True) else "No"
                    self.tree.insert("", "end", iid=str(idx),
                                     values=(days or "-", s.get("start"), s.get("end"), on))
                self.lb_ontime.delete(0, "end")
                for ot in self.app.cfg.get("one_time", []):
                    try:
                        s = datetime.fromisoformat(ot["start"])
                        e = datetime.fromisoformat(ot["end"])
                        txt = "%s  ->  %s" % (s.strftime("%a %d %b %Y, %H:%M"),
                                              e.strftime("%a %d %b %Y, %H:%M"))
                    except Exception:
                        txt = str(ot)
                    self.lb_ontime.insert("end", txt)
            except Exception:
                log("refresh_lists failed:\n" + traceback.format_exc())

        def update_status(self, text, locked=False):
            try:
                self.lbl_status.config(text=text, fg="#B00020" if locked else "#0A6B0A")
            except Exception:
                pass


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------
class App:
    def __init__(self, root, start_hidden=False):
        self.root = root
        self.cfg = load_config()
        self.overlay = None
        self.settings = None
        self.tray = None
        self._was_locked_session = False
        self._clock_guard_ref = None    # time.monotonic() when the guard was (re)anchored
        self._clock_guard_wall = None   # wall-clock time at that anchor
        self._seen_end = None           # longest active_until seen; re-anchor if it grows

        self.hook = KeyboardHook()
        self.hook.start()

        root.title(APP_NAME)
        root.withdraw()
        try:
            if ICON_PATH and os.path.exists(ICON_PATH):
                root.iconbitmap(ICON_PATH)
        except Exception:
            pass
        root.protocol("WM_DELETE_WINDOW", self._hide_root)

        self._setup_tray()
        if not start_hidden:
            root.after(250, self.show_window)
        self.tick()

    # ------------------------------------------------------------------ loop
    def tick(self):
        try:
            self._evaluate()
        except Exception:
            log("tick error:\n" + traceback.format_exc())
        self.root.after(1000, self.tick)

    def _evaluate(self):
        now = self.guarded_now(datetime.now())

        # second-instance handshake: show control panel when the flag file appears
        if os.path.exists(SHOW_FLAG_PATH):
            try:
                os.remove(SHOW_FLAG_PATH)
            except OSError:
                pass
            self.root.after(0, self.show_window)

        # instant re-assert right after the user signs back in
        if IS_WINDOWS:
            wl = is_workstation_locked()
            if self._was_locked_session and not wl and self.overlay is not None:
                self.root.after(0, self.overlay.reassert)
            self._was_locked_session = wl

        active = is_active_now(now, self.cfg)
        if active:
            end = active_until(now, self.cfg) or (now + timedelta(minutes=1))
            if self._seen_end is None or end > self._seen_end:
                # First tick of a new lock, or an overlapping window extended
                # it: re-anchor the anti-clock-tampering guard from here.
                self._clock_guard_ref = time.monotonic()
                self._clock_guard_wall = now
                self._seen_end = end
            need_create = self.overlay is None
            if not need_create:
                try:
                    if not self.overlay.winfo_exists():
                        self.overlay = None
                        need_create = True
                except Exception:
                    self.overlay = None
                    need_create = True
            if need_create:
                self.overlay = self._create_overlay(end)
                if self.overlay is not None:
                    self.hook.restart()   # fresh LL hook per lock beats a stale one
                    self.hook.blocking = True
                    self.notify_tray(APP_NAME, "PC is locked until %s." % end.strftime("%H:%M"))
            else:
                try:
                    self.overlay.end_dt = end
                    self.overlay.tick(now)
                    if now.second % 3 == 0:
                        self.overlay.reassert()
                except Exception:
                    log("overlay update failed:\n" + traceback.format_exc())
                    try:
                        self.overlay.destroy()
                    except Exception:
                        pass
                    self.overlay = None
        else:
            if self._seen_end is not None:
                # Lock ended: release the guard anchors and stale hook state.
                self._clock_guard_ref = None
                self._clock_guard_wall = None
                self._seen_end = None
                self.hook.reset_shift_counter()
            if self.overlay is not None:
                self._close_overlay()

        if self.settings is not None:
            try:
                if self.settings.winfo_exists():
                    self.settings.update_status(self.status_text(now), active)
                else:
                    self.settings = None
            except Exception:
                self.settings = None

    def _create_overlay(self, end):
        try:
            return LockOverlay(self.root, end, self.cfg)
        except Exception:
            log("overlay create failed:\n" + traceback.format_exc())
            return None  # fail-open: never trap the user because of a GUI bug

    def _close_overlay(self):
        self.hook.blocking = False
        self.hook.reset_shift_counter()
        try:
            self.overlay.destroy()
        except Exception:
            pass
        self.overlay = None
        self.notify_tray(APP_NAME, "Lock ended - welcome back!")
        self.refresh_settings_lists()

    # ------------------------------------------------------------- tray icon
    def _setup_tray(self):
        try:
            import pystray
        except Exception as e:
            log("pystray not available (%r) - tray icon disabled" % (e,))
            self.tray = None
            return
        try:
            image = self._tray_image()
            if image is None:
                self.tray = None
                return
            menu = pystray.Menu(
                pystray.MenuItem("Open LockIn", self._tray_open, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Lock for 30 minutes",
                                 lambda *a: self._tray_call(lambda: self.lock_now_minutes(30))),
                pystray.MenuItem("Lock for 1 hour",
                                 lambda *a: self._tray_call(lambda: self.lock_now_minutes(60))),
                pystray.MenuItem("Lock for 2 hours",
                                 lambda *a: self._tray_call(lambda: self.lock_now_minutes(120))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", self._tray_exit,
                                 enabled=lambda item: not self.is_locked()),
            )
            self.tray = pystray.Icon(APP_NAME, image, APP_NAME, menu)
            self.tray.run_detached()
        except Exception:
            log("tray init failed:\n" + traceback.format_exc())
            self.tray = None

    def _tray_image(self):
        try:
            from PIL import Image, ImageDraw
            if ICON_PATH and os.path.exists(ICON_PATH):
                img = Image.open(ICON_PATH).convert("RGBA")
                if img.size != (64, 64):
                    img = img.resize((64, 64))
                return img
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([2, 2, 61, 61], radius=14, fill=(24, 52, 100, 255))
            d.arc([22, 10, 42, 34], start=180, end=360, fill=(255, 255, 255, 255), width=3)
            d.rounded_rectangle([18, 28, 46, 54], radius=5, fill=(255, 255, 255, 255))
            d.ellipse([29, 37, 36, 44], fill=(24, 52, 100, 255))
            d.rectangle([31, 41, 34, 50], fill=(24, 52, 100, 255))
            return img
        except Exception:
            return None

    def _tray_open(self, *a):
        self.root.after(0, self.show_window)

    def _tray_call(self, fn):
        self.root.after(0, fn)

    def _tray_exit(self, *a):
        self.root.after(0, self.exit_app)

    def notify_tray(self, title, msg):
        try:
            if self.tray is not None:
                self.tray.notify(msg, title)
        except Exception:
            pass

    # ------------------------------------------------------------------ UI
    def show_window(self, *a):
        try:
            if self.settings is not None and self.settings.winfo_exists():
                self.settings.deiconify()
                self.settings.lift()
                self.settings.focus_force()
                return
        except Exception:
            self.settings = None
        try:
            self.settings = SettingsWindow(self)
        except Exception:
            log("settings window failed:\n" + traceback.format_exc())

    def _hide_root(self):
        self.root.withdraw()

    def refresh_settings_lists(self):
        try:
            if self.settings is not None and self.settings.winfo_exists():
                self.settings.refresh_lists()
        except Exception:
            pass

    # ------------------------------------------------------------- actions
    def is_locked(self):
        return self.overlay is not None

    def guarded_now(self, now):
        """Clamp wall-clock reads while a lock is active, so setting the system
        clock forward cannot shorten the lock. Clock moves backward are allowed
        (they can only ever lengthen the lock)."""
        if self._clock_guard_ref is None:
            return now
        elapsed = time.monotonic() - self._clock_guard_ref
        ceiling = self._clock_guard_wall + timedelta(seconds=elapsed + CLOCK_GUARD_SLACK)
        if now > ceiling:
            return ceiling
        return now

    def item_covers_now(self, kind, item):
        """Return the end time if this single schedule/one-time item would
        lock `now`, else None. Used to protect active entries in the UI."""
        now = self.guarded_now(datetime.now())
        test = {"enabled": True, kind: [item]}
        if is_active_now(now, test):
            return active_until(now, test)
        return None

    def save_config_only(self):
        save_config(self.cfg)

    def save_and_recheck(self):
        save_config(self.cfg)
        try:
            self._evaluate()
        except Exception:
            log("recheck failed:\n" + traceback.format_exc())
        self.refresh_settings_lists()

    def lock_now_minutes(self, total_minutes, parent=None):
        if self.is_locked():
            self.notify_tray(APP_NAME, "Already locked.")
            return False
        if total_minutes < MIN_LOCK_MINUTES:
            messagebox.showerror(APP_NAME, "Minimum lock time is %d minutes." % MIN_LOCK_MINUTES,
                                 parent=parent)
            return False
        if total_minutes > 360:
            if not messagebox.askyesno(
                    APP_NAME,
                    "This will lock the PC for %s with NO escape (not even a password).\n\n"
                    "Are you sure?" % format_seconds(total_minutes * 60), parent=parent):
                return False
        now = datetime.now()
        self.cfg["one_time"].append({"start": iso_min(now),
                                     "end": iso_min(now + timedelta(minutes=total_minutes))})
        self.save_and_recheck()
        self.notify_tray(APP_NAME, "PC locked for %s." % format_seconds(total_minutes * 60))
        return True

    def schedule_period(self, date_s, start_s, end_s, parent=None):
        d = parse_date_flexible(date_s)
        if d is None:
            messagebox.showerror(APP_NAME, "Invalid date. Use YYYY-MM-DD, 'today' or 'tomorrow'.",
                                 parent=parent)
            return False
        st = parse_time_flexible(start_s)
        en = parse_time_flexible(end_s)
        if st is None or en is None:
            messagebox.showerror(APP_NAME, "Invalid time. Use 14:00 or 2:00 pm.", parent=parent)
            return False
        start_dt = datetime.combine(d, dtime(st[0], st[1]))
        end_dt = datetime.combine(d, dtime(en[0], en[1]))
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)  # overnight
        mins = int((end_dt - start_dt).total_seconds() // 60)
        if mins < MIN_LOCK_MINUTES:
            messagebox.showerror(APP_NAME, "The period must be at least %d minutes."
                                 % MIN_LOCK_MINUTES, parent=parent)
            return False
        if mins > 360:
            if not messagebox.askyesno(
                    APP_NAME,
                    "This period lock lasts %s with NO escape.\n\nContinue?"
                    % format_seconds(mins * 60), parent=parent):
                return False
        self.cfg["one_time"].append({"start": iso_min(start_dt), "end": iso_min(end_dt)})
        self.save_and_recheck()
        messagebox.showinfo(APP_NAME, "Lock scheduled:\n%s  ->  %s"
                            % (start_dt.strftime("%a %d %b %Y, %H:%M"),
                               end_dt.strftime("%a %d %b %Y, %H:%M")), parent=parent)
        return True

    def set_autostart(self, enable, parent=None):
        if IS_WINDOWS:
            try:
                set_start_with_windows(enable)
            except Exception as e:
                log("autostart failed: %r" % (e,))
                messagebox.showerror(APP_NAME, "Could not update the Windows startup entry:\n%s"
                                     % (e,), parent=parent)
                return
        self.cfg["start_with_windows"] = bool(enable)
        self.save_config_only()

    def status_text(self, now):
        if is_active_now(now, self.cfg):
            end = active_until(now, self.cfg)
            until = end.strftime("%H:%M") if end else "?"
            rem = format_seconds((end - now).total_seconds()) if end else "?"
            return "LOCKED - shield up until %s   (%s remaining)" % (until, rem)
        nxt = next_lock_start(now, self.cfg)
        if nxt is None:
            return "Unlocked. No locks scheduled."
        if nxt.date() == now.date():
            when = "today at " + nxt.strftime("%H:%M")
        elif nxt.date() == (now + timedelta(days=1)).date():
            when = "tomorrow at " + nxt.strftime("%H:%M")
        else:
            when = nxt.strftime("%a %d %b at %H:%M")
        return "Unlocked. Next lock: %s." % when

    def exit_app(self):
        if self.is_locked():
            self.notify_tray(APP_NAME, "A lock is active. LockIn cannot exit now.")
            return
        try:
            self.hook.stop()
        except Exception:
            pass
        try:
            if self.tray is not None:
                self.tray.stop()
        except Exception:
            pass
        save_config(self.cfg)
        try:
            self.root.destroy()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def notify_already_running():
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        open(SHOW_FLAG_PATH, "w").close()
    except OSError:
        pass
    if IS_WINDOWS:
        windows_message_box("LockIn is already running in the tray.\n"
                            "Opening its control panel...", 0x40)


def main():
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except OSError:
        pass
    if IS_WINDOWS and not acquire_single_instance():
        notify_already_running()
        return
    log("=== %s started (pid %d, python %s) ===" % (APP_NAME, os.getpid(), sys.version))
    if IS_WINDOWS:
        # Per-monitor DPI awareness: crisp countdown text and true physical
        # pixel geometry on scaled high-DPI displays and multi-monitor setups.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    if not _HAS_TK:
        if IS_WINDOWS:
            windows_message_box("Python's tkinter module is missing.\n\n"
                                "Reinstall Python from python.org and keep\n"
                                "'tcl/tk and IDLE' ticked in the installer.", 0x30)
        log("tkinter missing - cannot start UI")
        return
    start_hidden = "--hidden" in sys.argv
    root = tk.Tk()
    root.withdraw()
    app = App(root, start_hidden=start_hidden)
    root.mainloop()
    log("=== %s exited ===" % APP_NAME)


if __name__ == "__main__":
    main()
