"""SKYNET COMMAND
Voice macros for games (like VoiceAttack), powered by the Whisper speech AI.
Say a phrase ("hellbomb", "five hundred kg") -> the app presses the keys for you.
Profiles are plain JSON files in ./profiles (one per game)."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PORTABLE = os.path.isdir(os.path.join(ROOT, "runtime", "python"))   # shared package: own Python in ..\runtime, models in ..\models
if PORTABLE: os.environ.setdefault("HF_HOME", os.path.join(ROOT, "models"))    # speech models stay inside the app folder
LOG_DIR = os.path.join(HERE, "logs"); os.makedirs(LOG_DIR, exist_ok=True)
if sys.stderr is None or sys.executable.lower().endswith("pythonw.exe"):
    sys.stderr = open(os.path.join(LOG_DIR, "app-errors.txt"), "a", encoding="utf-8", buffering=1)

import ctypes, json, math, queue, random, re, subprocess, threading, time, traceback, zlib, difflib
import xml.etree.ElementTree as ET
from collections import deque
WIN = os.name == "nt"
try:
    import numpy as np
except ImportError:  # double-clicked with the wrong Python -> restart with the app's own
    for _p in (os.path.join(ROOT, "runtime", "python", "pythonw.exe"), os.path.join(HERE, "venv", "Scripts", "pythonw.exe"),
               os.path.join(ROOT, "Claude Captions", "venv", "Scripts", "pythonw.exe")):
        if os.path.exists(_p) and os.path.normcase(sys.executable) != os.path.normcase(_p):
            subprocess.Popen([_p, os.path.abspath(__file__)]); sys.exit(0)
    raise

if WIN and __name__ == "__main__":
    _k32 = ctypes.windll.kernel32
    _MUTEX = _k32.CreateMutexW(None, False, "SkynetCommand_SingleInstance")
    if _k32.GetLastError() == 183:
        _h = ctypes.windll.user32.FindWindowW(None, "SKYNET COMMAND")
        if _h: ctypes.windll.user32.ShowWindow(_h, 9); ctypes.windll.user32.SetForegroundWindow(_h)
        sys.exit(0)
    try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception: pass

# GPU: let CUDA find cuBLAS / cuDNN (installed by Skynet Alpha's "Install GPU boost.bat")
GPU_LIBS = False
for _base in dict.fromkeys([sys.prefix, os.path.join(HERE, "venv"), os.path.join(os.path.dirname(HERE), "Claude Captions", "venv")]):
    for _sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
        _bin = os.path.join(_base, "Lib", "site-packages", "nvidia", _sub, "bin")
        if os.path.isdir(_bin):
            GPU_LIBS = GPU_LIBS or _sub == "cublas"
            try: os.add_dll_directory(_bin)
            except Exception: pass
            os.environ["PATH"] = _bin + os.pathsep + os.environ.get("PATH", "")

PROFILE_DIR = os.path.join(HERE, "profiles"); os.makedirs(PROFILE_DIR, exist_ok=True)
SFX_DIR = os.path.join(HERE, "sfx"); os.makedirs(SFX_DIR, exist_ok=True)
SETTINGS_FILE = os.path.join(HERE, "settings.json")
SR = 16000

BG, PANEL, GRID = "#06070A", "#0D0F14", "#1B1F28"
RED, RED_DIM, ORANGE, WHITE, DIM = "#FF3131", "#5A1414", "#FF8A1F", "#F2F2F2", "#666B78"
GREEN = "#46F08A"
MONO = "Consolas"

DEFAULTS = {
    "profile": "Helldivers 2", "mic": "", "model": "auto", "device": "auto", "language": "English",
    "mode": "always", "ptt_key": "mouse4", "toggle_key": "ctrl+alt+m", "sensitivity": 5, "silence_ms": 380,
    "threshold": 0.78, "bias": True, "focus_only": True, "auto_switch": True, "sounds": True, "voice": True,
    "listening": True, "ai_on": True, "ontop": False, "geometry": "", "key_ms": 60,
    "volume": 70, "ui_sounds": True, "ptt_sounds": True, "fail_sound": "ptt only", "confirm_voice": False,
    "ai_load": "balanced", "gpu_mem": "saver", "cpu_threads": 4, "game_first": True, "pause_anim": True, "max_age": 3.0,
}
MODEL_CHOICES = ["auto", "distil-small.en", "small.en", "base.en", "distil-medium.en", "medium.en", "large-v3-turbo", "distil-large-v3", "tiny.en", "small", "medium"]
DEFAULT_MIC = "(Windows default microphone)"
LANGS = {"English": "en", "Türkçe (Turkish)": "tr", "Deutsch (German)": "de", "Auto": None}


def lerp(a, b, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    a = [int(a[i:i + 2], 16) for i in (1, 3, 5)]; b = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(a, b))


# ======================================================================  keys
KEYMAP = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "backspace": 0x08,
          "shift": 0x10, "lshift": 0xA0, "rshift": 0xA1, "ctrl": 0x11, "lctrl": 0xA2, "rctrl": 0xA3,
          "alt": 0x12, "lalt": 0xA4, "ralt": 0xA5, "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C, "capslock": 0x14,
          "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "insert": 0x2D, "delete": 0x2E, "del": 0x2E,
          "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
          "numlock": 0x90, "scrolllock": 0x91, "pause": 0x13, "printscreen": 0x2C,
          "num*": 0x6A, "num+": 0x6B, "num-": 0x6D, "num.": 0x6E, "num/": 0x6F, "numenter": 0x0D,
          "minus": 0xBD, "-": 0xBD, "equals": 0xBB, "=": 0xBB, "comma": 0xBC, ",": 0xBC, "period": 0xBE, ".": 0xBE,
          "slash": 0xBF, "/": 0xBF, "semicolon": 0xBA, ";": 0xBA, "quote": 0xDE, "'": 0xDE, "lbracket": 0xDB, "[": 0xDB,
          "rbracket": 0xDD, "]": 0xDD, "backslash": 0xDC, "\\": 0xDC, "grave": 0xC0, "`": 0xC0, "tilde": 0xC0,
          "mouse1": 0x01, "lmb": 0x01, "mouse2": 0x02, "rmb": 0x02, "mouse3": 0x04, "mmb": 0x04, "mouse4": 0x05, "mouse5": 0x06}
for _c in "abcdefghijklmnopqrstuvwxyz": KEYMAP[_c] = ord(_c.upper())
for _d in range(10): KEYMAP[str(_d)] = 0x30 + _d; KEYMAP[f"num{_d}"] = 0x60 + _d
for _f in range(1, 25): KEYMAP[f"f{_f}"] = 0x6F + _f
VK2NAME = {}
for _n, _v in KEYMAP.items(): VK2NAME.setdefault(_v, _n)
VK2NAME.update({0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0x0D: "enter", 0x1B: "esc", 0x2E: "delete", 0x21: "pageup", 0x22: "pagedown",
                0xBD: "minus", 0xBB: "equals", 0xBC: "comma", 0xBE: "period", 0xBF: "slash", 0xBA: "semicolon", 0xDE: "quote",
                0xDB: "lbracket", 0xDD: "rbracket", 0xDC: "backslash", 0xC0: "grave", 0x5B: "lwin", 0x01: "mouse1",
                0x02: "mouse2", 0x04: "mouse3"})
EXTENDED = {0xA3, 0xA5, 0x5B, 0x5C, 0x26, 0x28, 0x25, 0x27, 0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x6F, 0x2C}
MOUSE_VK = {0x01: (0x0002, 0x0004, 0), 0x02: (0x0008, 0x0010, 0), 0x04: (0x0020, 0x0040, 0),
            0x05: (0x0080, 0x0100, 1), 0x06: (0x0080, 0x0100, 2)}


def key_vk(name):
    n = name.strip().lower()
    if n in KEYMAP: return KEYMAP[n]
    m = re.fullmatch(r"vk(\d+)", n) or re.fullmatch(r"0x([0-9a-f]+)", n)
    if m: return int(m.group(1), 16 if n.startswith("0x") else 10)
    raise ValueError(f"unknown key '{name}'")


def combo_vks(text):
    text = (text or "").strip()
    if not text: return []
    return [key_vk(k) for k in re.split(r"\s*\+\s*", text) if k] if text != "+" else [KEYMAP["num+"]]


if WIN:
    import ctypes.wintypes as wt
    user32 = ctypes.WinDLL("user32", use_last_error=True); kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]

    class _IU(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",); _fields_ = [("type", wt.DWORD), ("u", _IU)]

    user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.MapVirtualKeyW.argtypes = (wt.UINT, wt.UINT); user32.MapVirtualKeyW.restype = wt.UINT
    user32.GetAsyncKeyState.argtypes = (ctypes.c_int,); user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetForegroundWindow.restype = wt.HWND
    user32.GetWindowThreadProcessId.argtypes = (wt.HWND, ctypes.POINTER(wt.DWORD))
    kernel32.OpenProcess.restype = wt.HANDLE; kernel32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
    kernel32.QueryFullProcessImageNameW.argtypes = (wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD))
    kernel32.CloseHandle.argtypes = (wt.HANDLE,)

    def _send(inp):
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _kb(vk, scan, flags):
        i = INPUT(); i.type = 1; i.ki = KEYBDINPUT(vk, scan, flags, 0, 0); return i

    def _ms(data, flags):
        i = INPUT(); i.type = 0; i.mi = MOUSEINPUT(0, 0, data, flags, 0, 0); return i

    def key_event(vk, up):
        """Hardware scan codes (DirectInput games ignore plain virtual keys)."""
        if vk in MOUSE_VK:
            dn, upf, data = MOUSE_VK[vk]
            _send(_ms(data, upf if up else dn)); return
        scan = user32.MapVirtualKeyW(vk, 0)
        if scan:
            fl = 0x0008 | (0x0001 if vk in EXTENDED else 0) | (0x0002 if up else 0)
            _send(_kb(0, scan, fl))
        else:
            _send(_kb(vk, 0, 0x0002 if up else 0))

    def type_char(ch):
        for up in (0, 0x0002):
            _send(_kb(0, ord(ch), 0x0004 | up))

    def is_down(vk): return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    def foreground_exe():
        try:
            hwnd = user32.GetForegroundWindow()
            if not hwnd: return ""
            pid = wt.DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            h = kernel32.OpenProcess(0x1000, False, pid.value)
            if not h: return ""
            buf = ctypes.create_unicode_buffer(1024); n = wt.DWORD(1024)
            ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)); kernel32.CloseHandle(h)
            return os.path.basename(buf.value).lower() if ok else ""
        except Exception:
            return ""
    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class _MONINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", _RECT), ("rcWork", _RECT), ("dwFlags", wt.DWORD)]

    def _exe_of(hwnd):
        pid = wt.DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)
        if not h: return ""
        buf = ctypes.create_unicode_buffer(1024); n = wt.DWORD(1024)
        ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)); kernel32.CloseHandle(h)
        return os.path.basename(buf.value).lower() if ok else ""

    user32.MonitorFromWindow.restype = ctypes.c_void_p; user32.MonitorFromWindow.argtypes = (wt.HWND, wt.DWORD)
    user32.GetWindow.restype = wt.HWND; user32.GetWindow.argtypes = (wt.HWND, wt.UINT)
    user32.GetWindowRect.argtypes = (wt.HWND, ctypes.POINTER(_RECT))
    user32.GetMonitorInfoW.argtypes = (ctypes.c_void_p, ctypes.POINTER(_MONINFO))
    user32.IsWindowVisible.argtypes = (wt.HWND,); user32.GetWindowTextLengthW.argtypes = (wt.HWND,)
    user32.GetWindowTextW.argtypes = (wt.HWND, wt.LPWSTR, ctypes.c_int)

    def foreground_info():
        """(exe of the window in front, does it cover its whole monitor = game / full screen)"""
        try:
            hwnd = user32.GetForegroundWindow()
            if not hwnd: return "", False
            r = _RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
            mon = user32.MonitorFromWindow(hwnd, 2); mi = _MONINFO(); mi.cbSize = ctypes.sizeof(_MONINFO)
            user32.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi)); m = mi.rcMonitor
            full = r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom
            return _exe_of(hwnd), full
        except Exception:
            return "", False

    def list_windows():
        """programs with a visible window right now: [(exe, title)]"""
        out = {}
        CB = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def cb(hwnd, _):
            try:
                if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0 and not user32.GetWindow(hwnd, 4):
                    t = ctypes.create_unicode_buffer(256); user32.GetWindowTextW(hwnd, t, 256); exe = _exe_of(hwnd)
                    if exe and exe not in IGNORE_EXE and exe not in out: out[exe] = t.value
            except Exception: pass
            return True
        user32.EnumWindows(CB(cb), 0)
        return sorted(out.items())
else:   # lets the logic be tested on other systems
    SENT = []
    def foreground_info(): return "", False
    def list_windows(): return []
    def key_event(vk, up): SENT.append((vk, bool(up)))
    def type_char(ch): SENT.append(("char", ch))
    def is_down(vk): return False
    def foreground_exe(): return ""


def combo_down(vks): return bool(vks) and all(is_down(v) for v in vks)


IGNORE_EXE = {"explorer.exe", "python.exe", "pythonw.exe", "claude.exe", "searchhost.exe", "shellexperiencehost.exe", "startmenuexperiencehost.exe",
              "textinputhost.exe", "applicationframehost.exe", "systemsettings.exe", "lockapp.exe", "taskmgr.exe", "steamwebhelper.exe"}


def spoken_name(name):
    """'NUX-223 Hellbomb' -> 'Hellbomb', 'A/MG-43 Machine Gun Sentry' -> 'Machine Gun Sentry', 'Eagle 500kg Bomb' stays"""
    first, _, rest = name.partition(" ")
    return rest if rest and re.search(r"\d", first) and re.search(r"[-/]", first) else name


# ======================================================================  macro actions
STRAT_DEFAULT = {"menu_key": "lctrl", "menu_mode": "hold", "up": "up", "down": "down", "left": "left", "right": "right"}
ARROWS = {"↑": "U", "↓": "D", "←": "L", "→": "R", "U": "U", "D": "D", "L": "L", "R": "R"}
ACTION_HELP = ("one action per line   (key speed for every macro: ⚙ OPTIONS → MACRO SPEED)\n"
               "  press ctrl+shift+s     tap keys together   (press g 0.5 = hold 0.5 s)\n"
               "  down lctrl / up lctrl   hold / release a key       hold e 2   = hold e for 2 s\n"
               "  wait 0.2  (or 200ms)    click left 2               type gg wp\n"
               "  stratagem UDRLU  (or ↑↓→←↑)   uses this profile's stratagem keys\n"
               "  say Hellbomb inbound    spoken reply               # comment\n"
               "keys: a-z 0-9 f1-f24 space enter esc tab shift ctrl alt lctrl rctrl up down left right\n"
               "      num0-num9 mouse1-mouse5 insert delete home end pageup pagedown capslock ...")


def parse_time(s):
    s = s.strip().lower()
    if s.endswith("ms"): return float(s[:-2]) / 1000
    if s.endswith("s"): return float(s[:-1])
    return float(s)


def compile_actions(lines, profile, key_ms=60):
    """text actions -> primitive ops [('down', vk) | ('up', vk) | ('wait', s) | ('type', txt) | ('say', txt)]
    key_ms = total time per key press (half held down, half gap) - one speed for every macro."""
    ops, errs = [], []
    strat = dict(STRAT_DEFAULT); strat.update((profile or {}).get("stratagem") or {})
    ms = max(4.0, float(key_ms or 60)) / 1000.0
    hold_default = kh = kg = ms / 2
    od = max(0.05, ms)   # the stratagem menu needs a moment to open
    for n, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"): continue
        verb, _, rest = line.partition(" "); verb = verb.lower(); rest = rest.strip()
        try:
            if verb in ("press", "tap", "key"):
                parts = rest.split()
                if not parts: raise ValueError("which key?")
                hold = parse_time(parts[1]) if len(parts) > 1 else hold_default
                vks = combo_vks(parts[0])
                ops += [("down", v) for v in vks] + [("wait", hold)] + [("up", v) for v in reversed(vks)]
            elif verb in ("down", "up"):
                vks = combo_vks(rest)
                if not vks: raise ValueError("which key?")
                ops += [(verb, v) for v in (vks if verb == "down" else reversed(vks))]
            elif verb == "hold":
                parts = rest.split()
                if len(parts) < 2: raise ValueError("use: hold <key> <seconds>")
                vks = combo_vks(parts[0])
                ops += [("down", v) for v in vks] + [("wait", parse_time(parts[1]))] + [("up", v) for v in reversed(vks)]
            elif verb in ("wait", "pause", "sleep"):
                ops.append(("wait", parse_time(rest)))
            elif verb == "type":
                ops.append(("type", rest))
            elif verb == "say":
                ops.append(("say", rest))
            elif verb == "click":
                parts = rest.lower().split(); btn, cnt = "left", 1
                for p in parts:
                    if p.isdigit(): cnt = int(p)
                    elif p in ("left", "right", "middle"): btn = p
                    else: raise ValueError(f"click left|right|middle [count], not '{p}'")
                vk = {"left": 1, "right": 2, "middle": 4}[btn]
                for _ in range(min(cnt, 50)): ops += [("down", vk), ("wait", 0.03), ("up", vk), ("wait", 0.05)]
            elif verb == "stratagem":
                code = [ARROWS.get(c.upper() if c.isalpha() else c) for c in rest if not c.isspace() and c not in ",-"]
                if not code or None in code: raise ValueError("code uses U D L R (or arrows ↑ ↓ ← →)")
                menu = combo_vks(strat["menu_key"]); dirs = {d: key_vk(strat[k]) for d, k in (("U", "up"), ("D", "down"), ("L", "left"), ("R", "right"))}
                if strat.get("menu_mode", "hold") == "hold": ops += [("down", v) for v in menu]
                else: ops += [("down", v) for v in menu] + [("wait", kh)] + [("up", v) for v in reversed(menu)]
                ops.append(("wait", od))
                for c in code: ops += [("down", dirs[c]), ("wait", kh), ("up", dirs[c]), ("wait", kg)]
                if strat.get("menu_mode", "hold") == "hold": ops += [("up", v) for v in reversed(menu)]
            else:
                raise ValueError(f"unknown action '{verb}'")
        except ValueError as e:
            errs.append(f"line {n}: {e}")
    return ops, errs


def precise_wait(sec, stop):
    end = time.perf_counter() + sec
    while True:
        rem = end - time.perf_counter()
        if rem <= 0: return True
        if stop.is_set(): return False
        time.sleep(0.004 if rem > 0.006 else 0)


class Executor(threading.Thread):
    """Runs macros one after another; always releases every key it pressed."""
    def __init__(self, app):
        super().__init__(daemon=True); self.app, self.q, self.stop, self.held, self.busy = app, queue.Queue(), threading.Event(), set(), False
    def submit(self, cmd, profile):
        if self.q.qsize() < 3: self.q.put((cmd, profile))
    def abort(self):
        self.stop.set()
        while not self.q.empty():
            try: self.q.get_nowait()
            except queue.Empty: break
    def run(self):
        thread_priority(2)                                  # key presses: never delayed by the game
        while True:
            cmd, profile = self.q.get(); self.stop.clear(); self.busy = True
            if WIN:
                try: ctypes.windll.winmm.timeBeginPeriod(1)      # exact 1 ms key timing - only while a macro runs
                except Exception: pass
            try:
                ops, errs = compile_actions(cmd.get("actions", []), profile, self.app.cfg.get("key_ms", 60))
                if errs: self.app.log(f"'{cmd.get('name')}': " + "; ".join(errs), "err")
                for op, v in ops:
                    if self.stop.is_set(): break
                    if op == "down": key_event(v, False); self.held.add(v)
                    elif op == "up": key_event(v, True); self.held.discard(v)
                    elif op == "wait": precise_wait(v, self.stop)
                    elif op == "type":
                        for ch in v:
                            if self.stop.is_set(): break
                            type_char(ch); time.sleep(0.008)
                    elif op == "say": self.app.speak(v)
            except Exception as e:
                traceback.print_exc(); self.app.log(f"macro error: {e}", "err")
            finally:
                for vk in list(self.held): key_event(vk, True)
                self.held.clear(); self.busy = False
                if WIN:
                    try: ctypes.windll.winmm.timeEndPeriod(1)
                    except Exception: pass


# ======================================================================  matching
ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
        "seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
UNITS = {"kilogram": "kg", "kilograms": "kg", "kilo": "kg", "kilos": "kg", "kgs": "kg", "millimeter": "mm",
         "millimeters": "mm", "millimetre": "mm", "millimetres": "mm"}
JUNK = {"thank you", "thanks", "thanks for watching", "thank you for watching", "thank you very much", "you", "bye", "bye bye",
        "okay", "ok", "yeah", "yes", "no", "hmm", "uh", "oh", "subtitles by the amara org community"}   # Whisper's favourite noise words
FILLER = {"uh", "um", "uhm", "umm", "er", "erm", "ah", "hmm", "please", "okay", "ok", "the"}


def num_words(n):
    if n < 20: return ONES[n]
    if n < 100: return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    if n < 1000: return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + num_words(n % 100))
    if n < 1000000: return num_words(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + num_words(n % 1000))
    return str(n)


def normalize(s):
    s = s.lower().replace("&", " and ").replace("%", " percent ")
    s = re.sub(r"(\d),(\d{3})", r"\1\2", s)
    s = re.sub(r"(\d)([^\W\d_])", r"\1 \2", s); s = re.sub(r"([^\W\d_])(\d)", r"\1 \2", s)
    s = re.sub(r"\d+", lambda m: num_words(int(m.group())) if len(m.group()) < 7 else m.group(), s)
    s = re.sub(r"[^\w\s]|_", " ", s)
    return [UNITS.get(t, t) for t in s.split()]


def _sim(a, b, sms=None):
    """fuzzy similarity of two strings; length differences cost extra (stops 'hello' -> 'hellbomb').
    b is always a piece of what was heard: its compare table is built once and reused for every phrase (sms cache)"""
    if a == b: return 1.0
    pen = 0.5 * abs(len(a) - len(b)) / max(len(a), len(b), 1)
    if sms is None: sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    else:
        sm = sms.get(b)
        if sm is None: sm = sms[b] = difflib.SequenceMatcher(None, "", b, autojunk=False)
        sm.set_seq1(a)
    q = sm.real_quick_ratio() - pen
    if q < 0.55: return q                 # can't be a match anyway - skip the expensive part
    q = sm.quick_ratio() - pen
    if q < 0.55: return q
    return sm.ratio() - pen


_PH_RULES = (("ph", "f"), ("ck", "k"), ("gh", ""), ("kn", "n"), ("wr", "r"), ("th", "t"), ("sh", "s"), ("ch", "s"), ("qu", "kv"),
             ("x", "ks"), ("z", "s"), ("w", "v"), ("dg", "j"), ("y", "i"))


def phonetic(s):
    """sound-alike key: 'quasar' ~ 'kvasar', 'railgun' ~ 'real gun', v = w, th = t (accent friendly)"""
    s = re.sub(r"[^a-z]", "", s.lower())
    for a, b in _PH_RULES: s = s.replace(a, b)
    s = re.sub(r"c(?=[eiy])", "s", s).replace("c", "k").replace("q", "k")
    s = s[:1] + re.sub(r"[aeiou]+", "a", s[1:])
    return re.sub(r"(.)\1+", r"\1", s)


def phrase_score(p, t, pp=None, cache=None):
    """how well the spoken words t contain phrase p (0..1); tolerant of mishearing, accents and extra words"""
    if not p or not t: return 0.0
    pj = " ".join(p)
    if pj == " ".join(t): return 1.0
    pn, best, n, L = pj.replace(" ", ""), 0.0, len(t), len(p)
    pp = pp if pp is not None else phonetic(pn)
    cache = {} if cache is None else cache
    sms = cache.setdefault("\0sm", {})            # compare tables of the heard pieces, shared by all phrases
    if n <= 4 and pn == "".join(t): return 0.98          # 'S.O.S.' / 'E A T' / 'hell bomb'
    sizes = [w for w in range(max(1, L - 1), L + 2) if w <= n] or [n]
    for w in sizes:
        for i in range(0, n - w + 1):
            wj = " ".join(t[i:i + w]); wn = wj.replace(" ", "")
            wp = cache.get(wn)
            if wp is None: wp = cache[wn] = phonetic(wn)
            r = max(_sim(pj, wj, sms), _sim(pn, wn, sms))
            if len(pp) >= 3 and r >= 0.4: r = max(r, _sim(pp, wp, sms) * 0.89)    # sound-alike only lifts near misses
            r -= min(0.15, 0.035 * (n - w))                 # extra words around the command
            if w < L and wn != pn: r -= 0.08 * (L - w)      # words of the command missing
            best = max(best, r)
    return best


def _grams(s):
    """letter pairs of a string (spaces removed) - used to skip phrases that share almost nothing with what was heard"""
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


class Matcher:
    """finds the commands whose phrases best match what Whisper heard.
    Every phrase is prepared once (normalised words, sound-alike key, letter pairs). Per sentence, phrases that share
    too few letter pairs with it (spelling AND sound-alike) are skipped before the expensive fuzzy compare."""
    GATE = 0.34          # a phrase needs >= 34% of its letter pairs in the sentence (or in its sound-alike form) to be scored

    def __init__(self, commands):
        self.items, self.prompt = [], vocab_prompt(commands)      # the Whisper hint is made once per profile, too
        for i, c in enumerate(commands):
            if not c.get("enabled", True): continue
            for ph in c.get("phrases", []):
                if ph.strip():
                    p = normalize(ph); p = [x for x in p if x not in FILLER] or p
                    pn = "".join(p); pp = phonetic(pn)
                    self.items.append((i, p, pp, _grams(pn), _grams(pp)))

    def match(self, text):
        t = [x for x in normalize(text) if x not in FILLER] or normalize(text)
        if not t or len(t) > 16: return []                  # nothing / long chatting with friends - no command is that long
        tn = "".join(t); tg, tpg = _grams(tn), _grams(phonetic(tn)) | set().union(*(_grams(phonetic(w)) for w in t))
        tg |= set().union(*(_grams(w) for w in t))
        scores, cache = {}, {}
        for i, p, pp, g, gp in self.items:
            if len(g) > 2 and len(g & tg) < self.GATE * len(g) and len(gp & tpg) < self.GATE * len(gp):
                continue                                    # can't be this phrase - skip the slow part
            s = phrase_score(p, t, pp, cache)
            if s > scores.get(i, -1): scores[i] = s
        return sorted(scores.items(), key=lambda x: -x[1])[:5]


def vocab_prompt(commands, limit=700):
    seen, words = set(), []
    for c in commands:
        for ph in c.get("phrases", [])[:2]:
            k = ph.strip().lower()
            if k and k not in seen: seen.add(k); words.append(ph.strip())
    out = ""
    for w in words:
        if len(out) + len(w) + 2 > limit: break
        out += (", " if out else "") + w
    return ("Voice commands: " + out + ".") if out else None


# ======================================================================  profiles
HD2_VERSION = 4   # v4: + full names and code names (TD-220 / 'TD two twenty') as phrases; every stratagem page of helldivers.wiki.gg, each code read from its own page (Oct 2026); bump to merge new stratagems into old profiles
HD2 = [
    # ---- mission / general
    ("Reinforce", "General", "reinforce;reinforcements;revive", "UDRLU"),
    ("SOS Beacon", "General", "SOS;SOS beacon", "UDRU"),
    ("Resupply", "General", "resupply;ammo;supplies", "DDUR"),
    ("NUX-223 Hellbomb", "General", "hellbomb;hell bomb", "DULDURDU"),
    ("Eagle Rearm", "General", "rearm;eagle rearm", "UULUR"),
    ("SEAF Artillery", "General", "SEAF artillery;artillery", "RUUD"),
    ("Super Earth Flag", "General", "flag;super earth flag", "DUDU"),
    ("Upload Data", "Mission", "upload data;upload", "LRUUU"),
    ("SSSD Delivery", "Mission", "SSSD;SSSD delivery;hard drive", "DDDDDUU"),
    ("Seismic Probe", "Mission", "seismic probe", "UULRDD"),
    ("Prospecting Drill", "Mission", "prospecting drill", "DDLRDD"),
    ("Hive Breaker Drill", "Mission", "hive breaker;hive breaker drill", "LUDRDD"),
    ("Tectonic Drill", "Mission", "tectonic drill", "UDUDUD"),
    ("Aquifer Drill", "Mission", "aquifer drill", "LLLUDRDD"),
    ("Dark Fluid Vessel", "Mission", "dark fluid;dark fluid vessel", "ULRDUU"),
    ("Cargo Container", "Mission", "cargo container", "UUDDRD"),
    ("Tactical Video Camera", "Mission", "video camera;tactical camera", "RDDULLU"),
    ("Reinforcement Pods", "Mission", "reinforcement pods", "LRUUU"),
    ("Activate E-711 Extraction Drill", "Mission", "extraction drill;E711;activate drill", "DDLLDD"),
    ("Portable Comms Relay", "Mission", "comms relay;portable comms relay", "UUDDLLD"),
    ("Call In Super Destroyer", "Mission", "super destroyer;call in super destroyer", "UUDDLRLR"),
    # ---- orbital
    ("Orbital Precision Strike", "Orbital", "precision strike;orbital precision", "RRU"),
    ("Orbital Gatling Barrage", "Orbital", "gatling barrage;orbital gatling", "RDLUU"),
    ("Orbital Gas Strike", "Orbital", "gas strike;orbital gas", "RRDR"),
    ("Orbital 120mm HE Barrage", "Orbital", "120 barrage;one twenty barrage;120mm barrage", "RRDLRD"),
    ("Orbital Airburst Strike", "Orbital", "airburst;air burst;airburst strike", "RRR"),
    ("Orbital Smoke Strike", "Orbital", "orbital smoke", "RRDU"),
    ("Orbital EMS Strike", "Orbital", "EMS strike;orbital EMS", "RRLD"),
    ("Orbital 380mm HE Barrage", "Orbital", "380 barrage;three eighty barrage;380mm barrage", "RDUULDD"),
    ("Orbital Walking Barrage", "Orbital", "walking barrage", "RDRDRD"),
    ("Orbital Laser", "Orbital", "laser;orbital laser", "RDURD"),
    ("Orbital Napalm Barrage", "Orbital", "napalm barrage;orbital napalm", "RRDLRU"),
    ("Orbital Railcannon Strike", "Orbital", "railcannon;rail cannon", "RUDDR"),
    # ---- eagle
    ("Eagle Strafing Run", "Eagle", "strafing run;strafe", "URR"),
    ("Eagle Airstrike", "Eagle", "airstrike;air strike;eagle airstrike", "URDR"),
    ("Eagle Cluster Bomb", "Eagle", "cluster;cluster bomb", "URDDR"),
    ("Eagle Napalm Airstrike", "Eagle", "napalm;eagle napalm", "URDU"),
    ("Eagle Smoke Strike", "Eagle", "eagle smoke", "URUD"),
    ("Eagle 110mm Rocket Pods", "Eagle", "rocket pods;110mm rocket pods", "URUL"),
    ("Eagle 500kg Bomb", "Eagle", "500 kg;500 kg bomb;five hundred;600 kg bomb;600 kg;big bomb", "URDDD"),
    ("Eagle Gas Airstrike", "Eagle", "eagle gas;gas airstrike", "URLR"),
    # ---- support weapons
    ("MG-43 Machine Gun", "Weapons", "machine gun", "DLDUR"),
    ("EAT-17 Expendable Anti-Tank", "Weapons", "EAT;expendable anti tank", "DDLUR"),
    ("M-105 Stalwart", "Weapons", "stalwart", "DLDUUL"),
    ("LAS-98 Laser Cannon", "Weapons", "laser cannon", "DLDUL"),
    ("APW-1 Anti-Materiel Rifle", "Weapons", "anti materiel rifle;sniper;AMR", "DLRUD"),
    ("GL-21 Grenade Launcher", "Weapons", "grenade launcher", "DLULD"),
    ("GR-8 Recoilless Rifle", "Weapons", "recoilless;recoilless rifle", "DLRRL"),
    ("FLAM-40 Flamethrower", "Weapons", "flamethrower", "DLUDU"),
    ("MG-206 Heavy Machine Gun", "Weapons", "heavy machine gun", "DLUDD"),
    ("AC-8 Autocannon", "Weapons", "autocannon;auto cannon", "DLDUUR"),
    ("ARC-3 Arc Thrower", "Weapons", "arc thrower", "DRDULL"),
    ("LAS-99 Quasar Cannon", "Weapons", "quasar;quasar cannon", "DDULR"),
    ("RL-77 Airburst Rocket Launcher", "Weapons", "airburst launcher;airburst rocket launcher", "DUULR"),
    ("MLS-4X Commando", "Weapons", "commando", "DLUDR"),
    ("FAF-14 Spear", "Weapons", "spear", "DDUDD"),
    ("RS-422 Railgun", "Weapons", "railgun;rail gun", "DRDULR"),
    ("StA-X3 W.A.S.P. Launcher", "Weapons", "wasp;wasp launcher", "DDUDR"),
    ("CQC-20 Breaching Hammer", "Weapons", "breaching hammer;hammer", "DLRLU"),
    ("PLAS-45 Epoch", "Weapons", "epoch", "DLULR"),
    ("MGX-42 Bullet Storm", "Weapons", "bullet storm", "DLDRUL"),
    ("TX-41 Sterilizer", "Weapons", "sterilizer", "DLUDL"),
    ("S-11 Speargun", "Weapons", "speargun;spear gun", "DRDLUR"),
    ("CQC-9 Defoliation Tool", "Weapons", "defoliation tool;chainsaw", "DLRRD"),
    ("GL-52 De-Escalator", "Weapons", "de escalator;deescalator", "DRULR"),
    ("EAT-700 Expendable Napalm", "Weapons", "expendable napalm;napalm EAT", "DDLUL"),
    ("EAT-411 Leveller", "Weapons", "leveller;leveler", "DDLUD"),
    ("M-1000 Maxigun", "Weapons", "maxigun;maxi gun", "DLRDUU"),
    ("GL-28 Belt-Fed Grenade Launcher", "Weapons", "belt fed;belt fed grenade launcher", "DLULUU"),
    ("B/FLAM-80 Cremator", "Weapons", "cremator", "DDRDUU"),
    ("MS-11 Solo Silo", "Weapons", "solo silo;silo", "DURDD"),
    ("40-K Meltagun", "Weapons", "meltagun;melta gun;melta", "DLULLD"),
    ("B/MD C4 Pack", "Weapons", "C4;C4 pack", "DRUURU"),
    ("CQC-1 One True Flag", "Weapons", "one true flag", "DLRRU"),
    # ---- backpacks
    ("B-1 Supply Pack", "Backpacks", "supply pack", "DLDUUD"),
    ("LIFT-850 Jump Pack", "Backpacks", "jump pack", "DUUDU"),
    ("LIFT-860 Hover Pack", "Backpacks", "hover pack", "DUUDLR"),
    ("LIFT-182 Warp Pack", "Backpacks", "warp pack", "DLRDLR"),
    ("B-100 Portable Hellbomb", "Backpacks", "portable hellbomb;backpack hellbomb", "DRUUU"),
    ("SH-20 Ballistic Shield Backpack", "Backpacks", "ballistic shield", "DLDDUL"),
    ("SH-32 Shield Generator Pack", "Backpacks", "shield pack;shield backpack", "DULRLR"),
    ("SH-51 Directional Shield", "Backpacks", "directional shield", "DULRUU"),
    ("AX/AR-23 Guard Dog", "Backpacks", "guard dog", "DULURD"),
    ("AX/LAS-5 Rover", "Backpacks", "rover;laser dog", "DULURR"),
    ("AX/TX-13 Dog Breath", "Backpacks", "dog breath;gas dog", "DULURU"),
    ("AX/FLAM-75 Hot Dog", "Backpacks", "hot dog;flame dog", "DULULL"),
    ("AX/ARC-3 K-9", "Backpacks", "K9;arc dog", "DULURL"),
    # ---- sentries
    ("A/MG-43 Machine Gun Sentry", "Sentries", "machine gun sentry", "DURRU"),
    ("A/G-16 Gatling Sentry", "Sentries", "gatling sentry", "DURL"),
    ("A/M-12 Mortar Sentry", "Sentries", "mortar;mortar sentry", "DURRD"),
    ("A/AC-8 Autocannon Sentry", "Sentries", "autocannon sentry", "DURULU"),
    ("A/MLS-4X Rocket Sentry", "Sentries", "rocket sentry", "DURRL"),
    ("A/M-23 EMS Mortar Sentry", "Sentries", "EMS mortar", "DURDR"),
    ("A/ARC-3 Tesla Tower", "Sentries", "tesla;tesla tower", "DURULR"),
    ("A/FLAM-40 Flame Sentry", "Sentries", "flame sentry", "DURDUU"),
    ("A/GM-17 Gas Mortar Sentry", "Sentries", "gas mortar", "DURDL"),
    ("A/LAS-98 Laser Sentry", "Sentries", "laser sentry", "DURDUR"),
    # ---- emplacements + mines
    ("E/MG-101 HMG Emplacement", "Emplacements", "HMG emplacement;HMG", "DULRRL"),
    ("E/AT-12 Anti-Tank Emplacement", "Emplacements", "anti tank emplacement;AT emplacement", "DULRRR"),
    ("E/GL-21 Grenadier Battlement", "Emplacements", "grenadier;grenadier battlement", "DRDLR"),
    ("FX-12 Shield Generator Relay", "Emplacements", "shield relay;bubble shield", "DDLRLR"),
    ("MD-6 Anti-Personnel Minefield", "Mines", "minefield;mines", "DLUR"),
    ("MD-I4 Incendiary Mines", "Mines", "incendiary mines", "DLLD"),
    ("MD-17 Anti-Tank Mines", "Mines", "anti tank mines", "DLUU"),
    ("MD-8 Gas Mines", "Mines", "gas mines", "DLLR"),
    # ---- vehicles
    ("EXO-45 Patriot Exosuit", "Vehicles", "patriot;mech;exosuit", "LDRULDD"),
    ("EXO-49 Emancipator Exosuit", "Vehicles", "emancipator", "LDRULDU"),
    ("EXO-51 Lumberer Exosuit", "Vehicles", "lumberer", "LDRURLU"),
    ("EXO-55 Breakthrough Exosuit", "Vehicles", "breakthrough", "LDRLRDU"),
    ("M-102 Gunner FRV", "Vehicles", "gunner FRV;gunner car", "LDRDRDU"),
    ("M-103 Supply FRV", "Vehicles", "supply FRV;supply car", "LDLLDUR"),
    ("M-104 Incinerator FRV", "Vehicles", "incinerator FRV;flame car", "LDRLDUU"),
    ("TD-110 Maelstrom", "Vehicles", "maelstrom;maelstrom tank", "LDRDLDULR"),
    ("TD-220 Bastion MK XVI", "Vehicles", "bastion", "LDRDLDUDU"),
]
HD2_OLD_NAMES = {"Machine Gun", "Anti-Materiel Rifle", "Stalwart", "Expendable Anti-Tank", "Recoilless Rifle", "Flamethrower", "Autocannon",
                 "Railgun", "Spear", "Quasar Cannon", "Grenade Launcher", "Laser Cannon", "Arc Thrower", "Heavy Machine Gun", "Commando",
                 "Jump Pack", "Supply Pack", "Guard Dog Rover", "Guard Dog", "Shield Generator Pack", "Ballistic Shield",
                 "Machine Gun Sentry", "Gatling Sentry", "Mortar Sentry", "Autocannon Sentry", "Rocket Sentry", "EMS Mortar Sentry",
                 "Tesla Tower", "Shield Generator Relay", "HMG Emplacement", "Anti-Personnel Minefield", "Incendiary Mines",
                 "Anti-Tank Mines", "Patriot Exosuit", "Emancipator Exosuit",
                 "Hellbomb", "SH-20 Ballistic Shield", "E/GL-21 Grenadier Emplacement"}   # names used by v1 / v2
# on the wiki but without a code yet: added switched off, ready to fill in
HD2_NO_CODE = [("AMW-20 Apex", "Weapons", "apex"), ("LAS-44 Nova", "Weapons", "nova")]


def say_number(n):
    """how people say a code number: 220 -> 'two twenty', 110 -> 'one ten', 105 -> 'one oh five', 43 -> 'forty three'"""
    v = int(n)
    if len(n) == 3 and n[1:] != "00":
        return num_words(int(n[0])) + " " + (num_words(int(n[1:])) if n[1] != "0" else "oh " + num_words(int(n[2])))
    return num_words(v)


def split_code(name):
    """'TD-220 Bastion MK XVI' -> ('TD-220', 'Bastion MK XVI'); names without a code -> ('', name)"""
    first, _, rest = name.partition(" ")
    if rest and re.search(r"\d", first) and re.search(r"[-/]", first): return first, rest
    return "", name


def name_phrases(name):
    """extra things you can say for a stratagem: full name, code name written and spoken, code + name"""
    code, full = split_code(name)
    out = [full, name] if code else [name]
    if code:
        plain = code.replace("/", " ").replace("-", " ")                               # 'A/MG-43' -> 'A MG 43'
        spoken = " ".join(re.sub(r"\d+", lambda m: f" {say_number(m.group())} ", plain).split())   # 'A MG forty three', 'MD I four'
        if len(re.sub(r"[^A-Za-z0-9]", "", code)) > 2: out += [code, plain, spoken]        # 'B-1' alone is too short (sounds like 'be one')
        out.append(f"{spoken} {full}")
        if "/" in code: out.append(code.split("/", 1)[1])                              # 'MG-43' part of 'A/MG-43'
    return out


def _dedup(phr):
    seen, out = set(), []
    for x in phr:
        k = " ".join(normalize(x))
        if x.strip() and k not in seen: seen.add(k); out.append(x.strip())
    return out


def hd2_commands():
    return ([{"name": n, "category": cat, "phrases": _dedup(ph.split(";") + name_phrases(n)), "actions": [f"stratagem {code}"], "enabled": True}
             for n, cat, ph, code in HD2] +
            [{"name": n, "category": cat, "phrases": _dedup([ph] + name_phrases(n)), "enabled": False,
              "actions": ["# the wiki has no code for this one yet - write it here and tick ENABLED, e.g.", "# stratagem DLDUR"]}
             for n, cat, ph in HD2_NO_CODE])


def upgrade_hd2(p):
    """older Helldivers profile -> current list. Keeps your own commands, your taught phrases and any macro you changed."""
    v = p.get("version", 1)
    if p.get("name") != "Helldivers 2" or v >= HD2_VERSION: return False
    new = hd2_commands(); names = {c["name"] for c in new}
    old = {c.get("name"): c for c in p.get("commands", [])}
    merged = []
    for c in new:
        o = old.pop(c["name"], None)
        if o is None: merged.append(c); continue
        o["phrases"] = _dedup(list(o.get("phrases", [])) + c["phrases"])                # your phrases first, then the new ones
        acts = [a for a in o.get("actions", []) if a.strip() and not a.startswith("#")]
        if len(acts) <= 1 and (not acts or acts[0].lower().startswith("stratagem")): o["actions"] = c["actions"]
        merged.append(o)
    mine = [c for n, c in old.items() if n not in HD2_OLD_NAMES and n not in names]
    p["commands"] = merged + mine; p["version"] = HD2_VERSION
    if v < 3:   # v1/v2 used WASD -> arrows (v3+ keeps whatever keys you set)
        st = dict(STRAT_DEFAULT); st["menu_key"] = (p.get("stratagem") or {}).get("menu_key", "lctrl")
        st["menu_mode"] = (p.get("stratagem") or {}).get("menu_mode", "hold"); p["stratagem"] = st
    return True


def default_profiles():
    hd = {"name": "Helldivers 2", "process": "helldivers2.exe", "version": HD2_VERSION, "stratagem": dict(STRAT_DEFAULT),
          "commands": hd2_commands()}
    win = {"name": "Windows (example)", "process": "", "stratagem": dict(STRAT_DEFAULT), "commands": [
        {"name": "Screenshot", "category": "Desktop", "phrases": ["screenshot", "snip"], "actions": ["press win+shift+s"], "enabled": True},
        {"name": "Task Manager", "category": "Desktop", "phrases": ["task manager"], "actions": ["press ctrl+shift+esc"], "enabled": True},
        {"name": "Show desktop", "category": "Desktop", "phrases": ["show desktop"], "actions": ["press win+d"], "enabled": True},
        {"name": "Good game", "category": "Chat", "phrases": ["good game"], "actions": ["press enter", "wait 0.15", "type gg wp", "press enter"], "enabled": True},
    ]}
    return [hd, win]


def slug(name): return re.sub(r"[^\w\- ]+", "_", name).strip() or "profile"


def split_top(s):
    out, cur, depth = [], "", 0
    for ch in s:
        if ch == "[": depth += 1
        elif ch == "]": depth = max(0, depth - 1)
        if ch == ";" and depth == 0: out.append(cur); cur = ""
        else: cur += ch
    out.append(cur); return out


def expand_va(s):
    """VoiceAttack phrase syntax: 'fire;shoot' and '[fire;launch] [missile;missiles;]' -> list of phrases"""
    out = []
    for part in split_top(s.replace("*", " ")):
        combos = [""]
        for tok in re.split(r"(\[[^\]]*\])", part):
            if tok.startswith("["): combos = [c + o for c in combos for o in tok[1:-1].split(";")][:64]
            else: combos = [c + tok for c in combos]
        out += [" ".join(c.split()) for c in combos if c.strip()]
    return list(dict.fromkeys(out))


def import_vap(path):
    with open(path, "rb") as f: raw = f.read()
    if not raw.lstrip()[:5].lstrip(b"\xef\xbb\xbf").startswith(b"<"):
        for wb in (-15, 15, 31):
            try: raw = zlib.decompress(raw, wb); break
            except Exception: pass
        else:
            raise ValueError("this .vap is in VoiceAttack's binary format.\nIn VoiceAttack use 'Export Profile' and keep it as XML, then import that file.")
    root = ET.fromstring(raw)
    prof = {"name": (root.findtext("Name") or os.path.splitext(os.path.basename(path))[0]).strip(), "process": "",
            "key_hold": 0.05, "stratagem": dict(STRAT_DEFAULT), "commands": []}
    skipped = 0
    for c in root.iter("Command"):
        cs = c.findtext("CommandString") or ""
        phrases = expand_va(cs)
        acts = []
        for a in c.iter("CommandAction"):
            t = a.findtext("ActionType") or ""
            keys = [int(k.text) for k in a.findall("KeyCodes/unsignedShort") if (k.text or "").isdigit()]
            dur = float(a.findtext("Duration") or 0)
            names = "+".join(VK2NAME.get(k, f"vk{k}") for k in keys)
            if t == "PressKey" and keys: acts.append(f"press {names} {dur:g}" if dur > 0 else f"press {names}")
            elif t == "KeyDown" and keys: acts.append(f"down {names}")
            elif t == "KeyUp" and keys: acts.append(f"up {names}")
            elif t == "Pause": acts.append(f"wait {dur:g}")
            elif t == "Say": acts.append("say " + (a.findtext("Context") or "").split(";")[0])
            else: acts.append(f"# not imported: VoiceAttack '{t}' action"); skipped += 1
        if phrases:
            prof["commands"].append({"name": phrases[0], "category": c.findtext("Category") or "", "phrases": phrases,
                                     "actions": acts, "enabled": (c.findtext("Enabled") or "true").lower() != "false"})
    return prof, skipped


# ======================================================================  sound + voice
def _write_wav(path, x, sr=44100):
    import wave
    data = (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()
    with wave.open(path, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(data)


def _read_wav(path):
    import wave
    with wave.open(path, "rb") as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768
    if ch > 1: x = x.reshape(-1, ch).mean(1)
    return x, sr


def robotize(x, sr):
    """plain Windows voice -> cold machine voice: lower + slower, ring-modulated, metallic comb, crushed, hard-clipped, echo"""
    x = np.asarray(x, np.float64)
    nz = np.flatnonzero(np.abs(x) > 0.01)                                 # trim silence
    if len(nz): x = x[max(0, nz[0] - 200): nz[-1] + 400]
    k = 0.84                                                              # pitch + formants down
    x = np.interp(np.arange(0, len(x) - 1, k), np.arange(len(x)), x)
    t = np.arange(len(x)) / sr
    x = x * (0.6 + 0.4 * np.sin(2 * np.pi * 48 * t))                      # ring mod hum
    y = x.copy()
    for ms, g in ((4.1, 0.55), (9.3, 0.35)):                              # metal comb (tin can resonance)
        d = int(sr * ms / 1000); y[d:] += g * x[:-d]
    q = 2 ** 6; y = np.round(y * q) / q                                   # slight bit crush
    y = np.tanh(y * 2.6) / np.tanh(2.6)                                   # drive
    y = np.concatenate([y, np.zeros(int(sr * 0.35))]); o = y.copy()
    for ms, g in ((95, 0.28), (190, 0.12)):                               # hall echo
        d = int(sr * ms / 1000); o[d:] += g * y[:-d]
    o = np.diff(o, prepend=0) * 0.35 + o * 0.65                           # thin the mud a bit
    return (o / (np.abs(o).max() + 1e-9) * 0.92).astype(np.float32)


# ======================================================================  sounds (all synthesized here, original)
def _sfx(name, sr=44100):
    """Terminator / Skynet style: metal hits, servo whirs, sub-bass impacts, distorted machine tones. One per button / event."""
    rng = np.random.default_rng(sum(map(ord, name)))
    def T(d): return np.arange(int(sr * d)) / sr
    def env(t, a=0.002, r=0.05): return np.minimum(1, t / a) * np.exp(-t / r)
    def osc(f, d, w="sin"):
        t = T(d); f = np.broadcast_to(f, t.shape) if np.ndim(f) else np.full(t.shape, float(f))
        ph = 2 * np.pi * np.cumsum(f) / sr
        return {"sin": np.sin(ph), "sq": np.sign(np.sin(ph)), "saw": (ph / np.pi) % 2 - 1, "tri": 2 / np.pi * np.arcsin(np.sin(ph))}[w]
    def tone(f, d, r=0.05, w="sin", a=0.002): return osc(f, d, w) * env(T(d), a, r)
    def glide(f0, f1, d, r=0.1, w="sin", a=0.002):
        t = T(d); return osc(f0 * (f1 / f0) ** (t / d), d, w) * env(t, a, r)
    def fm(fc, ratio, idx, d, r=0.08, ri=None):
        """metallic FM clang"""
        t = T(d); mod = idx * np.exp(-t / (ri or r)) * np.sin(2 * np.pi * fc * ratio * t)
        return np.sin(2 * np.pi * fc * t + mod) * env(t, 0.001, r)
    def noise(d, r=0.03, smooth=1):
        n = rng.standard_normal(int(sr * d))
        if smooth > 1: n = np.convolve(n, np.ones(smooth) / smooth, "same")
        return n * env(T(d), 0.001, r)
    def hit(f0=110, d=0.35, r=0.12):
        """sub-bass impact: falling sine + crack"""
        return mix(glide(f0, f0 * 0.35, d, r), noise(0.04, 0.008, 2) * 0.5)
    def servo(f0, f1, d, r=None):
        """motor whir: buzzy saw with a wobble, rising or falling"""
        t = T(d); f = f0 * (f1 / f0) ** (t / d) * (1 + 0.04 * np.sin(2 * np.pi * 31 * t))
        y = osc(f, d, "saw"); y = np.convolve(y, np.ones(6) / 6, "same")
        e = np.minimum(1, t / 0.01) * (np.exp(-t / r) if r else np.minimum(1, (d - t) / 0.02))
        return y * e
    def sil(d): return np.zeros(int(sr * d))
    def cat(*a): return np.concatenate(a)
    def mix(*a):
        o = np.zeros(max(len(x) for x in a))
        for x in a: o[:len(x)] += x
        return o
    def at(dt, x): return cat(sil(dt), x)
    def dist(x, k=3.0): return np.tanh(x * k) / np.tanh(k)
    def tick(f=3200): return mix(noise(0.006, 0.0015), tone(f, 0.01, 0.003)) * 0.6
    def clank(f=900, r=0.025):
        """short metal clank: very short inharmonic FM burst + noise (no note you could hum)"""
        return mix(fm(f, 3.73, 7, min(0.12, r * 4), r, r * 0.5) * 0.6, noise(r * 2, r * 0.6, 2) * 0.5)
    key = lambda: dist(mix(tick(2600), noise(0.02, 0.005, 3) * 0.5, hit(140, 0.06, 0.02) * 0.35), 1.5) * 0.36
    s = {
        # ---- buttons (no tones / melodies - clicks, clanks, servos, thuds)
        "profile": lambda: dist(mix(clank(700, 0.03), hit(90, 0.25, 0.07) * 0.7), 2) * 0.34,
        "newprofile": lambda: dist(cat(clank(800, 0.02), sil(0.04), mix(clank(600, 0.03), hit(80, 0.25, 0.08) * 0.6)), 2) * 0.32,
        "plus": lambda: dist(mix(servo(140, 300, 0.09, 0.05) * 0.6, at(0.06, tick())), 2) * 0.3,
        "import": lambda: dist(mix(servo(400, 110, 0.16, 0.08) * 0.6, at(0.12, hit(80, 0.25, 0.08))), 2.5) * 0.32,
        "folder": lambda: dist(mix(hit(70, 0.2, 0.06), clank(500, 0.02) * 0.6), 2) * 0.36,
        "trash": lambda: dist(mix(noise(0.3, 0.09, 4) * 0.7, hit(60, 0.35, 0.12)), 3) * 0.32,
        "gear": lambda: dist(cat(*[cat(tick(2400), sil(0.03)) for _ in range(4)]), 1.5) * 0.4,
        "stop": lambda: dist(mix(hit(120, 0.3, 0.1), noise(0.08, 0.03, 3) * 0.4), 3) * 0.32,
        "edit": lambda: dist(cat(*[cat(tick(2800), sil(0.022)) for _ in range(3)]), 1.5) * 0.4,
        "copy": lambda: dist(cat(tick(2200), sil(0.03), tick(2600)), 1.5) * 0.4,
        "play": lambda: dist(mix(servo(90, 300, 0.2, 0.1) * 0.6, at(0.15, hit(110, 0.15, 0.05))), 2.5) * 0.32,
        "save": lambda: dist(cat(tick(2400), mix(clank(600, 0.03), hit(70, 0.25, 0.08) * 0.7)), 2.5) * 0.32,
        "cancel": lambda: dist(cat(tick(1800), servo(250, 80, 0.12, 0.06) * 0.5), 2) * 0.3,
        "detect": lambda: dist(mix(servo(180, 240, 0.5, 0.2) * 0.35, cat(*[cat(tick(3000), sil(0.09)) for _ in range(4)])), 2) * 0.32,
        "arrows": lambda: dist(cat(*[cat(tick(2600), sil(0.03)) for _ in range(4)]), 1.5) * 0.38,
        "wasd": lambda: dist(cat(*[cat(tick(2000), sil(0.03)) for _ in range(4)]), 1.5) * 0.38,
        "mic": lambda: dist(mix(tick(1800), at(0.01, noise(0.06, 0.02, 3) * 0.5)), 2) * 0.36,
        "search": lambda: dist(cat(tick(3200), sil(0.03), tick(3200)), 1.5) * 0.34,
        "locked": lambda: dist(mix(servo(300, 90, 0.14, 0.07) * 0.6, at(0.12, hit(110, 0.35, 0.12)), at(0.12, clank(400, 0.03))), 3) * 0.34,
        "unlocked": lambda: dist(mix(servo(80, 300, 0.2, 0.12) * 0.6, at(0.17, clank(700, 0.03)), at(0.17, hit(90, 0.2, 0.06) * 0.6)), 2.5) * 0.32,
        "gear_open": lambda: dist(servo(120, 260, 0.12, 0.07) * 0.6, 2) * 0.28,
        "rec": lambda: dist(cat(tick(3000), tick(2400)), 1.5) * 0.34,
        "undo": lambda: dist(servo(300, 140, 0.1, 0.06) * 0.6, 2) * 0.28,
        "wait": lambda: dist(cat(tick(2000), sil(0.07), tick(2000)), 1.5) * 0.36,
        "click": lambda: dist(mix(tick(2600), noise(0.02, 0.005, 2) * 0.3), 1.5) * 0.4,
        "key": key, "dir_U": key, "dir_D": key, "dir_L": key, "dir_R": key,
        "chip": lambda: dist(mix(tick(2200), noise(0.015, 0.004, 2) * 0.4), 1.5) * 0.36,
        "select": lambda: tick(3600) * 0.28,
        "open": lambda: dist(servo(110, 220, 0.12, 0.08) * 0.5, 2) * 0.24, "close": lambda: dist(servo(220, 100, 0.1, 0.06) * 0.5, 2) * 0.24,
        # ---- events
        "ok": lambda: dist(mix(hit(95, 0.16, 0.05), clank(650, 0.025), noise(0.04, 0.012, 2) * 0.4), 2.5) * 0.34,
        "miss": lambda: dist(cat(noise(0.08, 0.04, 6), sil(0.03), noise(0.1, 0.05, 6)) * 0.8, 3) * 0.3,
        "ptt_on": lambda: dist(mix(tick(3000), noise(0.04, 0.012, 2) * 0.5), 1.5) * 0.34,
        "ptt_off": lambda: dist(mix(tick(1800), noise(0.05, 0.02, 3) * 0.5), 1.5) * 0.32,
        "denied": lambda: dist(mix(cat(noise(0.1, 0.06, 8), sil(0.025), noise(0.1, 0.06, 8)), hit(80, 0.25, 0.1) * 0.5), 4) * 0.32,
        "on": lambda: dist(mix(servo(70, 260, 0.3, 0.18) * 0.6, at(0.26, hit(80, 0.3, 0.1)), at(0.26, clank(600, 0.03))), 2.5) * 0.3,
        "off": lambda: dist(mix(servo(260, 60, 0.35, 0.2) * 0.6, at(0.28, hit(70, 0.35, 0.12))), 2.5) * 0.3,
    }
    f = s.get(name) or s["click"]
    x = f()
    fade = min(len(x), int(sr * 0.006)); x[-fade:] *= np.linspace(1, 0, fade)   # no clicks at the end
    return np.clip(x, -1, 1).astype(np.float32)


SFX_NAMES = ["profile", "newprofile", "plus", "import", "folder", "trash", "gear", "stop", "edit", "copy", "play", "save", "cancel",
             "detect", "arrows", "wasd", "mic", "search", "locked", "unlocked", "rec", "undo", "wait", "click", "key", "chip", "select",
             "dir_U", "dir_D", "dir_L", "dir_R", "open", "close", "ok", "miss", "ptt_on", "ptt_off", "denied", "on", "off"]
SFX_VER = "v6_"


class Sfx:
    """plays the generated sounds; kind = ui / cmd / ptt decides which option switch controls it"""
    def __init__(self, app):
        self.app, self.busy_until = app, 0.0
        try:                                               # sound files of older versions are not needed any more
            for f in os.listdir(SFX_DIR):
                if f.endswith(".wav") and not f.startswith(SFX_VER): os.remove(os.path.join(SFX_DIR, f))
        except OSError: pass
        for nm in SFX_NAMES:
            p = os.path.join(SFX_DIR, f"{SFX_VER}{nm}.wav")
            if not os.path.exists(p):
                try: _write_wav(p, _sfx(nm))
                except Exception: traceback.print_exc()
        self.set_volume(app.cfg.get("volume", 70))

    def set_volume(self, v):
        if not WIN: return
        try:
            x = int(max(0, min(100, v)) / 100 * 0xFFFF)
            ctypes.windll.winmm.waveOutSetVolume(None, x | (x << 16))   # this app's own volume only
        except Exception: pass

    def play(self, name, kind="ui"):
        c = self.app.cfg
        if not WIN or c.get("volume", 70) <= 0: return
        if kind == "ui" and not c.get("ui_sounds", True): return
        if kind == "cmd" and not c.get("sounds", True): return
        if kind == "ptt" and not c.get("ptt_sounds", True): return
        if kind == "ui" and time.time() < self.busy_until: return        # don't cut the machine voice off with a click
        self.play_file(os.path.join(SFX_DIR, f"{SFX_VER}{name}.wav"))
        if kind == "cmd": self.app.mute_until = max(self.app.mute_until, time.time() + 0.3)

    def play_file(self, path, hold=0.0):
        try:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            if hold: self.busy_until = time.time() + hold
        except Exception: pass


class Voice(threading.Thread):
    """Skynet voice: Windows speech -> wav -> robotize() -> cached in sfx/voice -> played.
    The first time a line is said it takes ~0.5 s to make, after that it is instant."""
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app, self.q, self.proc, self.n = app, queue.PriorityQueue(), None, 0
        self.dir = os.path.join(SFX_DIR, "voice"); os.makedirs(self.dir, exist_ok=True)
        self.start()

    def path(self, text):
        import hashlib
        return os.path.join(self.dir, "r1_" + hashlib.md5(text.lower().encode("utf-8")).hexdigest()[:16] + ".wav")

    def put(self, pri, item): self.n += 1; self.q.put((pri, self.n, item))

    def say(self, text, delay=0.0): self.put(0, (text, time.time() + delay, True))      # spoken lines jump the queue

    def warm(self, texts):
        for t in dict.fromkeys(texts):
            if t and not os.path.exists(self.path(t)): self.put(1, (t, 0, False))

    def make(self, text):
        p = self.path(text)
        if os.path.exists(p): return p
        if self.proc is None or self.proc.poll() is not None:
            ps = os.path.join(SFX_DIR, "tts_wav.ps1")
            with open(ps, "w", encoding="utf-8-sig") as f: f.write(TTS_PS)
            self.proc = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", creationflags=0x08000000)
        raw = p[:-4] + "_raw.wav"
        self.proc.stdin.write(raw + "|" + text.replace("\n", " ").replace("|", " ") + "\n"); self.proc.stdin.flush()
        if self.proc.stdout.readline().strip() != "ok": raise RuntimeError("speech engine failed")
        x, sr = _read_wav(raw); _write_wav(p, robotize(x, sr), sr)
        try: os.remove(raw)
        except OSError: pass
        return p

    def run(self):
        while True:
            text, when, play = self.q.get()[2]
            try:
                p = self.make(text)
                if not play: continue
                d = when - time.time()
                if d > 0: time.sleep(d)
                x_len = os.path.getsize(p) / 2 / 22050
                self.app.mute_until = max(self.app.mute_until, time.time() + x_len + 0.2)   # don't hear ourselves
                if self.app.sfx: self.app.sfx.play_file(p, hold=x_len)
            except Exception as e:
                try: self.app.log(f"voice error: {e}", "err")
                except Exception: pass

    def stop(self):
        try: self.proc and self.proc.kill()
        except Exception: pass


SFX = None    # set by the App; widgets call sfx("name")
PAUSED = [False]   # True while a game (any other program) is in front and "pause animations in game" is on


def thread_priority(level):
    """raise the current thread above the (low) app priority: 2 = highest, 1 = above normal.
    Even with GAME FIRST, the threads that hear you and press the keys run at normal-or-better priority, so a busy game
    can't make a command wait - only drawing the window waits."""
    if not WIN: return
    try: kernel32.SetThreadPriority(wt.HANDLE(-2), level)          # -2 = this thread
    except Exception: pass


def set_priority(low):
    """game first: this app runs at below-normal CPU priority so the game always gets the processor first"""
    if not WIN: return
    try: kernel32.SetPriorityClass(wt.HANDLE(-1), 0x4000 if low else 0x20)     # -1 = this process
    except Exception: pass


def ram_mb():
    """RAM (working set) this app uses right now"""
    if not WIN: return 0
    try:
        class PMC(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + [(n, ctypes.c_size_t) for n in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        m = PMC(); m.cb = ctypes.sizeof(PMC)
        ctypes.windll.psapi.GetProcessMemoryInfo(wt.HANDLE(-1), ctypes.byref(m), m.cb)
        return m.WorkingSetSize / 1048576
    except Exception: return 0


def vram_mb():
    """graphics-card memory this app uses (asks nvidia-smi; None if it can't tell)"""
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=3, creationflags=0x08000000 if WIN else 0).stdout
        for line in out.splitlines():
            pid, _, mem = line.partition(",")
            if pid.strip() == str(os.getpid()) and mem.strip().isdigit(): return int(mem.strip())
        return None
    except Exception: return None


def sfx(name, kind="ui"):
    if SFX: SFX.play(name, kind)


# ======================================================================  audio
_PA, _PA_LOCK = None, threading.Lock()


def get_pa():
    global _PA
    with _PA_LOCK:
        if _PA is None:
            import pyaudiowpatch as pyaudio
            _PA = pyaudio.PyAudio()
        return _PA


def list_mics():
    import pyaudiowpatch as pyaudio
    pa = get_pa(); out = []
    with _PA_LOCK:
        w = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        dflt = pa.get_device_info_by_index(w["defaultInputDevice"])["name"] if w["defaultInputDevice"] >= 0 else ""
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d["hostApi"] == w["index"] and d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice"):
                out.append({"index": i, "name": d["name"], "default": d["name"] == dflt})
    out.sort(key=lambda d: (not d["default"], d["name"].lower()))
    return out


class Capture(threading.Thread):
    """Microphone -> 30 ms frames -> voice-activity detector (or push-to-talk) -> finished utterances."""
    FRAME = 480

    def __init__(self, app, mic_name):
        super().__init__(daemon=True)
        self.app, self.mic_name, self.running, self.level, self.err = app, mic_name, True, 0.0, ""
        self.pending = np.zeros(0, dtype=np.float32); self.reset(); self.noise = 0.003; self.ptt_rec = None

    def reset(self):
        self.preroll, self.rec, self.in_speech, self.hot, self.voiced, self.silent = deque(maxlen=15), [], False, 0, 0, 0

    def run(self):
        thread_priority(2)                                  # microphone: never miss audio
        try:
            import pyaudiowpatch as pyaudio
            mics = list_mics()
            dev = next((m for m in mics if m["name"] == self.mic_name), None) or (mics[0] if mics else None)
            if not dev: self.err = "no microphone found"; self.app.log("no microphone found", "err"); return
            pa = get_pa()
            with _PA_LOCK:
                info = pa.get_device_info_by_index(dev["index"])
                self.ch, self.rate = max(1, min(2, int(info["maxInputChannels"]))), int(info["defaultSampleRate"])
                st = pa.open(format=pyaudio.paInt16, channels=self.ch, rate=self.rate, input=True,
                             input_device_index=dev["index"], frames_per_buffer=int(self.rate * 0.03))
            self.app.log(f"microphone: {dev['name']}", "sys")
        except Exception as e:
            self.err = str(e); self.app.log(f"microphone error: {e}", "err"); traceback.print_exc(); return
        while self.running:
            try: raw = st.read(int(self.rate * 0.03), exception_on_overflow=False)
            except Exception as e:
                self.app.log(f"microphone stopped: {e}", "err"); break
            self.feed(self.to_16k(raw))
        try:
            with _PA_LOCK: st.stop_stream(); st.close()
        except Exception: pass

    def to_16k(self, raw):
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        a = a[: len(a) - len(a) % self.ch].reshape(-1, self.ch).mean(axis=1)
        if self.rate != SR and len(a):
            k = max(1, int(round(self.rate / SR)))
            if k > 1: a = np.convolve(a, np.ones(k, dtype=np.float32) / k, mode="same")
            a = np.interp(np.linspace(0, len(a) - 1, int(len(a) * SR / self.rate)), np.arange(len(a)), a).astype(np.float32)
        return a

    def feed(self, a):
        self.pending = np.concatenate([self.pending, a])
        while len(self.pending) >= self.FRAME:
            f, self.pending = self.pending[:self.FRAME], self.pending[self.FRAME:]
            self.frame(f)

    def emit(self, frames, need_voice=False):
        if need_voice:     # push-to-talk: was anything actually said? (no Whisper run for a key press without speech)
            thr = max(0.006, self.noise * 3.0)
            if sum(1 for f in frames if float(np.sqrt(np.mean(f * f))) > thr) < 5: return
        audio = np.concatenate(frames)
        if len(audio) < SR * 0.2: return
        if self.app.utt_q.qsize() < 2: self.app.utt_q.put((time.time(), audio))

    def frame(self, f):
        cfg = self.app.cfg
        rms = float(np.sqrt(np.mean(f * f))); self.level = max(rms, self.level * 0.85)
        if not self.app.listening:
            self.reset(); self.ptt_rec = None; return
        if cfg["mode"] == "ptt":
            # push-to-talk: you decide the window, so the app's own click sounds never mute it;
            # 0.3 s from before the key press and 0.25 s after the release are kept (no cut-off syllables)
            if self.app.ptt_down:
                if self.ptt_rec is None: self.ptt_rec = list(self.preroll)[-10:]
                self.ptt_tail = 5; self.ptt_rec.append(f)
                if len(self.ptt_rec) * 0.03 > 15: self.emit(self.ptt_rec, True); self.ptt_rec = []
            elif self.ptt_rec is not None:
                self.ptt_rec.append(f); self.ptt_tail = getattr(self, "ptt_tail", 0) - 1
                if self.ptt_tail <= 0:
                    if self.ptt_rec: self.emit(self.ptt_rec, True)
                    self.ptt_rec = None
            else:
                self.preroll.append(f)          # key up: learn the room's noise level
                self.noise = self.noise * 0.9 + rms * 0.1 if rms < self.noise else self.noise * 0.995 + rms * 0.005
            return
        if time.time() < self.app.mute_until:
            self.reset(); return
        s = float(cfg.get("sensitivity", 5))
        thr = max(0.012 - 0.001 * s, self.noise * (4.5 - 0.3 * s))
        if not self.in_speech:
            self.preroll.append(f)
            self.hot = self.hot + 1 if rms > thr else 0
            self.noise = self.noise * 0.9 + rms * 0.1 if rms < self.noise else self.noise * 0.995 + rms * 0.005
            if self.hot >= 3:
                self.in_speech, self.rec, self.voiced, self.silent = True, list(self.preroll), self.hot, 0
        else:
            self.rec.append(f)
            if rms > thr * 0.75: self.voiced += 1; self.silent = 0
            else: self.silent += 1
            if self.silent * 30 >= int(cfg.get("silence_ms", 380)) or len(self.rec) * 0.03 > 6:
                if self.voiced >= 5: self.emit(self.rec[:len(self.rec) - max(0, self.silent - 8)])
                self.reset()


# ======================================================================  UI
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont


# ---------------- readable key names ----------------
PRETTY = {"lctrl": "LEFT CTRL", "rctrl": "RIGHT CTRL", "ctrl": "CTRL", "lshift": "LEFT SHIFT", "rshift": "RIGHT SHIFT", "shift": "SHIFT",
          "lalt": "LEFT ALT", "ralt": "ALT GR", "alt": "ALT", "lwin": "WINDOWS", "win": "WINDOWS", "rwin": "RIGHT WINDOWS",
          "up": "↑ UP", "down": "↓ DOWN", "left": "← LEFT", "right": "→ RIGHT",
          "mouse1": "LEFT MOUSE", "mouse2": "RIGHT MOUSE", "mouse3": "MIDDLE MOUSE", "mouse4": "MOUSE 4 (BACK)", "mouse5": "MOUSE 5 (FORWARD)",
          "esc": "ESC", "enter": "ENTER", "space": "SPACE", "tab": "TAB", "capslock": "CAPS LOCK", "backspace": "BACKSPACE",
          "pageup": "PAGE UP", "pagedown": "PAGE DOWN", "printscreen": "PRINT SCREEN", "scrolllock": "SCROLL LOCK", "numlock": "NUM LOCK",
          "insert": "INSERT", "delete": "DELETE", "home": "HOME", "end": "END", "pause": "PAUSE",
          "grave": "` (TILDE)", "minus": "-", "equals": "=", "comma": ",", "period": ".", "slash": "/", "semicolon": ";", "quote": "'",
          "lbracket": "[", "rbracket": "]", "backslash": "\\", "num*": "NUMPAD *", "num+": "NUMPAD +", "num-": "NUMPAD -",
          "num.": "NUMPAD .", "num/": "NUMPAD /"}
ARROW_GLYPH = {"U": "↑", "D": "↓", "L": "←", "R": "→"}


SHORT_KEY = {"lctrl": "LCTRL", "rctrl": "RCTRL", "ctrl": "CTRL", "lshift": "LSHIFT", "rshift": "RSHIFT", "shift": "SHIFT", "lalt": "LALT",
             "ralt": "ALTGR", "alt": "ALT", "lwin": "WIN", "win": "WIN", "mouse4": "M4", "mouse5": "M5", "mouse3": "M3", "mouse2": "RMB",
             "mouse1": "LMB", "capslock": "CAPS", "space": "SPACE", "up": "↑", "down": "↓", "left": "←", "right": "→"}


def pretty_key(k):
    k = k.strip().lower()
    if k in PRETTY: return PRETTY[k]
    m = re.fullmatch(r"num(\d)", k)
    return f"NUMPAD {m.group(1)}" if m else k.upper()


def pretty_combo(c):
    c = (c or "").strip()
    return " + ".join(pretty_key(k) for k in re.split(r"\s*\+\s*", c) if k) if c else ""


def pretty_action(a):
    a = a.strip(); verb, _, rest = a.partition(" "); v = verb.lower()
    if v == "stratagem": return "★ " + " ".join(ARROW_GLYPH.get(ARROWS.get(ch.upper() if ch.isalpha() else ch, ""), ch) for ch in rest if not ch.isspace())
    if v in ("press", "tap", "key", "down", "up", "hold"):
        parts = rest.split()
        return f"{v.upper()} {pretty_combo(parts[0]) if parts else ''}" + (f" {parts[1]}" if len(parts) > 1 else "")
    return a


# ---------------- animated vector icons (all original) ----------------
def draw_icon(c, name, x, y, s, col, t=0.0, hot=0.0):
    cx, cy, r = x + s / 2, y + s / 2, s / 2
    w = max(2, round(s / 11))
    def L(*p, width=w, fill=col): c.create_line(*p, fill=fill, width=width, capstyle="round", joinstyle="round")
    def brackets(k=0.95, a=0.3):
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            px, py = cx + sx * r * k, cy + sy * r * k
            L(px, py, px - sx * r * a, py); L(px, py, px, py - sy * r * a)
    if name == "bolt":            # lightning strike (the logo)
        f = 0.75 + 0.25 * abs(math.sin(t * 9)) * (1 if int(t * 3) % 4 == 0 else 0.3)
        pts = [(0.18, -0.95), (-0.42, 0.08), (-0.02, 0.08), (-0.24, 0.95), (0.44, -0.18), (0.04, -0.18), (0.28, -0.95)]
        c.create_polygon([v for px, py in pts for v in (cx + px * r, cy + py * r)], fill=lerp(col, WHITE, 0.35 * f), outline=col, width=1)
    elif name == "profile":       # id card
        c.create_rectangle(cx - r * 0.85, cy - r * 0.6, cx + r * 0.85, cy + r * 0.6, outline=col, width=w)
        hb = math.sin(t * 3) * r * 0.05
        c.create_oval(cx - r * 0.62, cy - r * 0.38 + hb, cx - r * 0.18, cy + r * 0.06 + hb, outline=col, width=w)
        L(cx - r * 0.66, cy + r * 0.42, cx - r * 0.14, cy + r * 0.42)
        for k, ln in enumerate((0.55, 0.4, 0.5)):
            yy = cy - r * 0.25 + k * r * 0.25; L(cx + r * 0.05, yy, cx + r * (0.05 + ln * (0.8 + 0.2 * math.sin(t * 4 + k))), yy, width=max(1, w - 1))
    elif name in ("plus", "newprofile"):
        a = math.radians(t * 40); k = 0.55
        for q in range(4):
            aa = a + q * math.pi / 2
            c.create_arc(cx - r * 0.9, cy - r * 0.9, cx + r * 0.9, cy + r * 0.9, start=math.degrees(aa), extent=50, style="arc", outline=lerp(col, BG, 0.4), width=max(1, w - 1))
        L(cx - r * k, cy, cx + r * k, cy, width=w + 1); L(cx, cy - r * k, cx, cy + r * k, width=w + 1)
        if name == "newprofile": c.create_rectangle(cx + r * 0.45, cy - r * 0.9, cx + r * 0.9, cy - r * 0.45, outline=col, width=1)
    elif name == "import":        # arrow dropping into a tray
        o = ((t * 1.2) % 1) * r * 0.35
        L(cx, cy - r * 0.9 + o, cx, cy + r * 0.15 + o); L(cx - r * 0.38, cy - r * 0.2 + o, cx, cy + r * 0.18 + o, cx + r * 0.38, cy - r * 0.2 + o)
        L(cx - r * 0.85, cy + r * 0.25, cx - r * 0.85, cy + r * 0.8, cx + r * 0.85, cy + r * 0.8, cx + r * 0.85, cy + r * 0.25)
    elif name == "folder":
        op = 0.18 * hot
        L(cx - r * 0.9, cy + r * 0.75, cx - r * 0.9, cy - r * 0.65, cx - r * 0.3, cy - r * 0.65, cx - r * 0.1, cy - r * 0.42,
          cx + r * 0.9, cy - r * 0.42, cx + r * 0.9, cy + r * 0.75, cx - r * 0.9, cy + r * 0.75)
        L(cx - r * 0.9, cy - r * (0.15 + op), cx + r * 0.9, cy - r * (0.15 + op), width=max(1, w - 1))
    elif name == "trash":
        lift = r * 0.22 * hot + r * 0.04 * math.sin(t * 5) * hot
        L(cx - r * 0.75, cy - r * 0.55 - lift, cx + r * 0.75, cy - r * 0.55 - lift); L(cx - r * 0.2, cy - r * 0.75 - lift, cx + r * 0.2, cy - r * 0.75 - lift)
        L(cx - r * 0.6, cy - r * 0.4, cx - r * 0.45, cy + r * 0.85, cx + r * 0.45, cy + r * 0.85, cx + r * 0.6, cy - r * 0.4)
        for dx in (-0.2, 0.2): L(cx + r * dx, cy - r * 0.2, cx + r * dx, cy + r * 0.6, width=max(1, w - 1))
    elif name == "gear":
        a0 = t * 1.4
        for k in range(8):
            ang = a0 + k * math.pi / 4
            L(cx + r * 0.55 * math.cos(ang), cy + r * 0.55 * math.sin(ang), cx + r * 0.9 * math.cos(ang), cy + r * 0.9 * math.sin(ang), width=max(3, int(s / 6)))
        c.create_oval(cx - r * 0.62, cy - r * 0.62, cx + r * 0.62, cy + r * 0.62, outline=col, width=w + 1, fill=BG)
        c.create_oval(cx - r * 0.24, cy - r * 0.24, cx + r * 0.24, cy + r * 0.24, outline=col, width=w)
    elif name == "stop":
        brackets(); p = 0.32 + 0.06 * math.sin(t * 5)
        c.create_rectangle(cx - r * p, cy - r * p, cx + r * p, cy + r * p, fill=col, outline="")
    elif name in ("locked", "unlocked"):
        up = name == "unlocked"; lift = r * (0.32 if up else 0.0) + (r * 0.05 * abs(math.sin(t * 4)) if up else 0)
        c.create_rectangle(cx - r * 0.65, cy - r * 0.05, cx + r * 0.65, cy + r * 0.85, outline=col, width=w,
                           fill=lerp(BG, col, 0.25 if not up else 0.1))
        sx = r * 0.4
        c.create_arc(cx - sx, cy - r * 0.75 - lift, cx + sx, cy + r * 0.05 - lift, start=0, extent=180, style="arc", outline=col, width=w)
        L(cx - sx, cy - r * 0.35 - lift, cx - sx, cy - r * 0.05 - (lift if up else 0))
        L(cx + sx, cy - r * 0.35 - lift, cx + sx, cy - r * 0.05 + (0 if up else 0))
        kr = r * 0.12 * (1 + 0.3 * math.sin(t * 6)); c.create_oval(cx - kr, cy + r * 0.3 - kr, cx + kr, cy + r * 0.3 + kr, fill=col, outline="")
    elif name == "edit":          # pencil writing a line
        k = (t * 0.8) % 1
        L(cx - r * 0.7, cy + r * 0.85, cx - r * 0.7 + k * r * 1.4, cy + r * 0.85, width=max(1, w - 1), fill=lerp(col, BG, 0.4))
        L(cx - r * 0.55, cy + r * 0.55, cx + r * 0.55, cy - r * 0.55); L(cx - r * 0.35, cy + r * 0.75, cx + r * 0.75, cy - r * 0.35)
        L(cx - r * 0.55, cy + r * 0.55, cx - r * 0.7, cy + r * 0.9, cx - r * 0.35, cy + r * 0.75); L(cx + r * 0.55, cy - r * 0.55, cx + r * 0.75, cy - r * 0.35)
    elif name == "copy":
        o = r * 0.12 * math.sin(t * 3)
        c.create_rectangle(cx - r * 0.8 - o, cy - r * 0.4 + o, cx + r * 0.3 - o, cy + r * 0.85 + o, outline=col, width=w)
        L(cx - r * 0.4 + o, cy - r * 0.8 - o, cx + r * 0.8 + o, cy - r * 0.8 - o, cx + r * 0.8 + o, cy + r * 0.45 - o)
    elif name == "play":
        a = t * 90
        c.create_arc(cx - r * 0.92, cy - r * 0.92, cx + r * 0.92, cy + r * 0.92, start=a, extent=270, style="arc", outline=lerp(col, BG, 0.35), width=max(1, w - 1))
        k = 1 + 0.08 * math.sin(t * 6)
        c.create_polygon(cx - r * 0.3 * k, cy - r * 0.45 * k, cx + r * 0.5 * k, cy, cx - r * 0.3 * k, cy + r * 0.45 * k, fill=col, outline="")
    elif name == "save":          # check mark drawn on
        k = min(1.0, ((t * 0.9) % 1.4)); pts = [(-0.6, 0.0), (-0.15, 0.45), (0.65, -0.5)]
        brackets(0.95, 0.25)
        if k < 0.4:
            f = k / 0.4; L(cx + r * pts[0][0], cy + r * pts[0][1], cx + r * (pts[0][0] + (pts[1][0] - pts[0][0]) * f), cy + r * (pts[0][1] + (pts[1][1] - pts[0][1]) * f), width=w + 1)
        else:
            f = min(1, (k - 0.4) / 0.6)
            L(cx + r * pts[0][0], cy + r * pts[0][1], cx + r * pts[1][0], cy + r * pts[1][1],
              cx + r * (pts[1][0] + (pts[2][0] - pts[1][0]) * f), cy + r * (pts[1][1] + (pts[2][1] - pts[1][1]) * f), width=w + 1)
    elif name == "cancel":
        k = 0.42 + 0.05 * math.sin(t * 4)
        L(cx - r * k, cy - r * k, cx + r * k, cy + r * k, width=w + 1); L(cx + r * k, cy - r * k, cx - r * k, cy + r * k, width=w + 1)
    elif name == "detect":        # crosshair
        a = t * 1.5
        c.create_oval(cx - r * 0.62, cy - r * 0.62, cx + r * 0.62, cy + r * 0.62, outline=col, width=w)
        for q in range(4):
            aa = a + q * math.pi / 2
            L(cx + math.cos(aa) * r * 0.35, cy + math.sin(aa) * r * 0.35, cx + math.cos(aa) * r * 0.95, cy + math.sin(aa) * r * 0.95)
        c.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=col, outline="")
    elif name == "arrows":        # stratagem input: arrows light up in turn
        on = int(t * 4) % 4
        for q, (dx, dy) in enumerate(((0, -1), (1, 0), (0, 1), (-1, 0))):
            cc = lerp(col, WHITE, 0.6) if q == on else lerp(col, BG, 0.25)
            px, py = cx + dx * r * 0.55, cy + dy * r * 0.55; nx, ny = -dy, dx
            c.create_polygon(px + dx * r * 0.35, py + dy * r * 0.35, px + nx * r * 0.3, py + ny * r * 0.3, px - nx * r * 0.3, py - ny * r * 0.3, fill=cc, outline="")
    elif name == "wasd":
        on = int(t * 4) % 4; ks = (("W", 0, -0.5), ("D", 0.6, 0.35), ("S", 0, 0.35), ("A", -0.6, 0.35))
        for q, (ch, dx, dy) in enumerate(ks):
            kx, ky, kr = cx + dx * r, cy + dy * r, r * 0.28; cc = lerp(col, WHITE, 0.6) if q == on else col
            c.create_rectangle(kx - kr, ky - kr, kx + kr, ky + kr, outline=cc, width=1)
            c.create_text(kx, ky, text=ch, fill=cc, font=(MONO, max(6, int(s / 5)), "bold"))
    elif name == "mic":
        c.create_oval(cx - r * 0.32, cy - r * 0.9, cx + r * 0.32, cy + r * 0.25, outline=col, width=w)
        c.create_arc(cx - r * 0.62, cy - r * 0.5, cx + r * 0.62, cy + r * 0.55, start=200, extent=140, style="arc", outline=col, width=w)
        L(cx, cy + r * 0.55, cx, cy + r * 0.9); L(cx - r * 0.4, cy + r * 0.9, cx + r * 0.4, cy + r * 0.9)
        for k in range(2):
            rr = r * (0.75 + 0.2 * k) + r * 0.1 * ((t * 1.5 + k * 0.5) % 1)
            c.create_arc(cx - rr, cy - rr - r * 0.3, cx + rr, cy + rr - r * 0.3, start=-30, extent=60, style="arc", outline=lerp(col, BG, 0.5), width=1)
    elif name == "rec":           # keyboard capture: key cap with a live dot
        c.create_rectangle(cx - r * 0.85, cy - r * 0.45, cx + r * 0.85, cy + r * 0.75, outline=col, width=w)
        for k in range(4): L(cx - r * 0.6 + k * r * 0.4, cy - r * 0.05, cx - r * 0.45 + k * r * 0.4, cy - r * 0.05, width=max(1, w - 1))
        L(cx - r * 0.45, cy + r * 0.35, cx + r * 0.45, cy + r * 0.35, width=max(1, w - 1))
        pr = r * (0.18 + 0.06 * math.sin(t * 6)); c.create_oval(cx + r * 0.55 - pr, cy - r * 0.75 - pr, cx + r * 0.55 + pr, cy - r * 0.75 + pr, fill=col, outline="")
    elif name == "undo":
        a = (t * 60) % 40
        c.create_arc(cx - r * 0.7, cy - r * 0.6, cx + r * 0.7, cy + r * 0.8, start=-60 + a * 0.2, extent=230, style="arc", outline=col, width=w)
        L(cx - r * 0.85, cy - r * 0.15, cx - r * 0.62, cy + r * 0.25, cx - r * 0.25, cy - r * 0.05)
    elif name == "wait":          # hourglass with falling sand
        L(cx - r * 0.6, cy - r * 0.85, cx + r * 0.6, cy - r * 0.85); L(cx - r * 0.6, cy + r * 0.85, cx + r * 0.6, cy + r * 0.85)
        L(cx - r * 0.5, cy - r * 0.85, cx + r * 0.5, cy + r * 0.85); L(cx + r * 0.5, cy - r * 0.85, cx - r * 0.5, cy + r * 0.85)
        k = (t * 0.7) % 1; c.create_oval(cx - 1.5, cy - r * 0.1 + k * r * 0.7, cx + 1.5, cy - r * 0.1 + k * r * 0.7 + 3, fill=col, outline="")
    elif name == "click":         # mouse with a pulsing left button
        c.create_oval(cx - r * 0.55, cy - r * 0.85, cx + r * 0.55, cy + r * 0.85, outline=col, width=w)
        L(cx - r * 0.55, cy - r * 0.15, cx + r * 0.55, cy - r * 0.15); L(cx, cy - r * 0.85, cx, cy - r * 0.15)
        c.create_polygon(cx - r * 0.5, cy - r * 0.2, cx - r * 0.45, cy - r * 0.6, cx - r * 0.05, cy - r * 0.8, cx - r * 0.05, cy - r * 0.2,
                         fill=lerp(col, BG, 0.5 - 0.5 * math.sin(t * 6)), outline="")
    elif name == "gauge":         # speedometer, needle sweeps
        c.create_arc(cx - r * 0.9, cy - r * 0.75, cx + r * 0.9, cy + r * 1.05, start=0, extent=180, style="arc", outline=col, width=w)
        for k in range(5):
            a = math.radians(180 - k * 45); L(cx + r * 0.62 * math.cos(a), cy + r * 0.15 - r * 0.62 * math.sin(a), cx + r * 0.85 * math.cos(a), cy + r * 0.15 - r * 0.85 * math.sin(a), width=1)
        a = math.radians(160 - 140 * (0.5 + 0.5 * math.sin(t * 1.3)))
        L(cx, cy + r * 0.15, cx + r * 0.7 * math.cos(a), cy + r * 0.15 - r * 0.7 * math.sin(a)); c.create_oval(cx - 2, cy + r * 0.15 - 2, cx + 2, cy + r * 0.15 + 2, fill=col, outline="")
    elif name == "cpu":           # processor chip, data runs along the pins
        c.create_rectangle(cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55, outline=col, width=w)
        on = int(t * 6) % 4
        for k in range(4):
            o = -r * 0.36 + k * r * 0.24; cc = lerp(col, WHITE, 0.6) if k == on else col
            L(cx + o, cy - r * 0.55, cx + o, cy - r * 0.9, width=1, fill=cc); L(cx + o, cy + r * 0.55, cx + o, cy + r * 0.9, width=1, fill=cc)
            L(cx - r * 0.55, cy + o, cx - r * 0.9, cy + o, width=1, fill=cc); L(cx + r * 0.55, cy + o, cx + r * 0.9, cy + o, width=1, fill=cc)
        c.create_rectangle(cx - r * 0.22, cy - r * 0.22, cx + r * 0.22, cy + r * 0.22, fill=col, outline="")
    elif name == "gpu":           # graphics card, fan spinning
        c.create_rectangle(cx - r * 0.95, cy - r * 0.55, cx + r * 0.95, cy + r * 0.55, outline=col, width=w)
        fr = r * 0.4; fx = cx - r * 0.35
        c.create_oval(fx - fr, cy - fr, fx + fr, cy + fr, outline=col, width=1)
        for k in range(3):
            a = t * 9 + k * 2.094; L(fx, cy, fx + fr * 0.9 * math.cos(a), cy + fr * 0.9 * math.sin(a), width=max(1, w - 1))
        for k in range(3): L(cx + r * 0.25 + k * r * 0.22, cy - r * 0.3, cx + r * 0.25 + k * r * 0.22, cy + r * 0.3, width=1)
        L(cx - r * 0.6, cy + r * 0.55, cx - r * 0.6, cy + r * 0.8); L(cx + r * 0.6, cy + r * 0.55, cx + r * 0.6, cy + r * 0.8)
    elif name == "gamepad":
        c.create_polygon(cx - r * 0.95, cy - r * 0.05, cx - r * 0.6, cy - r * 0.45, cx + r * 0.6, cy - r * 0.45, cx + r * 0.95, cy - r * 0.05,
                         cx + r * 0.8, cy + r * 0.5, cx + r * 0.45, cy + r * 0.5, cx + r * 0.25, cy + r * 0.2, cx - r * 0.25, cy + r * 0.2,
                         cx - r * 0.45, cy + r * 0.5, cx - r * 0.8, cy + r * 0.5, outline=col, fill="", width=w)
        L(cx - r * 0.6, cy - r * 0.05, cx - r * 0.3, cy - r * 0.05, width=max(1, w - 1)); L(cx - r * 0.45, cy - r * 0.2, cx - r * 0.45, cy + r * 0.1, width=max(1, w - 1))
        b = 0.5 + 0.5 * math.sin(t * 5)
        for k, (bx, by) in enumerate(((0.45, -0.18), (0.62, 0.0))):
            c.create_oval(cx + r * bx - 2, cy + r * by - 2, cx + r * bx + 2, cy + r * by + 2, fill=lerp(col, WHITE, b if k == 0 else 1 - b), outline="")
    elif name == "listen":        # waves going out (always listening)
        c.create_oval(cx - r * 0.18, cy - r * 0.18, cx + r * 0.18, cy + r * 0.18, fill=col, outline="")
        for k in range(3):
            rr = r * (0.35 + 0.6 * (((t * 0.9) + k / 3) % 1))
            cc = lerp(col, BG, ((t * 0.9) + k / 3) % 1)
            for st in (-50, 130): c.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, start=st, extent=100, style="arc", outline=cc, width=w)
    elif name == "spinner":
        a0 = t * 300
        c.create_arc(cx - r * 0.75, cy - r * 0.75, cx + r * 0.75, cy + r * 0.75, start=a0, extent=250, style="arc", outline=col, width=w + 1)
    elif name == "offline":
        c.create_oval(cx - r * 0.8, cy - r * 0.8, cx + r * 0.8, cy + r * 0.8, outline=col, width=w)
        L(cx - r * 0.55, cy + r * 0.55, cx + r * 0.55, cy - r * 0.55, width=w + 1)
    elif name == "search":
        rr = r * 0.48; ox = math.sin(t * 2) * r * 0.08
        c.create_oval(cx - r * 0.25 - rr + ox, cy - r * 0.25 - rr, cx - r * 0.25 + rr + ox, cy - r * 0.25 + rr, outline=col, width=w)
        L(cx + r * 0.12 + ox, cy + r * 0.12, cx + r * 0.8 + ox, cy + r * 0.8, width=w + 1)
    else:
        brackets()


TIP_HELP = {}


class Tip:
    """hover a thing -> after a moment a small panel explains it (first line = title)"""
    def __init__(self, w, text):
        self.w, self.text, self.tw, self.job = w, text, None, None
        w.bind("<Enter>", self.sched, add="+"); w.bind("<Leave>", self.hide, add="+"); w.bind("<Button-1>", self.hide, add="+")
    def sched(self, e=None):
        self.hide(); self.job = self.w.after(380, self.show)
    def show(self):
        self.job = None
        if not self.text: return
        try:
            tw = self.tw = tk.Toplevel(self.w); tw.overrideredirect(True); tw.attributes("-topmost", True)
            try: tw.attributes("-alpha", 0.0)
            except Exception: pass
            box = tk.Frame(tw, bg="#101218", highlightthickness=1, highlightbackground=RED); box.pack()
            title, _, body = self.text.partition("\n")
            tk.Label(box, text="◢ " + title.upper(), bg="#101218", fg=ORANGE, font=(MONO, 9, "bold"), justify="left", anchor="w", padx=9).pack(fill="x", pady=(5, 0 if body else 5))
            if body: tk.Label(box, text=body, bg="#101218", fg=WHITE, font=(MONO, 9), justify="left", anchor="w", padx=9, wraplength=420).pack(fill="x", pady=(1, 6))
            tw.update_idletasks()
            x = min(self.w.winfo_rootx(), self.w.winfo_screenwidth() - tw.winfo_reqwidth() - 8)
            y = self.w.winfo_rooty() + self.w.winfo_height() + 6
            if getattr(self, "at", None):     # region tips: next to the mouse
                x = min(self.at[0] - 20, self.w.winfo_screenwidth() - tw.winfo_reqwidth() - 8); y = self.at[1] + 22
            if y + tw.winfo_reqheight() > self.w.winfo_screenheight() - 40: y = self.w.winfo_rooty() - tw.winfo_reqheight() - 6
            tw.geometry(f"+{max(0, x)}+{max(0, y)}")
            def fade(i=1):
                if self.tw:
                    try: self.tw.attributes("-alpha", min(0.97, i / 6))
                    except Exception: return
                    if i < 6: self.tw.after(16, lambda: fade(i + 1))
            fade()
        except tk.TclError:
            self.tw = None
    def hide(self, e=None):
        if self.job: self.w.after_cancel(self.job); self.job = None
        if self.tw:
            try: self.tw.destroy()
            except tk.TclError: pass
            self.tw = None


class IconButton(tk.Canvas):
    """Animated icon-only button: the icon moves, brackets lock on when hovered, the name + what it does appear on hover."""
    def __init__(self, parent, icon, cmd, title, desc="", fg=RED, bg=BG, size=34, sound=True):
        super().__init__(parent, width=size + 10, height=size + 6, bg=bg, highlightthickness=0, cursor="hand2")
        self.sound = (icon if icon in SFX_NAMES else "click") if sound is True else sound
        self.icon, self.cmd, self.fg, self.bgc, self.size = icon, cmd, fg, bg, size
        self.h = self.ht = self.flash = 0.0; self.t0 = time.time() - random.random() * 5
        self.tip = Tip(self, title + ("\n" + desc if desc else ""))
        self.bind("<Enter>", lambda e: setattr(self, "ht", 1.0), add="+"); self.bind("<Leave>", lambda e: setattr(self, "ht", 0.0), add="+")
        self.bind("<Button-1>", self.click, add="+")
        self.after(30, self.tick)

    def click(self, e=None):
        self.flash = 1.0
        if self.sound: sfx(self.sound)
        try: self.cmd()
        except Exception: traceback.print_exc()

    def config(self, **kw):
        for k in ("icon", "fg"):
            if k in kw: setattr(self, k, kw.pop(k))
        if "title" in kw or "desc" in kw:
            self.tip.text = kw.pop("title", "") + ("\n" + kw.pop("desc") if kw.get("desc") else "")
            kw.pop("desc", None)
        if kw: super().configure(**kw)
    configure = config

    def tick(self):
        try:
            if PAUSED[0]: self.after(500, self.tick); return
            if self.winfo_ismapped(): self.draw()
            self.after(45 if (self.h > 0.02 or self.flash > 0.02) else 120, self.tick)
        except tk.TclError:
            pass

    def draw(self):
        self.h += (self.ht - self.h) * 0.3; self.flash *= 0.8
        self.delete("all"); W, H = self.winfo_width(), self.winfo_height(); t = time.time() - self.t0
        h, f = self.h, self.flash; x0, y0, x1, y1, cut = 3, 2, W - 4, H - 3, 7
        breathe = 0.5 + 0.5 * math.sin(t * 2.2)
        edge = lerp(lerp(self.bgc, self.fg, 0.35 + 0.15 * breathe), self.fg, h)
        fill = lerp(lerp(self.bgc, "#2A0C0C" if self.fg != ORANGE else "#2A1606", h), self.fg, f * 0.7)
        self.create_polygon(x0, y0, x1 - cut, y0, x1, y0 + cut, x1, y1, x0 + cut, y1, x0, y1 - cut, fill=fill, outline=edge)
        if h > 0.05:   # sweep line + lock-on brackets
            sx = x0 + ((t * 120) % max(1, x1 - x0)); self.create_line(sx, y0 + 1, sx, y1 - 1, fill=lerp(fill, self.fg, 0.3 * h))
            d = 4 * (1 - h); a = 6; bc = lerp(self.bgc, ORANGE, h)
            for (px, py, sx_, sy_) in ((x0 - d + 1, y0 - d + 1, 1, 1), (x1 + d - 1, y0 - d + 1, -1, 1), (x0 - d + 1, y1 + d - 1, 1, -1), (x1 + d - 1, y1 + d - 1, -1, -1)):
                self.create_line(px, py, px + a * sx_, py, fill=bc, width=2); self.create_line(px, py, px, py + a * sy_, fill=bc, width=2)
        col = lerp(lerp(self.fg, self.bgc, 0.25 * (1 - breathe)), WHITE if self.fg != DIM else RED, 0.25 * h)
        if f > 0.3: col = lerp(col, BG, f)
        isz = self.size - 12
        draw_icon(self, self.icon, (W - isz) / 2, (H - isz) / 2, isz, col, t * (1.0 + 1.2 * h), h)


class StatusChip(tk.Canvas):
    """small animated symbol with a key cap / value (PTT key, lock key, macro speed) - hover explains it, click opens OPTIONS"""
    def __init__(self, parent, icon, value_fn, title_fn, cmd, fg=RED, bg=BG):
        super().__init__(parent, width=90, height=34, bg=bg, highlightthickness=0, cursor="hand2")
        self.icon, self.value_fn, self.fg, self.bgc, self.h, self.t0 = icon, value_fn, fg, bg, 0.0, time.time() - random.random() * 4
        self.f = tkfont.Font(family=MONO, size=8, weight="bold")
        self.tip = Tip(self, title_fn()); self.title_fn = title_fn
        self.bind("<Enter>", lambda e: (setattr(self, "h", 1.0), setattr(self.tip, "text", self.title_fn())), add="+")
        self.bind("<Leave>", lambda e: setattr(self, "h", 0.0), add="+")
        self.bind("<Button-1>", lambda e: (sfx("gear"), cmd()), add="+"); self.refresh(); self.after(40, self.tick)
    def refresh(self):
        self.value = self.value_fn() or "—"
        w = 34 + sum(self.f.measure(v) + 12 for v in self.value.split("+")) + 4 * self.value.count("+")
        self.config(width=max(44, w))
    def tick(self):
        try:
            if PAUSED[0]: self.after(500, self.tick); return
            if self.winfo_ismapped(): self.draw()
            self.after(70, self.tick)
        except tk.TclError: pass
    def draw(self):
        self.delete("all"); W, H = self.winfo_width(), self.winfo_height(); t = time.time() - self.t0; h = self.h
        self.create_polygon(1, 1, W - 7, 1, W - 1, 7, W - 1, H - 2, 7, H - 2, 1, H - 8, fill=lerp(self.bgc, "#2A0C0C", h * 0.8),
                            outline=lerp(lerp(self.bgc, self.fg, 0.4 + 0.15 * math.sin(t * 2)), ORANGE, h))
        draw_icon(self, self.icon, 6, 7, 20, lerp(self.fg, WHITE, 0.2 * h), t)
        x = 32
        for k, v in enumerate(self.value.split("+")):           # each key as a key cap
            if k: self.create_text(x - 1, H / 2, text="+", fill=DIM, font=self.f); x += 4
            vw = self.f.measure(v) + 8
            self.create_rectangle(x, 8, x + vw, H - 9, fill="#16181E", outline=lerp(RED_DIM, ORANGE, h))
            self.create_line(x + 1, H - 9, x + vw - 1, H - 9, fill=lerp(RED_DIM, RED, 0.5 + 0.5 * math.sin(t * 3 + k)), width=2)
            self.create_text(x + vw / 2, H / 2 - 1, text=v, fill=WHITE, font=self.f); x += vw + 4


class RegionTip:
    """tooltip for areas of a canvas (header glyphs)"""
    def __init__(self, widget):
        self.w, self.text, self.tip = widget, None, None
    def set(self, text):
        if text == self.text: return
        if self.tip: self.tip.hide()
        self.text = text
        if text:
            self.tip = Tip.__new__(Tip); self.tip.w, self.tip.text, self.tip.tw, self.tip.job = self.w, text, None, None
            self.tip.at = self.w.winfo_pointerxy(); self.tip.sched()
        else: self.tip = None


BTN = {   # label -> (icon, name, what it does)
    "✔ SAVE": ("save", "Save", "keep the changes"),
    "▶ TEST IN 3 s": ("play", "Test", "presses the keys after 3 seconds -\nswitch to the game or Notepad"),
    "CANCEL": ("cancel", "Cancel", "close without saving"),
    "⌖ DETECT": ("detect", "Detect game", "click, then switch to the game within 5 seconds"),
    "ARROW KEYS": ("arrows", "Arrow keys", "stratagem directions = ↑ ↓ ← →"),
    "WASD": ("wasd", "WASD", "stratagem directions = W A S D"),
    "✎ PROFILE": ("profile", "Profile", "name, game .exe and stratagem keys of this profile"),
    "＋ NEW": ("newprofile", "New profile", "start an empty profile for another game"),
    "⇩ IMPORT": ("import", "Import", "VoiceAttack .vap (XML) or a Skynet .json profile"),
    "▣ FOLDER": ("folder", "Profiles folder", "open the folder with the profile files"),
    "✖": ("trash", "Delete profile", "moves the file to profiles\\deleted"),
    "■ STOP MACRO": ("stop", "Stop macro", "abort the macro that is running right now"),
    "⚙ OPTIONS": ("gear", "Options", "recording device, push-to-talk, lock key,\nmacro speed, speech AI"),
    "＋ ADD": ("plus", "Add command", "new voice command for this profile"),
    "✎ EDIT": ("edit", "Edit command", "change the selected command (or double-click it)"),
    "⧉ COPY": ("copy", "Duplicate", "copy the selected command"),
    "▶ TEST": ("play", "Test command", "presses its keys after 3 seconds"),
    "✖ DELETE": ("trash", "Delete command", "remove the selected command"),
    "■ LOCK LISTENING": ("unlocked", "Listening is ON", "click to LOCK - nothing you say will fire"),
    "▶ UNLOCK LISTENING": ("locked", "Listening is LOCKED", "click to UNLOCK - commands go live"),
}


def hbtn(parent, text, cmd, fg=RED, bold=False, bg=PANEL, tip=None, size=None):
    icon, title, desc = BTN.get(text, ("plus", text.title(), ""))
    b = IconButton(parent, icon, cmd, title, tip or desc, fg=fg, bg=bg, size=size or (40 if bold else 34))
    _cfg = b.config
    def config(**kw):   # hbtn(...).config(text=...) swaps icon + hover text
        if "text" in kw:
            i, tl, d = BTN.get(kw.pop("text"), (b.icon, "", "")); kw.update(icon=i, title=tl, desc=d)
        _cfg(**kw)
    b.config = b.configure = config
    return b


# ======================================================================  static background + HUD lists
def _png_b64(rgb):
    """numpy HxWx3 uint8 -> base64 PNG that tk.PhotoImage reads directly (no Pillow needed)"""
    import base64, struct
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode("ascii")


_STATIC_CACHE = {}


def static_frames(bg, amount):
    """8 tiles of dark red-tinted TV static (made once, shared by every background)"""
    key = (bg, amount)
    if key not in _STATIC_CACHE:
        rng = np.random.default_rng(7); TH, TW = 110, 190; base = np.array([int(bg[i:i + 2], 16) for i in (1, 3, 5)], np.float32)
        out = []
        for _ in range(8):
            g = rng.random((TH, TW), dtype=np.float32) ** 2.2                     # mostly dark grain, a few bright specks
            g += rng.normal(0, 0.06, (TH, 1)).astype(np.float32)                  # horizontal interference streaks
            hot = rng.random(TH) < 0.03; g[hot] += 0.25                            # a few brighter scan rows
            lum = np.clip(g, 0, 1) * amount
            rgb = base + lum[..., None] * np.array([1.0, 0.42, 0.42], np.float32)
            img = tk.PhotoImage(data=_png_b64(np.clip(rgb, 0, 255).astype(np.uint8)))
            out.append(img.zoom(2, 2))
        _STATIC_CACHE[key] = out
    return _STATIC_CACHE[key]


class StaticField:
    """Background = flickering TV static. Pre-made image tiles, each frame only swaps which tile picture is shown,
    so it is very light. No text, no shapes, never reacts to the mouse."""
    def __init__(self, canvas, amount=34, fps=11, **_ignored):
        self.c, self.amount, self.dt = canvas, amount, int(1000 / fps)
        self.bg = canvas.cget("bg"); self.key, self.job, self.oy, self.tiles, self.frames = None, None, 0.0, [], None
        self.rnd = random.Random()
        canvas.bind("<Configure>", lambda e: self.schedule(), add="+")
        canvas.after(120, self.tick)

    def schedule(self):
        if self.job: self.c.after_cancel(self.job)
        self.job = self.c.after(150, self.rebuild)

    def rebuild(self):
        self.job = None; c = self.c
        try: w, h = c.winfo_width(), c.winfo_height()
        except tk.TclError: return
        if w < 4 or h < 4: return
        try: self.frames = self.frames or static_frames(self.bg, self.amount)
        except Exception: traceback.print_exc(); self.frames = []
        c.delete("amb"); self.tiles = []
        if not self.frames: return
        tw, th = self.frames[0].width(), self.frames[0].height(); oy = c.canvasy(0); self.oy = oy; self.key = (w, h)
        for i in range(int(w // tw) + 1):
            for j in range(int(h // th) + 1):
                self.tiles.append(c.create_image(i * tw, oy + j * th, image=self.rnd.choice(self.frames), anchor="nw", tags=("amb",)))
        c.tag_lower("amb")

    def tick(self):
        c = self.c
        try:
            if not c.winfo_ismapped() or PAUSED[0]: c.after(500, self.tick); return
            if (c.winfo_width(), c.winfo_height()) != self.key and not self.job: self.schedule()
            oy = c.canvasy(0)
            if oy != self.oy: c.move("amb", 0, oy - self.oy); self.oy = oy
            fr = self.frames
            if self.tiles:                                   # a few tiles per frame: still flickers, a third of the work
                for iid in self.rnd.sample(self.tiles, max(1, len(self.tiles) // 3)): c.itemconfig(iid, image=fr[self.rnd.randrange(len(fr))])
            c.after(self.dt, self.tick)
        except tk.TclError:
            pass



def clear_except(c, keep="amb"):
    """delete everything on a canvas except the background animation"""
    c.addtag_all("old"); c.dtag(keep, "old"); c.delete("old")


class Splitter(tk.Frame):
    """Two panes with a modern drag handle between them (glowing rail + grip pill with ◂ ▸ chevrons).
    Drag to resize, double-click to reset. The position is remembered."""
    def __init__(self, parent, ratio=0.58, on_change=None, bg=BG):
        super().__init__(parent, bg=bg)
        self.ratio, self.on_change, self.h, self.drag = ratio, on_change, 0.0, False
        self.left = tk.Frame(self, bg=bg); self.right = tk.Frame(self, bg=bg)
        self.grip = tk.Canvas(self, width=18, bg=bg, highlightthickness=0, cursor="sb_h_double_arrow")
        g = self.grip
        g.bind("<Enter>", lambda e: self.hover(1)); g.bind("<Leave>", lambda e: None if self.drag else self.hover(0))
        g.bind("<Button-1>", self.press); g.bind("<B1-Motion>", self.move); g.bind("<ButtonRelease-1>", self.release)
        g.bind("<Double-Button-1>", lambda e: self.set_ratio(0.58, True)); g.bind("<Configure>", lambda e: self.draw())
        self.bind("<Configure>", lambda e: self.layout()); Tip(g, "Resize\ndrag to make the command list or the log wider\ndouble-click = reset")
        self.layout()

    def layout(self):
        r = self.ratio
        self.left.place(relx=0, rely=0, relwidth=r, relheight=1, width=-9)
        self.grip.place(relx=r, rely=0, relheight=1, x=-9, width=18)
        self.right.place(relx=r, rely=0, relwidth=1 - r, relheight=1, x=9, width=-9)

    def set_ratio(self, r, save=False):
        self.ratio = max(0.28, min(0.8, r)); self.layout(); self.draw()
        if save and self.on_change: self.on_change(self.ratio)

    def hover(self, v): self.h = v; self.draw()
    def press(self, e): self.drag = True; self.hover(1); sfx("select")
    def move(self, e):
        w = max(1, self.winfo_width()); self.set_ratio((e.x_root - self.winfo_rootx()) / w)
    def release(self, e):
        self.drag = False; self.hover(0); self.on_change and self.on_change(self.ratio)

    def draw(self):
        g = self.grip; g.delete("all"); w, h = g.winfo_width(), g.winfo_height(); cx, cy = w / 2, h / 2; on = self.h
        g.create_line(cx, 6, cx, h - 6, fill=lerp(GRID, RED_DIM, on), width=1)            # rail
        if on: g.create_line(cx, cy - 70, cx, cy + 70, fill=RED, width=2)                  # glowing section while hovered
        ph, pw = 46, 12                                                                    # grip pill
        g.create_polygon(cx - pw / 2, cy - ph / 2 + 4, cx - pw / 2 + 4, cy - ph / 2, cx + pw / 2 - 4, cy - ph / 2, cx + pw / 2, cy - ph / 2 + 4,
                         cx + pw / 2, cy + ph / 2 - 4, cx + pw / 2 - 4, cy + ph / 2, cx - pw / 2 + 4, cy + ph / 2, cx - pw / 2, cy + ph / 2 - 4,
                         fill=lerp(PANEL, "#2A1606", on), outline=lerp(RED_DIM, ORANGE, on))
        col = lerp(RED, ORANGE, on)
        for d in (-1, 1):                                                                  # ◂ ▸ chevrons
            yy = cy + d * 11
            g.create_polygon(cx - 3, yy, cx + 1, yy - 4, cx + 1, yy + 4, fill=col, outline="") if d < 0 else \
                g.create_polygon(cx + 3, yy, cx - 1, yy - 4, cx - 1, yy + 4, fill=col, outline="")
        for k in (-3, 0, 3): g.create_oval(cx - 1.2, cy + k - 1.2, cx + 1.2, cy + k + 1.2, fill=col, outline="")   # grip dots


class HudScrollbar(tk.Canvas):
    """thin animated HUD scrollbar: glowing thumb, ticks, drag / click / wheel"""
    def __init__(self, parent, target, bg=PANEL):
        super().__init__(parent, width=12, bg=bg, highlightthickness=0, cursor="hand2")
        self.target, self.first, self.last, self.hot, self.th, self.glow, self.drag = target, 0.0, 1.0, 0.0, 0.0, 0.0, None
        self.bind("<Enter>", lambda e: self._h(1)); self.bind("<Leave>", lambda e: self._h(0))
        self.bind("<Button-1>", self.press); self.bind("<B1-Motion>", self.move)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))
        self.bind("<MouseWheel>", lambda e: target.wheel(e) if hasattr(target, "wheel") else target.yview_scroll(int(-e.delta / 40), "units"))
        self.bind("<Configure>", lambda e: self.draw())
    def _h(self, v): self.th = v; self.anim()
    def anim(self):
        self.hot += (self.th - self.hot) * 0.3; self.glow *= 0.88; self.draw()
        if abs(self.th - self.hot) > 0.02 or self.glow > 0.03: self.after(16, self.anim)
    def set_pos(self, first, last):
        self.first, self.last = float(first), float(last); self.glow = 1.0; self.anim()
    def draw(self):
        self.delete("all"); w, h = self.winfo_width(), self.winfo_height()
        if self.last - self.first >= 0.999 or h < 10: return
        for k in range(0, h, 18): self.create_line(w / 2 - 2, k, w / 2 + 2, k, fill=GRID)
        self.create_line(w / 2, 2, w / 2, h - 2, fill=GRID)
        y0, y1 = 2 + self.first * (h - 4), max(2 + self.first * (h - 4) + 18, 2 + self.last * (h - 4))
        col = lerp(RED_DIM, ORANGE if self.hot > 0.5 else RED, max(self.hot, self.glow))
        x0 = 2 if self.hot > 0.3 else 3
        self.create_polygon(x0, y0 + 4, w / 2, y0, w - x0, y0 + 4, w - x0, y1 - 4, w / 2, y1, x0, y1 - 4, fill=col, outline="")
        for k in range(3):
            yy = (y0 + y1) / 2 + (k - 1) * 4; self.create_line(x0 + 2, yy, w - x0 - 2, yy, fill=lerp(col, BG, 0.5))
    def press(self, e):
        h = max(1, self.winfo_height()); pos = e.y / h
        if not (self.first <= pos <= self.last): self.target.yview_moveto(max(0, pos - (self.last - self.first) / 2))
        self.drag = (e.y, self.first)
    def move(self, e):
        if self.drag: self.target.yview_moveto(self.drag[1] + (e.y - self.drag[0]) / max(1, self.winfo_height()))


class SmoothScroll:
    """mixin for a canvas self.c: wheel = eased scrolling"""
    def wheel(self, e):
        c = self.c; total = float(c.cget("scrollregion").split()[3]) if c.cget("scrollregion") else 0
        view = c.winfo_height()
        if total <= view: return
        cur = c.canvasy(0) if self.target_y is None else self.target_y
        self.target_y = max(0.0, min(total - view, cur - e.delta / 120 * 70))
        if not self.scrolling: self.scrolling = True; self.ease()
    def ease(self):
        c = self.c; total = float(c.cget("scrollregion").split()[3]); cur = c.canvasy(0)
        d = self.target_y - cur
        if abs(d) < 1:
            c.yview_moveto(self.target_y / total); self.scrolling = False; self.target_y = None; return
        c.yview_moveto((cur + d * 0.28) / total); c.after(15, self.ease)
    def yview(self, *a): return self.c.yview(*a)
    def yview_moveto(self, f): self.target_y = None; self.c.yview_moveto(f)
    def yview_scroll(self, n, what): self.c.yview_scroll(n, what)


class RowCard:
    """hover card for a command: every phrase you can say + the macro (arrows drawn)"""
    def __init__(self, owner):
        self.owner, self.tw, self.key = owner, None, None

    def show(self, info, x, y):
        key = info.get("name")
        if self.tw and key == self.key: self.place(x, y); return
        self.hide(); self.key = key
        tw = self.tw = tk.Toplevel(self.owner); tw.overrideredirect(True); tw.attributes("-topmost", True); tw.configure(bg=RED)
        try: tw.attributes("-alpha", 0.0)
        except Exception: pass
        box = tk.Frame(tw, bg="#0B0C10"); box.pack(padx=1, pady=1)
        tk.Label(box, text="◢ " + info["name"].upper(), bg="#0B0C10", fg=ORANGE, font=(MONO, 10, "bold"), anchor="w", padx=10).pack(fill="x", pady=(7, 2))
        if info.get("code"):
            cv = tk.Canvas(box, height=26, width=max(120, 22 * len(info["code"]) + 20), bg="#0B0C10", highlightthickness=0); cv.pack(anchor="w", padx=10, pady=(0, 4))
            for k, d in enumerate(info["code"]): draw_arrow(cv, 18 + k * 22, 13, 8, d, ORANGE)
        tk.Label(box, text="SAY ANY OF THESE", bg="#0B0C10", fg=RED_DIM, font=(MONO, 8, "bold"), anchor="w", padx=10).pack(fill="x")
        ph = info.get("phrases") or ["—"]; cols = 2 if len(ph) > 6 else 1
        grid = tk.Frame(box, bg="#0B0C10"); grid.pack(fill="x", padx=10, pady=(2, 4))
        for k, p in enumerate(ph):
            tk.Label(grid, text="▸ " + p, bg="#0B0C10", fg=WHITE, font=(MONO, 9), anchor="w").grid(row=k // cols, column=k % cols, sticky="w", padx=(0, 18))
        acts = [pretty_action(a) for a in info.get("actions", []) if not a.startswith("#")]
        if acts and not info.get("code"):
            tk.Label(box, text="DOES", bg="#0B0C10", fg=RED_DIM, font=(MONO, 8, "bold"), anchor="w", padx=10).pack(fill="x")
            tk.Label(box, text="\n".join(acts), bg="#0B0C10", fg=ORANGE, font=(MONO, 9), anchor="w", justify="left", padx=10).pack(fill="x", pady=(0, 4))
        tk.Label(box, text="double-click to edit", bg="#0B0C10", fg=DIM, font=(MONO, 8), anchor="w", padx=10).pack(fill="x", pady=(0, 6))
        tw.update_idletasks(); self.place(x, y)
        def fade(i=1):
            if self.tw:
                try: self.tw.attributes("-alpha", min(0.97, i / 5))
                except Exception: return
                if i < 5: self.tw.after(16, lambda: fade(i + 1))
        fade()

    def place(self, x, y):
        tw = self.tw
        if not tw: return
        w, h = tw.winfo_reqwidth(), tw.winfo_reqheight(); sw, sh = tw.winfo_screenwidth(), tw.winfo_screenheight()
        x = x + 24 if x + 24 + w < sw else x - w - 24; y = min(max(0, y - 20), sh - h - 40)
        tw.geometry(f"+{int(x)}+{int(y)}")

    def hide(self):
        if self.tw:
            try: self.tw.destroy()
            except tk.TclError: pass
        self.tw, self.key = None, None


def draw_arrow(c, cx, cy, r, d, col, tags=()):
    dx, dy = {"U": (0, -1), "D": (0, 1), "L": (-1, 0), "R": (1, 0)}[d]; nx, ny = -dy, dx
    return c.create_polygon(cx + dx * r, cy + dy * r, cx - dx * r * 0.55 + nx * r, cy - dy * r * 0.55 + ny * r,
                            cx - dx * r * 0.55 - nx * r, cy - dy * r * 0.55 - ny * r, fill=col, outline="", tags=tags)


def stratagem_code(actions):
    """the arrows of a command whose macro is one stratagem, else None"""
    acts = [a for a in actions if a.strip() and not a.startswith("#")]
    if len(acts) == 1 and acts[0].lower().startswith("stratagem "):
        code = [ARROWS.get(ch.upper() if ch.isalpha() else ch) for ch in acts[0].split(None, 1)[1] if not ch.isspace() and ch not in ",-"]
        if code and None not in code: return code
    return None


class HudList(tk.Frame, SmoothScroll):
    """the command table on a canvas: clearly separated columns, hover card with every phrase,
    animated stratagem arrows (chase on the hovered / selected row + a slow scan wave), lock-on selection, smooth scroll"""
    ROW = 30

    def __init__(self, parent, cols, on_open, on_delete):
        super().__init__(parent, bg=PANEL, highlightthickness=1, highlightbackground=GRID)
        self.cols, self.on_open, self.on_delete = cols, on_open, on_delete      # cols: [(title, weight)]
        self.head = tk.Canvas(self, height=28, bg=BG, highlightthickness=0); self.head.pack(fill="x")
        self.sb = HudScrollbar(self, self); self.sb.pack(side="right", fill="y", padx=(0, 2), pady=2)
        self.c = tk.Canvas(self, bg=PANEL, highlightthickness=0, yscrollincrement=1, takefocus=1); self.c.pack(fill="both", expand=True)
        self.c.config(yscrollcommand=self.sb.set_pos)
        self.amb = StaticField(self.c)
        self.font = tkfont.Font(family=MONO, size=10); self.fontb = tkfont.Font(family=MONO, size=10, weight="bold")
        self.fonts = tkfont.Font(family=MONO, size=8, weight="bold")
        self.rows, self.sel, self.hover, self.target_y, self.scrolling, self.t0, self.job = [], None, None, None, False, time.time(), None
        self.card, self.card_job, self.lit, self.mouse = RowCard(self), None, {}, (0, 0)
        c = self.c
        c.bind("<Configure>", lambda e: self.later(), add="+"); self.head.bind("<Configure>", lambda e: self.draw_head())
        c.bind("<Motion>", self.motion); c.bind("<Leave>", lambda e: self.set_hover(None))
        c.bind("<Button-1>", self.click); c.bind("<Double-Button-1>", lambda e: (self.card.hide(), self.on_open()))
        c.bind("<MouseWheel>", lambda e: (self.card.hide(), self.wheel(e))); c.bind("<Return>", lambda e: self.on_open()); c.bind("<Delete>", lambda e: self.on_delete())
        c.bind("<Up>", lambda e: self.step(-1)); c.bind("<Down>", lambda e: self.step(1))
        self.after(60, self.pulse)

    def later(self):
        if self.job: self.after_cancel(self.job)
        self.job = self.after(60, self.redraw)

    def set_rows(self, rows):     # rows: [(iid, (values...), enabled, info)]
        self.rows = [r if len(r) > 3 else (*r, {}) for r in rows]
        if self.sel not in [r[0] for r in self.rows]: self.sel = None
        self.redraw()

    def widths(self):
        W = max(100, self.c.winfo_width() - 4); tot = sum(wt for _, wt in self.cols)
        return [W * wt / tot for _, wt in self.cols]

    def fit(self, text, px, font):
        if font.measure(text) <= px: return text
        lo, hi = 0, len(text)
        while lo < hi:
            m = (lo + hi + 1) // 2
            if font.measure(text[:m] + "…") <= px: lo = m
            else: hi = m - 1
        return text[:lo] + "…"

    def draw_head(self):
        h = self.head; h.delete("all"); x = 0; W = h.winfo_width()
        for k, ((title, _), w) in enumerate(zip(self.cols, self.widths())):
            h.create_polygon(x + 3, 4, x + w - 10, 4, x + w - 4, 10, x + w - 4, 25, x + 3, 25, fill="#120707" if k % 2 == 0 else "#0E0E12", outline=RED_DIM)
            h.create_text(x + 12, 15, text="◢ " + title, fill=ORANGE if k == 0 else RED, font=(MONO, 9, "bold"), anchor="w"); x += w

    def redraw(self):
        self.job = None; c = self.c; c.delete("row"); W = c.winfo_width(); ws = self.widths(); R = self.ROW; self.lit = {}
        H = max(c.winfo_height(), len(self.rows) * R)
        c.create_rectangle(0, 0, ws[0], H, fill="#110909", outline="", tags=("row", "colband"))       # COMMAND column band
        x = 0
        for w in ws[:-1]:
            x += w; c.create_line(x, 0, x, H, fill=lerp(PANEL, RED_DIM, 0.75), tags=("row",))           # column separators
        for n, (iid, vals, on, info) in enumerate(self.rows):
            y = n * R; cy = y + R / 2
            c.create_rectangle(1, y + 1, W - 2, y + R - 1, fill="", outline="", tags=("row", f"bg{n}"))
            x = 0
            for k, (v, w) in enumerate(zip(vals, ws)):
                tx = x + 12
                if k == 1 and info.get("phrases"):                     # first phrases + "+N" badge (hover shows all)
                    ph = info["phrases"]; more = len(ph) - 2
                    badge = f"+{more}" if more > 0 else ""
                    bw = self.fonts.measure(badge) + 10 if badge else 0
                    c.create_text(tx, cy, text=self.fit(" · ".join(ph[:2]), w - 26 - bw, self.font), fill="#C8CCD6" if on else lerp(DIM, PANEL, 0.3),
                                  font=self.font, anchor="w", tags=("row", f"t{n}"))
                    if badge:
                        bx = x + w - bw - 8
                        c.create_rectangle(bx, cy - 8, bx + bw, cy + 8, fill="#2A1606", outline=RED_DIM, tags=("row",))
                        c.create_text(bx + bw / 2, cy, text=badge, fill=ORANGE, font=self.fonts, tags=("row",))
                elif k == 2 and info.get("code"):                      # animated stratagem arrows
                    c.create_polygon(tx, cy, tx + 4, cy - 4, tx + 8, cy, tx + 4, cy + 4, fill=RED if on else GRID, outline="", tags=("row",))
                    step = min(15, (w - 34) / max(1, len(info["code"])))
                    for j, d in enumerate(info["code"]):
                        draw_arrow(c, tx + 20 + j * step, cy, min(6, step * 0.42), d, ORANGE if on else lerp(DIM, PANEL, 0.3), tags=("row", f"a{n}", f"a{n}_{j}"))
                else:
                    col = (WHITE if k == 0 else DIM) if on else lerp(DIM, PANEL, 0.3)
                    f = self.fontb if k == 0 else self.font
                    c.create_text(tx, cy, text=self.fit(str(v), w - 22, f), fill=col, font=f, anchor="w", tags=("row", f"t{n}"))
                x += w
            c.create_line(6, y + R - 1, W - 6, y + R - 1, fill=lerp(PANEL, GRID, 0.6), tags=("row",))
        c.config(scrollregion=(0, 0, W, H))
        c.tag_raise("row"); c.tag_lower("colband", "row"); self.draw_head(); self.paint()

    def index_of(self, iid):
        return next((n for n, r in enumerate(self.rows) if r[0] == iid), None)

    def paint(self):
        c = self.c; c.delete("mark"); R = self.ROW
        for n in range(len(self.rows)): c.itemconfig(f"bg{n}", fill="", stipple="")
        hn = self.index_of(self.hover) if self.hover is not None else None
        if hn is not None and self.hover != self.sel: c.itemconfig(f"bg{hn}", fill="#2A0C0C", stipple="gray50")
        sn = self.index_of(self.sel) if self.sel is not None else None
        if sn is not None:
            y = sn * R; c.itemconfig(f"bg{sn}", fill="#3A0E0E", stipple="gray75")
            c.create_rectangle(1, y + 2, 4, y + R - 2, fill=ORANGE, outline="", tags=("mark",))
            self.brackets(sn)

    def brackets(self, n, k=0.0):
        c = self.c; c.delete("brk"); W = c.winfo_width(); y0, y1 = n * self.ROW + 2, (n + 1) * self.ROW - 2; a = 7; d = 2 * math.sin(k)
        for x, y, sx, sy in ((6 - d, y0, 1, 1), (W - 8 + d, y0, -1, 1), (6 - d, y1, 1, -1), (W - 8 + d, y1, -1, -1)):
            c.create_line(x, y, x + a * sx, y, fill=ORANGE, width=2, tags=("mark", "brk")); c.create_line(x, y, x, y + a * sy, fill=ORANGE, width=2, tags=("mark", "brk"))

    def pulse(self):
        """arrows: a light runs along them on the hovered / selected row; every few seconds a scan wave sweeps the visible rows"""
        try:
            if PAUSED[0]: self.after(500, self.pulse); return
            if self.winfo_ismapped():
                t = time.time() - self.t0; c = self.c
                sn = self.index_of(self.sel) if self.sel is not None else None
                if sn is not None: self.brackets(sn, t * 4)
                hn = self.index_of(self.hover) if self.hover is not None else None
                top = int(c.canvasy(0) // self.ROW); vis = range(max(0, top), min(len(self.rows), top + c.winfo_height() // self.ROW + 2))
                wave = (t % 7.0) * (len(vis) + 6) / 2.2 - 3 + top          # row index the scan wave is on (runs ~2.2 s of every 7 s)
                for n in vis:
                    code = self.rows[n][3].get("code") if self.rows[n][2] else None
                    if not code: continue
                    if n in (hn, sn):
                        j = int(t * 9) % (len(code) + 2)
                        state = tuple(WHITE if q == j else (lerp(ORANGE, WHITE, 0.45) if q == j - 1 else ORANGE) for q in range(len(code)))
                    else:
                        g = max(0.0, 1 - abs(n - wave) / 1.6) if (t % 7.0) < 2.2 else 0.0
                        state = tuple(lerp(ORANGE, "#FFD7A8", g) for _ in code)
                    if self.lit.get(n) != state:
                        for j, col in enumerate(state): c.itemconfig(f"a{n}_{j}", fill=col)
                        self.lit[n] = state
            self.after(60, self.pulse)
        except tk.TclError: pass

    def row_at(self, e):
        n = int(self.c.canvasy(e.y) // self.ROW)
        return self.rows[n][0] if 0 <= n < len(self.rows) else None

    def motion(self, e):
        self.mouse = (e.x_root, e.y_root); self.set_hover(self.row_at(e))
        if self.card.tw: self.card.place(e.x_root, e.y_root)

    def set_hover(self, iid):
        if iid == self.hover: return
        self.hover = iid; self.paint(); self.c.config(cursor="hand2" if iid is not None else "")
        if self.card_job: self.after_cancel(self.card_job); self.card_job = None
        if iid is None: self.card.hide(); return
        n = self.index_of(iid); info = self.rows[n][3] if n is not None else {}
        if not info: self.card.hide(); return
        if self.card.tw: self.card.show(info, *self.mouse)                     # already open -> follow instantly
        else: self.card_job = self.after(380, lambda: self.hover == iid and self.card.show(info, *self.mouse))

    def click(self, e):
        self.c.focus_set(); iid = self.row_at(e)
        if iid is not None and iid != self.sel: sfx("select")
        self.sel = iid; self.paint()

    def step(self, d):
        if not self.rows: return
        n = self.index_of(self.sel); n = 0 if n is None else max(0, min(len(self.rows) - 1, n + d))
        self.select(self.rows[n][0]); sfx("select")

    def select(self, iid):
        self.sel = iid; self.paint(); n = self.index_of(iid)
        if n is None: return
        c = self.c; top, h = c.canvasy(0), c.winfo_height(); total = max(1, len(self.rows) * self.ROW)
        if n * self.ROW < top or (n + 1) * self.ROW > top + h: c.yview_moveto(max(0, n * self.ROW - h / 3) / total)

    def selected(self): return self.sel


class LogView(tk.Frame, SmoothScroll):
    """command log on the hex armor; lines with a ▸ can be clicked (open the command / make a new one)"""
    COLORS = {"ok": GREEN, "miss": DIM, "err": RED, "sys": ORANGE, "dim": DIM}

    def __init__(self, parent, on_link):
        super().__init__(parent, bg=PANEL, highlightthickness=1, highlightbackground=GRID)
        self.on_link = on_link
        self.sb = HudScrollbar(self, self); self.sb.pack(side="right", fill="y", padx=(0, 2), pady=2)
        self.c = tk.Canvas(self, bg=PANEL, highlightthickness=0, yscrollincrement=1); self.c.pack(fill="both", expand=True)
        self.c.config(yscrollcommand=self.sb.set_pos); self.amb = StaticField(self.c, amount=26)
        self.font = tkfont.Font(family=MONO, size=10)
        self.data, self.y, self.width, self.target_y, self.scrolling, self.job = [], 6, 0, None, False, None
        self.c.bind("<Configure>", self.resized, add="+"); self.c.bind("<MouseWheel>", self.wheel)

    def resized(self, e):
        if abs(e.width - self.width) > 8:
            self.width = e.width
            if self.job: self.after_cancel(self.job)
            self.job = self.after(80, self.relayout)

    def relayout(self):
        self.job = None; self.c.delete("entry"); self.y = 6
        for n in range(len(self.data) + 120):              # old click handlers would point at the wrong lines
            for ev in ("<Enter>", "<Leave>", "<Button-1>"): self.c.tag_unbind(f"e{n}", ev)
        for n, d in enumerate(self.data): self.draw(n, d, fade=False)
        self.finish(True)

    def add(self, ts, text, tag, link=None):
        at_end = self.c.yview()[1] >= 0.98
        self.data.append((ts, text, tag, link))
        if len(self.data) > 400: self.data = self.data[-300:]; self.relayout(); return
        self.draw(len(self.data) - 1, self.data[-1]); self.finish(at_end)

    def finish(self, to_end):
        c = self.c; c.config(scrollregion=(0, 0, c.winfo_width(), max(c.winfo_height(), self.y + 6)))
        if to_end: c.yview_moveto(1.0)

    def draw(self, n, d, fade=True):
        ts, text, tag, link = d; c = self.c; W = max(200, c.winfo_width()); g = f"e{n}"
        col = self.COLORS.get(tag, WHITE)
        c.create_text(10, self.y, text=ts, fill=RED_DIM, font=(MONO, 9), anchor="nw", tags=("entry", g))
        t = c.create_text(84, self.y, text=text + ("  ▸" if link else ""), fill=WHITE if fade else col, font=self.font, anchor="nw",
                          width=W - 100, tags=("entry", g, f"x{n}"))
        bb = c.bbox(t) or (0, self.y, 0, self.y + 16); h = bb[3] - self.y
        if link:
            hit = c.create_rectangle(4, self.y - 3, W - 6, self.y + h + 3, fill="", outline="", tags=("entry", g, f"h{n}"))
            c.tag_lower(hit, t)
            for ev, fn in (("<Enter>", lambda e, n=n, col=col: self.hl(n, True, col)), ("<Leave>", lambda e, n=n, col=col: self.hl(n, False, col)),
                           ("<Button-1>", lambda e, link=link: (sfx("edit"), self.on_link(link)))):
                c.tag_bind(g, ev, fn)
        self.y += h + 7
        if fade: self.fade(n, col, 0)

    def hl(self, n, on, col):
        c = self.c
        c.itemconfig(f"h{n}", fill="#2A1606" if on else "", stipple="gray50" if on else "", outline=ORANGE if on else "")
        c.itemconfig(f"x{n}", fill=WHITE if on else col); c.config(cursor="hand2" if on else "")

    def fade(self, n, col, k):
        try:
            self.c.itemconfig(f"x{n}", fill=lerp(WHITE, col, k / 10))
            if k < 10: self.after(50, lambda: self.fade(n, col, k + 1))
        except tk.TclError: pass


class Chip(tk.Canvas):
    """small selectable group pill"""
    def __init__(self, parent, text, on_pick, bg=BG):
        self.f = tkfont.Font(family=MONO, size=9, weight="bold"); w = self.f.measure(text) + 22
        super().__init__(parent, width=w, height=24, bg=bg, highlightthickness=0, cursor="hand2")
        self.text, self.on_pick, self.on, self.h, self.bgc = text, on_pick, False, 0.0, bg
        self.bind("<Enter>", lambda e: self.set_h(1)); self.bind("<Leave>", lambda e: self.set_h(0))
        self.bind("<Button-1>", lambda e: (sfx("chip"), on_pick(text))); self.bind("<Configure>", lambda e: self.draw())
    def set_h(self, v): self.h = v; self.draw()
    def set(self, on): self.on = on; self.draw()
    def draw(self):
        self.delete("all"); w, h = self.winfo_width(), self.winfo_height(); cut = 6
        fill = ORANGE if self.on else (lerp(self.bgc, "#2A0C0C", self.h))
        self.create_polygon(1, 1, w - cut, 1, w - 1, cut, w - 1, h - 2, cut, h - 2, 1, h - cut, fill=fill, outline=ORANGE if (self.on or self.h) else RED_DIM)
        self.create_text(w / 2, h / 2, text=self.text, fill=BG if self.on else (WHITE if self.h else "#B8BCC6"), font=self.f)


class PadKey(tk.Canvas):
    """one key of the clickable stratagem pad: arrow + its WASD letter; flashes when used"""
    def __init__(self, parent, d, on_press, bg=BG, size=50):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, cursor="hand2")
        self.d, self.on_press, self.bgc, self.h, self.flash = d, on_press, bg, 0.0, 0.0
        self.bind("<Enter>", lambda e: setattr(self, "h", 1.0)); self.bind("<Leave>", lambda e: setattr(self, "h", 0.0))
        self.bind("<Button-1>", lambda e: on_press(d)); self.after(40, self.tick)
    def hit(self): self.flash = 1.0
    def tick(self):
        try:
            self.flash *= 0.82; sig = (round(self.flash, 2), self.h)
            if sig != getattr(self, "sig", None): self.sig = sig; self.draw()     # redraw only when it changes
            self.after(40, self.tick)
        except tk.TclError: pass
    def draw(self):
        self.delete("all"); s = self.winfo_width(); f, h = self.flash, self.h
        edge = lerp(lerp(RED_DIM, ORANGE, h), WHITE, f); fill = lerp(lerp(PANEL, "#2A1606", h), ORANGE, f * 0.8)
        self.create_rectangle(3, 3, s - 3, s - 3, fill=fill, outline=edge, width=2)
        self.create_line(6, s - 6, s - 6, s - 6, fill=lerp(edge, BG, 0.5))
        col = lerp(ORANGE if h else RED, BG if f > 0.5 else WHITE, f)
        cx, cy, r = s / 2, s / 2 - 3, s * 0.2; dx, dy = {"U": (0, -1), "D": (0, 1), "L": (-1, 0), "R": (1, 0)}[self.d]; nx, ny = -dy, dx
        self.create_polygon(cx + dx * r, cy + dy * r, cx - dx * r * 0.4 + nx * r * 0.9, cy - dy * r * 0.4 + ny * r * 0.9,
                            cx - dx * r * 0.4 - nx * r * 0.9, cy - dy * r * 0.4 - ny * r * 0.9, fill=col, outline="")
        self.create_text(s - 9, s - 11, text={"U": "W", "D": "S", "L": "A", "R": "D"}[self.d], fill=lerp(DIM, WHITE, h), font=(MONO, 8, "bold"))


# ======================================================================  dialog look: nanosuit armour + modern controls
CARD = "#0A0C11"
SECTION_ICON = {"listening": "mic", "macros": "gauge", "sound": "listen", "speech ai": "cpu", "stratagem keys": "arrows", "speed": "gauge"}


class Toggle(tk.Canvas):
    """sliding ON / OFF switch (replaces the checkbox)"""
    def __init__(self, parent, var, bg=CARD):
        super().__init__(parent, width=58, height=24, bg=bg, highlightthickness=0, cursor="hand2")
        self.var, self.bgc, self.k, self.h = var, bg, 1.0 if var.get() else 0.0, 0.0
        self.bind("<Button-1>", lambda e: self.flip()); self.bind("<Enter>", lambda e: setattr(self, "h", 1.0))
        self.bind("<Leave>", lambda e: setattr(self, "h", 0.0)); self.after(30, self.tick)
    def flip(self):
        self.var.set(not self.var.get()); sfx("unlocked" if self.var.get() else "chip")
    def tick(self):
        try:
            tgt = 1.0 if self.var.get() else 0.0; self.k += (tgt - self.k) * 0.35
            if abs(tgt - self.k) < 0.01: self.k = tgt
            sig = (round(self.k, 2), self.h)
            if self.h or sig != getattr(self, "sig", None): self.sig = sig; self.draw()   # idle = no redraw
            self.after(50 if (self.h or self.k != tgt) else 120, self.tick)
        except tk.TclError: pass
    def draw(self):
        self.delete("all"); k, h, t = self.k, self.h, time.time()
        W, H = 56, 24; c = 6
        edge = lerp(lerp(GRID, ORANGE, k), WHITE, 0.25 * h)
        self.create_polygon(2, 3, W - c, 3, W - 1, 3 + c, W - 1, H - 3, 2 + c, H - 3, 2, H - 3 - c, fill=lerp(PANEL, "#2E1406", k), outline=edge)
        for q in range(5):                                       # energy cells inside the track
            x = 9 + q * 5; on = k > 0.5
            pulse = (0.5 + 0.5 * math.sin(t * 6 - q)) if h else 0.7
            self.create_line(x, 8, x, H - 8, fill=lerp(GRID, ORANGE, k * (0.4 + 0.6 * pulse)) if on else GRID)
        kx = 4 + k * (W - 26)
        self.create_polygon(kx, 5, kx + 17, 5, kx + 20, 8, kx + 20, H - 5, kx + 3, H - 5, kx, H - 8, fill=lerp(DIM, ORANGE, k), outline="")
        self.create_line(kx + 7, 9, kx + 7, H - 9, fill=lerp(BG, "#5A2A08", k)); self.create_line(kx + 12, 9, kx + 12, H - 9, fill=lerp(BG, "#5A2A08", k))
        if k < 0.4: self.create_text(W - 16, H / 2, text="OFF", fill=lerp(DIM, WHITE, 0.3 * h), font=(MONO, 6, "bold"))


class HudSlider(tk.Canvas):
    """segmented energy bar with a value box (replaces tk.Scale): click / drag, mouse wheel or arrow keys"""
    def __init__(self, parent, var, frm, to, res=1, length=260, bg=CARD, on_release=None):
        super().__init__(parent, width=length, height=30, bg=bg, highlightthickness=0, cursor="hand2", takefocus=1)
        self.var, self.frm, self.to, self.res, self.L, self.bgc, self.on_release, self.h, self.drag = var, frm, to, res, length, bg, on_release, 0.0, False
        self.x0, self.x1 = 6, length - 62
        self.bind("<Button-1>", self.press); self.bind("<B1-Motion>", self.move); self.bind("<ButtonRelease-1>", self.release)
        self.bind("<Enter>", lambda e: setattr(self, "h", 1.0)); self.bind("<Leave>", lambda e: setattr(self, "h", 0.0))
        self.bind("<MouseWheel>", lambda e: self.nudge(1 if e.delta > 0 else -1))
        self.bind("<Left>", lambda e: self.nudge(-1)); self.bind("<Right>", lambda e: self.nudge(1))
        self.after(30, self.tick)
    def frac(self):
        try: v = float(self.var.get())
        except (tk.TclError, ValueError): v = self.frm
        return max(0.0, min(1.0, (v - self.frm) / ((self.to - self.frm) or 1)))
    def setx(self, x):
        f = max(0.0, min(1.0, (x - self.x0) / (self.x1 - self.x0))); v = self.frm + f * (self.to - self.frm)
        v = round(round(v / self.res) * self.res, 4); self.var.set(int(v) if self.res >= 1 else v)
    def press(self, e): self.focus_set(); self.drag = True; self.setx(e.x); sfx("select")
    def move(self, e):
        if self.drag: self.setx(e.x)
    def release(self, e):
        self.drag = False
        if self.on_release: self.on_release(self.var.get())
    def nudge(self, d):
        step = self.res if (self.to - self.frm) / self.res <= 60 else (self.to - self.frm) / 50
        v = max(self.frm, min(self.to, float(self.var.get()) + d * step)); v = round(round(v / self.res) * self.res, 4)
        self.var.set(int(v) if self.res >= 1 else v); sfx("select")
        if self.on_release: self.on_release(self.var.get())
    def tick(self):
        try:
            sig = (self.frac(), self.h, self.drag)
            if self.h or sig != getattr(self, "sig", None): self.sig = sig; self.draw()
            self.after(50 if self.h else 120, self.tick)
        except tk.TclError: pass
    def draw(self):
        self.delete("all"); f, h, t = self.frac(), max(self.h, 1.0 if self.drag else 0.0), time.time()
        x0, x1, n = self.x0, self.x1, 26; seg = (x1 - x0) / n
        for q in range(n):
            lit = (q + 0.5) / n <= f; a = q / (n - 1)
            col = lerp(RED, ORANGE, a) if lit else GRID
            if lit and h: col = lerp(col, WHITE, 0.25 * (0.5 + 0.5 * math.sin(t * 8 - q * 0.5)))
            self.create_rectangle(x0 + q * seg, 10 + (0 if lit else 3), x0 + (q + 1) * seg - 2, 20 - (0 if lit else 3), fill=col, outline="")
        tx = x0 + f * (x1 - x0)
        self.create_polygon(tx, 4, tx + 5, 9, tx + 5, 21, tx, 26, tx - 5, 21, tx - 5, 9, fill=lerp(ORANGE, WHITE, 0.5 * h), outline=BG)
        bx = self.L - 54
        self.create_polygon(bx, 3, self.L - 8, 3, self.L - 2, 9, self.L - 2, 27, bx + 6, 27, bx, 21, fill=PANEL, outline=lerp(RED_DIM, ORANGE, 0.4 + 0.6 * h))
        try: v = float(self.var.get())
        except (tk.TclError, ValueError): v = 0
        self.create_text((bx + self.L - 2) / 2, 15, text=(f"{v:.2f}" if self.res < 1 else f"{int(round(v))}"), fill=WHITE, font=(MONO, 9, "bold"))


class Segmented(tk.Canvas):
    """2-4 choices side by side (replaces short dropdowns: always / ptt, auto / gpu / cpu ...)"""
    def __init__(self, parent, var, values, bg=CARD):
        self.f = tkfont.Font(family=MONO, size=9, weight="bold")
        self.ws = [max(46, self.f.measure(v.upper()) + 22) for v in values]
        super().__init__(parent, width=sum(self.ws) + 4, height=26, bg=bg, highlightthickness=0, cursor="hand2")
        self.var, self.values, self.bgc, self.hov = var, list(values), bg, None
        self.bind("<Motion>", lambda e: self.set_hov(self.at(e.x))); self.bind("<Leave>", lambda e: self.set_hov(None))
        self.bind("<Button-1>", self.click); var.trace_add("write", lambda *a: self.draw()); self.bind("<Configure>", lambda e: self.draw())
    def at(self, x):
        acc = 2
        for k, w in enumerate(self.ws):
            if acc <= x < acc + w: return k
            acc += w
        return None
    def set_hov(self, k):
        if k != self.hov: self.hov = k; self.draw()
    def click(self, e):
        k = self.at(e.x)
        if k is not None and self.values[k] != self.var.get(): self.var.set(self.values[k]); sfx("chip")
    def draw(self):
        try: self.delete("all")
        except tk.TclError: return
        x, H, cur = 2, 26, self.var.get()
        for k, (v, w) in enumerate(zip(self.values, self.ws)):
            on, hv = v == cur, k == self.hov; c = 6
            pts = (x + 1, 2, x + w - 1, 2, x + w - 1, H - 2, x + 1, H - 2)
            if k == 0: pts = (x + 1, 2 + c, x + 1 + c, 2, x + w - 1, 2, x + w - 1, H - 2, x + 1, H - 2)
            if k == len(self.values) - 1: pts = (x + 1, 2, x + w - 1, 2, x + w - 1, H - 2 - c, x + w - 1 - c, H - 2, x + 1, H - 2)
            self.create_polygon(*pts, fill=ORANGE if on else ("#2A0C0C" if hv else PANEL), outline=ORANGE if on or hv else RED_DIM)
            self.create_text(x + w / 2, H / 2, text=v.upper(), fill=BG if on else (WHITE if hv else "#B8BCC6"), font=self.f)
            x += w


class HudSelect(tk.Canvas):
    """dropdown field with a dark animated list (replaces the grey Windows combobox)"""
    def __init__(self, parent, var, values, width=32, bg=CARD):
        self.f = tkfont.Font(family=MONO, size=10); W = max(120, int(width * self.f.measure("0") + 34))
        super().__init__(parent, width=W, height=28, bg=bg, highlightthickness=0, cursor="hand2", takefocus=1)
        self.var, self.values, self.W, self.bgc, self.h, self.pop = var, list(values), W, bg, 0.0, None
        self.bind("<Button-1>", lambda e: self.toggle()); self.bind("<Enter>", lambda e: setattr(self, "h", 1.0))
        self.bind("<Leave>", lambda e: setattr(self, "h", 0.0)); self.bind("<Return>", lambda e: self.toggle())
        self.after(30, self.tick)
    def tick(self):
        try:
            sig = (self.var.get(), self.h, bool(self.pop))
            if self.h or sig != getattr(self, "sig", None): self.sig = sig; self.draw()
            self.after(60 if self.h else 150, self.tick)
        except tk.TclError: pass
    def draw(self):
        self.delete("all"); W, H, h, t = self.W, 28, max(self.h, 1.0 if self.pop else 0.0), time.time()
        self.create_polygon(1, 1, W - 8, 1, W - 1, 8, W - 1, H - 2, 8, H - 2, 1, H - 9, fill=lerp(PANEL, "#1C0909", h), outline=lerp(GRID, ORANGE, h))
        txt = self.var.get(); maxw = W - 40
        while txt and self.f.measure(txt) > maxw: txt = txt[:-2] + "…" if len(txt) > 2 else ""
        self.create_text(10, H / 2, text=txt, fill=WHITE, font=self.f, anchor="w")
        cx, cy, b = W - 16, H / 2 + (1.5 * math.sin(t * 4) if h else 0), 4
        d = -1 if self.pop else 1
        self.create_polygon(cx - b, cy - b * d * 0.6, cx + b, cy - b * d * 0.6, cx, cy + b * d * 0.6, fill=ORANGE if h else RED, outline="")
        self.create_line(W - 30, 6, W - 30, H - 7, fill=lerp(GRID, RED_DIM, 0.6))
    def toggle(self):
        if self.pop: self.close(); return
        sfx("open"); top = self.winfo_toplevel()
        p = self.pop = tk.Toplevel(self); p.overrideredirect(True); p.attributes("-topmost", True); p.configure(bg=RED)
        n = min(10, len(self.values)); fr = tk.Frame(p, bg=PANEL); fr.pack(padx=1, pady=1)
        lb = tk.Listbox(fr, bg=PANEL, fg="#C9CDD6", selectbackground="#3A0E0E", selectforeground=ORANGE, font=(MONO, 10), height=n,
                        activestyle="none", highlightthickness=0, bd=0, relief="flat", exportselection=False,
                        width=max(8, int((self.W - 20) / max(1, self.f.measure("0")))))
        lb.pack(side="left", padx=(6, 0), pady=4)
        if len(self.values) > n:
            sb = ttk.Scrollbar(fr, orient="vertical", command=lb.yview); sb.pack(side="right", fill="y"); lb.config(yscrollcommand=sb.set)
        for v in self.values: lb.insert("end", "  " + v)
        if self.var.get() in self.values:
            i = self.values.index(self.var.get()); lb.selection_set(i); lb.see(i)
        lb.bind("<Motion>", lambda e: (lb.selection_clear(0, "end"), lb.selection_set(lb.nearest(e.y))))
        lb.bind("<ButtonRelease-1>", lambda e: self.choose(lb.nearest(e.y)))
        lb.bind("<Return>", lambda e: self.choose(lb.curselection()[0] if lb.curselection() else -1))
        p.bind("<Escape>", lambda e: self.close())
        p.update_idletasks()
        x = self.winfo_rootx(); y = self.winfo_rooty() + 30
        if y + p.winfo_reqheight() > self.winfo_screenheight() - 40: y = self.winfo_rooty() - p.winfo_reqheight() - 2
        p.geometry(f"{max(self.W, p.winfo_reqwidth())}x{p.winfo_reqheight()}+{x}+{y}")
        lb.focus_set(); top._hud_pop = self          # the dialog closes the list when you click anywhere else
    def choose(self, i):
        if 0 <= i < len(self.values): self.var.set(self.values[i]); sfx("select")
        self.close()
    def close(self):
        if not self.pop: return
        try: self.pop.destroy()
        except tk.TclError: pass
        self.pop = None


def set_win_icon(win, ico):
    """sharp taskbar / Alt+Tab icon at this screen's DPI (a borderless window gets no icon otherwise)"""
    if not WIN or not ico: return
    try:
        win.update_idletasks(); u = ctypes.windll.user32
        u.LoadImageW.restype = ctypes.c_void_p
        u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
        hwnd = u.GetParent(win.winfo_id()) or win.winfo_id()
        try: dpi = u.GetDpiForWindow(hwnd) or 96
        except Exception: dpi = 96
        big, small = max(32, round(32 * dpi / 96)), max(16, round(16 * dpi / 96))
        hb = u.LoadImageW(None, ico, 1, big, big, 0x10); hs = u.LoadImageW(None, ico, 1, small, small, 0x10)
        if hb: u.SendMessageW(hwnd, 0x80, 1, hb)
        if hs: u.SendMessageW(hwnd, 0x80, 0, hs)
        _ICON_HANDLES.extend([hb, hs])
    except Exception:
        traceback.print_exc()


def make_borderless(win, appwindow=True):
    """no Windows title bar / border; appwindow = still shows in the taskbar and Alt+Tab"""
    win.overrideredirect(True)
    if not WIN: return None
    try:
        win.update_idletasks(); u = ctypes.windll.user32; hwnd = u.GetParent(win.winfo_id())
        if appwindow:
            ex = u.GetWindowLongW(hwnd, -20); u.SetWindowLongW(hwnd, -20, (ex & ~0x80) | 0x40000)
            st = u.GetWindowLongW(hwnd, -16); u.SetWindowLongW(hwnd, -16, st | 0x00020000 | 0x00080000)
        for attr, val in ((33, 1), (34, 0xFFFFFFFE)):   # square corners, no border line
            v = ctypes.c_uint(val); ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        if appwindow: win.withdraw(); win.after(15, win.deiconify)
        return hwnd
    except Exception:
        traceback.print_exc(); return None


def drag_window(win, *widgets):
    def press(e): win._drag0 = (e.x_root - win.winfo_x(), e.y_root - win.winfo_y())
    def move(e):
        d = getattr(win, "_drag0", None)
        if d: win.geometry(f"+{e.x_root - d[0]}+{e.y_root - d[1]}")
    for w in widgets:
        w.bind("<Button-1>", press, add="+"); w.bind("<B1-Motion>", move, add="+")


CAPTURE_SKIP = {0x01, 0x10, 0x11, 0x12, 0xFF}       # left click + generic shift/ctrl/alt (left/right versions are used)
MODS = {0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}


class KeyField(tk.Frame):
    """Click it, then press the key (or key combo / mouse button) - it fills itself in."""
    def __init__(self, parent, value, combo=True, width=24, on_set=None, empty="— none —", clear=True, bg=BG):
        super().__init__(parent, bg=bg); self.value, self.combo, self.capturing, self.on_set, self.empty = value or "", combo, False, on_set, empty
        self.lbl = tk.Label(self, bg=PANEL, fg=WHITE, font=(MONO, 10, "bold"), width=width, anchor="w", padx=8, pady=4, cursor="hand2",
                            highlightthickness=1, highlightbackground=GRID)
        self.lbl.pack(side="left")
        if clear: IconButton(self, "cancel", lambda: self.set(""), "Clear", "no key", fg=DIM, bg=bg, size=24).pack(side="left", padx=(4, 0))
        self.lbl.bind("<Button-1>", self.start)
        self.lbl.bind("<Enter>", lambda e: None if self.capturing else self.lbl.config(highlightbackground=ORANGE), add="+")
        self.lbl.bind("<Leave>", lambda e: None if self.capturing else self.lbl.config(highlightbackground=GRID), add="+")
        self.show()

    def get(self): return self.value
    def set(self, v):
        self.value = v; self.capturing = False; self.show()
        if v and self.on_set: self.on_set(v)
    def show(self):
        self.lbl.config(text=pretty_combo(self.value) if self.value else self.empty, fg=WHITE if self.value else DIM, bg=PANEL, highlightbackground=GRID)

    def start(self, e=None):
        if self.capturing or not WIN: return
        sfx("key"); self.capturing, self.pressed, self.armed, self.t0 = True, [], False, time.time()
        self.lbl.config(text="press a key…", fg=ORANGE, bg="#2A1606", highlightbackground=ORANGE)
        self.after(15, self.poll)

    def poll(self):
        if not self.capturing: return
        try:
            down = [vk for vk in range(1, 255) if vk not in CAPTURE_SKIP and is_down(vk)]
            if not self.armed:
                self.armed = not is_down(0x01)        # wait until the click that started it is released
            else:
                for vk in down:
                    if vk not in self.pressed: self.pressed.append(vk)
                if self.pressed and not down: return self.finish()
                if not self.combo and any(v not in MODS for v in self.pressed): return self.finish()
            if time.time() - self.t0 > 10: self.capturing = False; self.show(); return
            self.after(15, self.poll)
        except tk.TclError:
            self.capturing = False

    def finish(self):
        self.capturing = False
        if self.pressed == [0x1B]: self.show(); return       # Esc = cancel
        keys = sorted(self.pressed, key=lambda v: (v not in MODS, self.pressed.index(v)))
        if not self.combo: keys = ([k for k in keys if k not in MODS] or keys)[-1:]
        sfx("save"); self.set("+".join(VK2NAME.get(k, f"vk{k}") for k in keys))


class Dialog(tk.Toplevel):
    """Borderless window: nanosuit hex armour background, settings on cards (section = card, newcol = next column),
    modern controls (switches, energy sliders, segmented choices, dark dropdowns)."""
    M, GAP, TOP = 22, 16, 58

    def __init__(self, app, title):
        super().__init__(app.root); self.app = app
        self.title(title); self.configure(bg=BG); self.transient(app.root)
        make_borderless(self, appwindow=False); self.attributes("-topmost", True)
        self.cv = tk.Canvas(self, bg=BG, highlightthickness=0); self.cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.nano = StaticField(self.cv, amount=30); self.ttl = title.upper(); self.t0 = time.time(); self._W = self._H = 0
        drag_window(self, self.cv)
        self.closeb = IconButton(self, "cancel", self.destroy, "Close", "Esc", fg=RED, bg=BG, size=26, sound=None)
        self.cbg = CARD; self.cols, self.heads = [[]], []
        self.new_card(None)
        self.bar = tk.Frame(self, bg=BG)
        self.bind("<Escape>", lambda e: self.destroy()); self.bind("<Button-1>", self._click_any, add="+")
        sfx("open"); self.after(40, self._tick)

    # ---------- cards
    def new_card(self, title):
        outer = tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground="#2A1010")
        if title: self._head(outer, title)
        self.body = tk.Frame(outer, bg=CARD); self.body.pack(fill="both", expand=True, padx=14, pady=(6 if title else 12, 12))
        self.body.columnconfigure(1, weight=1); self.row, self.c0 = 0, 0
        outer.body = self.body; outer.titled = bool(title); self.cols[-1].append(outer); self.card = outer

    def _head(self, outer, title):
        hc = tk.Canvas(outer, height=30, bg=CARD, highlightthickness=0); hc.pack(fill="x", padx=1, pady=(1, 0), before=getattr(outer, "body", None)) \
            if getattr(outer, "body", None) else hc.pack(fill="x", padx=1, pady=(1, 0))
        key = next((v for k, v in SECTION_ICON.items() if title.lower().startswith(k)), "gear")
        hc.title, hc.icon, hc.ph = title.upper(), key, random.random() * 6; self.heads.append(hc)

    def section(self, text):
        if self.row == 0 and not self.card.titled:            # empty card -> just give it the title
            self._head(self.card, text); self.card.titled = True
        else:
            self.new_card(text)

    def newcol(self):
        """start the next column of cards"""
        self.cols.append([]); self.new_card(None)

    def _draw_head(self, hc, t):
        hc.delete("all"); W = hc.winfo_width(); ph = hc.ph
        draw_icon(hc, hc.icon, 10, 5, 20, lerp(RED, ORANGE, 0.5 + 0.5 * math.sin(t * 1.5 + ph)), t)
        hc.create_text(38, 15, text=hc.title, fill=RED, font=(MONO, 9, "bold"), anchor="w")
        if not hasattr(hc, "tw"): hc.tw = tkfont.Font(family=MONO, size=9, weight="bold").measure(hc.title)
        x0 = 46 + hc.tw; x1 = W - 12
        if x1 > x0 + 10:
            hc.create_line(x0, 15, x1, 15, fill="#2A1010")
            p = x0 + ((t * 90 + ph * 40) % (x1 - x0 + 60)) - 30            # running energy dash
            hc.create_line(max(x0, p), 15, min(x1, p + 30), 15, fill=ORANGE, width=2) if p + 30 > x0 and p < x1 else None
            hc.create_rectangle(x1 - 3, 13, x1 + 1, 17, fill=RED_DIM, outline="")
        hc.create_line(1, 29, W - 1, 29, fill="#1A1D25")

    def _draw_frame(self, t):
        c = self.cv; c.delete("ttl"); W, H = c.winfo_width(), c.winfo_height(); k = 14
        if W < 50: return
        c.create_polygon(1, 1, W - k, 1, W - 2, k, W - 2, H - 2, k, H - 2, 1, H - k, fill="", outline=lerp(RED_DIM, RED, 0.35 + 0.25 * math.sin(t * 2)), tags=("ttl",))
        for x, y, sx, sy in ((3, 3, 1, 1), (W - 4, H - 4, -1, -1)):
            c.create_line(x + sx * 34, y, x, y, x, y + sy * 34, fill=ORANGE, width=2, tags=("ttl",))
        c.create_rectangle(self.M - 4, 14, self.M + 260, 44, fill=BG, outline="", tags=("ttl",))
        c.create_text(self.M, 24, text="◢ " + self.ttl, fill=RED, font=(MONO, 13, "bold"), anchor="w", tags=("ttl",))
        c.create_text(self.M + 2, 40, text="SKYNET COMMAND  //  " + ("CONFIG" if self.ttl == "OPTIONS" else "EDITOR"), fill=DIM, font=(MONO, 7, "bold"), anchor="w", tags=("ttl",))
        x0, x1 = self.M + 270, W - self.M - 40
        if x1 > x0:
            c.create_line(x0, 30, x1, 30, fill="#2A1010", tags=("ttl",))
            p = x0 + (t * 160) % (x1 - x0 + 80) - 40
            c.create_line(max(x0, p), 30, min(x1, p + 60), 30, fill=RED, width=2, tags=("ttl",))

    def _tick(self):
        try:
            if not self.winfo_exists(): return
            t = time.time() - self.t0; self._draw_frame(t)
            for hc in self.heads:
                if hc.winfo_ismapped(): self._draw_head(hc, t)
            self.after(90, self._tick)
        except tk.TclError:
            pass

    def _click_any(self, e):
        pop = getattr(self, "_hud_pop", None)
        if pop and pop.pop and e.widget is not pop: pop.close()

    def layout(self):
        """place the cards in their columns over the armour, the buttons under them, size the window"""
        self.update_idletasks()
        x, colh = self.M, []
        for col in self.cols:
            cards = [cd for cd in col if cd.titled or cd.body.grid_slaves()]
            for cd in col:
                if cd not in cards: cd.destroy()
            if not cards: continue
            w = max(cd.winfo_reqwidth() for cd in cards); y = self.TOP
            for cd in cards:
                h = cd.winfo_reqheight(); cd.place(x=x, y=y, width=w, height=h); y += h + self.GAP
            colh.append(y - self.GAP); x += w + self.GAP
        W = max(x - self.GAP + self.M, 420); by = max(colh or [self.TOP]) + 14
        bh = self.bar.winfo_reqheight(); self.bar.place(x=self.M, y=by)
        H = by + bh + 18; self._W, self._H = W, H
        self.closeb.place(x=W - self.M - 26, y=14); self.geometry(f"{W}x{H}")

    # ---------- rows
    def label(self, text, hint=None):
        """row label; hovering the label or its control explains the setting"""
        lb = tk.Label(self.body, text=text, bg=self.cbg, fg="#8A8F9C", font=(MONO, 9, "bold"), anchor="nw", justify="left", cursor="question_arrow" if hint else "")
        lb.grid(row=self.row, column=self.c0, sticky="nw", padx=(0, 12), pady=6)
        self._tiptext = (text.replace("\n", " ") + ("\n" + hint if hint else "")) if hint else ""
        if hint:
            Tip(lb, self._tiptext)
            lb.bind("<Enter>", lambda e: lb.config(fg=ORANGE), add="+"); lb.bind("<Leave>", lambda e: lb.config(fg="#8A8F9C"), add="+")
            dot = tk.Canvas(self.body, width=14, height=14, bg=self.cbg, highlightthickness=0); dot.grid(row=self.row, column=self.c0 + 2, sticky="nw", padx=(8, 0), pady=9)
            Tip(dot, self._tiptext); self._pulse(dot)
        return lb

    def _pulse(self, c, k=0):
        """tiny animated 'info' beacon next to every setting that has an explanation"""
        try:
            c.delete("all"); a = 0.5 + 0.5 * math.sin(k * 0.25)
            c.create_polygon(7, 1, 13, 7, 7, 13, 1, 7, outline=lerp(RED_DIM, ORANGE, a), fill=""); c.create_rectangle(6, 6, 8, 8, fill=lerp(RED_DIM, RED, a), outline="")
            c.after(160, lambda: self._pulse(c, k + 2))
        except tk.TclError:
            pass

    def tipped(self, widget):
        if getattr(self, "_tiptext", ""): Tip(widget, self._tiptext)
        return widget

    def entry(self, text, value, hint=None, width=34):
        self.label(text, hint); v = tk.StringVar(value=str(value))
        e = tk.Entry(self.body, textvariable=v, bg="#07080B", fg=WHITE, insertbackground=ORANGE, relief="flat", font=(MONO, 10), width=width,
                     highlightthickness=1, highlightbackground=GRID, highlightcolor=ORANGE)
        e.grid(row=self.row, column=self.c0 + 1, sticky="we", pady=5, ipady=4); e.bind("<Button-1>", lambda ev: e.focus_force(), add="+"); self.tipped(e)
        self.row += 1; self.last = e; return v

    def keyfield(self, text, value, hint=None, combo=True):
        self.label(text, hint); k = KeyField(self.body, value, combo, bg=self.cbg)
        k.grid(row=self.row, column=self.c0 + 1, sticky="w", pady=4); self.tipped(k.lbl); self.row += 1; return k

    def text(self, label, value, height, hint=None):
        self.label(label + ("\n\n" + hint if hint else ""))
        t = tk.Text(self.body, bg="#07080B", fg=WHITE, insertbackground=ORANGE, relief="flat", font=(MONO, 10), height=height, width=56,
                    highlightthickness=1, highlightbackground=GRID, highlightcolor=ORANGE, wrap="none", undo=True, padx=6, pady=4)
        t.insert("1.0", value); t.grid(row=self.row, column=self.c0 + 1, columnspan=2, sticky="nsew", pady=5)
        t.bind("<Button-1>", lambda ev: t.focus_force(), add="+")
        self.body.rowconfigure(self.row, weight=1); self.row += 1; return t

    def combo(self, label, values, value, hint=None, width=32, editable=False):
        self.label(label, hint); v = tk.StringVar(value=value)
        if editable:
            c = ttk.Combobox(self.body, textvariable=v, values=values, state="normal", width=width, font=(MONO, 10))
            c.bind("<<ComboboxSelected>>", lambda e: sfx("select"), add="+")
        elif 1 < len(values) <= 4 and max(len(x) for x in values) <= 9:
            c = Segmented(self.body, v, values, bg=self.cbg)
        else:
            c = HudSelect(self.body, v, values, width=min(width, 40), bg=self.cbg)
        c.grid(row=self.row, column=self.c0 + 1, sticky="w", pady=5); self.tipped(c)
        self.row += 1; self.last = c; return v

    def check(self, label, value, hint=None):
        self.label(label, hint); v = tk.BooleanVar(value=bool(value))
        tg = Toggle(self.body, v, bg=self.cbg); tg.grid(row=self.row, column=self.c0 + 1, sticky="w", pady=4); self.tipped(tg)
        self.row += 1; return v

    def scale(self, label, frm, to, value, res=1, hint=None, length=280, on_release=None):
        self.label(label, hint); v = tk.DoubleVar(value=value)
        sc = HudSlider(self.body, v, frm, to, res, length, bg=self.cbg, on_release=on_release)
        sc.grid(row=self.row, column=self.c0 + 1, sticky="w", pady=4); self.tipped(sc)
        self.row += 1; return v

    def destroy(self):
        sfx("close"); super().destroy()

    def center(self):
        self.layout(); r = self.app.root; W, H = self._W, self._H
        x = r.winfo_rootx() + (r.winfo_width() - W) // 2
        y = r.winfo_rooty() + max(0, (r.winfo_height() - H) // 3)
        y = min(y, max(0, r.winfo_screenheight() - H - 50))
        x = min(max(0, x), max(0, r.winfo_screenwidth() - W))
        self.geometry(f"{W}x{H}+{max(0, x)}+{max(0, y)}")
        self.after(30, lambda: (self.lift(), self.focus_force()))
        try: self.grab_set()
        except tk.TclError: self.after(80, lambda: self.grab_set())



GROUPS = ["General", "Mission", "Orbital", "Eagle", "Weapons", "Backpacks", "Sentries", "Emplacements", "Mines", "Vehicles", "Chat", "Desktop"]
DIR_VK = {0x26: "U", 0x28: "D", 0x25: "L", 0x27: "R", 0x57: "U", 0x53: "D", 0x41: "L", 0x44: "R"}   # arrows + WASD


class CommandDialog(Dialog):
    """Edit a command. The macro is built by clicking: arrow pad / your arrow keys or WASD = stratagem,
    + KEY = press any key or combo, + WAIT, + CLICK. The text box below shows (and still accepts) the result."""
    def __init__(self, app, cmd, on_save):
        super().__init__(app, "Edit command" if cmd.get("name") else "New command"); self.on_save, self.cmd = on_save, cmd
        self.v_name = self.entry("NAME", cmd.get("name", ""), "shown in the list and the log")
        # ---- group chips
        self.label("GROUP", "click a group - or type your own")
        gf = tk.Frame(self.body, bg=self.cbg); gf.grid(row=self.row, column=1, sticky="w", pady=4)
        groups = list(dict.fromkeys(GROUPS + [c.get("category") for c in app.profile["commands"] if c.get("category")]))
        self.v_cat = tk.StringVar(value=cmd.get("category", "")); self.chips = {}
        for k, g in enumerate(groups):
            ch = Chip(gf, g, self.pick_group, bg=self.cbg); ch.grid(row=k // 8, column=k % 8, padx=(0, 4), pady=2, sticky="w"); self.chips[g] = ch
        ce = tk.Entry(gf, textvariable=self.v_cat, bg=PANEL, fg=WHITE, insertbackground=ORANGE, relief="flat", font=(MONO, 9), width=14,
                      highlightthickness=1, highlightbackground=GRID, highlightcolor=ORANGE)
        ce.grid(row=(len(groups) - 1) // 8 + 1, column=0, columnspan=3, sticky="w", pady=2, ipady=2); Tip(ce, "Own group\ntype any name")
        ce.bind("<Button-1>", lambda e: ce.focus_force(), add="+")
        self.v_cat.trace_add("write", lambda *a: self.mark_group()); self.mark_group(); self.row += 1
        self.t_ph = self.text("WHEN I SAY", "\n".join(cmd.get("phrases", [])), 3, "one phrase\nper line")
        # ---- macro builder
        self.label("BUILD THE\nMACRO", "click the arrows (or press your arrow keys / WASD while\n"
                                       "no text box is selected) - each one is added to a stratagem.\n"
                                       "+ KEY: click it, then press any key or combo on your keyboard.")
        mb = tk.Frame(self.body, bg=PANEL, highlightthickness=1, highlightbackground=RED_DIM)
        mb.grid(row=self.row, column=1, sticky="we", pady=4); self.row += 1
        pad = tk.Frame(mb, bg=PANEL); pad.pack(side="left", padx=10, pady=8)
        self.keys = {d: PadKey(pad, d, self.add_dir, bg=PANEL) for d in "UDLR"}
        self.keys["U"].grid(row=0, column=1); self.keys["L"].grid(row=1, column=0); self.keys["D"].grid(row=1, column=1); self.keys["R"].grid(row=1, column=2)
        mid = tk.Frame(mb, bg=PANEL); mid.pack(side="left", fill="both", expand=True, padx=6, pady=8)
        self.code = tk.Canvas(mid, height=44, bg=BG, highlightthickness=1, highlightbackground=GRID); self.code.pack(fill="x")
        Tip(self.code, "Stratagem code\nthe arrows of the stratagem in this macro")
        self.live = tk.Label(mid, text="", bg=PANEL, fg=DIM, font=(MONO, 8), anchor="w"); self.live.pack(fill="x", pady=(4, 2))
        tools = tk.Frame(mid, bg=PANEL); tools.pack(fill="x")
        self.kf = KeyField(tools, "", combo=True, width=14, on_set=self.add_key, empty="＋ KEY", clear=False, bg=PANEL); self.kf.pack(side="left")
        Tip(self.kf.lbl, "＋ Key press\nclick, then press a key or combo (ctrl+shift+s, mouse4...)\nit is added as 'press ...'")
        for icon, fn, title, desc in (("wait", lambda: self.add_line("wait 0.1"), "＋ Wait", "adds 'wait 0.1' (change the number below)"),
                                      ("click", lambda: self.add_line("click left"), "＋ Mouse click", "adds 'click left'"),
                                      ("undo", self.undo, "Undo", "removes the last arrow / line"),
                                      ("trash", self.clear, "Clear macro", "empties the whole macro")):
            IconButton(tools, icon, fn, title, desc, bg=PANEL, size=28, sound=None if icon in ("wait", "click", "undo") else "trash").pack(side="left", padx=(6, 0))
        self.rec = tk.BooleanVar(value=True)
        self.recbtn = IconButton(tools, "rec", self.toggle_rec, "Keyboard capture is ON", "press ↑ ↓ ← → or W A S D (while no text box is selected)\nclick to switch off",
                                 fg=GREEN, bg=PANEL, size=28)
        self.recbtn.pack(side="right")
        self.t_act = self.text("DO THIS", "\n".join(cmd.get("actions", [])), 5, "built above -\nor type here")
        Tip(self.t_act, "Macro (advanced)\n" + ACTION_HELP)
        self.v_en = self.check("ENABLED", cmd.get("enabled", True), "off = the command is kept but never fires")
        self.err = tk.Label(self.body, text="", bg=self.cbg, fg=RED, font=(MONO, 9), justify="left", anchor="w")
        self.err.grid(row=self.row, column=1, columnspan=2, sticky="w"); self.row += 1
        hbtn(self.bar, "✔ SAVE", self.save, fg=ORANGE, bold=True, bg=BG).pack(side="left")
        hbtn(self.bar, "▶ TEST IN 3 s", self.test, bg=BG).pack(side="left", padx=8)
        hbtn(self.bar, "CANCEL", self.destroy, fg=DIM, bg=BG).pack(side="left")
        grab = lambda e: (self.focus_force(), None)[1]      # clicking the builder takes the keyboard away from text boxes
        for w in (mb, pad, mid, tools, self.code, self.live, self.body, *self.keys.values()): w.bind("<Button-1>", grab, add="+")
        self.prev = {}; self.center(); self.after(100, self.tick)
        if not cmd.get("name"): self.after(200, lambda: (self.t_ph.focus_force() if not cmd.get("phrases") else None))

    # ---- groups
    def pick_group(self, g): self.v_cat.set(g)
    def mark_group(self):
        cur = self.v_cat.get().strip()
        for g, ch in self.chips.items(): ch.set(g == cur)

    # ---- macro builder
    def lines(self): return [l.rstrip() for l in self.t_act.get("1.0", "end").splitlines() if l.strip()]
    def set_lines(self, ls):
        self.t_act.delete("1.0", "end"); self.t_act.insert("1.0", "\n".join(ls)); self.t_act.see("end")

    def add_dir(self, d):
        ls = self.lines()
        if ls and ls[-1].lower().startswith("stratagem"): ls[-1] += d
        else: ls.append("stratagem " + d)
        self.set_lines(ls); self.keys[d].hit(); sfx("dir_" + d)

    def add_line(self, line):
        self.set_lines(self.lines() + [line]); sfx("plus")

    def add_key(self, combo):
        self.add_line(f"press {combo}"); self.kf.value = ""; self.kf.show()

    def undo(self):
        ls = self.lines()
        if not ls: return
        if ls[-1].lower().startswith("stratagem ") and len(ls[-1].split(None, 1)[1].strip()) > 1: ls[-1] = ls[-1][:-1]
        else: ls.pop()
        self.set_lines(ls); sfx("undo")

    def clear(self): self.set_lines([])

    def toggle_rec(self):
        self.rec.set(not self.rec.get()); on = self.rec.get()
        self.recbtn.config(fg=GREEN if on else DIM, title=f"Keyboard capture is {'ON' if on else 'OFF'}",
                           desc="press ↑ ↓ ← → or W A S D (while no text box is selected)\nclick to switch " + ("off" if on else "on"))

    def tick(self):
        try:
            if not self.winfo_exists(): return
        except tk.TclError: return
        # keyboard capture: arrows / WASD -> directions, only while no text box has the focus
        try: f = self.focus_get()
        except Exception: f = None
        typing = isinstance(f, (tk.Entry, tk.Text, ttk.Combobox))
        live = self.rec.get() and WIN and not typing and f is not None and f.winfo_toplevel() is self
        if live:
            for vk, d in DIR_VK.items():
                now = is_down(vk)
                if now and not self.prev.get(vk): self.add_dir(d)
                self.prev[vk] = now
        else: self.prev = {vk: is_down(vk) for vk in DIR_VK} if WIN else {}
        txt = "● LIVE: press ↑ ↓ ← → / W A S D" if live else "○ click an empty spot here to use your keys" if self.rec.get() else "keyboard capture off"
        if txt != getattr(self, "live_txt", None): self.live_txt = txt; self.live.config(text=txt, fg=GREEN if live else DIM)
        self.n_tick = getattr(self, "n_tick", 0) + 1
        if self.n_tick % 4 == 0: self.draw_code()          # the code glow only needs ~16 fps
        self.after(15, self.tick)

    def draw_code(self):
        c = self.code; c.delete("all"); W, H = c.winfo_width(), c.winfo_height()
        st = next((l.split(None, 1)[1] for l in reversed(self.lines()) if l.lower().startswith("stratagem ") and len(l.split()) > 1), "")
        code = [ARROWS.get(ch.upper() if ch.isalpha() else ch) for ch in st if not ch.isspace()]
        if not code:
            c.create_text(W / 2, H / 2, text="click the arrows ←", fill=DIM, font=(MONO, 10)); return
        s = min(30, (W - 16) / max(1, len(code))); x0 = (W - s * len(code)) / 2; t = time.time()
        for k, d in enumerate(code):
            if d is None: continue
            cx, cy, r = x0 + s * k + s / 2, H / 2, s * 0.32
            glow = 0.5 + 0.5 * math.sin(t * 5 - k * 0.6)
            dx, dy = {"U": (0, -1), "D": (0, 1), "L": (-1, 0), "R": (1, 0)}[d]; nx, ny = -dy, dx
            c.create_polygon(cx + dx * r, cy + dy * r, cx - dx * r * 0.5 + nx * r, cy - dy * r * 0.5 + ny * r,
                             cx - dx * r * 0.5 - nx * r, cy - dy * r * 0.5 - ny * r, fill=lerp(RED, ORANGE, glow), outline="")

    # ---- save / test
    def collect(self):
        acts = self.lines()
        phr = [l.strip() for l in self.t_ph.get("1.0", "end").splitlines() if l.strip()]
        return {"name": self.v_name.get().strip() or (phr[0] if phr else "command"), "category": self.v_cat.get().strip(),
                "phrases": phr, "actions": acts, "enabled": self.v_en.get()}

    def check_errors(self, c):
        _, errs = compile_actions(c["actions"], self.app.profile)
        if not c["phrases"]: errs.insert(0, "add at least one phrase under WHEN I SAY")
        if not [a for a in c["actions"] if not a.startswith("#")] and c["enabled"]: errs.append("the macro is empty - click the arrows or + KEY")
        self.err.config(text="\n".join(errs[:5]))
        if errs: sfx("denied")
        return not errs

    def save(self):
        c = self.collect()
        if self.check_errors(c): self.destroy(); self.on_save(c)

    def test(self):
        c = self.collect()
        if self.check_errors(c): self.app.test_command(c)


class ProfileDialog(Dialog):
    def __init__(self, app, prof, on_save):
        super().__init__(app, "Profile"); self.on_save, self.prof = on_save, prof
        st = dict(STRAT_DEFAULT); st.update(prof.get("stratagem") or {})
        self.v_name = self.entry("NAME", prof.get("name", ""), "the profile name, e.g. the game's name")
        self.wins = list_windows()
        self.v_proc = self.combo("GAME .EXE", [f"{exe}   —   {title[:40]}" for exe, title in self.wins], prof.get("process", ""),
                                 "pick the game from the programs running now\n(no alt-tabbing) or type the .exe name.\nempty = commands work in any program",
                                 width=44, editable=True)
        self.proc_box = self.last
        hbtn(self.body, "⌖ DETECT", self.detect, bg=self.cbg).grid(row=self.row - 1, column=3, padx=6)
        self.v_auto = self.check("AUTO-DETECT GAME", prof.get("auto_detect", True),
                                 "while GAME .EXE is empty: the first time you say a\ncommand inside a full-screen program, that program\nbecomes this profile's game - automatically\n(same switch as the Skynet eye: open = on)")
        self.section("stratagem keys  ·  click, then press")
        self.k_menu = self.keyfield("MENU KEY", st["menu_key"], "Helldivers 2 default: left ctrl", combo=False)
        self.v_mode = self.combo("MENU MODE", ["hold", "tap"], st["menu_mode"], "hold = keep menu key down\ntap = game option 'toggle'")
        self.k_dirs = {d: self.keyfield(d.upper(), st[d], f"the key the game uses for stratagem {d.upper()}\nclick the box, then press it", combo=False) for d in ("up", "down", "left", "right")}
        self.section("speed  ·  ⚙ options → macro speed")
        self.err = tk.Label(self.body, text="", bg=self.cbg, fg=RED, font=(MONO, 9)); self.err.grid(row=self.row, column=1, sticky="w"); self.row += 1
        hbtn(self.bar, "✔ SAVE", self.save, fg=ORANGE, bold=True, bg=BG).pack(side="left")
        hbtn(self.bar, "ARROW KEYS", lambda: [self.k_dirs[d].set(d) for d in self.k_dirs], bg=BG).pack(side="left", padx=(8, 0))
        hbtn(self.bar, "WASD", lambda: [self.k_dirs[d].set(k) for d, k in zip(("up", "down", "left", "right"), "wsad")], bg=BG).pack(side="left", padx=(6, 0))
        hbtn(self.bar, "CANCEL", self.destroy, fg=DIM, bg=BG).pack(side="left", padx=8)
        self.center()

    def detect(self, n=5):
        if n == 0:
            exe = foreground_exe()
            if exe and exe not in IGNORE_EXE: self.v_proc.set(exe); self.err.config(text=f"detected: {exe}", fg=GREEN); sfx("detect")
            else: self.err.config(text="could not detect - pick it from the list", fg=RED)
            self.lift(); return
        self.err.config(text=f"switch to the game... {n}", fg=ORANGE); self.after(1000, lambda: self.detect(n - 1))

    def save(self):
        st = {"menu_key": self.k_menu.get(), "menu_mode": self.v_mode.get(), **{d: k.get() for d, k in self.k_dirs.items()}}
        if not all(st[k] for k in ("menu_key", "up", "down", "left", "right")):
            self.err.config(text="set the menu key and all four direction keys", fg=RED); sfx("denied"); return
        name = self.v_name.get().strip()
        if not name: self.err.config(text="give the profile a name", fg=RED); sfx("denied"); return
        proc = self.v_proc.get().split("   —   ")[0].strip().lower()
        was = self.app.autogame_on(); self.prof["auto_detect"] = self.v_auto.get()
        if self.prof is self.app.profile and self.v_auto.get() != was: self.app.set_autogame(self.v_auto.get())
        self.destroy(); self.on_save(name, proc, st)


class SettingsDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, "Options"); c = app.cfg
        self.section("listening")
        self.v_mic = self.combo("RECORDING DEVICE", app.mic_names(), c["mic"] or DEFAULT_MIC, "the microphone Skynet Command listens to\n(also in the main window)", width=40)
        self.v_mode = self.combo("LISTEN MODE", ["always", "ptt"], c["mode"], "always = voice detection\nptt = only while the key is held")
        self.k_ptt = self.keyfield("PUSH-TO-TALK KEY", c["ptt_key"], "mouse buttons work too")
        self.k_tog = self.keyfield("LOCK / UNLOCK\nLISTENING KEY", c["toggle_key"], "press it anywhere (also in game)\nto stop / start listening")
        self.v_sens = self.scale("MIC SENSITIVITY", 1, 10, c["sensitivity"], hint="higher = reacts to quieter speech")
        self.v_sil = self.scale("END OF PHRASE (ms)", 200, 900, c["silence_ms"], 10, "silence that ends a command\nlower = faster, higher = longer phrases")
        self.section("speech ai")
        self.v_model = self.combo("WHISPER MODEL", MODEL_CHOICES, c["model"], "auto = large-v3-turbo on NVIDIA GPU, distil-small.en on CPU\n.en models are English-only and faster\n"
                                   "memory (GPU saver / normal):  large-v3-turbo ~0.9 / 1.6 GB · distil-small.en ~0.25 / 0.4 GB\n"
                                   "small.en ~0.3 / 0.5 GB · base.en ~0.1 / 0.15 GB  - smaller = lighter on the game", width=18)
        self.v_dev = self.combo("RUN ON", ["auto", "gpu", "cpu"], c["device"], "auto = NVIDIA GPU if its libraries are installed, else CPU", width=18)
        self.v_lang = self.combo("LANGUAGE", list(LANGS), c["language"], "the language of your command phrases\nnot English = a multilingual model is used", width=18)
        self.label("GPU BOOST", "NVIDIA cards: installs the CUDA libraries (~1 GB, one time)\nso the big accurate model runs on the graphics card -\nbetter recognition AND faster. Restart the app afterwards.")
        gb = tk.Frame(self.body, bg=self.cbg); gb.grid(row=self.row, column=self.c0 + 1, sticky="w", pady=2)
        IconButton(gb, "bolt", self.gpu_boost, "Install GPU boost", "opens the installer window (about 1 GB download)", fg=ORANGE, bg=self.cbg, size=28, sound="play").pack(side="left")
        st = "installed ✔" if GPU_LIBS else ("NVIDIA card found - not installed" if getattr(app, "gpus", 0) else "not installed")
        tk.Label(gb, text=st, bg=self.cbg, fg=GREEN if GPU_LIBS else ORANGE, font=(MONO, 9)).pack(side="left", padx=6); self.row += 1
        self.v_thr = self.scale("MATCH STRICTNESS", 0.5, 0.95, c["threshold"], 0.01, "lower = forgives more mishearing\nhigher = fewer wrong triggers")
        self.v_bias = self.check("TEACH WHISPER\nMY COMMANDS", c["bias"], "gives Whisper the command words as a hint")
        self.v_top = self.check("WINDOW ON TOP", c["ontop"], "keep Skynet Command above other windows")
        self.newcol()
        self.section("macros")
        self.v_speed = self.scale("MACRO SPEED\n(ms per key)", 10, 200, c.get("key_ms", 60), 1,
                                  "time for each key press in EVERY macro\n15 = very fast · 60 = safe · 80+ = slow PCs\nif the game misses keys, raise it")
        self.v_focus = self.check("ONLY WHEN GAME\nIS IN FRONT", c["focus_only"], "uses the profile's GAME .EXE")
        self.v_auto = self.check("AUTO-DETECT GAME", c["auto_switch"] and (app.profile or {}).get("auto_detect", True), "pick the profile of the game you open, and learn the game\nof a profile that has none (same as clicking the Skynet eye)")
        self.section("sound")
        self.v_vol = self.scale("VOLUME", 0, 100, c.get("volume", 70), 1, "all sounds and the voice of this app\n(your game and Windows are not touched)",
                                on_release=self.preview_volume)
        self.v_ui = self.check("BUTTON SOUNDS", c.get("ui_sounds", True), "every button has its own sound")
        self.v_snd = self.check("COMMAND SOUND", c["sounds"], "a chime when a command fires")
        self.v_fail = self.combo("FAIL SOUND", ["off", "ptt only", "always"], c.get("fail_sound", "ptt only"),
                                 "a buzz when nothing matched or the game was not in front\nptt only = only with push-to-talk (talking to friends\nin 'always' mode would buzz a lot)", width=10)
        self.v_ptts = self.check("PUSH-TO-TALK SOUNDS", c.get("ptt_sounds", True), "radio click when you press / release the PTT key,\nlock / unlock sounds")
        self.v_conf = self.check("SKYNET VOICE", c.get("confirm_voice", False), "a cold machine voice says the command name when it fires\n('Hellbomb') and 'listening online / offline'")
        self.v_voice = self.check("SPOKEN REPLIES", c["voice"], "lets 'say ...' actions talk (Skynet voice)")
        self.newcol()
        self.section("performance  ·  game fps")
        self.v_load = self.combo("AI LOAD", ["low", "balanced", "max"], c.get("ai_load", "balanced"),
                                 "how hard the speech AI works on every command\nlow = lightest on your GPU / CPU (one quick pass)\n"
                                 "balanced = good accuracy, short bursts\nmax = most accurate, heaviest (second careful pass)")
        self.v_gmem = self.combo("GPU MEMORY", ["saver", "normal"], c.get("gpu_mem", "saver"),
                                 "saver = the model is stored smaller on the graphics card\n(about half the VRAM, same accuracy for commands)\nnormal = full size")
        cores = os.cpu_count() or 4
        self.v_thr_n = self.scale("CPU THREADS", 1, cores, min(cores, int(c.get("cpu_threads", 4))), 1,
                                  f"how many of your {cores} CPU threads the speech AI may use\nfewer = more left for the game (CPU mode is slower then)")
        self.v_first = self.check("GAME FIRST", c.get("game_first", True), "runs this app at low priority:\nWindows always serves the game first")
        self.v_pause = self.check("PAUSE ANIMATIONS\nIN GAME", c.get("pause_anim", True),
                                  "while another program is in front, all animations stop\n(the window uses almost nothing for drawing)")
        self.v_age = self.scale("DROP LATE\nCOMMANDS (s)", 1, 8, float(c.get("max_age", 3.0)), 0.5,
                                "a command that could not fire within this many seconds\nof you saying it is thrown away instead of pushed late")
        self.label("NOW USING", "memory this app uses right now\nRAM = system memory · VRAM = graphics card memory\n"
                                "biggest saving: a smaller WHISPER MODEL or RUN ON: cpu (frees the GPU completely)")
        self.usage = tk.Label(self.body, text="…", bg=self.cbg, fg=WHITE, font=(MONO, 9, "bold"), justify="left", anchor="w")
        self.usage.grid(row=self.row, column=self.c0 + 1, sticky="w", pady=5); self.row += 1
        self.after(200, self.show_usage)
        self.err = tk.Label(self.body, text="", bg=self.cbg, fg=RED, font=(MONO, 9)); self.err.grid(row=self.row, column=self.c0 + 1, sticky="w"); self.row += 1
        hbtn(self.bar, "✔ SAVE", self.save, fg=ORANGE, bold=True, bg=BG).pack(side="left")
        hbtn(self.bar, "CANCEL", self.destroy, fg=DIM, bg=BG).pack(side="left", padx=8)
        self.center()

    def show_usage(self):
        def work(): self._vram = vram_mb()                  # nvidia-smi can take a moment -> background thread
        threading.Thread(target=work, daemon=True).start()
        v = getattr(self, "_vram", None); r = ram_mb()
        try:
            self.usage.config(text=f"RAM  {r / 1024:.2f} GB" + (f"\nVRAM {v / 1024:.2f} GB" if v else ""))
            self.after(3000, self.show_usage)
        except tk.TclError: pass

    def gpu_boost(self):
        bat = next((b for b in (os.path.join(HERE, "Install GPU boost.bat"), os.path.join(ROOT, "GPU boost (NVIDIA only).bat")) if os.path.exists(b)),
                   os.path.join(HERE, "Install GPU boost.bat"))
        if not os.path.exists(bat): self.err.config(text="Install GPU boost.bat is missing"); return
        try: os.startfile(bat)
        except Exception as e: self.err.config(text=str(e))

    def preview_volume(self, v):
        if self.app.sfx: self.app.sfx.set_volume(v); sfx("ok")

    def destroy(self):
        if self.app.sfx: self.app.sfx.set_volume(self.app.cfg.get("volume", 70))
        super().destroy()

    def save(self):
        mic = self.v_mic.get(); mic = "" if mic == DEFAULT_MIC else mic
        if self.v_mode.get() == "ptt" and not self.k_ptt.get(): self.err.config(text="set a push-to-talk key first"); sfx("denied"); return
        new = dict(mic=mic, mode=self.v_mode.get(), ptt_key=self.k_ptt.get(), toggle_key=self.k_tog.get(),
                   model=self.v_model.get(), device=self.v_dev.get(), language=self.v_lang.get(), sensitivity=int(self.v_sens.get()),
                   silence_ms=int(self.v_sil.get()), threshold=round(float(self.v_thr.get()), 2), bias=self.v_bias.get(),
                   focus_only=self.v_focus.get(), auto_switch=self.v_auto.get(), sounds=self.v_snd.get(), voice=self.v_voice.get(),
                   ontop=self.v_top.get(), key_ms=int(self.v_speed.get()), volume=int(self.v_vol.get()), ui_sounds=self.v_ui.get(),
                   fail_sound=self.v_fail.get(), ptt_sounds=self.v_ptts.get(), confirm_voice=self.v_conf.get(),
                   ai_load=self.v_load.get(), gpu_mem=self.v_gmem.get(), cpu_threads=int(self.v_thr_n.get()), game_first=self.v_first.get(),
                   pause_anim=self.v_pause.get(), max_age=round(float(self.v_age.get()), 1))
        app = self.app; super().destroy(); app.apply_settings(new)


class App:
    def __init__(self):
        if WIN:
            try: ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SkynetCommand.App")
            except Exception: pass
        self.cfg = dict(DEFAULTS)
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f: self.cfg.update(json.load(f))
        except Exception: pass
        if self.cfg.get("threshold") == 0.72: self.cfg["threshold"] = 0.78   # v1 default -> stricter v2 matcher
        self.root = tk.Tk(); self.root.title("SKYNET COMMAND"); self.root.configure(bg=BG)
        self.icon = next((p for p in (os.path.join(HERE, "skynet_command.ico"), os.path.join(os.path.dirname(HERE), "Claude Captions", "skynet_alpha.ico")) if os.path.exists(p)), "")
        try: self.root.iconbitmap(default=self.icon)
        except Exception: pass
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        geo = f"{int(sw * 0.58)}x{int(sh * 0.66)}+{int(sw * 0.2)}+{int(sh * 0.1)}"
        m = re.match(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", self.cfg.get("geometry") or "")
        if m:   # keep the borderless window on screen (it can't be grabbed off-screen)
            w, h, x, y = map(int, m.groups()); w, h = min(w, sw), min(h, sh - 40)
            geo = f"{w}x{h}+{max(0, min(x, sw - w))}+{max(0, min(y, sh - h - 40))}"
        self.root.geometry(geo)
        self.root.minsize(820, 480); self.root.attributes("-topmost", bool(self.cfg["ontop"]))
        self.ui_q, self.utt_q, self.flush_until = queue.Queue(), queue.Queue(), 0.0
        self.listening, self.ptt_down, self.mute_until = bool(self.cfg["listening"]), False, 0.0
        self.model, self.model_key, self.model_desc, self.loading = None, None, "--", False
        self.latency, self.fg_exe, self.capture, self.voice, self.t0 = 0.0, "", None, None, time.time()
        self.profiles, self.profile_files, self.profile = {}, {}, None
        self.load_profiles()
        self.exec = Executor(self); self.exec.start()
        global SFX
        set_priority(self.cfg.get("game_first", True))
        self.sfx = SFX = Sfx(self); self.build_ui(); self.make_frameless()
        self.select_profile(self.cfg["profile"] if self.cfg["profile"] in self.profiles else next(iter(self.profiles)))
        self.start_capture()
        threading.Thread(target=self.recognize_loop, daemon=True).start()
        threading.Thread(target=self.hotkey_loop, daemon=True).start()
        self.root.after(40, self.pump); self.root.after(50, self.animate)
        self.root.protocol("WM_DELETE_WINDOW", self.quit); self.make_shortcut()
        self.log("SKYNET COMMAND online. loading the speech model...", "sys")
        self.log("made by Salutem · this app is FREE and cannot be sold", "dim")
        if getattr(self, "upgraded", 0): self.log(f"Helldivers 2 profile upgraded ({self.upgraded} commands): every stratagem now also answers to its full name and code name (e.g. 'TD-220' / 'TD two twenty') - your own phrases and changes were kept", "ok")
        if self.cfg.get("toggle_key"): self.log(f"lock / unlock listening anytime with {self.cfg['toggle_key'].upper()}", "dim")

    # ---------------- profiles ----------------
    def load_profiles(self):
        files = [f for f in os.listdir(PROFILE_DIR) if f.lower().endswith(".json")]
        if not files:
            for p in default_profiles(): self.write_profile(p)
            files = [f for f in os.listdir(PROFILE_DIR) if f.lower().endswith(".json")]
        for f in sorted(files):
            try:
                with open(os.path.join(PROFILE_DIR, f), encoding="utf-8") as fh: p = json.load(fh)
                p.setdefault("commands", []); p.setdefault("name", f[:-5]); p.setdefault("process", "")
                self.profiles[p["name"]] = p; self.profile_files[p["name"]] = os.path.join(PROFILE_DIR, f)
                if upgrade_hd2(p):
                    self.write_profile(p); self.upgraded = len(p["commands"])
            except Exception as e:
                traceback.print_exc(); print(f"bad profile {f}: {e}", file=sys.stderr)
        if not self.profiles:
            p = default_profiles()[0]; self.profiles[p["name"]] = p

    def write_profile(self, p):
        path = self.profile_files.get(p["name"]) if hasattr(self, "profile_files") else None
        path = path or os.path.join(PROFILE_DIR, slug(p["name"]) + ".json")
        with open(path, "w", encoding="utf-8") as f: json.dump(p, f, ensure_ascii=False, indent=1)
        if hasattr(self, "profile_files"): self.profile_files[p["name"]] = path

    def save_profile(self):
        try: self.write_profile(self.profile)
        except Exception as e: self.log(f"could not save profile: {e}", "err")
        self.matcher = Matcher(self.profile["commands"])

    def select_profile(self, name, why=""):
        if name not in self.profiles: return
        self.profile = self.profiles[name]; self.matcher = Matcher(self.profile["commands"])
        self.prof_var.set(name); self.cfg["profile"] = name; self.fill_tree(); self.save_settings()
        n = len([c for c in self.profile["commands"] if c.get("enabled", True)])
        self.log(f"profile '{name}' · {n} commands" + (f" · {why}" if why else ""), "sys")

    def refresh_profile_list(self):
        self.prof_box.config(values=sorted(self.profiles))

    def new_profile(self):
        tmp = {"name": "", "process": "", "auto_detect": True}
        def done(name, proc, st):
            if name in self.profiles: messagebox.showerror("Skynet Command", "a profile with that name exists", parent=self.root); return
            p = {"name": name, "process": proc, "stratagem": st, "auto_detect": tmp.get("auto_detect", True), "commands": []}
            self.profiles[name] = p; self.write_profile(p); self.refresh_profile_list(); self.select_profile(name)
        ProfileDialog(self, tmp, done)

    def edit_profile(self):
        p = self.profile; old = p["name"]
        def done(name, proc, st):
            if name != old:
                if name in self.profiles: messagebox.showerror("Skynet Command", "a profile with that name exists", parent=self.root); return
                path = self.profile_files.pop(old, None)
                if path:
                    try: os.remove(path)
                    except Exception: pass
                del self.profiles[old]; p["name"] = name; self.profiles[name] = p
            p.update(process=proc, stratagem=st); self.save_profile(); self.refresh_profile_list(); self.select_profile(name)
        ProfileDialog(self, p, done)

    def delete_profile(self):
        if len(self.profiles) < 2: self.log("keep at least one profile", "err"); return
        name = self.profile["name"]
        if not messagebox.askyesno("Skynet Command", f"Delete profile '{name}'?\n(the file goes to profiles/deleted)", parent=self.root): return
        path = self.profile_files.pop(name, None)
        if path:
            d = os.path.join(PROFILE_DIR, "deleted"); os.makedirs(d, exist_ok=True)
            try: os.replace(path, os.path.join(d, f"{int(time.time())}_{os.path.basename(path)}"))
            except Exception: pass
        del self.profiles[name]; self.refresh_profile_list(); self.select_profile(sorted(self.profiles)[0])

    def import_profile(self):
        path = filedialog.askopenfilename(parent=self.root, title="Import VoiceAttack profile (.vap) or Skynet profile (.json)",
                                          filetypes=[("Profiles", "*.vap *.json *.xml"), ("All files", "*.*")])
        if not path: return
        try:
            if path.lower().endswith(".json"):
                with open(path, encoding="utf-8") as f: p = json.load(f)
                skipped = 0
            else:
                p, skipped = import_vap(path)
        except Exception as e:
            messagebox.showerror("Skynet Command", f"Could not import:\n{e}", parent=self.root); return
        base, k = p["name"], 2
        while p["name"] in self.profiles: p["name"] = f"{base} ({k})"; k += 1
        self.profiles[p["name"]] = p; self.write_profile(p); self.refresh_profile_list(); self.select_profile(p["name"])
        self.log(f"imported '{p['name']}': {len(p['commands'])} commands" + (f" · {skipped} unsupported actions kept as # comments" if skipped else ""), "ok")

    def open_folder(self):
        try: os.startfile(PROFILE_DIR)
        except Exception: pass

    # ---------------- commands ----------------
    def fill_tree(self, *_):
        q = self.search.get().strip().lower(); rows = []
        for i, c in enumerate(self.profile["commands"]):
            says = " · ".join(c.get("phrases", [])); does = "   ".join(pretty_action(a) for a in c.get("actions", []) if not a.startswith("#")) or "— not set —"
            if q and q not in (c.get("name", "") + " " + says + " " + c.get("category", "")).lower(): continue
            rows.append((i, (c.get("name", ""), says, does, c.get("category", "")), c.get("enabled", True),
                         {"name": c.get("name", ""), "phrases": c.get("phrases", []), "actions": c.get("actions", []), "code": stratagem_code(c.get("actions", []))}))
        self.tree.set_rows(rows)
        self.count_lbl.config(text=f"{len(self.profile['commands'])} commands")

    def selected(self):
        return self.tree.selected()

    def add_command(self, phrase=""):
        def done(c):
            self.profile["commands"].append(c); self.save_profile(); self.fill_tree(); self.tree.select(len(self.profile["commands"]) - 1)
            self.log(f"added '{c['name']}'", "ok", ("cmd", self.profile["name"], c["name"]))
        CommandDialog(self, {"phrases": [phrase] if phrase else [], "actions": [], "enabled": True}, done)

    def edit_command(self, e=None, i=None):
        i = self.selected() if i is None else i
        if i is None: return
        def done(c): self.profile["commands"][i] = c; self.save_profile(); self.fill_tree(); self.tree.select(i)
        CommandDialog(self, self.profile["commands"][i], done)

    def dup_command(self):
        i = self.selected()
        if i is None: return
        c = json.loads(json.dumps(self.profile["commands"][i])); c["name"] += " copy"
        self.profile["commands"].insert(i + 1, c); self.save_profile(); self.fill_tree(); self.tree.select(i + 1)

    def del_command(self, e=None):
        i = self.selected()
        if i is None: return
        c = self.profile["commands"][i]
        if not messagebox.askyesno("Skynet Command", f"Delete command '{c['name']}'?", parent=self.root): return
        del self.profile["commands"][i]; self.save_profile(); self.fill_tree()

    def test_selected(self):
        i = self.selected()
        if i is not None: self.test_command(self.profile["commands"][i])

    def test_command(self, c, n=3):
        if n:
            self.status(f"TEST '{c['name']}' in {n} s - switch to the game / Notepad now"); self.root.after(1000, lambda: self.test_command(c, n - 1)); return
        self.status(f"TEST '{c['name']}' - keys sent"); self.exec.submit(c, self.profile)

    # ---------------- speech ----------------
    def start_capture(self):
        if self.capture: self.capture.running = False
        self.capture = Capture(self, self.cfg["mic"]); self.capture.start()

    def want_key(self):
        return (self.cfg["model"], self.cfg["device"], self.cfg["language"], self.cfg.get("gpu_mem", "saver"), self.threads())

    def threads(self):
        return max(1, min(os.cpu_count() or 4, int(self.cfg.get("cpu_threads", 4))))

    def load_model(self):
        from faster_whisper import WhisperModel
        model, dev, lang = self.want_key()[:3]; code = LANGS.get(lang, "en")
        try:
            import ctranslate2; gpus = ctranslate2.get_cuda_device_count()
        except Exception: gpus = 0
        tries = []
        if dev == "auto" and gpus > 0 and not GPU_LIBS:
            self.log("NVIDIA card found, but its speed-up libraries are missing: ⚙ OPTIONS → GPU BOOST (one click, ~1 GB) makes "
                     "recognition much more accurate AND faster (large-v3-turbo on the GPU). Using the CPU for now.", "sys")
        if (dev == "gpu" or (dev == "auto" and GPU_LIBS)) and gpus > 0:
            gname = "large-v3-turbo" if model == "auto" else model
            if self.cfg.get("gpu_mem", "saver") == "saver": tries.append(("cuda", "int8_float16", gname))
            tries.append(("cuda", "float16", gname))           # also the fallback if the card can't do the saver format
        if dev in ("auto", "cpu") or not tries:
            tries.append(("cpu", "int8", "distil-small.en" if model == "auto" else model))   # small's accuracy, much faster decoder
            if model == "auto": tries.append(("cpu", "int8", "base.en"))                    # safety fallback
        last = None
        for d, ct, name in tries:
            self.model = None; import gc; gc.collect()          # free the old model's memory first
            if code != "en" and name.endswith(".en"): name = name[:-3]
            self.loading = True; self.log(f"loading Whisper '{name}' on {d.upper()} (first time downloads it)...", "sys")
            try:
                m = WhisperModel(name, device=d, compute_type=ct, cpu_threads=self.threads(), num_workers=1)
                list(m.transcribe(np.zeros(SR, dtype=np.float32), beam_size=1, language=code or None)[0])
                self.model, self.model_desc, self.dev, self.gpus = m, f"{name}·{'gpu' if d == 'cuda' else 'cpu'}", d, gpus
                self.log(f"speech ready: {name} on {'GPU' if d == 'cuda' else 'CPU'}. say a command!", "ok")
                return True
            except Exception as e:
                last = e; traceback.print_exc(); self.log(f"{d.upper()} failed: {str(e)[:160]}", "err")
            finally:
                self.loading = False
        self.model = None; self.log(f"could not load the speech model: {last}", "err"); return False

    def recognize_loop(self):
        thread_priority(1)
        while True:
            try:
                if not self.cfg.get("ai_on", True):                 # speech AI switched off: no model in memory at all
                    if self.model is not None or self.model_key is not None:
                        self.model, self.model_key = None, None; import gc; gc.collect()
                        self.log("speech AI OFFLINE - its RAM / graphics memory is free", "sys")
                    while not self.utt_q.empty():
                        try: self.utt_q.get_nowait()
                        except queue.Empty: break
                    time.sleep(0.2); continue
                if self.model_key != self.want_key():
                    self.model_key = self.want_key(); self.model = None
                    if self.load_model(): self.zap_at = time.time()      # online: electric burst in the header
                try: t_end, audio = self.utt_q.get(timeout=0.3)
                except queue.Empty: continue
                if self.model is None or t_end <= self.flush_until: continue
                if time.time() - t_end > float(self.cfg.get("max_age", 3.0)):
                    self.log(f"dropped a command said {time.time() - t_end:.1f} s ago (too late)", "miss"); continue
                self.handle(audio, t_end)
            except Exception as e:
                traceback.print_exc(); self.log(f"speech error: {e}", "err"); time.sleep(0.5)

    @staticmethod
    def clean_audio(audio):
        """remove hum/rumble (high-pass), even out the loudness, add a little silence around it - Whisper likes that"""
        a = audio.astype(np.float32); a = a - float(np.mean(a))
        if len(a) > 400: a = a - np.convolve(a, np.ones(201, dtype=np.float32) / 201, mode="same")   # ~80 Hz high-pass
        rms = float(np.sqrt(np.mean(a * a))) or 1e-6
        a = a * min(30.0, 0.1 / rms); peak = float(np.max(np.abs(a))) or 1.0
        if peak > 0.97: a = a * (0.97 / peak)
        pad = np.zeros(int(SR * 0.25), dtype=np.float32)
        return np.concatenate([pad, a, pad])

    def transcribe(self, audio, focus=None):
        """focus = a few candidate commands: second, narrower pass that only 'expects' those words"""
        audio = self.clean_audio(audio)
        code = LANGS.get(self.cfg["language"], "en")
        if focus:
            words = list(dict.fromkeys(ph for c in focus for ph in c.get("phrases", [])[:2]))
            prompt = "Voice commands: " + ", ".join(words) + "."; hot = " ".join(words)
        else:
            prompt = self.matcher.prompt if self.cfg["bias"] else None; hot = None
        load = self.cfg.get("ai_load", "balanced")
        beam = {"low": 1, "balanced": 3 if focus else 2}.get(load, 5 if (self.dev == "cuda" or focus) else 3)
        kw = dict(language=code, beam_size=beam, best_of=1, temperature=0.0,
                  condition_on_previous_text=False, without_timestamps=True, initial_prompt=prompt, vad_filter=False,
                  no_speech_threshold=0.6)
        if hot: kw["hotwords"] = hot
        try: segs, info = self.model.transcribe(audio, **kw)
        except TypeError:
            kw.pop("hotwords", None); segs, info = self.model.transcribe(audio, **kw)
        segs = [s for s in segs if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)]
        text = " ".join(s.text.strip() for s in segs).strip()
        if prompt and text.lower().startswith("voice commands"): text = ""   # echo of the hint = Whisper heard nothing
        return text

    def fail_sound(self):
        f = self.cfg.get("fail_sound", "ptt only")
        if f == "always" or (f == "ptt only" and self.cfg["mode"] == "ptt"): self.play("miss", "cmd")

    def handle(self, audio, t_end):
        t = time.time(); text = self.transcribe(audio); self.latency = time.time() - t_end
        self.t_wait, self.t_ai = t - t_end, time.time() - t           # waiting in line / Whisper itself
        if not re.search(r"\w", text) or " ".join(normalize(text)) in JUNK:
            if self.cfg["mode"] == "ptt": self.fail_sound()
            return
        ranked = self.matcher.match(text); thr = float(self.cfg["threshold"]); prof = self.profile; second = ""
        if ranked and thr > ranked[0][1] >= 0.45 and self.cfg.get("ai_load", "balanced") != "low":
            # near miss -> second, focused pass: Whisper listens again expecting only the 5 closest commands
            cands = [i for i, _ in ranked[:5]]
            t2 = self.transcribe(audio, focus=[prof["commands"][i] for i in cands])
            r2 = self.matcher.match(t2) if t2 else []
            if r2 and r2[0][1] >= thr and r2[0][0] in cands: ranked, second = r2, f"  (2nd pass: “{t2}”)"
            self.latency = time.time() - t_end
        if not ranked or ranked[0][1] < thr:
            if ranked and ranked[0][1] >= 0.4:
                near = prof["commands"][ranked[0][0]]["name"]
                link = ("teach", prof["name"], near, text); hint = f"   (closest: {near} {ranked[0][1] * 100:.0f}%)  · click to teach it"
            else:
                link = ("new", text); hint = "  · click to make it a command"
            self.ui_q.put(("heard", text, None, ranked[0][1] if ranked else 0))
            self.log(f"“{text}” → no match{hint}", "miss", link); self.fail_sound(); return
        i, score = ranked[0]; cmd = prof["commands"][i]; link = ("cmd", prof["name"], cmd["name"])
        need = (prof.get("process") or "").lower()
        if not need and prof.get("auto_detect", True):           # learn the game by itself: the full-screen program you talk to
            exe, full = foreground_info()
            if exe and full and exe not in IGNORE_EXE: self.ui_q.put(("learn", prof["name"], exe))
        if self.cfg["focus_only"] and need and self.fg_exe != need:
            self.ui_q.put(("heard", text, cmd["name"] + " (game not in front)", score))
            self.log(f"“{text}” → {cmd['name']} — ignored, {need} is not in front", "miss", link); self.fail_sound(); return
        late = time.time() - t_end
        if t_end <= self.flush_until or late > float(self.cfg.get("max_age", 3.0)) + 1.0:     # refreshed meanwhile / way too late
            self.log(f"“{text}” → {cmd['name']} — dropped, said {late:.1f} s ago", "miss", link); return
        self.exec.submit(cmd, prof); self.fired_at = time.time()
        self.ui_q.put(("heard", text, cmd["name"], score))
        keys = self.macro_time(cmd, prof)
        self.log(f"“{text}” → {cmd['name']}   {score * 100:.0f}% · {self.latency * 1000:.0f} ms to fire (AI {self.t_ai * 1000:.0f} ms"
                 + (f", waited {self.t_wait * 1000:.0f} ms" if self.t_wait > 0.05 else "") + f") + keys {keys * 1000:.0f} ms{second}", "ok", link)
        self.play("ok", "cmd")
        if self.cfg.get("confirm_voice"): self.speak(spoken_name(cmd["name"]), confirm=True, delay=0.2)

    def macro_time(self, cmd, prof):
        """how long the key presses of a macro take at the current MACRO SPEED"""
        ops, _ = compile_actions(cmd.get("actions", []), prof, self.cfg.get("key_ms", 60))
        return sum(v for op, v in ops if op == "wait")

    # ---------------- sound / voice ----------------
    def play(self, name, kind="ui"):
        if self.sfx: self.sfx.play(name, kind)

    def beep(self, nm): self.play(nm, "cmd")

    def speak(self, text, confirm=False, delay=0.0):
        if not self.cfg["confirm_voice" if confirm else "voice"] or not text.strip() or not WIN: return
        if self.voice is None:
            self.voice = Voice(self)
            if self.cfg.get("confirm_voice") and self.profile:      # pre-make every command name in the background
                self.voice.warm([spoken_name(c["name"]) for c in self.profile["commands"] if c.get("enabled", True)])
        self.voice.say(text, delay)

    # ---------------- hotkeys + game focus ----------------
    def hotkey_loop(self):
        thread_priority(2)                                  # push-to-talk key: reacts at once
        prev, last_fg, keys, combos = False, 0.0, None, ([], [])
        while True:
            time.sleep(0.012)
            k = (self.cfg["toggle_key"], self.cfg["ptt_key"])
            if k != keys:                                   # parse the key names only when they change
                keys = k
                try: combos = (combo_vks(k[0]), combo_vks(k[1]))
                except ValueError: combos = ([], [])
            tog, ptt = combos
            d = combo_down(tog)
            if d and not prev: self.ui_q.put(("toggle",))
            prev = d
            down = self.cfg["mode"] == "ptt" and combo_down(ptt)
            if down != self.ptt_down: self.ui_q.put(("ptt", down))
            self.ptt_down = down
            if time.time() - last_fg > 0.4:
                last_fg = time.time(); exe = foreground_exe()
                if exe != self.fg_exe:
                    self.fg_exe = exe; self.ui_q.put(("fg", exe))

    def learn_game(self, prof, exe):
        p = self.profiles.get(prof)
        if not p or p.get("process"): return
        p["process"] = exe; self.write_profile(p); self.play("detect")
        self.log(f"game detected automatically: {exe} → saved in profile '{prof}'", "sys")

    def update_pause(self):
        """animations stop while another program (your game) is in front - the app then uses almost no CPU / GPU for drawing"""
        exe = self.fg_exe; mine = os.path.basename(sys.executable).lower()
        PAUSED[0] = bool(self.cfg.get("pause_anim", True) and exe and exe != mine and exe not in ("python.exe", "pythonw.exe"))

    def flush_commands(self):
        """refresh: forget everything that was heard but not fired yet, and stop a running macro"""
        self.flush_until = time.time(); n = self.utt_q.qsize()
        while not self.utt_q.empty():
            try: self.utt_q.get_nowait()
            except queue.Empty: break
        self.exec.abort()
        if self.capture: self.capture.reset(); self.capture.ptt_rec = None
        self.log(f"⟳ refreshed - {n} waiting command{'s' if n != 1 else ''} dropped, nothing old will fire", "sys")

    def on_foreground(self, exe):
        if not self.cfg["auto_switch"] or not exe: return
        for name, p in self.profiles.items():
            if (p.get("process") or "").lower() == exe and self.profile is not p:
                self.select_profile(name, f"{exe} detected"); break

    # ---------------- UI ----------------
    def build_ui(self):
        st = ttk.Style(); st.theme_use("clam")
        st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=WHITE, rowheight=26, bordercolor=GRID, borderwidth=0, font=(MONO, 10))
        st.configure("Treeview.Heading", background=BG, foreground=RED, font=(MONO, 9, "bold"), bordercolor=GRID, relief="flat")
        st.map("Treeview", background=[("selected", "#3A0E0E")], foreground=[("selected", WHITE)])
        st.map("Treeview.Heading", background=[("active", "#1C0909")])
        st.configure("TCombobox", fieldbackground=PANEL, background=GRID, foreground=WHITE, arrowcolor=RED, bordercolor=RED_DIM,
                     lightcolor=PANEL, darkcolor=PANEL, selectbackground=PANEL, selectforeground=WHITE)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", WHITE)])
        st.configure("Vertical.TScrollbar", background=GRID, troughcolor=BG, arrowcolor=RED, bordercolor=BG, lightcolor=GRID, darkcolor=GRID)
        st.configure("TPanedwindow", background=BG); st.configure("Sash", sashthickness=6, background=BG)
        for k, v in (("background", PANEL), ("foreground", WHITE), ("selectBackground", RED_DIM), ("font", (MONO, 10))):
            self.root.option_add(f"*TCombobox*Listbox.{k}", v)
        r = self.root
        self.hdr = tk.Canvas(r, height=84, bg=BG, highlightthickness=0); self.hdr.pack(fill="x", padx=10, pady=(8, 0))
        self.hdramb = StaticField(self.hdr, amount=22)
        self.heard = tk.Label(r, text="", bg=BG, fg=DIM, font=(MONO, 15, "bold"), anchor="w"); self.heard.pack(fill="x", padx=16, pady=(0, 4))
        bar = tk.Frame(r, bg=BG); bar.pack(fill="x", padx=12, pady=4)
        IconButton(bar, "profile", lambda: self.prof_box.event_generate("<Button-1>"), "Profile", "which game's commands are active\n(switches by itself when you open a game)", fg=ORANGE, bg=BG).pack(side="left", padx=(0, 4))
        self.prof_var = tk.StringVar()
        self.prof_box = ttk.Combobox(bar, textvariable=self.prof_var, values=sorted(self.profiles), state="readonly", width=26, font=(MONO, 11))
        self.prof_box.pack(side="left", ipady=3); self.prof_box.bind("<<ComboboxSelected>>", lambda e: self.select_profile(self.prof_var.get()))
        for txt, cmd, tip in (("✎ PROFILE", self.edit_profile, "Name, game .exe, stratagem keys (arrows / WASD)"), ("＋ NEW", self.new_profile, "New empty profile"),
                              ("⇩ IMPORT", self.import_profile, "Import a VoiceAttack .vap (XML) or a Skynet .json profile"),
                              ("▣ FOLDER", self.open_folder, "Open the profiles folder"), ("✖", self.delete_profile, "Delete this profile")):
            hbtn(bar, txt, cmd, fg=DIM if txt in ("▣ FOLDER", "✖") else RED, bg=BG, tip=tip).pack(side="left", padx=(6, 0))
        self.listen_btn = hbtn(bar, "", self.toggle_listen, fg=ORANGE, bold=True, bg=BG, tip="Lock / unlock listening (hotkey in ⚙ OPTIONS)")
        self.listen_btn.pack(side="right"); self.listen_btn.sound = None   # toggle_listen plays lock / unlock itself
        hbtn(bar, "■ STOP MACRO", self.exec.abort, fg=DIM, bg=BG, tip="Abort the macro that is running").pack(side="right", padx=6)
        hbtn(bar, "⚙ OPTIONS", lambda: SettingsDialog(self), bg=BG, tip="Recording device, push-to-talk, lock key, macro speed, speech AI").pack(side="right")
        bar2 = tk.Frame(r, bg=BG); bar2.pack(fill="x", padx=12, pady=(2, 4))
        IconButton(bar2, "mic", lambda: self.mic_box.event_generate("<Button-1>"), "Recording device", "the microphone Skynet Command listens to\nthe bar in the header shows its level", fg=GREEN, bg=BG).pack(side="left", padx=(0, 4))
        self.mic_var = tk.StringVar(value=self.cfg["mic"] or DEFAULT_MIC)
        self.mic_box = ttk.Combobox(bar2, textvariable=self.mic_var, values=[self.mic_var.get()], state="readonly", width=48, font=(MONO, 10),
                                    postcommand=lambda: self.mic_box.config(values=self.mic_names()))
        self.mic_box.pack(side="left", ipady=2); self.mic_box.bind("<<ComboboxSelected>>", lambda e: self.change_mic(self.mic_var.get()))
        Tip(self.mic_box, "Which microphone Skynet Command listens to (the bar in the header shows its level)")
        opts = lambda: SettingsDialog(self); short = lambda k: "+".join(SHORT_KEY.get(x, x.upper()) for x in (k or "").split("+") if x)
        self.chip_speed = StatusChip(bar2, "gauge", lambda: f"{self.cfg.get('key_ms', 60)}ms",
                                     lambda: f"Macro speed: {self.cfg.get('key_ms', 60)} ms per key\nhow fast every macro presses its keys - click to change", opts, fg=ORANGE)
        self.chip_lock = StatusChip(bar2, "locked", lambda: short(self.cfg.get("toggle_key")),
                                    lambda: f"Lock / unlock listening: {pretty_combo(self.cfg.get('toggle_key')) or 'no key'}\nworks anywhere, also in game - click to change", opts)
        self.chip_ptt = StatusChip(bar2, "mic", lambda: short(self.cfg.get("ptt_key")),
                                   lambda: f"Push-to-talk: hold {pretty_combo(self.cfg.get('ptt_key')) or '-'} while you speak\nclick to change", opts, fg=GREEN)
        for ch in (self.chip_speed, self.chip_lock): ch.pack(side="right", padx=(6, 0))
        self.update_info()
        self.status_lbl = tk.Label(r, text="", bg=BG, fg=DIM, font=(MONO, 9), anchor="w"); self.status_lbl.pack(side="bottom", fill="x", padx=14, pady=(0, 6))
        self.split = Splitter(r, float(self.cfg.get("split", 0.58)), on_change=lambda v: (self.cfg.__setitem__("split", round(v, 3)), self.save_settings()))
        self.split.pack(fill="both", expand=True, padx=12, pady=(4, 4)); left, right = self.split.left, self.split.right
        top = tk.Frame(left, bg=BG); top.pack(fill="x", pady=(0, 4))
        IconButton(top, "search", lambda: self.search_e.focus_force(), "Search", "type to filter the commands by name, phrase or group", bg=BG, size=28).pack(side="left")
        self.search = tk.StringVar(); self.search.trace_add("write", self.fill_tree)
        self.search_e = tk.Entry(top, textvariable=self.search, bg=PANEL, fg=WHITE, insertbackground=ORANGE, relief="flat", font=(MONO, 10), width=22,
                 highlightthickness=1, highlightbackground=GRID, highlightcolor=ORANGE)
        self.search_e.pack(side="left", padx=6, ipady=3); self.search_e.bind("<Button-1>", lambda e: self.search_e.focus_force(), add="+")
        self.count_lbl = tk.Label(top, text="", bg=BG, fg=DIM, font=(MONO, 9)); self.count_lbl.pack(side="left")
        btns = tk.Frame(left, bg=BG); btns.pack(side="bottom", fill="x", pady=(6, 0))
        for txt, cmd, fg in (("＋ ADD", self.add_command, ORANGE), ("✎ EDIT", self.edit_command, RED), ("⧉ COPY", self.dup_command, RED),
                             ("▶ TEST", self.test_selected, RED), ("✖ DELETE", self.del_command, DIM)):
            hbtn(btns, txt, cmd, fg=fg, bold=txt.startswith("＋"), bg=BG).pack(side="left", padx=(0, 6))
        self.tree = HudList(left, [("COMMAND", 3), ("WHEN I SAY", 3.4), ("DO THIS", 3.2), ("GROUP", 1.2)], self.edit_command, self.del_command)
        self.tree.pack(fill="both", expand=True)
        Tip(self.tree.head, "Commands\nclick = select · double-click / Enter = edit · Delete = remove\nscroll with the wheel or the bar on the right")
        lh = tk.Frame(right, bg=BG); lh.pack(fill="x", pady=(0, 4))
        IconButton(lh, "detect", lambda: self.logv.c.yview_moveto(1.0), "Command log", "what was heard and what fired\nclick a line with ▸ to edit that command,\nor to turn something unrecognised into a new command", bg=BG, size=28).pack(side="left")
        tk.Label(lh, text="COMMAND LOG", bg=BG, fg=RED, font=(MONO, 9, "bold")).pack(side="left", padx=4)
        IconButton(lh, "undo", self.flush_commands, "Refresh - drop waiting commands",
                   "forgets everything you said that has not fired yet\nand stops a macro that is running -\nnothing old will be pushed into the game", fg=ORANGE, bg=BG, size=28, sound="cancel").pack(side="right")
        tk.Label(lh, text="click ▸ lines to edit", bg=BG, fg=RED_DIM, font=(MONO, 8)).pack(side="right", padx=6)
        self.logv = LogView(right, self.open_link); self.logv.pack(fill="both", expand=True)
        self.update_listen_btn()

    def mic_names(self):
        try: return [DEFAULT_MIC] + [m["name"] for m in list_mics()]
        except Exception: return [DEFAULT_MIC]

    def change_mic(self, name):
        self.cfg["mic"] = "" if name == DEFAULT_MIC else name; self.save_settings(); self.start_capture()

    def autogame_on(self):
        """auto-detect game: one switch, shown by the Skynet eye (open = watching for the game), the AUTO chip,
        OPTIONS → AUTO-SWITCH PROFILE and PROFILE → AUTO-DETECT GAME"""
        return bool(self.cfg.get("auto_switch", True) and (self.profile or {}).get("auto_detect", True))

    def toggle_autogame(self): self.set_autogame(not self.autogame_on())

    def toggle_ai(self):
        """speech AI online / offline (offline = model unloaded: no RAM, no graphics memory, no listening)"""
        on = not self.cfg.get("ai_on", True); self.cfg["ai_on"] = on; self.save_settings()
        if on:
            self.zap_at = time.time(); self.play("on")
            self.log("⚡ speech AI coming ONLINE…", "sys")
        else:
            self.zap_at = 0.0; self.play("off")

    def set_autogame(self, on):
        self.cfg["auto_switch"] = on
        for p in self.profiles.values():
            p["auto_detect"] = on
            try: self.write_profile(p)
            except Exception: pass
        self.save_settings(); self.update_info(); self.play("unlocked" if on else "locked")
        self.log("auto-detect game ON - profiles follow the game you open" if on else "auto-detect game OFF - profiles stay as you pick them", "sys")
        if on and self.fg_exe: self.on_foreground(self.fg_exe)

    def update_info(self):
        for ch in (self.chip_speed, self.chip_lock, self.chip_ptt): ch.refresh()
        if self.cfg["mode"] == "ptt": self.chip_ptt.pack(side="right", padx=(6, 0), before=self.chip_lock)
        else: self.chip_ptt.pack_forget()

    # ---------------- borderless window ----------------
    def make_frameless(self):
        r = self.root; self.win_hover, self.maxed, self.normal_geo, self.drag0 = None, False, None, None
        self.hwnd = make_borderless(r, appwindow=True)
        if self.icon: r.after(150, lambda: set_win_icon(r, self.icon))
        c = self.hdr
        c.bind("<Button-1>", self.hdr_press); c.bind("<B1-Motion>", self.hdr_drag)
        c.bind("<Double-Button-1>", lambda e: None if self.hit_btn(e) else self.toggle_max())
        c.bind("<Motion>", self.hdr_motion); c.bind("<Leave>", lambda e: (setattr(self, "win_hover", None), setattr(self, "glyph_hover", None),
                                                                         setattr(self, "credit_hover", False), self.hdr_tip.set(None)))
        self.hdr_tip = RegionTip(c)
        r.bind("<Button-1>", lambda e: r.focus_force() if r.focus_get() is None else None, add="+")
        g = self.grip = tk.Canvas(r, width=18, height=18, bg=BG, highlightthickness=0, cursor="size_nw_se")
        for k in (5, 10, 15): g.create_line(18 - k, 17, 17, 18 - k, fill=RED_DIM, width=2)
        g.place(relx=1.0, rely=1.0, anchor="se"); g.tk.call("raise", g._w)
        g.bind("<Button-1>", lambda e: setattr(self, "rs", (e.x_root, e.y_root, r.winfo_width(), r.winfo_height())))
        g.bind("<B1-Motion>", self.grip_drag)
        g.bind("<Enter>", lambda e: [g.itemconfig(i, fill=ORANGE) for i in g.find_all()])
        g.bind("<Leave>", lambda e: [g.itemconfig(i, fill=RED_DIM) for i in g.find_all()])
        r.after(250, lambda: (r.lift(), r.focus_force()))

    def win_btn_boxes(self, w):
        bw, bh, gap = 34, 24, 4
        return {n: (w - (3 - i) * (bw + gap) - 2, 4, w - (3 - i) * (bw + gap) - 2 + bw, 4 + bh) for i, n in enumerate(("min", "max", "close"))}

    def draw_win_buttons(self, c, w):
        boxes = self.win_btn_boxes(w)
        for name, (x0, y0, x1, y1) in boxes.items():
            hov = getattr(self, "win_hover", None) == name
            col = (WHITE if name == "close" else ORANGE) if hov else RED
            fill = ("#8A1010" if name == "close" else "#2A0C0C") if hov else BG
            c.create_polygon(x0, y0, x1 - 5, y0, x1, y0 + 5, x1, y1, x0 + 5, y1, x0, y1 - 5, fill=fill, outline=col if hov else RED_DIM)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if name == "min": c.create_line(cx - 6, cy + 4, cx + 6, cy + 4, fill=col, width=2)
            elif name == "max": c.create_rectangle(cx - 6, cy - 5, cx + 6, cy + 5, outline=col, width=2 if not getattr(self, "maxed", False) else 1)
            else:
                c.create_line(cx - 5, cy - 5, cx + 5, cy + 5, fill=col, width=2); c.create_line(cx + 5, cy - 5, cx - 5, cy + 5, fill=col, width=2)
        return min(b[0] for b in boxes.values())

    def hit_btn(self, e):
        for n, (x0, y0, x1, y1) in self.win_btn_boxes(self.hdr.winfo_width()).items():
            if x0 <= e.x <= x1 and y0 <= e.y <= y1: return n
        return None

    def on_eye(self, e): return math.hypot(e.x - 30, e.y - 32) <= 30

    def hdr_motion(self, e):
        n = self.hit_btn(e); self.win_hover = n
        tip = next((b[4] for b in getattr(self, "glyph_boxes", []) if b[0] <= e.x <= b[2] and b[1] <= e.y <= b[3]), None)
        b = getattr(self, "ai_box", None)
        if b and b[0] <= e.x <= b[2] and b[1] <= e.y <= b[3]: n = "ai"
        self.credit_hover = self.on_credit(e)
        if self.credit_hover: n = "credit"; tip = None
        if self.on_eye(e):
            n = "eye"; tip = ("Skynet eye: auto-detect game ON\nthe eye is open and watching for your game - click to close it"
                              if self.autogame_on() else "Skynet eye: auto-detect game OFF\nthe eye is shut - click to open it and detect games")
        self.glyph_hover = tip; self.hdr_tip.set(tip)
        self.hdr.config(cursor="hand2" if n else ("question_arrow" if tip else "fleur"))

    def hdr_press(self, e):
        self.root.focus_force(); n = self.hit_btn(e)
        if self.on_eye(e): self.drag0 = None; self.toggle_autogame(); return
        if self.on_credit(e): self.drag0 = None; self.show_credit_card(); return
        b = getattr(self, "ai_box", None)
        if b and b[0] <= e.x <= b[2] and b[1] <= e.y <= b[3]: self.drag0 = None; self.toggle_ai(); return
        if n:
            self.drag0 = None
            if n == "close": self.quit()
            elif n == "min":
                try: ctypes.windll.user32.ShowWindow(self.hwnd, 6)
                except Exception: self.root.iconify()
            else: self.toggle_max()
            return
        self.drag0 = None if self.maxed else (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def hdr_drag(self, e):
        if self.drag0: self.root.geometry(f"+{e.x_root - self.drag0[0]}+{e.y_root - self.drag0[1]}")

    def toggle_max(self):
        r = self.root
        if self.maxed:
            if self.normal_geo: r.geometry(self.normal_geo)
            self.maxed = False
        else:
            self.normal_geo = r.geometry()
            try:
                rect = wt.RECT(); ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)   # work area (no taskbar)
                r.geometry(f"{rect.right - rect.left}x{rect.bottom - rect.top}+{rect.left}+{rect.top}")
            except Exception:
                r.geometry(f"{r.winfo_screenwidth()}x{r.winfo_screenheight() - 48}+0+0")
            self.maxed = True
        self.grip.tk.call("raise", self.grip._w)

    def grip_drag(self, e):
        if self.maxed or not getattr(self, "rs", None): return
        x0, y0, w0, h0 = self.rs
        self.root.geometry(f"{max(820, w0 + e.x_root - x0)}x{max(480, h0 + e.y_root - y0)}")

    def animate(self):
        c = self.hdr; clear_except(c); w, h = c.winfo_width(), c.winfo_height(); t = time.time() - self.t0
        on = self.listening and self.model is not None
        self.draw_logo(c, 30, 32, 27, t, on)
        c.create_text(66, 20, text="SKYNET COMMAND", fill=RED, font=(MONO, 16, "bold"), anchor="w")
        self.draw_credit(c, 67, 42, t)
        bx = self.draw_win_buttons(c, w) - 12
        self.draw_status(c, bx, t)
        lv = self.capture.level if self.capture else 0.0; lvl = min(1.0, math.sqrt(lv) * 2.4)
        x0, x1, y = 66, w - 20, 72; n = 60; seg = (x1 - x0) / n
        for k in range(n):
            lit = k < lvl * n
            cc = (ORANGE if k > n * 0.75 else (GREEN if on else RED)) if lit else GRID
            c.create_rectangle(x0 + k * seg, y - 5, x0 + (k + 1) * seg - 2, y + 5, fill=cc, outline="")
        if self.capture and self.capture.err: c.create_text(w / 2, y, text="MIC: " + self.capture.err[:60], fill=RED, font=(MONO, 9, "bold"))
        self.root.after(400 if PAUSED[0] else 50, self.animate)     # in game: ~2 frames a second

    CREDIT = "MADE BY SALUTEM"
    STEAM_URL = "https://steamcommunity.com/id/hecton/"
    DISCORD = "hekton"

    def draw_credit(self, c, x, y, t):
        """'MADE BY SALUTEM': a light sweeps over the letters, now and then a letter glitches; hover = brighter + underline, click = contact card"""
        if not hasattr(self, "credit_cw"): self.credit_cw = tkfont.Font(family=MONO, size=8, weight="bold").measure("M")
        txt, cw, hov = self.CREDIT, self.credit_cw, getattr(self, "credit_hover", False)
        sweep = (t * 9) % (len(txt) + 14) - 4                       # position of the running light
        glitch = random.randrange(len(txt)) if random.random() < 0.04 else -1
        for k, ch in enumerate(txt):
            if ch == " ": continue
            g = max(0.0, 1 - abs(k - sweep) / 2.5)
            base = lerp(RED_DIM, RED, 0.55 + 0.25 * math.sin(t * 2 + k * 0.4)) if k >= 8 else lerp(DIM, "#9AA0AD", 0.3)   # SALUTEM in red
            col = lerp(base, WHITE if hov else ORANGE, max(g, 0.55 if hov else 0.0))
            show = random.choice("01#%@$&") if k == glitch else ch
            c.create_text(x + k * cw, y + (random.choice((-1, 1)) if k == glitch else 0), text=show, fill=col, font=(MONO, 8, "bold"), anchor="w")
        w = len(txt) * cw; self.credit_box = (x - 2, y - 8, x + w + 2, y + 8)
        if hov: c.create_line(x, y + 8, x + w, y + 8, fill=ORANGE)
        else: c.create_line(x + 8 * cw, y + 8, x + 8 * cw + (w - 8 * cw) * (0.5 + 0.5 * math.sin(t * 1.5)), y + 8, fill=RED_DIM)

    def on_credit(self, e):
        b = getattr(self, "credit_box", None)
        return bool(b) and b[0] <= e.x <= b[2] and b[1] <= e.y <= b[3]

    def show_credit_card(self):
        """small contact card under the credit: Steam profile (opens the browser) + Discord name (copies it)"""
        old = getattr(self, "credit_card", None)
        if old is not None:
            try: old.destroy()
            except tk.TclError: pass
            self.credit_card = None; return
        sfx("open")
        w = self.credit_card = tk.Toplevel(self.root); w.overrideredirect(True); w.attributes("-topmost", True); w.configure(bg=RED)
        box = tk.Frame(w, bg="#101218"); box.pack(padx=1, pady=1)
        tk.Label(box, text="◢ SALUTEM", bg="#101218", fg=ORANGE, font=(MONO, 10, "bold"), anchor="w").pack(fill="x", padx=12, pady=(8, 4))
        def row(icon, label, value, action, tip):
            f = tk.Frame(box, bg="#101218", cursor="hand2"); f.pack(fill="x", padx=8, pady=2)
            ic = tk.Canvas(f, width=24, height=24, bg="#101218", highlightthickness=0); ic.pack(side="left")
            draw_icon(ic, icon, 1, 1, 22, RED)
            lb = tk.Label(f, text=f"{label}  ", bg="#101218", fg=DIM, font=(MONO, 9, "bold")); lb.pack(side="left")
            val = tk.Label(f, text=value, bg="#101218", fg=WHITE, font=(MONO, 9, "underline"), cursor="hand2"); val.pack(side="left")
            hint = tk.Label(f, text=tip, bg="#101218", fg=RED_DIM, font=(MONO, 8)); hint.pack(side="left", padx=(8, 4))
            for wd in (f, ic, lb, val, hint):
                wd.bind("<Enter>", lambda e: val.config(fg=ORANGE)); wd.bind("<Leave>", lambda e: val.config(fg=WHITE))
                wd.bind("<Button-1>", lambda e: action(hint))
            return f
        def steam(hint):
            import webbrowser
            sfx("play"); webbrowser.open(self.STEAM_URL); hint.config(text="opened ✔", fg=GREEN)
        def discord(hint):
            self.root.clipboard_clear(); self.root.clipboard_append(self.DISCORD); sfx("copy"); hint.config(text="copied ✔", fg=GREEN)
        row("gamepad", "STEAM  ", "steamcommunity.com/id/hecton", steam, "click to open")
        row("listen", "DISCORD", self.DISCORD, discord, "click to copy")
        tk.Frame(box, bg=RED_DIM, height=1).pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(box, text="⚠ THIS APP IS FREE - IT CANNOT BE SOLD", bg="#101218", fg=RED, font=(MONO, 9, "bold"), anchor="w").pack(fill="x", padx=12)
        tk.Label(box, text="if you paid for it, you were scammed", bg="#101218", fg=DIM, font=(MONO, 8), anchor="w").pack(fill="x", padx=12)
        lic = tk.Label(box, text="license: PolyForm Noncommercial 1.0.0  (LICENSE.txt)", bg="#101218", fg=RED_DIM, font=(MONO, 8, "underline"),
                       anchor="w", cursor="hand2")
        lic.pack(fill="x", padx=12, pady=(2, 8))
        lic.bind("<Button-1>", lambda e: os.path.exists(os.path.join(HERE, "LICENSE.txt")) and os.startfile(os.path.join(HERE, "LICENSE.txt")) if WIN else None)
        w.bind("<Escape>", lambda e: self.show_credit_card())
        w.update_idletasks(); x0, y0, x1, y1 = self.credit_box
        w.geometry(f"+{self.hdr.winfo_rootx() + int(x0)}+{self.hdr.winfo_rooty() + int(y1) + 6}")
        def lost(e=None):
            try: f = self.root.focus_get()
            except (KeyError, tk.TclError): f = None
            if self.credit_card is w and f is not w: self.show_credit_card()      # clicked somewhere else -> close
        w.bind("<FocusOut>", lambda e: self.root.after(150, lost))
        w.focus_force()

    def status_glyphs(self, t):
        """(icon, colour, small label, hover text) for: listening state, speech model, latency, game"""
        key = pretty_combo(self.cfg.get("ptt_key")) or "-"; lock = pretty_combo(self.cfg.get("toggle_key")) or "the lock button"
        if not self.cfg.get("ai_on", True): st = ("offline", DIM, "AI OFF", "Speech AI is OFFLINE - uses no RAM / graphics memory\nclick to bring it online")
        elif self.loading: st = ("spinner", ORANGE, "LOADING", "Speech AI is coming online…")
        elif self.model is None: st = ("offline", RED, "OFFLINE", "Speech AI could not start - see the log\nclick to switch it off")
        elif not self.listening: st = ("locked", DIM, "LOCKED", f"Listening is LOCKED\npress {lock} to unlock")
        elif self.cfg["mode"] == "ptt":
            st = ("mic", GREEN if self.ptt_down else ORANGE, "TALK" if self.ptt_down else "PTT",
                  "Transmitting - speak now" if self.ptt_down else f"Push-to-talk ready\nhold {key} and speak")
        else: st = ("listen", lerp(RED_DIM, GREEN, 0.6 + 0.4 * math.sin(t * 4)), "LIVE", "Always listening\njust say a command")
        md = self.model_desc if self.model is not None else "--"; name, _, dev = md.partition("·")
        short = {"large-v3-turbo": "TURBO", "distil-small.en": "D-SMALL", "distil-medium.en": "D-MED", "distil-large-v3": "D-LARGE",
                 "small.en": "SMALL", "base.en": "BASE", "tiny.en": "TINY", "medium.en": "MEDIUM"}.get(name, name.upper()[:7])
        mo = ("gpu" if dev == "gpu" else "cpu", ORANGE if dev == "gpu" else RED, short,
              f"Speech AI: {name} on the {'graphics card (GPU)' if dev == 'gpu' else 'processor (CPU)'}" + ("" if dev == "gpu" else "\n⚙ OPTIONS → GPU BOOST makes it faster + more accurate"))
        ms = self.latency * 1000
        la = ("gauge", GREEN if ms < 400 else ORANGE if ms < 900 else RED, f"{ms:.0f}ms" if ms else "--",
              f"Last command took {ms:.0f} ms from the end of your words to the keys\ngreen < 400 ms · orange < 900 ms")
        need = (self.profile or {}).get("process") or ""; front = need and self.fg_exe == need
        ga = ("gamepad", GREEN if front else (DIM if need else RED_DIM), "IN GAME" if front else ("WAITING" if need else "ANY"),
              (f"Game: {need}\n" + ("in front - commands fire" if front else "not in front - commands wait")) if need else "No game set - commands work in any program\n(✎ PROFILE → GAME .EXE)")
        if self.cfg.get("ai_on", True) and self.model is not None and not self.loading:
            st = (st[0], st[1], st[2], st[3] + "\nclick: speech AI OFFLINE (frees RAM / graphics memory)")
        return [st, mo, la, ga]

    def draw_status(self, c, right, t):
        """header glyphs instead of text: state · model · latency · game (hover for details)"""
        self.glyph_boxes = []; x = right; self.ai_box = None
        for k, (icon, col, label, tip) in reversed(list(enumerate(self.status_glyphs(t)))):
            wdt = 60; x0 = x - wdt
            hov = getattr(self, "glyph_hover", None) == tip
            c.create_polygon(x0, 6, x - 7, 6, x - 1, 12, x - 1, 54, x0 + 6, 54, x0, 48, fill="#1C0909" if hov else "#0B0C10",
                             outline=lerp(RED_DIM, col, 0.6 if hov else 0.35))
            draw_icon(c, icon, x0 + wdt / 2 - 13, 9, 26, col, t)
            c.create_text(x0 + wdt / 2, 46, text=label, fill=col if col != DIM else "#8A8F9C", font=(MONO, 7, "bold"))
            self.glyph_boxes.append((x0, 6, x, 54, tip))
            if k == 0: self.ai_box = (x0, 6, x, 54)
            x = x0 - 6
        self.draw_zap(c)

    def draw_zap(self, c):
        """electric burst from the speech-AI glyph: lightning arcs crackle out of it for ~0.9 s when the AI comes online"""
        age = time.time() - getattr(self, "zap_at", 0.0)
        if age > 0.9 or not self.ai_box: return
        x0, y0, x1, y1 = self.ai_box; cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; k = 1 - age / 0.9
        c.create_polygon(x0, y0, x1 - 7, y0, x1 - 1, y0 + 6, x1 - 1, y1, x0 + 6, y1, x0, y1 - 6, fill="", outline=lerp(BG, WHITE, k), width=2)
        for _ in range(3 + int(4 * k)):                 # jagged bolts in random directions, longer at the start
            ang = random.uniform(0, 2 * math.pi); L = random.uniform(30, 95) * (0.4 + 0.6 * k)
            pts, px, py = [cx, cy], cx, cy
            for q in range(1, 7):
                d = L * q / 6; j = random.uniform(-9, 9)
                px, py = cx + d * math.cos(ang) - j * math.sin(ang), cy + d * math.sin(ang) * 0.55 + j * math.cos(ang) * 0.6
                pts += [px, max(2, min(c.winfo_height() - 2, py))]
            col = lerp(ORANGE, WHITE, random.random() * k)
            c.create_line(*pts, fill=lerp(BG, RED, 0.35 + 0.4 * k), width=5)                 # glow
            c.create_line(*pts, fill=lerp(BG, col, 0.6 + 0.4 * k), width=2 if random.random() < 0.5 else 1)
            c.create_oval(px - 2, pts[-1] - 2, px + 2, pts[-1] + 2, fill=lerp(BG, WHITE, k), outline="")

    def draw_logo(self, c, cx, cy, r, t, on):
        """the Skynet eye: a machine eye in a rotating ring that always looks at the mouse pointer (anywhere on screen),
        blinks with metal shutters now and then, glows orange when a command fires and half-closes when listening is locked"""
        now = time.time(); strike = max(0.0, 1.0 - (now - getattr(self, "fired_at", 0.0)) / 0.6)
        # --- where to look
        try:
            px, py = c.winfo_pointerxy(); gx, gy = c.winfo_rootx() + cx, c.winfo_rooty() + cy
            dx, dy = px - gx, py - gy; d = math.hypot(dx, dy) or 1.0
            k = min(1.0, d / 260) * r * 0.3; tx, ty = dx / d * k, dy / d * k
        except tk.TclError:
            tx = ty = 0.0
        watch = self.autogame_on()
        if not watch: tx = ty = 0.0                     # closed eye looks nowhere
        ox, oy = getattr(self, "eye_off", (0.0, 0.0)); ox += (tx - ox) * 0.4; oy += (ty - oy) * 0.4; self.eye_off = (ox, oy)
        # --- blink (shutters) every 3-8 s
        if now > getattr(self, "blink_at", 0.0) + 0.22: self.blink_at = now + random.uniform(3, 8)
        bt = now - self.blink_at; blink = math.sin(bt / 0.22 * math.pi) if 0 <= bt <= 0.22 else 0.0
        want = 1.0 if not watch else (0.0 if on else 0.42)     # closed = auto-detect game is off
        el = getattr(self, "eye_lid", want); el += max(-0.16, min(0.16, want - el)); self.eye_lid = el   # mechanical open / close
        lid = max(blink if el < 0.5 else 0.0, el)      # 0 open .. 1 shut
        # --- ring
        if strike > 0:
            rr = r * (1.0 + 0.6 * (1 - strike)); c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=lerp(BG, ORANGE, strike), width=2)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#07080B", outline=lerp(RED_DIM, RED, 0.55 + 0.45 * math.sin(t * 3)) if on else RED_DIM, width=2)
        spin = t * (30 if on else 6)
        for q in range(24):
            a = math.radians(q * 15 + spin); major = q % 6 == 0; r1 = r * (0.78 if major else 0.84)
            c.create_line(cx + r1 * math.cos(a), cy + r1 * math.sin(a), cx + r * 0.92 * math.cos(a), cy + r * 0.92 * math.sin(a),
                          fill=(RED if on else RED_DIM) if major else lerp(BG, RED_DIM, 0.8), width=2 if major else 1)
        # --- iris: glowing rings, hot core, black pupil, white glint
        hot = ORANGE if strike > 0 else RED
        ex, ey, ir = cx + ox, cy + oy, r * 0.44
        glow = 0.75 + 0.25 * math.sin(t * 5) if on else 0.35
        for k, (f, a) in enumerate(((1.45, 0.12), (1.22, 0.25), (1.0, 0.55), (0.78, 0.85))):
            rr = ir * f; c.create_oval(ex - rr, ey - rr, ex + rr, ey + rr, fill=lerp("#07080B", hot, a * glow), outline="")
        c.create_oval(ex - ir, ey - ir, ex + ir, ey + ir, outline=lerp(RED_DIM, hot, glow), width=1)
        pr = ir * (0.36 + 0.12 * strike) * (1.15 if not on else 1.0)
        c.create_oval(ex - pr, ey - pr, ex + pr, ey + pr, fill="#050506", outline=lerp("#050506", hot, 0.6))
        g = ir * 0.16; c.create_oval(ex - ir * 0.42 - g, ey - ir * 0.42 - g, ex - ir * 0.42 + g, ey - ir * 0.42 + g, fill=lerp(hot, WHITE, 0.7), outline="")
        # --- shutters (top + bottom lid plates meeting in the middle)
        if lid > 0.01:
            s = r * 0.7; cut = s * (1 - lid)                      # lids = circle segments cut at +-cut from the centre
            ha = math.acos(max(-1.0, min(1.0, cut / s)))
            for sgn in (-1, 1):
                pts = []
                for q in range(17):
                    a = -ha + 2 * ha * q / 16
                    pts += [cx + s * math.sin(a), cy + sgn * s * math.cos(a)]
                c.create_polygon(*pts, fill="#101218", outline=RED_DIM)
                c.create_line(cx - s * math.sin(ha), cy + sgn * cut, cx + s * math.sin(ha), cy + sgn * cut, fill=lerp(RED_DIM, RED, 0.5), width=1)
        if lid > 0.97:                                   # shut: a faint red standby slit, like a sleeping cyborg
            s2 = r * 0.6; pu = 0.5 + 0.5 * math.sin(t * 2.2)
            c.create_line(cx - s2, cy, cx + s2, cy, fill=lerp(RED_DIM, RED, 0.25 + 0.45 * pu), width=2)
            c.create_line(cx - s2 * 0.35, cy, cx + s2 * 0.35, cy, fill=lerp(RED, ORANGE, pu * 0.5), width=2)
        # re-draw the socket rim on top so the lid plates stay inside the eye
        c.create_oval(cx - r * 0.76, cy - r * 0.76, cx + r * 0.76, cy + r * 0.76, outline="#07080B", width=max(2, r * 0.2))
        c.create_oval(cx - r * 0.66, cy - r * 0.66, cx + r * 0.66, cy + r * 0.66, outline=lerp(RED_DIM, hot, 0.35), width=1)
        # lock-on brackets
        b, a = r * 0.98, r * 0.2; bc = ORANGE if on else lerp(BG, ORANGE, 0.45)
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            px, py = cx + sx * b, cy + sy * b
            c.create_line(px, py, px - sx * a, py, fill=bc, width=2); c.create_line(px, py, px, py - sy * a, fill=bc, width=2)


    def pump(self):
        try:
            while True:
                m = self.ui_q.get_nowait()
                if m[0] == "log":
                    _, txt, tag, link = m; self.logv.add(time.strftime("%H:%M:%S"), txt, tag, link)
                elif m[0] == "heard":
                    _, text, name, score = m
                    if name: self.heard.config(text=f"“{text}”  ▸  {name.upper()}  {score * 100:.0f}%", fg=GREEN if "(" not in name else ORANGE)
                    else: self.heard.config(text=f"“{text}”  ▸  no match", fg=DIM)
                elif m[0] == "toggle": self.toggle_listen()
                elif m[0] == "ptt": self.play(("ptt_on" if m[1] else "ptt_off") if self.listening else ("denied" if m[1] else "off"), "ptt")
                elif m[0] == "learn": self.learn_game(m[1], m[2])
                elif m[0] == "fg": self.update_pause(); self.on_foreground(m[1])
                elif m[0] == "status": self.status_lbl.config(text="▸ " + m[1])
        except queue.Empty:
            pass
        self.root.after(40, self.pump)

    def log(self, text, tag="dim", link=None): self.ui_q.put(("log", text, tag, link))

    def open_link(self, link):
        """click on a log line: open that command's editor, or start a new command from what was heard"""
        if link[0] == "cmd":
            _, prof, name = link
            if prof in self.profiles and self.profiles[prof] is not self.profile: self.select_profile(prof)
            i = next((k for k, c in enumerate(self.profile["commands"]) if c.get("name") == name), None)
            if i is None: self.status(f"'{name}' is not in this profile any more"); return
            self.search.set(""); self.fill_tree(); self.tree.select(i); self.edit_command(i=i)
        elif link[0] == "new":
            self.add_command(link[1])
        elif link[0] == "teach":            # add what Whisper heard as an extra phrase of the closest command
            _, prof, name, heard = link
            if prof in self.profiles and self.profiles[prof] is not self.profile: self.select_profile(prof)
            i = next((k for k, c in enumerate(self.profile["commands"]) if c.get("name") == name), None)
            if i is None: self.add_command(heard); return
            self.search.set(""); self.fill_tree(); self.tree.select(i)
            c = dict(self.profile["commands"][i]); c["phrases"] = list(c.get("phrases", [])) + [heard]
            def done(new): self.profile["commands"][i] = new; self.save_profile(); self.fill_tree(); self.tree.select(i); self.log(f"taught: “{heard}” now means {new['name']}", "ok", ("cmd", self.profile["name"], new["name"]))
            CommandDialog(self, c, done); self.status(f"“{heard}” was added to {name}'s phrases - press SAVE to keep it")
    def status(self, text): self.ui_q.put(("status", text))

    def update_listen_btn(self):
        self.listen_btn.config(text="■ LOCK LISTENING" if self.listening else "▶ UNLOCK LISTENING", fg=ORANGE if self.listening else GREEN)

    def toggle_listen(self):
        self.listening = not self.listening; self.cfg["listening"] = self.listening; self.update_listen_btn(); self.save_settings()
        self.log("listening UNLOCKED - commands are live" if self.listening else "listening LOCKED - nothing you say will fire", "sys")
        self.play("unlocked" if self.listening else "locked", "ptt")
        self.speak("Listening online." if self.listening else "Listening offline.", confirm=True, delay=0.35)

    def apply_settings(self, new):
        old = dict(self.cfg); self.cfg.update(new); self.save_settings()
        self.root.attributes("-topmost", bool(self.cfg["ontop"])); self.update_info(); self.sfx.set_volume(self.cfg.get("volume", 70))
        if new["mic"] != old["mic"]: self.start_capture(); self.mic_var.set(new["mic"] or DEFAULT_MIC)
        set_priority(self.cfg.get("game_first", True)); self.update_pause()
        if new.get("auto_switch") != old.get("auto_switch") or (new.get("auto_switch") and not self.autogame_on()): self.set_autogame(bool(new.get("auto_switch")))
        self.log("settings saved" + (" - reloading speech model" if self.want_key() != self.model_key else ""), "sys")

    def save_settings(self):
        try:
            if getattr(self, "maxed", False) and self.normal_geo: self.cfg["geometry"] = self.normal_geo
            elif self.root.state() == "normal": self.cfg["geometry"] = self.root.geometry()
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f: json.dump(self.cfg, f, ensure_ascii=False, indent=1)
        except Exception: pass

    def make_shortcut(self):
        if not WIN: return
        lnk = os.path.join(ROOT if PORTABLE else HERE, "Skynet Command.lnk")
        moved = PORTABLE and self.cfg.get("lnk_root") not in (None, ROOT)            # folder was moved -> old shortcut points nowhere
        if moved or (self.cfg.get("icon_ver") != 3 and self.icon.endswith("skynet_command.ico")):   # new eye icon -> rebuild shortcut
            self.cfg["icon_ver"] = 3; self.cfg["lnk_root"] = ROOT; self.save_settings()
            try: os.remove(lnk)
            except Exception: pass
            try: subprocess.Popen(["ie4uinit.exe", "-show"], creationflags=0x08000000)   # refresh Windows' icon cache
            except Exception: pass
        if os.path.exists(lnk): return
        self.cfg["lnk_root"] = ROOT
        vpy = sys.executable.replace("python.exe", "pythonw.exe")
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath='{vpy}';"
              f"$s.Arguments='\"{os.path.abspath(__file__)}\"';$s.WorkingDirectory='{HERE}';"
              + (f"$s.IconLocation='{self.icon},0';" if self.icon else "") + "$s.Description='Skynet Command';$s.Save()")
        try: subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], creationflags=0x08000000)
        except Exception: pass

    def quit(self):
        self.exec.abort(); self.save_settings()
        if self.capture: self.capture.running = False
        if self.voice: self.voice.stop()
        self.root.destroy()


if __name__ == "__main__":
    try:
        App().root.mainloop()
    except Exception:
        traceback.print_exc()
