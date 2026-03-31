#!/usr/bin/env python3
"""
WanGP Timeline Editor  v1.0
────────────────────────────────────────────────────────────────────────────────
Prompt-driven video segment timeline editor for WanGP AI video generation.
Kdenlive-inspired dark UI built with Tkinter.

Dependencies (pip install):
    Required : tkinter  (stdlib)
    Audio    : pygame                   (pip install pygame)
    Images   : Pillow                   (pip install Pillow)
    API      : requests                 (pip install requests)
    Frames   : ffmpeg must be on PATH   (https://ffmpeg.org)

Usage:
    python wangp_timeline_editor.py
────────────────────────────────────────────────────────────────────────────────
"""

import os, sys, json, math, wave, time, uuid, struct, copy, threading, subprocess
import threading
import time
import dataclasses
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Any
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser

# ── Optional dependencies ─────────────────────────────────────────────────────
try:
    import pygame
    pygame.mixer.pre_init(44100, -16, 2, 2048)
    pygame.mixer.init()
    PYGAME_OK = True
except Exception:
    PYGAME_OK = False

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import requests as _requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

# ── App metadata ──────────────────────────────────────────────────────────────
APP_NAME    = "WanGP Timeline Editor"
APP_VERSION = "1.0.0"
FILE_EXT    = ".wgp"

# ── Layout ────────────────────────────────────────────────────────────────────
RULER_H     = 30
TRACK_H     = 76
HEADER_W    = 148
HANDLE_W    = 9        # resize handle width px
SNAP_S      = 0.25     # snap grid seconds
MIN_BLOCK   = 0.5      # minimum block duration seconds
DEF_ZOOM    = 90       # px / second
MIN_ZOOM    = 0.5
MAX_ZOOM    = 700
WANGP_SAFE  = 55.0     # split video threshold seconds

# ── Tracks ────────────────────────────────────────────────────────────────────
#TRACK_AUDIO   = 0
#TRACK_PROMPTS = 1
#TRACK_GLOBAL  = 2
#TRACK_COUNT   = 3
#
#TRACK_DEFS = [
#    {"id": "audio",   "name": "Audio",          "locked": True},
#    {"id": "prompts", "name": "Prompt Segments", "locked": False},
#    {"id": "global",  "name": "Global Modifiers","locked": False},
#]
# ── Tracks (reordered: Global top, Prompts middle, Audio bottom) [For more natural feel] ─────────
TRACK_GLOBAL  = 0
TRACK_PROMPTS = 1
TRACK_AUDIO   = 2
TRACK_COUNT   = 3

TRACK_DEFS = [
    {"id": "global",  "name": "Global Modifiers","locked": False},
    {"id": "prompts", "name": "Prompt Segments", "locked": False},
    {"id": "audio",   "name": "Audio",          "locked": True},
]
# ── Color palette ─────────────────────────────────────────────────────────────
BG          = "#1b1c2a"
PANEL_BG    = "#171825"
HEADER_BG   = "#111220"
RULER_BG    = "#0e0f1c"
RULER_FG    = "#8888bb"
TRACK_EVEN  = "#1f2035"
TRACK_ODD   = "#1a1b2f"
GRID_MINOR  = "#272840"
GRID_MAJOR  = "#343558"
FG          = "#ccccdd"
FG_DIM      = "#5555aa"
PLAYHEAD_C  = "#ff3344"
SEL_BORDER  = "#ffcc33"
WAVEFORM_C  = "#2299ee"
WAVE_BG     = "#0f1825"
BLOCK_FG    = "#ffffff"
ACCENT      = "#4466ff"
BTN_BG      = "#272840"
BTN_HOV     = "#353658"
SEP         = "#252638"
ENTRY_BG    = "#1f2038"

BLOCK_PALETTE = [
    "#1e5a9e", "#8b2d8b", "#1f8055", "#994315",
    "#5a2090", "#156080", "#7c2255", "#2a6040",
    "#6b4010", "#10506b", "#6b1010", "#106b40",
]

###############################################################################
# DATA MODEL
###############################################################################

@dataclass
class PromptBlock:
    bid:              str
    start:            float
    duration:         float
    prompt:           str   = ""
    negative_prompt:  str   = ""
    label:            str   = ""
    color:            str   = "#1e5a9e"
    variable_overrides: Dict[str, str] = field(default_factory=dict)
    steps:  int   = 30
    cfg:    float = 7.0
    seed:   int   = -1

    @property
    def end(self) -> float:
        return self.start + self.duration

    def resolve_prompt(self, variables: Dict[str, str]) -> str:
        merged = {**variables, **self.variable_overrides}
        text = self.prompt
        for k, v in merged.items():
            text = text.replace(f"{{{k}}}", v)
        return text


@dataclass
class GlobalBlock:
    bid:      str
    start:    float
    duration: float
    prompt:   str  = ""
    label:    str  = ""
    color:    str  = "#5a2090"
    variable_overrides: Dict[str, str] = field(default_factory=dict)

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class Project:
    name:           str  = "Untitled"
    audio_file:     str  = ""
    audio_duration: float = 0.0
    video_description: str = ""    # <--- User Provided story ideas for ollama integration
    global_vars:    Dict[str, str] = field(default_factory=dict)
    prompt_blocks:  List[PromptBlock]  = field(default_factory=list)
    global_blocks:  List[GlobalBlock]  = field(default_factory=list)
    wangp_url:      str  = "http://192.168.1.232:9876"
    wangp_api_type: str  = "gradio"    # "gradio" | "rest"
    output_dir:     str  = "output"
    default_width:  int  = 832
    default_height: int  = 480
    default_fps:    int  = 16
    default_steps:  int  = 8
    default_cfg:    float = 1.0
    ollama_url:     str  = "http://127.0.0.1:11434"
    ollama_model:   str  = "llama3.2"

    def sorted_prompt_blocks(self) -> List[PromptBlock]:
        return sorted(self.prompt_blocks, key=lambda b: b.start)

    def sorted_global_blocks(self) -> List[GlobalBlock]:
        return sorted(self.global_blocks, key=lambda b: b.start)

    def globals_at(self, t: float) -> List[GlobalBlock]:
        return [b for b in self.global_blocks if b.start <= t < b.end]


###############################################################################
# SERIALIZER
###############################################################################

class ProjectSerializer:
    VERSION = "1.0"

    @classmethod
    def save(cls, project: Project, path: str):
        import dataclasses
        raw = dataclasses.asdict(project)
        raw["_version"] = cls.VERSION
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        p = Project(
            name           = data.get("name", "Untitled"),
            audio_file     = data.get("audio_file", ""),
            audio_duration = data.get("audio_duration", 0.0),
            global_vars    = data.get("global_vars", {}),
            wangp_url      = data.get("wangp_url", "http://127.0.0.1:7860"),
            wangp_api_type = data.get("wangp_api_type", "gradio"),
            output_dir     = data.get("output_dir", "output"),
            default_width  = data.get("default_width", 1280),
            default_height = data.get("default_height", 720),
            default_fps    = data.get("default_fps", 24),
            default_steps  = data.get("default_steps", 30),
            default_cfg    = data.get("default_cfg", 7.0),
        )
        for bd in data.get("prompt_blocks", []):
            p.prompt_blocks.append(PromptBlock(**bd))
        for bd in data.get("global_blocks", []):
            p.global_blocks.append(GlobalBlock(**bd))
        return p


###############################################################################
# AUDIO PLAYER
###############################################################################

class AudioPlayer:
    def __init__(self):
        self._path       = None
        self._duration   = 0.0
        self._playing    = False
        self._start_pos  = 0.0   # audio position when play() was called
        self._start_wall = None  # wall-clock time when play() was called

    # ── Public API ────────────────────────────────────────────────────────────
    def load(self, path: str) -> float:
        self.stop()
        self._path     = path
        self._duration = self._probe_duration(path)
        if PYGAME_OK:
            try:
                pygame.mixer.music.load(path)
            except Exception as e:
                print(f"[Audio] pygame load error: {e}")
        return self._duration

    def play(self, from_pos: float = None):
        if from_pos is not None:
            self._start_pos = max(0.0, min(from_pos, self._duration))
        if PYGAME_OK and self._path:
            try:
                pygame.mixer.music.play(start=self._start_pos)
            except Exception as e:
                print(f"[Audio] play error: {e}")
        self._start_wall = time.time()
        self._playing    = True

    def pause(self):
        if not self._playing:
            return
        self._start_pos = self.position
        if PYGAME_OK:
            try: pygame.mixer.music.pause()
            except: pass
        self._playing    = False
        self._start_wall = None

    def stop(self):
        if PYGAME_OK:
            try: pygame.mixer.music.stop()
            except: pass
        self._playing    = False
        self._start_pos  = 0.0
        self._start_wall = None

    def seek(self, t: float):
        t = max(0.0, min(t, self._duration))
        was = self._playing
        self.stop()
        self._start_pos = t
        if was:
            self.play()

    @property
    def position(self) -> float:
        if self._playing and self._start_wall is not None:
            return min(self._start_pos + (time.time() - self._start_wall),
                       self._duration)
        return self._start_pos

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def is_playing(self) -> bool:
        return self._playing

    # ── Internal ──────────────────────────────────────────────────────────────
    @staticmethod
    def _probe_duration(path: str) -> float:
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=10
            )
            return float(r.stdout.strip())
        except Exception:
            pass
        if path.lower().endswith(".wav"):
            try:
                with wave.open(path, "r") as wf:
                    return wf.getnframes() / wf.getframerate()
            except Exception:
                pass
        return 60.0


###############################################################################
# WAVEFORM DATA
###############################################################################

class WaveformData:
    """Computes audio peak data for waveform rendering."""

    def __init__(self):
        self.peaks: List[Tuple[float, float]] = []
        self.duration: float = 0.0
        self.ready = False

    def load_async(self, path: str, callback=None, num_peaks: int = 3000):
        """Load in background thread; call callback() when done."""
        def _work():
            self._compute(path, num_peaks)
            if callback:
                callback()
        threading.Thread(target=_work, daemon=True).start()

    def _compute(self, path: str, num_peaks: int):
        self.ready = False
        wav_path = path
        tmp = None

        # Convert non-WAV to temp WAV via ffmpeg
        if not path.lower().endswith(".wav"):
            tmp = path + "_wf_tmp.wav"
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", path,
                     "-ac", "1", "-ar", "22050", "-f", "wav", tmp],
                    capture_output=True, timeout=60
                )
                wav_path = tmp
            except Exception as e:
                print(f"[Waveform] ffmpeg error: {e}"); return

        try:
            with wave.open(wav_path, "r") as wf:
                n_ch   = wf.getnchannels()
                sw     = wf.getsampwidth()
                rate   = wf.getframerate()
                nfr    = wf.getnframes()
                self.duration = nfr / rate
                raw    = wf.readframes(nfr)

            if sw == 2:
                samples = list(struct.unpack(f"<{len(raw)//2}h", raw))
                norm = 32768.0
            elif sw == 1:
                samples = [b - 128 for b in raw]
                norm = 128.0
            else:
                return

            # Mix to mono
            if n_ch > 1:
                samples = samples[::n_ch]

            n     = len(samples)
            chunk = max(1, n // num_peaks)
            peaks = []
            for i in range(num_peaks):
                sl = samples[i*chunk:(i+1)*chunk]
                if sl:
                    peaks.append((min(sl)/norm, max(sl)/norm))
                else:
                    peaks.append((0.0, 0.0))
            self.peaks = peaks
            self.ready = True
        except Exception as e:
            print(f"[Waveform] error: {e}")
        finally:
            if tmp and os.path.exists(tmp):
                try: os.remove(tmp)
                except: pass

    def peak_range(self, t0: float, t1: float) -> Tuple[float, float]:
        if not self.ready or not self.peaks or self.duration <= 0:
            return (0.0, 0.0)
        n  = len(self.peaks)
        i0 = max(0, int(t0 / self.duration * n))
        i1 = min(n-1, int(t1 / self.duration * n))
        sl = self.peaks[i0:i1+1] or [self.peaks[i0]]
        return (min(p[0] for p in sl), max(p[1] for p in sl))


###############################################################################
# TIMELINE CANVAS
###############################################################################

class TimelineCanvas(tk.Frame):
    """
    The main timeline widget.
    Tracks: Audio (waveform, locked) | Prompts | Global
    """

    def __init__(self, parent, app: "App"):
        super().__init__(parent, bg=BG)
        self.app       = app
        self.zoom      = DEF_ZOOM    # px / second
        self._scroll   = 0           # horizontal scroll offset in pixels
        self.selected  = None        # (track_idx, block) or None
        self._drag     = None        # active drag state
        self._pan_x    = None        # middle-mouse pan origin
        self._color_i  = 0
        self._waveform = WaveformData()
        self._tick_id  = None

        self._build()
        self.after(100, self.redraw)

    # ─────────────────────────────────────────── Build ───────────────────────
    def _build(self):
        style = ttk.Style()
        style.configure("TScrollbar", background=BTN_BG, troughcolor=BG,
                         arrowcolor=FG, bordercolor=SEP)

        # ── Top: ruler row ────────────────────────────────────────────────
        ruler_row = tk.Frame(self, bg=RULER_BG)
        ruler_row.pack(fill=tk.X)
        tk.Frame(ruler_row, width=HEADER_W, bg=RULER_BG).pack(side=tk.LEFT)
        self.ruler = tk.Canvas(ruler_row, height=RULER_H, bg=RULER_BG,
                                highlightthickness=0)
        self.ruler.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ── Middle: header + track canvas ─────────────────────────────────
        mid = tk.Frame(self, bg=BG)
        mid.pack(fill=tk.BOTH, expand=True)

        self.headers = tk.Canvas(mid, width=HEADER_W, bg=HEADER_BG,
                                  highlightthickness=0)
        self.headers.pack(side=tk.LEFT, fill=tk.Y)

        self.canvas = tk.Canvas(mid, bg=TRACK_EVEN, highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ── Bottom: horizontal scrollbar ──────────────────────────────────
        self.hbar = ttk.Scrollbar(self, orient=tk.HORIZONTAL,
                                   command=self._on_hscroll)
        self.hbar.pack(fill=tk.X)

        # ── Events ────────────────────────────────────────────────────────
        self.canvas.bind("<Configure>",      lambda e: self.redraw())
        self.canvas.bind("<ButtonPress-1>",  self._on_press)
        self.canvas.bind("<B1-Motion>",      self._on_motion)
        self.canvas.bind("<ButtonRelease-1>",self._on_release)
        self.canvas.bind("<Motion>",         self._on_hover)
        self.canvas.bind("<ButtonPress-3>",  self._on_rclick)
        self.canvas.bind("<Double-Button-1>",self._on_dblclick)
        self.canvas.bind("<MouseWheel>",     self._on_wheel)
        self.canvas.bind("<Button-4>",       self._on_wheel)
        self.canvas.bind("<Button-5>",       self._on_wheel)
        self.canvas.bind("<ButtonPress-2>",  self._pan_start)
        self.canvas.bind("<B2-Motion>",      self._pan_drag)
        self.canvas.bind("<Delete>",         lambda e: self.delete_selected())
        self.canvas.bind("<BackSpace>",      lambda e: self.delete_selected())

        self.ruler.bind("<ButtonPress-1>",   self._ruler_click)
        self.ruler.bind("<B1-Motion>",       self._ruler_drag)

    # ─────────────────────────────────────────── Coordinates ─────────────────
    def t2x(self, t: float) -> float:
        return t * self.zoom - self._scroll

    def x2t(self, x: float) -> float:
        return (x + self._scroll) / self.zoom

    def track_y(self, idx: int) -> int:
        return idx * TRACK_H

    def track_at(self, y: int) -> int:
        return max(0, min(int(y // TRACK_H), TRACK_COUNT - 1))

    def snap(self, t: float) -> float:
        return round(t / SNAP_S) * SNAP_S

    def _cw(self) -> int:
        return max(1, self.canvas.winfo_width())

    def _ch(self) -> int:
        return TRACK_H * TRACK_COUNT

    def _total_px(self) -> int:
        dur = max(self.app.project.audio_duration, 60.0)
        return int(dur * self.zoom) + 400

    # ─────────────────────────────────────────── Draw ────────────────────────
    def redraw(self):
        self.canvas.delete("all")
        self.ruler.delete("all")
        self.headers.delete("all")
        self._draw_track_bgs()
        self._draw_grid()
        self._draw_waveform()
        self._draw_blocks()
        self._draw_playhead()
        self._draw_ruler()
        self._draw_headers()
        self._update_scrollbar()

    def _draw_track_bgs(self):
        w = self._cw()
        for i in range(TRACK_COUNT):
            y  = self.track_y(i)
            bg = TRACK_EVEN if i % 2 == 0 else TRACK_ODD
            self.canvas.create_rectangle(0, y, w, y + TRACK_H,
                                          fill=bg, outline="")
            self.canvas.create_line(0, y + TRACK_H - 1,
                                     w, y + TRACK_H - 1, fill=SEP)

    def _draw_grid(self):
        h = self._ch()
        w = self._cw()
        ivs = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60]
        iv  = ivs[-1]
        for v in ivs:
            if v * self.zoom >= 50:
                iv = v; break

        t  = math.floor(self.x2t(0) / iv) * iv
        mt = self.x2t(w) + iv
        while t <= mt:
            x  = self.t2x(t)
            is_sec = (iv >= 1) or (abs(t - round(t)) < 0.001)
            col = GRID_MAJOR if is_sec else GRID_MINOR
            self.canvas.create_line(x, 0, x, h, fill=col)
            t += iv

    def _draw_waveform(self):
        wf = self._waveform
        if not wf.ready:
            return
        y0  = self.track_y(TRACK_AUDIO)
        y1  = y0 + TRACK_H
        mid = (y0 + y1) // 2
        half = (TRACK_H - 14) // 2
        w   = self._cw()
        self.canvas.create_rectangle(0, y0 + 2, w, y1 - 2,
                                      fill=WAVE_BG, outline="")
        for px in range(0, w, 1):
            t0 = self.x2t(px)
            t1 = self.x2t(px + 1)
            if t1 > wf.duration:
                break
            lo, hi = wf.peak_range(t0, t1)
            py0 = mid - int(hi * half)
            py1 = mid - int(lo * half)
            if py1 <= py0:
                py1 = py0 + 1
            self.canvas.create_line(px, py0, px, py1,
                                     fill=WAVEFORM_C)

    def _draw_blocks(self):
        proj = self.app.project
        for blk in proj.prompt_blocks:
            self._draw_one_block(blk, TRACK_PROMPTS)
        for blk in proj.global_blocks:
            self._draw_one_block(blk, TRACK_GLOBAL)

    def _draw_one_block(self, blk, ti: int):
        x1 = self.t2x(blk.start)
        x2 = self.t2x(blk.end)
        y1 = self.track_y(ti) + 5
        y2 = self.track_y(ti) + TRACK_H - 5

        if x2 < 0 or x1 > self._cw():
            return  # off-screen

        sel = (self.selected is not None and
               self.selected[1].bid == blk.bid)
        border = SEL_BORDER if sel else _darken(blk.color, 0.6)
        bw     = 2 if sel else 1

        # Shadow
        self.canvas.create_rectangle(x1+2, y1+2, x2+2, y2+2,
                                      fill="#000000", outline="")
        # Body
        self.canvas.create_rectangle(x1, y1, x2, y2,
                                      fill=blk.color, outline=border,
                                      width=bw,
                                      tags=("block", f"bid:{blk.bid}",
                                            f"ti:{ti}"))
        # Label
        visible_w = min(x2, self._cw()) - max(x1, 0)
        if visible_w > 24:
            label = blk.label or blk.prompt or "(empty)"
            if len(label) > 40:
                label = label[:37] + "…"
            lx = max(x1 + 6, 4)
            self.canvas.create_text(
                lx, (y1 + y2) // 2, text=label,
                fill=BLOCK_FG, anchor=tk.W,
                font=("Helvetica", 9),
                tags=("block", f"bid:{blk.bid}"))

        # Duration badge
        if visible_w > 60:
            self.canvas.create_text(
                min(x2 - 6, self._cw() - 4), y2 - 3,
                text=f"{blk.duration:.1f}s",
                fill="#ffffff", anchor=tk.SE,
                font=("Helvetica", 7),
                tags=("block",))

        # Resize handles
        hw = HANDLE_W
        if x2 - x1 > hw * 3:
            for hx1, hx2, tag in [
                (x1, x1 + hw, "hl"),
                (x2 - hw, x2, "hr"),
            ]:
                self.canvas.create_rectangle(
                    hx1, y1, hx2, y2,
                    fill="#ffffff", outline="",
                    tags=(tag, f"bid:{blk.bid}", f"ti:{ti}"))

    def _draw_playhead(self):
        t = self.app.player.position
        x = self.t2x(t)
        h = self._ch()
        if -2 <= x <= self._cw() + 2:
            self.canvas.create_line(x, 0, x, h, fill=PLAYHEAD_C,
                                     width=2, tags="ph")
            self.canvas.create_polygon(
                x - 7, 0, x + 7, 0, x, 11,
                fill=PLAYHEAD_C, tags="ph")

    def _draw_ruler(self):
        w = self.ruler.winfo_width() or 800
        h = RULER_H
        ivs = [0.25, 0.5, 1, 2, 5, 10, 15, 30, 60]
        iv = ivs[-1]
        for v in ivs:
            if v * self.zoom >= 70:
                iv = v; break

        t  = math.floor(self.x2t(0) / iv) * iv
        mt = self.x2t(w) + iv
        while t <= mt:
            x      = self.t2x(t)
            is_sec = (iv >= 1) or abs(t - round(t)) < 0.001
            tick   = 12 if is_sec else 5
            self.ruler.create_line(x, h, x, h - tick, fill=RULER_FG)
            if is_sec and -5 < x < w + 5:
                m, s = divmod(int(round(t)), 60)
                lbl  = f"{m}:{s:02d}" if m else f"{int(round(t))}s"
                self.ruler.create_text(x + 3, h // 2 - 2, text=lbl,
                                        fill=RULER_FG, anchor=tk.W,
                                        font=("Helvetica", 8))
            t += iv

        # Playhead marker on ruler
        ph_x = self.t2x(self.app.player.position)
        self.ruler.create_polygon(ph_x - 5, 2, ph_x + 5, 2, ph_x, 12,
                                   fill=PLAYHEAD_C)

    def _draw_headers(self):
        w = HEADER_W
        for i, td in enumerate(TRACK_DEFS):
            y  = self.track_y(i)
            bg = _darken(HEADER_BG, 0.85) if i % 2 == 0 else HEADER_BG
            self.headers.create_rectangle(0, y, w, y + TRACK_H,
                                           fill=bg, outline=SEP)
            # Colour swatch strip on left
            #####       sw_col = ["#336699", "#1e5a9e", "#5a2090"][i]
            ##### # # # Swath swapped to accomodate reordered track layout # # # #####
            sw_col = ["#5a2090", "#1e5a9e", "#336699"][i]
            self.headers.create_rectangle(0, y, 5, y + TRACK_H,
                                           fill=sw_col, outline="")
            self.headers.create_text(
                w // 2 + 3, y + TRACK_H // 2,
                text=td["name"], fill=FG,
                font=("Helvetica", 9, "bold"), anchor=tk.CENTER)
            if td["locked"]:
                self.headers.create_text(
                    w - 8, y + TRACK_H - 12, text="🔒",
                    fill=FG_DIM, font=("Helvetica", 8))

    def _update_scrollbar(self):
        total = self._total_px()
        w     = self._cw()
        lo    = self._scroll / total
        hi    = min(1.0, (self._scroll + w) / total)
        self.hbar.set(lo, hi)

    # ─────────────────────────────────────────── Hit test ────────────────────
    def _hit_test(self, x: int, y: int) -> Tuple[Optional[str], Any, int]:
        """Return (hit_type, block, track_idx). hit_type: body|hl|hr|None"""
        ti = self.track_at(y)
        if ti == TRACK_AUDIO:
            return None, None, TRACK_AUDIO
        t    = self.x2t(x)
        proj = self.app.project
        blks = proj.prompt_blocks if ti == TRACK_PROMPTS else proj.global_blocks

        for blk in reversed(blks):
            if blk.start <= t <= blk.end:
                x1 = self.t2x(blk.start)
                x2 = self.t2x(blk.end)
                if x2 - x1 > HANDLE_W * 3:
                    if x <= x1 + HANDLE_W:
                        return "hl", blk, ti
                    if x >= x2 - HANDLE_W:
                        return "hr", blk, ti
                return "body", blk, ti
        return None, None, ti

    # ─────────────────────────────────────────── Mouse events ─────────────────
    def _on_press(self, ev):
        self.canvas.focus_set()
        hit, blk, ti = self._hit_test(ev.x, ev.y)
        if hit is None:
            self._deselect()
            return

        self.selected = (ti, blk)
        self.app.block_editor.load(blk, ti)
        self._drag = {
            "hit": hit, "blk": blk, "ti": ti,
            "sx": ev.x,
            "os": blk.start, "od": blk.duration,
            "dirty": False,
        }
        self.redraw()

    def _on_motion(self, ev):
        if self._drag is None:
            return
        dx = ev.x - self._drag["sx"]
        dt = dx / self.zoom
        blk = self._drag["blk"]
        ti  = self._drag["ti"]
        if abs(dx) > 2:
            self._drag["dirty"] = True

        if self._drag["hit"] == "body":
            ns = self.snap(max(0.0, self._drag["os"] + dt))
            if self._can_place(blk, ti, ns, blk.duration):
                blk.start = ns

        elif self._drag["hit"] == "hr":
            nd = self.snap(max(MIN_BLOCK, self._drag["od"] + dt))
            if self._can_place(blk, ti, blk.start, nd):
                blk.duration = nd

        elif self._drag["hit"] == "hl":
            ns  = self.snap(max(0.0, self._drag["os"] + dt))
            nd  = self.snap(self._drag["od"] - (ns - self._drag["os"]))
            if nd >= MIN_BLOCK and self._can_place(blk, ti, ns, nd):
                blk.start    = ns
                blk.duration = nd

        self.redraw()
        self.app.statusbar.set_time(blk.start, blk.end)

    def _on_release(self, ev):
        if self._drag and self._drag["dirty"]:
            self.app.mark_modified()
        self._drag = None
        self.redraw()

    def _on_hover(self, ev):
        hit, _, _ = self._hit_test(ev.x, ev.y)
        cursor = {"hl": "sb_h_double_arrow",
                   "hr": "sb_h_double_arrow",
                   "body": "fleur"}.get(hit, "")
        self.canvas.config(cursor=cursor)

    def _on_rclick(self, ev):
        hit, blk, ti = self._hit_test(ev.x, ev.y)
        menu = _dark_menu(self)
        if hit and blk:
            self.selected = (ti, blk)
            self.app.block_editor.load(blk, ti)
            self.redraw()
            menu.add_command(label="✏  Edit Properties…",
                command=lambda: self.app.block_editor.open_dialog(blk, ti))
            menu.add_command(label="⧉  Duplicate",
                command=lambda: self._dup(blk, ti))
            menu.add_separator()
            menu.add_command(label="✕  Delete  [Del]",
                command=self.delete_selected)
        else:
            t = self.snap(self.x2t(ev.x))
            if ti == TRACK_PROMPTS:
                menu.add_command(label="＋ Add Prompt Segment here",
                    command=lambda: self.add_prompt_block(t))
                menu.add_command(label="Fill Timeline...",
                    command=lambda: self._open_fill_timeline_dialog())
            elif ti == TRACK_GLOBAL:
                menu.add_command(label="＋ Add Global Modifier here",
                    command=lambda: self.add_global_block(t))
        try:
            menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            menu.grab_release()

    def _on_dblclick(self, ev):
        hit, blk, ti = self._hit_test(ev.x, ev.y)
        if blk:
            self.selected = (ti, blk)
            self.app.block_editor.open_dialog(blk, ti)
        else:
            t = self.snap(self.x2t(ev.x))
            if ti == TRACK_PROMPTS:
                self.add_prompt_block(t)
            elif ti == TRACK_GLOBAL:
                self.add_global_block(t)

    def _on_wheel(self, ev):
        ctrl = bool(ev.state & 0x4)
        if hasattr(ev, "delta"):
            delta = ev.delta
        else:
            delta = -120 if ev.num == 5 else 120

        if ctrl:
            t_at = self.x2t(ev.x)
            fac  = 1.15 if delta > 0 else 1 / 1.15
            nz   = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * fac))
            self._scroll = max(0, t_at * nz - ev.x)
            self.zoom    = nz
            self.app.statusbar.set_zoom(self.zoom)
        else:
            step = 80 * (-1 if delta > 0 else 1)
            self._scroll = max(0, self._scroll + step)
        self.redraw()

    def _pan_start(self, ev):
        self._pan_x = ev.x
        self._pan_s = self._scroll

    def _pan_drag(self, ev):
        if self._pan_x is not None:
            self._scroll = max(0, self._pan_s - (ev.x - self._pan_x))
            self.redraw()

    def _ruler_click(self, ev):
        t = max(0, self.x2t(ev.x))
        self.app.player.seek(t)
        try:
            self.app.update_live_preview()
        except Exception:
            pass
        self.redraw()

    def _ruler_drag(self, ev):
        t = max(0, self.x2t(ev.x))
        self.app.player.seek(t)
        try:
            self.app.update_live_preview()
        except Exception:
            pass
        self.redraw()

    def _on_hscroll(self, *args):
        cmd = args[0]
        if cmd == "moveto":
            self._scroll = float(args[1]) * self._total_px()
        elif cmd == "scroll":
            unit = args[2]
            step = 100 if unit == "units" else self._cw()
            self._scroll += int(args[1]) * step
        self._scroll = max(0, self._scroll)
        self.redraw()

    # ─────────────────────────────────────────── Block ops ────────────────────
    def _can_place(self, blk, ti: int, ns: float, nd: float) -> bool:
        """Only prompt track enforces no-overlap."""
        if ti != TRACK_PROMPTS:
            return True
        ne = ns + nd
        for o in self.app.project.prompt_blocks:
            if o.bid == blk.bid:
                continue
            if o.start < ne and ns < o.end:
                return False
        return True

    def _next_color(self) -> str:
        c = BLOCK_PALETTE[self._color_i % len(BLOCK_PALETTE)]
        self._color_i += 1
        return c

    def _deselect(self):
        self.selected = None
        self.app.block_editor.clear()
        self.redraw()

    def _dup(self, blk, ti: int):
        nb = copy.deepcopy(blk)
        nb.bid   = str(uuid.uuid4())
        nb.start = self.snap(blk.end + SNAP_S)
        if ti == TRACK_PROMPTS:
            self.app.project.prompt_blocks.append(nb)
        else:
            self.app.project.global_blocks.append(nb)
        self.selected = (ti, nb)
        self.redraw()
        self.app.mark_modified()

    def add_prompt_block(self, start: float = 0.0, duration: float = 4.0):
        blk = PromptBlock(bid=str(uuid.uuid4()),
                           start=self.snap(start),
                           duration=duration,
                           label="New Segment",
                           color=self._next_color())
        while not self._can_place(blk, TRACK_PROMPTS, blk.start, blk.duration):
            blk.start = self.snap(blk.start + SNAP_S)
        self.app.project.prompt_blocks.append(blk)
        self.selected = (TRACK_PROMPTS, blk)
        self.redraw()
        self.app.mark_modified()
        self.app.block_editor.open_dialog(blk, TRACK_PROMPTS)

    def add_global_block(self, start: float = 0.0, duration: float = 8.0):
        blk = GlobalBlock(bid=str(uuid.uuid4()),
                           start=self.snap(start),
                           duration=duration,
                           label="Style Modifier",
                           color="#5a2090")
        self.app.project.global_blocks.append(blk)
        self.selected = (TRACK_GLOBAL, blk)
        self.redraw()
        self.app.mark_modified()
        self.app.block_editor.open_dialog(blk, TRACK_GLOBAL)

    def delete_selected(self):
        if self.selected is None:
            return
        ti, blk = self.selected
        proj = self.app.project
        if ti == TRACK_PROMPTS:
            proj.prompt_blocks = [b for b in proj.prompt_blocks
                                   if b.bid != blk.bid]
        elif ti == TRACK_GLOBAL:
            proj.global_blocks = [b for b in proj.global_blocks
                                   if b.bid != blk.bid]
        self._deselect()
        self.app.mark_modified()

    def load_audio(self, path: str):
        self.app.statusbar.set_status("Loading waveform…")
        self._waveform.load_async(path, callback=lambda: (
            self.after(0, self.redraw),
            self.app.statusbar.set_status("Waveform ready")))
    

    # ─────────────────────────────────────────── Playhead tick ───────────────
    def start_tick(self):
        def _tick():
            if self.app.player.is_playing:
                self.redraw()
                try:
                    self.app.update_live_preview()
                except Exception:
                    pass
                t = self.app.player.position
                x = self.t2x(t)
                w = self._cw()
                if x > w - 100:
                    self._scroll += 40
                elif x < 30 and self._scroll > 0:
                    self._scroll = max(0, self._scroll - 40)
            self._tick_id = self.after(40, _tick)
        _tick()

    def stop_tick(self):
        if self._tick_id:
            self.after_cancel(self._tick_id)

    def _open_fill_timeline_dialog(self):
        dlg = FillTimelineDialog(self.winfo_toplevel(), self)  # Dialog is modal; after it closes:
        #dlg = FillTimelineDialog(self, app = self)  # Dialog is modal; after it closes:
        if not dlg.result:
            return
        mode, params = dlg.result
        self._fill_timeline(mode, params)
    # ─────────────────────────────────────────── Timeline Randomization ──────────
    def _fill_timeline(self, mode: str, params: dict):
        # Always clear existing prompt blocks for a full Fill Timeline
        self.app.project.prompt_blocks = []
        # Save the user-provided description to the project
        vd = params.get("video_description", "")
        self.app.project.video_description = vd

        snap = SNAP_S
        dur_total = max(self.app.project.audio_duration, 60.0)
        total_ticks = int(round(dur_total / snap))

        start_tick = 0


        import random
        if mode == "fixed":
            block_ticks = max(1, int(round(float(params.get("duration", 4.0)) / snap)))
        else:
            seed = params.get("seed")
            if seed is not None:
                random.seed(int(seed))
            min_ticks = max(1, int(round(float(params.get("min", 3.0)) / snap)))
            max_ticks = max(min_ticks, int(round(float(params.get("max", 7.0)) / snap)))

        while start_tick < total_ticks:
            if mode == "fixed":
                dt = block_ticks
            else:
                dt = random.randint(min_ticks, max_ticks)

            # Trim last block to fit exactly
            if start_tick + dt > total_ticks:
                dt = total_ticks - start_tick
                if dt * snap < MIN_BLOCK:
                    break

            start = start_tick * snap
            duration = dt * snap

            blk = PromptBlock(
                bid=str(uuid.uuid4()),
                start=round(start, 3),
                duration=round(duration, 3),
                label="Segment",
                color=self._next_color()
            )
            # Ensure no overlap with existing blocks (preserve mode)
            while not self._can_place(blk, TRACK_PROMPTS, blk.start, blk.duration):
                # move forward one tick until it fits or we run out
                start_tick += 1
                if start_tick >= total_ticks:
                    break
                start = start_tick * snap
                blk.start = round(start, 3)

            if start_tick >= total_ticks:
                break

            self.app.project.prompt_blocks.append(blk)
            start_tick += dt

        self.app.mark_modified()
        self.redraw()
        # If user requested Ollama generation, run it now for each block
        if params.get("use_ollama"):
            # Run in background so UI doesn't freeze; sequential or parallel per user choice
            seq = bool(params.get("sequential_ollama", True))
            self.app.generate_prompts_with_ollama(self.app.project.prompt_blocks, sequential=seq, video_description=vd)


    # ─────────────────────────────────────────── Zoom helpers ─────────────────
    def zoom_fit(self):
        dur = max(1.0, self.app.project.audio_duration or 60.0)
        computed = (self._cw() - 20) / dur
        self.zoom = max(1.0, min(MAX_ZOOM, computed))
        self._scroll = 0
        self.redraw()
        ######### Deprecated by above code #########
        #dur = self.app.project.audio_duration or 60.0  #### Did not account for full length of project
        #self.zoom = max(MIN_ZOOM, (self._cw() - 20) / dur)
        #self._scroll = 0
        #self.redraw()

    def zoom_in(self):
        self.zoom = min(MAX_ZOOM, self.zoom * 1.25)
        self.redraw()

    def zoom_out(self):
        self.zoom = max(MIN_ZOOM, self.zoom / 1.25)
        self.redraw()

    def zoom_reset(self):
        self.zoom = DEF_ZOOM
        self.redraw()


###############################################################################
# VARIABLES PANEL
###############################################################################

class VariablesPanel(tk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, bg=PANEL_BG)
        self.app = app
        self._build()

    def _build(self):
        # Title bar
        tb = tk.Frame(self, bg=HEADER_BG, height=26)
        tb.pack(fill=tk.X)
        tk.Label(tb, text="  GLOBAL VARIABLES", bg=HEADER_BG, fg=FG_DIM,
                 font=("Helvetica", 8, "bold")).pack(side=tk.LEFT)

        # Treeview
        cols = ("name", "value")
        self.tree = ttk.Treeview(self, columns=cols, show="headings",
                                  selectmode="browse", height=12)
        self.tree.heading("name",  text="Variable")
        self.tree.heading("value", text="Value")
        self.tree.column("name",   width=90,  minwidth=60)
        self.tree.column("value",  width=110, minwidth=60)

        _apply_tree_style(self.tree)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.tree.bind("<Double-Button-1>", self._on_edit)

        # Buttons
        bb = tk.Frame(self, bg=PANEL_BG)
        bb.pack(fill=tk.X, padx=4, pady=(0, 4))
        for lbl, cmd in [("Add", self._add),
                          ("Edit", self._on_edit),
                          ("Delete", self._del)]:
            _dark_btn(bb, lbl, cmd).pack(side=tk.LEFT, padx=2)

        # Usage hint
        tk.Label(self, text="Use {varname} in prompts",
                 bg=PANEL_BG, fg=FG_DIM,
                 font=("Helvetica", 8)).pack(pady=4)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for k, v in self.app.project.global_vars.items():
            self.tree.insert("", tk.END, values=(k, v))

    def _add(self):
        dlg = _VarEditDialog(self.app.root, "", "")
        if dlg.result:
            k, v = dlg.result
            if k:
                self.app.project.global_vars[k] = v
                self.refresh()
                self.app.mark_modified()

    def _on_edit(self, _event=None):
        sel = self.tree.selection()
        if not sel: return
        k, v = self.tree.item(sel[0])["values"]
        dlg = _VarEditDialog(self.app.root, k, v)
        if dlg.result:
            nk, nv = dlg.result
            if nk:
                del self.app.project.global_vars[k]
                self.app.project.global_vars[nk] = nv
                self.refresh()
                self.app.mark_modified()

    def _del(self):
        sel = self.tree.selection()
        if not sel: return
        k = self.tree.item(sel[0])["values"][0]
        del self.app.project.global_vars[k]
        self.refresh()
        self.app.mark_modified()


###############################################################################
# BLOCK EDITOR PANEL (bottom)
###############################################################################

class BlockEditorPanel(tk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, bg=PANEL_BG)
        self.app  = app
        self._blk = None
        self._ti  = None
        self._build()

    def _build(self):
        # Title row
        title_row = tk.Frame(self, bg=HEADER_BG, height=26)
        title_row.pack(fill=tk.X)
        title_row.pack_propagate(False)
        self._title_lbl = tk.Label(title_row, text="  No block selected",
                                   bg=HEADER_BG, fg=FG,
                                   font=("Helvetica", 9, "bold"), anchor=tk.W)
        self._title_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        _dark_btn(title_row, "⚙ Properties…",
                  self._open_dialog, pad=4).pack(side=tk.RIGHT, padx=4)

        # Content
        content = tk.Frame(self, bg=PANEL_BG)
        content.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        # Label
        row0 = tk.Frame(content, bg=PANEL_BG)
        row0.pack(fill=tk.X, pady=(0, 3))
        tk.Label(row0, text="Label:", bg=PANEL_BG, fg=FG_DIM,
                 font=("Helvetica", 8), width=10, anchor=tk.E).pack(side=tk.LEFT)
        self._label_var = tk.StringVar()
        self._label_entry = _dark_entry(row0, textvariable=self._label_var, width=30)
        self._label_entry.pack(side=tk.LEFT, padx=(4, 0))
        self._label_var.trace_add("write", lambda *_: self._apply_label())

        # Prompts side by side
        prompts = tk.Frame(content, bg=PANEL_BG)
        prompts.pack(fill=tk.BOTH, expand=True)

        # Positive prompt
        self._prompt_frame = tk.LabelFrame(prompts, text=" Prompt ", bg=PANEL_BG, fg=WAVEFORM_C,
        font=("Helvetica", 8))
        self._prompt_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 3))
        self._prompt = _dark_text(self._prompt_frame, height=3)
        self._prompt.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)
        self._prompt.bind("<FocusOut>", lambda _: self._apply())

        # Negative prompt
        self._neg_frame = tk.LabelFrame(prompts, text=" Negative Prompt ", bg=PANEL_BG,
                                     fg="#cc4444", font=("Helvetica", 8))
        self._neg_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._neg = _dark_text(self._neg_frame, height=3)
        self._neg.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)
        self._neg.bind("<FocusOut>", lambda _: self._apply())

        # Positive prompt
        #lf1 = tk.LabelFrame(prompts, text=" Prompt ", bg=PANEL_BG, fg=WAVEFORM_C,
        #                      font=("Helvetica", 8))
        #lf1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 3))
        #self._prompt = _dark_text(lf1, height=3)
        #self._prompt.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)
        #self._prompt.bind("<FocusOut>", lambda _: self._apply())
        # Negative prompt
        #lf2 = tk.LabelFrame(prompts, text=" Negative Prompt ", bg=PANEL_BG,
        #                      fg="#cc4444", font=("Helvetica", 8))
        #lf2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        #self._neg = _dark_text(lf2, height=3)
        #self._neg.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)
        #self._neg.bind("<FocusOut>", lambda _: self._apply())

        # Apply button
        _dark_btn(content, "✔ Apply  [Ctrl+Enter]", self._apply,
                  accent=True).pack(side=tk.RIGHT, pady=(3, 0))
        # Bind Ctrl+Enter
        self._prompt.bind("<Control-Return>", lambda _: self._apply())
        self._neg.bind("<Control-Return>",    lambda _: self._apply())
        # After the Apply button creation: Think button for ollama integration.
        think_btn = _dark_btn(content, "💭 Think", self._think_for_block)
        think_btn.pack(side=tk.RIGHT, pady=(3,0), padx=(6,0))

    # ── Public ────────────────────────────────────────────────────────────────
    def _think_for_block(self):
        if not getattr(self, "_blk", None):
            return
        try:
            if getattr(self.app, "live_preview_var", None):
                self.app.live_preview_var.set(False)
        except Exception:
            pass
        blk = self._blk
        proj = self.app.project
        duration = blk.duration
        total_dur = proj.audio_duration or 60.0

        # Build the prompt for generating a positive prompt
        proj_desc = self.app.project.video_description or ""
        prompt = (
            f"Write a short visual prompt for a music-video segment.\n"
            f"Project description: {proj_desc}\n"
            f"Segment label: {blk.label}\n"
            f"Segment start: {blk.start:.1f}s, duration: {duration:.1f}s.\n"
            f"Song length: {total_dur:.1f}s.\n"
            f"Project globals: {proj.global_vars}\n"
            f"Segment label: {blk.label}\n"
            f"Return a single concise prompt (1-2 sentences) suitable for image/video generation.\n"
            f"They should be structured as (at 0 seconds: then the prompt sentences.)\n"
        )

        try:
            # Generate positive prompt
            raw_out = self.app._call_ollama_generate(prompt, max_tokens=200)
            positive = self.app._sanitize_model_output(raw_out).strip()

            if not positive:
                messagebox.showwarning("Think", "Model returned no usable prompt text.")
                return

            # Generate negative prompt using the positive prompt as context
            neg_prompt = (
                "Given the following positive prompt, write a concise negative prompt "
                "(things to avoid, undesired elements, artifacts) suitable for image/video generation.\n\n"
                f"Project description: {proj_desc}\n"
                f"Positive prompt: {positive}\n\n"
                "Return a short list or a single-line negative prompt (avoid commentary)."
            )
            raw_neg = self.app._call_ollama_generate(neg_prompt, max_tokens=200)
            negative = self.app._sanitize_model_output(raw_neg).strip()

            # Apply results to UI and block
            self._prompt.delete("1.0", tk.END)
            self._prompt.insert("1.0", positive)
            if hasattr(blk, "negative_prompt"):
                self._neg.delete("1.0", tk.END)
                self._neg.insert("1.0", negative)

            self._apply()
            messagebox.showinfo("Think", "Positive and negative prompts generated and applied to block.")
        except Exception as e:
            messagebox.showerror("Think Failed", str(e))
        
    def load(self, blk, ti: int):
        self._blk = blk
        self._ti  = ti
        lbl = f"  {'Prompt Segment' if ti == TRACK_PROMPTS else 'Global Modifier'}  —  {blk.label or blk.bid[:8]}"
        self._title_lbl.config(text=lbl)
        self._label_var.set(blk.label)
        self._prompt.delete("1.0", tk.END)
        self._prompt.insert("1.0", blk.prompt)
        self._neg.delete("1.0", tk.END)
        if hasattr(blk, "negative_prompt"):
            self._neg.insert("1.0", blk.negative_prompt)

    def clear(self):
        self._blk = None
        self._ti  = None
        self._title_lbl.config(text="  No block selected")
        self._label_var.set("")
        self._prompt.delete("1.0", tk.END)
        self._neg.delete("1.0", tk.END)

    def open_dialog(self, blk=None, ti=None):
        blk = blk or (self._blk)
        ti  = ti  or (self._ti)
        if blk is None:
            return
        BlockPropertiesDialog(self.app.root, blk, ti, self.app)

    def _apply_label(self):
        if self._blk:
            self._blk.label = self._label_var.get()
            self.app.timeline.redraw()

    def _apply(self):
        if self._blk is None:
            return
        self._blk.prompt = self._prompt.get("1.0", tk.END).strip()
        if hasattr(self._blk, "negative_prompt"):
            self._blk.negative_prompt = self._neg.get("1.0", tk.END).strip()
        self._blk.label = self._label_var.get().strip()
        self.app.timeline.redraw()
        self.app.mark_modified()

    def _open_dialog(self):
        if self._blk:
            self.open_dialog(self._blk, self._ti)


###############################################################################
# BLOCK PROPERTIES DIALOG
###############################################################################

class BlockPropertiesDialog(tk.Toplevel):
    def __init__(self, parent, blk, ti: int, app: "App"):
        super().__init__(parent)
        self.blk = blk
        self.ti  = ti
        self.app = app
        self.title("Block Properties")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.geometry("640x580")
        self.transient(parent)
        self.grab_set()
        self._build()
        self._populate()
        self.wait_window()

    def _build(self):
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        _apply_notebook_style(nb)

        # ── Tab 1: General ─────────────────────────────────────────────────
        gen = tk.Frame(nb, bg=PANEL_BG)
        nb.add(gen, text="  General  ")

        self._label_var = _lf_entry(gen, "Label", row=0)
        self._color_var = tk.StringVar(value=self.blk.color)

        row_f = tk.Frame(gen, bg=PANEL_BG)
        row_f.grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=12, pady=4)
        tk.Label(row_f, text="Color:", bg=PANEL_BG, fg=FG,
                 font=("Helvetica", 9), width=12, anchor=tk.E).pack(side=tk.LEFT)
        self._color_swatch = tk.Button(
            row_f, width=6, relief=tk.FLAT, cursor="hand2",
            command=self._pick_color)
        self._color_swatch.pack(side=tk.LEFT, padx=4)
        self._update_swatch()

        # Timing
        self._start_var = _lf_entry(gen, "Start (s)", row=2)
        self._dur_var   = _lf_entry(gen, "Duration (s)", row=3)

        # Prompts
        tk.Label(gen, text="Prompt:", bg=PANEL_BG, fg=FG,
                 font=("Helvetica", 9), anchor=tk.W).grid(
            row=4, column=0, sticky=tk.W, padx=12, pady=(8, 2))
        self._prompt = _dark_text(gen, height=5, width=60)
        self._prompt.grid(row=5, column=0, columnspan=2, padx=12, pady=(0,6), sticky=tk.EW)

        tk.Label(gen, text="Negative Prompt:", bg=PANEL_BG, fg=FG,
                 font=("Helvetica", 9), anchor=tk.W).grid(
            row=6, column=0, sticky=tk.W, padx=12, pady=(4, 2))
        self._neg = _dark_text(gen, height=3, width=60)
        self._neg.grid(row=7, column=0, columnspan=2, padx=12, pady=(0,6), sticky=tk.EW)

        gen.columnconfigure(1, weight=1)

        # ── Tab 2: Generation ─────────────────────────────────────────────
        gen2 = tk.Frame(nb, bg=PANEL_BG)
        nb.add(gen2, text="  Generation  ")

        if self.ti == TRACK_PROMPTS:
            self._steps_var = _lf_entry(gen2, "Steps", row=0)
            self._cfg_var   = _lf_entry(gen2, "CFG Scale", row=1)
            self._seed_var  = _lf_entry(gen2, "Seed (-1=random)", row=2)
            tk.Label(gen2, text="Width and height use project defaults unless\n"
                     "overridden in Project Settings.",
                     bg=PANEL_BG, fg=FG_DIM, font=("Helvetica", 8),
                     justify=tk.LEFT).grid(row=3, column=0, columnspan=2,
                                           padx=12, pady=8, sticky=tk.W)
        else:
            tk.Label(gen2, text="Global blocks do not have generation parameters.\n"
                     "Their prompts are merged into overlapping Prompt Segments.",
                     bg=PANEL_BG, fg=FG_DIM, font=("Helvetica", 9),
                     justify=tk.LEFT).pack(padx=12, pady=20)

        # ── Tab 3: Variable Overrides ─────────────────────────────────────
        vo = tk.Frame(nb, bg=PANEL_BG)
        nb.add(vo, text="  Variables  ")

        tk.Label(vo, text="Variable overrides apply when this block starts.\n"
                 "Use {varname} syntax in your prompts.",
                 bg=PANEL_BG, fg=FG_DIM, font=("Helvetica", 8),
                 justify=tk.LEFT).pack(anchor=tk.W, padx=10, pady=6)

        cols = ("name", "value")
        self._vo_tree = ttk.Treeview(vo, columns=cols, show="headings",
                                      height=8)
        self._vo_tree.heading("name",  text="Variable")
        self._vo_tree.heading("value", text="Override Value")
        self._vo_tree.column("name",  width=130)
        self._vo_tree.column("value", width=240)
        _apply_tree_style(self._vo_tree)
        self._vo_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        bb = tk.Frame(vo, bg=PANEL_BG)
        bb.pack(fill=tk.X, padx=8, pady=(0,6))
        for lbl, cmd in [("Add", self._vo_add),
                          ("Edit", self._vo_edit),
                          ("Remove", self._vo_del)]:
            _dark_btn(bb, lbl, cmd).pack(side=tk.LEFT, padx=2)

        # ── Bottom buttons ─────────────────────────────────────────────────
        bot = tk.Frame(self, bg=BG)
        bot.pack(fill=tk.X, padx=8, pady=6)
        _dark_btn(bot, "Cancel", self.destroy).pack(side=tk.RIGHT, padx=4)
        _dark_btn(bot, "OK", self._ok, accent=True).pack(side=tk.RIGHT)

    def _populate(self):
        blk = self.blk
        self._label_var.set(blk.label)
        self._start_var.set(f"{blk.start:.3f}")
        self._dur_var.set(f"{blk.duration:.3f}")
        self._prompt.insert("1.0", blk.prompt)
        if hasattr(blk, "negative_prompt"):
            self._neg.insert("1.0", blk.negative_prompt)
        if self.ti == TRACK_PROMPTS:
            self._steps_var.set(str(blk.steps))
            self._cfg_var.set(str(blk.cfg))
            self._seed_var.set(str(blk.seed))
        self._vo_refresh()

    def _ok(self):
        blk = self.blk
        blk.label  = self._label_var.get().strip()
        blk.color  = self._color_var.get()
        blk.prompt = self._prompt.get("1.0", tk.END).strip()
        if hasattr(blk, "negative_prompt"):
            blk.negative_prompt = self._neg.get("1.0", tk.END).strip()
        try:
            ns = float(self._start_var.get())
            nd = float(self._dur_var.get())
            if nd < MIN_BLOCK:
                nd = MIN_BLOCK
            blk.start    = round(ns, 3)
            blk.duration = round(nd, 3)
        except ValueError:
            pass
        if self.ti == TRACK_PROMPTS:
            try:
                blk.steps = int(self._steps_var.get())
                blk.cfg   = float(self._cfg_var.get())
                blk.seed  = int(self._seed_var.get())
            except ValueError:
                pass
        self.app.block_editor.load(blk, self.ti)
        self.app.timeline.redraw()
        self.app.mark_modified()
        self.destroy()

    def _pick_color(self):
        col = colorchooser.askcolor(color=self._color_var.get(),
                                     parent=self, title="Block Color")
        if col and col[1]:
            self._color_var.set(col[1])
            self._update_swatch()

    def _update_swatch(self):
        self._color_swatch.config(bg=self._color_var.get(),
                                   activebackground=self._color_var.get())

    def _vo_refresh(self):
        self._vo_tree.delete(*self._vo_tree.get_children())
        for k, v in self.blk.variable_overrides.items():
            self._vo_tree.insert("", tk.END, values=(k, v))

    def _vo_add(self):
        dlg = _VarEditDialog(self, "", "")
        if dlg.result:
            k, v = dlg.result
            if k:
                self.blk.variable_overrides[k] = v
                self._vo_refresh()

    def _vo_edit(self):
        sel = self._vo_tree.selection()
        if not sel: return
        k, v = self._vo_tree.item(sel[0])["values"]
        dlg  = _VarEditDialog(self, k, v)
        if dlg.result:
            nk, nv = dlg.result
            if nk:
                del self.blk.variable_overrides[k]
                self.blk.variable_overrides[nk] = nv
                self._vo_refresh()

    def _vo_del(self):
        sel = self._vo_tree.selection()
        if not sel: return
        k = self._vo_tree.item(sel[0])["values"][0]
        del self.blk.variable_overrides[k]
        self._vo_refresh()


###############################################################################
# SETTINGS DIALOG
###############################################################################

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, app: "App"):
        super().__init__(parent)
        self.app = app
        self.title("Project Settings")
        self.configure(bg=BG)
        self.geometry("480x400")
        self.transient(parent)
        self.grab_set()
        self._build()
        self._populate()
        self.wait_window()

    def _build(self):
        f = tk.Frame(self, bg=PANEL_BG)
        f.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        rows = [
            ("Project Name",       "_name"),
            ("WanGP URL",          "_url"),
            ("Output Folder",      "_out"),
            ("Default Width",      "_w"),
            ("Default Height",     "_h"),
            ("Default FPS",        "_fps"),
            ("Default Steps",      "_steps"),
            ("Default CFG Scale",  "_cfg"),
        ]
        for i, (lbl, attr) in enumerate(rows):
            tk.Label(f, text=lbl+":", bg=PANEL_BG, fg=FG,
                     font=("Helvetica", 9), width=18, anchor=tk.E).grid(
                row=i, column=0, padx=8, pady=5, sticky=tk.E)
            var = tk.StringVar()
            setattr(self, attr+"_var", var)
            _dark_entry(f, textvariable=var, width=30).grid(
                row=i, column=1, padx=8, pady=5, sticky=tk.EW)

        # API type
        i += 1
        tk.Label(f, text="API Type:", bg=PANEL_BG, fg=FG,
                 font=("Helvetica", 9), width=18, anchor=tk.E).grid(
            row=i, column=0, padx=8, pady=5, sticky=tk.E)
        self._api_var = tk.StringVar()
        ttk.Combobox(f, textvariable=self._api_var,
                     values=["gradio", "rest"],
                     state="readonly", width=15).grid(
            row=i, column=1, padx=8, pady=5, sticky=tk.W)

        f.columnconfigure(1, weight=1)

        bot = tk.Frame(self, bg=BG)
        bot.pack(fill=tk.X, padx=10, pady=6)
        _dark_btn(bot, "Cancel", self.destroy).pack(side=tk.RIGHT, padx=4)
        _dark_btn(bot, "Save", self._save, accent=True).pack(side=tk.RIGHT)

    def _populate(self):
        p = self.app.project
        self._name_var.set(p.name)
        self._url_var.set(p.wangp_url)
        self._out_var.set(p.output_dir)
        self._w_var.set(str(p.default_width))
        self._h_var.set(str(p.default_height))
        self._fps_var.set(str(p.default_fps))
        self._steps_var.set(str(p.default_steps))
        self._cfg_var.set(str(p.default_cfg))
        self._api_var.set(p.wangp_api_type)

    def _save(self):
        p = self.app.project
        p.name           = self._name_var.get().strip() or "Untitled"
        p.wangp_url      = self._url_var.get().strip()
        p.output_dir     = self._out_var.get().strip() or "output"
        p.wangp_api_type = self._api_var.get()
        try: p.default_width  = int(self._w_var.get())
        except: pass
        try: p.default_height = int(self._h_var.get())
        except: pass
        try: p.default_fps    = int(self._fps_var.get())
        except: pass
        try: p.default_steps  = int(self._steps_var.get())
        except: pass
        try: p.default_cfg    = float(self._cfg_var.get())
        except: pass
        self.app.mark_modified()
        self.app.root.title(f"{APP_NAME} — {p.name}")
        self.destroy()

###############################################################################
# FILL TIMELINE DIALOG
###############################################################################


class FillTimelineDialog(tk.Toplevel):
    def __init__(self, parent, timeline):
        super().__init__(parent)
        self.timeline = timeline
        self.parent = parent
        self.app = getattr(timeline, "app", None) or parent.app
        self.result = None
        self.title("Fill Timeline")
        self.transient(parent)
        self.resizable(False, False)
        # Make modal in a cross-platform friendly way
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._build()
        # center on parent
        self.update_idletasks()
        px = parent.winfo_rootx(); py = parent.winfo_rooty()
        pw = parent.winfo_width(); ph = parent.winfo_height()
        w = self.winfo_width(); h = self.winfo_height()
        self.geometry(f"+{px + max(0,(pw - w)//2)}+{py + 30 + max(0,(ph - h)//2)}")
        self.wait_window()

    def _build(self):
        pad = 10
        f = tk.Frame(self, bg=PANEL_BG)
        f.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)
        self.minsize(400, 340)
        self.mode_var = tk.StringVar(value="fixed")

        rb_fixed = tk.Radiobutton(f, text="Fixed duration (seconds)",
                                  variable=self.mode_var, value="fixed",
                                  bg=PANEL_BG, fg=FG, selectcolor=BTN_BG,
                                  activebackground=PANEL_BG, activeforeground=FG,
                                  anchor="w")
        rb_fixed.pack(fill=tk.X, pady=(0,4))

        row_fixed = tk.Frame(f, bg=PANEL_BG)
        row_fixed.pack(fill=tk.X, padx=18)
        tk.Label(row_fixed, text="Duration:", bg=PANEL_BG, fg=FG).pack(side=tk.LEFT)
        self.fixed_var = tk.StringVar(value="4.0")
        self.fixed_entry = tk.Entry(row_fixed, textvariable=self.fixed_var, width=8,
                                    bg=ENTRY_BG, fg=FG, insertbackground=FG)
        self.fixed_entry.pack(side=tk.LEFT, padx=(6,0))

        tk.Label(f, text="", bg=PANEL_BG).pack()  # spacer

        rb_rand = tk.Radiobutton(f, text="Random durations (min / max seconds)",
                                 variable=self.mode_var, value="random",
                                 bg=PANEL_BG, fg=FG, selectcolor=BTN_BG,
                                 activebackground=PANEL_BG, activeforeground=FG,
                                 anchor="w")
        rb_rand.pack(fill=tk.X, pady=(6,4))

        row_rand = tk.Frame(f, bg=PANEL_BG)
        row_rand.pack(fill=tk.X, padx=18)
        tk.Label(row_rand, text="Min:", bg=PANEL_BG, fg=FG).pack(side=tk.LEFT)
        self.min_var = tk.StringVar(value="3.0")
        self.min_entry = tk.Entry(row_rand, textvariable=self.min_var, width=6,
                                  bg=ENTRY_BG, fg=FG, insertbackground=FG)
        self.min_entry.pack(side=tk.LEFT, padx=(6,8))
        tk.Label(row_rand, text="Max:", bg=PANEL_BG, fg=FG).pack(side=tk.LEFT)
        self.max_var = tk.StringVar(value="7.0")
        self.max_entry = tk.Entry(row_rand, textvariable=self.max_var, width=6,
                                  bg=ENTRY_BG, fg=FG, insertbackground=FG)
        self.max_entry.pack(side=tk.LEFT, padx=(6,0))

        tk.Label(f, text="", bg=PANEL_BG).pack()  # spacer

        seed_row = tk.Frame(f, bg=PANEL_BG)
        seed_row.pack(fill=tk.X, padx=18)
        tk.Label(seed_row, text="Seed (optional):", bg=PANEL_BG, fg=FG).pack(side=tk.LEFT)
        self.seed_var = tk.StringVar()
        self.seed_entry = tk.Entry(seed_row, textvariable=self.seed_var, width=12,
                                   bg=ENTRY_BG, fg=FG, insertbackground=FG)
        self.seed_entry.pack(side=tk.LEFT, padx=(6,0))

        # Buttons
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill=tk.X, pady=(8,8), padx=pad)
        cancel_btn = tk.Button(btn_row, text="Cancel", command=self._on_cancel,
                               bg=BTN_BG, fg=FG, activebackground=BTN_HOV)
        cancel_btn.pack(side=tk.RIGHT, padx=(6,0))
        ok_btn = tk.Button(btn_row, text="Fill", command=self._on_ok,
                           bg=ACCENT, fg="#ffffff", activebackground="#3355cc")
        ok_btn.pack(side=tk.RIGHT)
        # Bind radio change to enable/disable fields
        self.mode_var.trace_add("write", lambda *a: self._update_mode())
        self._update_mode()

        ############################################
        btn_frame = tk.Frame(f, bg=BG)
        btn_frame.pack(fill=tk.X, padx=4, pady=(6,2))
        #start_btn = tk.Button(btn_frame, text="Start Fill", command=self._on_fill_start)
        #start_btn.pack(side=tk.LEFT)
        #stop_btn = tk.Button(btn_frame, text="Stop", command=self._on_fill_stop)
        #stop_btn.pack(side=tk.LEFT, padx=(6,0))
        #o_frame = tk.Frame(btn_frame, bg=BG)
        self._use_ollama_var = tk.BooleanVar(value=False)
        cb_ollama_enable = tk.Checkbutton(btn_frame, text="Use Ollama to write script", variable=self._use_ollama_var)
        cb_ollama_enable.pack(side=tk.LEFT)
        self._sequential_var = tk.BooleanVar(value=True)
        cb_ollama_seq = tk.Checkbutton(btn_frame, text="Generate sequentially (one-by-one, stoppable)", variable=self._sequential_var)
        cb_ollama_seq.pack(side=tk.LEFT)

        # --- Video description label + text box ---
        tk.Label(f, text="Video description (story / mood for Ollama):",
                 bg=PANEL_BG, fg=FG, anchor="w").pack(fill=tk.X, padx=12, pady=(10,2))
        self._video_desc_box = tk.Text(f, height=5, bg=ENTRY_BG, fg=FG,
                                       wrap="word", relief="flat")
        self._video_desc_box.pack(fill=tk.BOTH, padx=12, pady=(0,8), expand=False)
        # Optionally prefill with project description if dialog is opened from app
        try:
            if getattr(self, "app", None) and self.app.project.video_description:
                self._video_desc_box.insert("1.0", self.app.project.video_description)
        except Exception:
            pass
        ############################################


    def _on_fill_start(self):
        if not self._use_ollama_var.get():
            # fallback to existing fill behavior
            self._on_ok()  # your existing call
            return
        # compute segment_count and durations as before
        self._on_ok(False)
        computed_durations_list = []
        computed_count = 0
        stored_count = self.app.project.audio_duration
        print(stored_count)
        for pb in self.app.project.prompt_blocks:
            computed_durations_list.append(pb.duration)
            computed_count += 1
        segment_count = computed_count
        durations = computed_durations_list
        print(segment_count)
        print(durations)
        user_instruction = self._instruction_entry.get().strip() if hasattr(self, "_instruction_entry") else ""
        # call App.start_fill_timeline_sequential
        self.app.start_fill_timeline_sequential(segment_count, durations, user_instruction, commit_each=True)
        self._on_ok()
    def _on_fill_stop(self):
        self.parent.stop_fill_timeline_sequential()

    def _update_mode(self):
        mode = self.mode_var.get()
        if mode == "fixed":
            self.fixed_entry.config(state="normal")
            self.min_entry.config(state="disabled")
            self.max_entry.config(state="disabled")
        else:
            self.fixed_entry.config(state="disabled")
            self.min_entry.config(state="normal")
            self.max_entry.config(state="normal")

    def _on_cancel(self):
        self.result = None
        try: self.grab_release()
        except: pass
        self.destroy()

    def _on_ok(self, done = True):
        if done == True:
            self.destroy()
        try:
            mode = self.mode_var.get()
            if mode == "fixed":
                duration = float(self.fixed_var.get() or 4.0)
                params = {"duration": duration}
            else:
                mn = float(self.min_var.get() or 3.0)
                mx = float(self.max_var.get() or 7.0)
                if mn <= 0 or mx <= 0 or mn > mx:
                    raise ValueError("Invalid min/max")
                params = {"min": mn, "max": mx}
                if self.seed_var.get().strip():
                    params["seed"] = int(self.seed_var.get().strip())
            params["use_ollama"] = bool(self._use_ollama_var.get())
            params["sequential_ollama"] = bool(self._sequential_var.get())
            # after building params and before setting self.result:
            desc = ""
            try:
                desc = self._video_desc_box.get("1.0", "end").strip()
            except Exception:
                desc = ""
            params["video_description"] = desc
            # existing: params["use_ollama"], params["sequential_ollama"], etc.
            self.result = (mode, params)
        except Exception as e:
            messagebox.showerror("Invalid input", f"Please check your values.\n\n{e}", parent=self)
            return
        try: self.grab_release()
        except: pass

###############################################################################
# PROCESS DIALOG
###############################################################################

class ProcessDialog(tk.Toplevel):
    def __init__(self, parent, app: "App"):
        super().__init__(parent)
        self.app = app
        self.title("Processing…")
        self.configure(bg=BG)
        self.geometry("560x380")
        self.resizable(False, False)
        self.transient(parent)
        self._cancelled = False
        self._build()
        self.grab_set()

    def _build(self):
        tk.Label(self, text="WanGP Video Generation",
                 bg=BG, fg=FG, font=("Helvetica", 11, "bold")).pack(pady=(14,6))

        self._status = tk.Label(self, text="Preparing…",
                                 bg=BG, fg=WAVEFORM_C, font=("Helvetica", 9))
        self._status.pack()

        # Overall progress
        tk.Label(self, text="Overall:", bg=BG, fg=FG_DIM,
                 font=("Helvetica", 8)).pack(anchor=tk.W, padx=16, pady=(10,2))
        self._prog_var = tk.IntVar()
        self._prog = ttk.Progressbar(self, variable=self._prog_var,
                                      maximum=100, length=520, mode="determinate")
        self._prog.pack(padx=16)

        # Log
        tk.Label(self, text="Log:", bg=BG, fg=FG_DIM,
                 font=("Helvetica", 8)).pack(anchor=tk.W, padx=16, pady=(10,2))
        log_frame = tk.Frame(self, bg=BG)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=16)
        self._log = tk.Text(log_frame, bg=ENTRY_BG, fg=FG, font=("Courier", 8),
                             height=10, state=tk.DISABLED, wrap=tk.WORD,
                             relief=tk.FLAT)
        sb = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.config(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._log.pack(fill=tk.BOTH, expand=True)

        bot = tk.Frame(self, bg=BG)
        bot.pack(fill=tk.X, padx=16, pady=8)
        self._cancel_btn = _dark_btn(bot, "✕ Cancel", self._cancel)
        self._cancel_btn.pack(side=tk.RIGHT)

    def log(self, msg: str):
        self._log.config(state=tk.NORMAL)
        self._log.insert(tk.END, msg + "\n")
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

    def set_progress(self, pct: int, status: str = ""):
        self._prog_var.set(pct)
        if status:
            self._status.config(text=status)

    def _cancel(self):
        self._cancelled = True
        self.log("Cancellation requested…")

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def finish(self, success: bool, msg: str = ""):
        self._cancel_btn.config(text="Close", command=self.destroy)
        if success:
            self._status.config(text="✔  Complete!", fg="#44cc44")
            self.set_progress(100)
            self.log("Done! Check your output folder.")
        else:
            self._status.config(text=f"✗  Error: {msg}", fg="#ff4444")
            self.log(f"Error: {msg}")


###############################################################################
# PROCESSING ENGINE
###############################################################################

class ProcessingEngine:
    def __init__(self, app: "App"):
        self.app = app

    def run(self, dialog: ProcessDialog):
        """Launch processing in a background thread."""
        def _work():
            try:
                self._run_inner(dialog)
            except Exception as e:
                self.app.root.after(0, lambda: dialog.finish(False, str(e)))
        threading.Thread(target=_work, daemon=True).start()

    def _run_inner(self, dlg: ProcessDialog):
        proj   = self.app.project
        blocks = proj.sorted_prompt_blocks()

        if not blocks:
            raise ValueError("No prompt blocks to process.")

        os.makedirs(proj.output_dir, exist_ok=True)
        dlg.log(f"Output folder: {os.path.abspath(proj.output_dir)}")
        dlg.log(f"WanGP URL:     {proj.wangp_url}  ({proj.wangp_api_type})")
        dlg.log(f"Blocks to process: {len(blocks)}")
        dlg.log("─" * 50)

        cum_dur       = 0.0
        video_idx     = 1
        last_frame    = None
        current_vars  = dict(proj.global_vars)

        for i, blk in enumerate(blocks):
            if dlg.cancelled:
                break

            pct = int(i / len(blocks) * 100)
            label = blk.label or blk.prompt[:30] or f"Block {i+1}"
            dlg.set_progress(pct, f"[{i+1}/{len(blocks)}] {label}")

            # Variable override cascade
            for gb in proj.sorted_global_blocks():
                if gb.start <= blk.start:
                    current_vars.update(gb.variable_overrides)
            current_vars.update(blk.variable_overrides)

            # Safety split
            if cum_dur + blk.duration > WANGP_SAFE and cum_dur > 0:
                dlg.log(f"  ↩ Video split at {cum_dur:.1f}s (WanGP limit)")
                cum_dur    = 0.0
                video_idx += 1

            # Build final prompt
            final_prompt = self._build_prompt(blk, proj, current_vars)
            dlg.log(f"  [{i+1}] {label}")
            dlg.log(f"      Prompt: {final_prompt[:80]}…")

            out_name = (f"video{video_idx:02d}_"
                        f"seg{i+1:03d}_{int(blk.start)}s.mp4")
            out_path = os.path.join(proj.output_dir, out_name)

            # API call
            try:
                self._call_api(
                    prompt          = final_prompt,
                    negative_prompt = getattr(blk, "negative_prompt", ""),
                    duration        = blk.duration,
                    width           = proj.default_width,
                    height          = proj.default_height,
                    fps             = proj.default_fps,
                    steps           = blk.steps,
                    cfg             = blk.cfg,
                    seed            = blk.seed,
                    start_image     = last_frame,
                    output_path     = out_path,
                )
                dlg.log(f"      ✔ Saved → {out_name}")
            except Exception as e:
                dlg.log(f"      ✗ API error: {e}")
                if not dlg.cancelled:
                    pass  # continue with next block

            # Extract last frame for continuity
            last_frame = self._extract_last_frame(out_path)
            if last_frame:
                dlg.log(f"      Frame extracted for next segment.")

            cum_dur += blk.duration

        if not dlg.cancelled:
            self.app.root.after(0, lambda: dlg.finish(True))

    # ─────────────────────────────────────────── Prompt building ──────────────
    def _build_prompt(self, blk: PromptBlock, proj: Project,
                       vars_: Dict[str, str]) -> str:
        # Gather overlapping global prompts
        global_parts = []
        for gb in proj.sorted_global_blocks():
            if gb.start < blk.end and blk.start < gb.end:
                if gb.prompt.strip():
                    global_parts.append(gb.prompt.strip())

        parts = global_parts + ([blk.prompt.strip()] if blk.prompt.strip() else [])
        text  = ", ".join(parts)

        # Variable substitution
        for k, v in vars_.items():
            text = text.replace(f"{{{k}}}", v)
        return text

    # ─────────────────────────────────────────── Last frame ───────────────────
    @staticmethod
    def _extract_last_frame(video_path: str) -> Optional[str]:
        if not os.path.exists(video_path):
            return None
        out = video_path + "_last_frame.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-sseof", "-0.2", "-i", video_path,
                 "-update", "1", "-frames:v", "1", "-q:v", "2", out],
                capture_output=True, timeout=30
            )
            return out if os.path.exists(out) else None
        except Exception as e:
            print(f"[Frame] {e}")
            return None

    # ─────────────────────────────────────────── API call ─────────────────────
    def _call_api(self, prompt, negative_prompt, duration, width, height,
                  fps, steps, cfg, seed, start_image, output_path):
        if not REQUESTS_OK:
            raise RuntimeError(
                "The 'requests' library is not installed. "
                "Run: pip install requests")

        proj = self.app.project
        url  = proj.wangp_url.rstrip("/")

        num_frames = max(1, int(round(duration * fps)))

        # Build start-image payload
        start_img_b64 = None
        if start_image and os.path.exists(start_image):
            import base64
            with open(start_image, "rb") as fh:
                start_img_b64 = base64.b64encode(fh.read()).decode()

        if proj.wangp_api_type == "gradio":
            self._call_gradio(url, prompt, negative_prompt, num_frames,
                               width, height, steps, cfg, seed,
                               start_img_b64, output_path)
        else:
            self._call_rest(url, prompt, negative_prompt, num_frames,
                             width, height, steps, cfg, seed,
                             start_img_b64, output_path)

    def _call_gradio(self, url, prompt, neg, num_frames, w, h,
                     steps, cfg, seed, img_b64, out_path):
        """Gradio /run/predict endpoint (WanGP default)."""
        import base64

        payload = {
            "fn_index": 0,
            "data": [
                prompt, neg, num_frames, w, h, steps, cfg, seed,
                {"data": img_b64, "is_file": False} if img_b64 else None,
            ]
        }
        resp = _requests.post(f"{url}/run/predict", json=payload, timeout=600)
        resp.raise_for_status()
        result = resp.json()

        # WanGP typically returns {data: [{data: <b64>, is_file: false}]}
        for item in result.get("data", []):
            if isinstance(item, dict) and "data" in item:
                raw = item["data"]
                if raw.startswith("data:"):
                    raw = raw.split(",", 1)[1]
                with open(out_path, "wb") as fh:
                    fh.write(base64.b64decode(raw))
                return
            elif isinstance(item, str) and item.startswith("http"):
                vr = _requests.get(item, timeout=300)
                with open(out_path, "wb") as fh:
                    fh.write(vr.content)
                return
        raise RuntimeError(f"Unexpected API response: {str(result)[:200]}")

    def _call_rest(self, url, prompt, neg, num_frames, w, h,
                   steps, cfg, seed, img_b64, out_path):
        """Generic REST endpoint."""
        import base64

        payload = {
            "prompt":           prompt,
            "negative_prompt":  neg,
            "num_frames":       num_frames,
            "width":            w,
            "height":           h,
            "num_inference_steps": steps,
            "guidance_scale":   cfg,
            "seed":             seed,
        }
        if img_b64:
            payload["start_image"] = img_b64

        resp = _requests.post(f"{url}/api/generate", json=payload,
                               timeout=600)
        resp.raise_for_status()
        result = resp.json()

        video_url = result.get("video_url") or result.get("output")
        if not video_url:
            raise RuntimeError(f"No video_url in response: {result}")

        if video_url.startswith("http"):
            vr = _requests.get(video_url, timeout=300)
            with open(out_path, "wb") as fh:
                fh.write(vr.content)
        else:
            if video_url.startswith("data:"):
                video_url = video_url.split(",", 1)[1]
            with open(out_path, "wb") as fh:
                fh.write(base64.b64decode(video_url))


###############################################################################
# STATUS BAR
###############################################################################

class StatusBar(tk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, bg=HEADER_BG, height=22)
        self.pack_propagate(False)
        self.app = app
        self._build()

    def _build(self):
        def _seg(txt="", w=None, anchor=tk.W):
            kw = dict(bg=HEADER_BG, fg=FG_DIM, font=("Helvetica", 8),
                      anchor=anchor)
            if w: kw["width"] = w
            return tk.Label(self, text=txt, **kw)

        self._lbl_status = _seg("Ready", w=28)
        self._lbl_status.pack(side=tk.LEFT, padx=(8, 4))

        tk.Frame(self, bg=SEP, width=1).pack(side=tk.LEFT, fill=tk.Y, pady=3)
        self._lbl_time = _seg("", w=18)
        self._lbl_time.pack(side=tk.LEFT, padx=4)

        tk.Frame(self, bg=SEP, width=1).pack(side=tk.LEFT, fill=tk.Y, pady=3)
        self._lbl_zoom = _seg("Zoom: 100%", w=14)
        self._lbl_zoom.pack(side=tk.LEFT, padx=4)

        tk.Frame(self, bg=SEP, width=1).pack(side=tk.LEFT, fill=tk.Y, pady=3)
        self._lbl_blocks = _seg("", w=20)
        self._lbl_blocks.pack(side=tk.LEFT, padx=4)

        # Right side: dep warnings
        if not PYGAME_OK:
            tk.Label(self, text="⚠ pygame missing (no audio)",
                     bg=HEADER_BG, fg="#cc8833",
                     font=("Helvetica", 7)).pack(side=tk.RIGHT, padx=6)
        if not REQUESTS_OK:
            tk.Label(self, text="⚠ requests missing (no API)",
                     bg=HEADER_BG, fg="#cc8833",
                     font=("Helvetica", 7)).pack(side=tk.RIGHT, padx=6)

    def set_status(self, msg: str):
        self._lbl_status.config(text=msg)

    def set_time(self, start=None, end=None):
        if start is not None and end is not None:
            self._lbl_time.config(text=f"{start:.2f}s → {end:.2f}s")
        else:
            t = self.app.player.position
            m, s = divmod(t, 60)
            self._lbl_time.config(text=f"{int(m):02d}:{s:05.2f}")

    def set_zoom(self, zoom: float):
        pct = int(zoom / DEF_ZOOM * 100)
        self._lbl_zoom.config(text=f"Zoom: {pct}%")

    def update_blocks(self):
        p  = self.app.project
        nb = len(p.prompt_blocks)
        ng = len(p.global_blocks)
        self._lbl_blocks.config(text=f"{nb} segments, {ng} globals")


###############################################################################
# MAIN APPLICATION
###############################################################################

class App:
    def __init__(self):
        self.root    = tk.Tk()
        self.project = Project()
        self.player  = AudioPlayer()
        self.engine  = ProcessingEngine(self)
        self._path   = None
        self._mod    = False   # unsaved changes

        self._setup_window()
        self._setup_styles()
        self._setup_layout()
        self._setup_menu()
        self._setup_toolbar()
        self.timeline.start_tick()
        self._tick_status()

    # ─────────────────────────────────────────── Setup ────────────────────────
    def _setup_window(self):
        self.root.title(f"{APP_NAME} — Untitled")
        self.root.configure(bg=BG)
        self.root.geometry("1400x780")
        self.root.minsize(900, 600)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Icon (skip gracefully)
        try:
            icon = tk.PhotoImage(data=_ICON_B64)
            self.root.iconphoto(True, icon)
        except Exception:
            pass

    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=ENTRY_BG,
                     selectbackground=ACCENT, selectforeground=BLOCK_FG,
                     bordercolor=SEP, troughcolor=PANEL_BG,
                     arrowcolor=FG_DIM, relief=tk.FLAT)
        s.configure("TScrollbar", background=BTN_BG, relief=tk.FLAT,
                     arrowsize=12)
        s.configure("Treeview", background=ENTRY_BG, foreground=FG,
                     rowheight=22, fieldbackground=ENTRY_BG,
                     borderwidth=0, relief=tk.FLAT)
        s.configure("Treeview.Heading", background=HEADER_BG, foreground=FG_DIM,
                     relief=tk.FLAT, font=("Helvetica", 8, "bold"))
        s.map("Treeview", background=[("selected", ACCENT)])
        s.configure("TNotebook", background=PANEL_BG, tabmargins=[0,0,0,0])
        s.configure("TNotebook.Tab", background=HEADER_BG, foreground=FG_DIM,
                     padding=[10, 4], font=("Helvetica", 8))
        s.map("TNotebook.Tab",
              background=[("selected", PANEL_BG)],
              foreground=[("selected", FG)])
        s.configure("TCombobox", background=ENTRY_BG, foreground=FG,
                     fieldbackground=ENTRY_BG, arrowcolor=FG_DIM)
        s.configure("TProgressbar", troughcolor=ENTRY_BG,
                     background=ACCENT, borderwidth=0)

    def _setup_menu(self):
        mb = tk.Menu(self.root, bg=BTN_BG, fg=FG, activebackground=BTN_HOV,
                     activeforeground=FG, relief=tk.FLAT, tearoff=False,
                     bd=0)
        self.root.config(menu=mb)

        # File
        fm = _sub_menu(mb, "File")
        fm.add_command(label="New Project",       command=self.new_project,  accelerator="Ctrl+N")
        fm.add_command(label="Open Project…",     command=self.open_project, accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="Save",              command=self.save,         accelerator="Ctrl+S")
        fm.add_command(label="Save As…",          command=self.save_as,      accelerator="Ctrl+Shift+S")
        fm.add_separator()
        fm.add_command(label="Import Audio…",     command=self.import_audio)
        fm.add_separator()
        fm.add_command(label="Export Timeline as JSON…", command=self.export_timeline_json)
        fm.add_command(label="Export Prompts as Text…", command=self.export_timeline_text)
        fm.add_separator()
        fm.add_command(label="Exit",              command=self._on_close)

        # Edit
        em = _sub_menu(mb, "Edit")
        em.add_command(label="Delete Selected Block", command=lambda: self.timeline.delete_selected(), accelerator="Del")
        em.add_separator()
        em.add_command(label="Project Settings…", command=self.open_settings)
        em.add_command(label="Variables…",        command=self.open_variables)

        # View
        vm = _sub_menu(mb, "View")
        vm.add_command(label="Zoom In",   command=self.timeline.zoom_in,   accelerator="Ctrl++")
        vm.add_command(label="Zoom Out",  command=self.timeline.zoom_out,  accelerator="Ctrl+-")
        vm.add_command(label="Zoom Fit",  command=self.timeline.zoom_fit,  accelerator="Ctrl+0")
        vm.add_command(label="Zoom Reset",command=self.timeline.zoom_reset)

        # Timeline
        tm = _sub_menu(mb, "Timeline")
        tm.add_command(label="Add Prompt Segment", command=self._add_prompt_here)
        tm.add_command(label="Add Global Modifier",command=self._add_global_here)

        # Process
        pm = _sub_menu(mb, "Process")
        pm.add_command(label="▶ Generate Videos…", command=self.run_processing, accelerator="F5")
        pm.add_separator()
        pm.add_command(label="Test API Connection", command=self._test_api)

        # Help
        hm = _sub_menu(mb, "Help")
        hm.add_command(label="Keyboard Shortcuts", command=self._show_shortcuts)
        hm.add_command(label="About…",             command=self._show_about)

        # Keyboard shortcuts
        self.root.bind("<Control-n>", lambda _: self.new_project())
        self.root.bind("<Control-o>", lambda _: self.open_project())
        self.root.bind("<Control-s>", lambda _: self.save())
        self.root.bind("<Control-S>", lambda _: self.save_as())
        self.root.bind("<F5>",        lambda _: self.run_processing())
        self.root.bind("<Control-equal>", lambda _: self.timeline.zoom_in())
        self.root.bind("<Control-minus>", lambda _: self.timeline.zoom_out())
        self.root.bind("<Control-0>",     lambda _: self.timeline.zoom_fit())

    def _setup_toolbar(self):
        tb = tk.Frame(self.root, bg=HEADER_BG, height=38)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)

        def tbtn(lbl, cmd, tip=""):
            b = tk.Button(tb, text=lbl, command=cmd,
                          bg=BTN_BG, fg=FG, font=("Helvetica", 9),
                          relief=tk.FLAT, padx=10, pady=4, cursor="hand2",
                          activebackground=BTN_HOV, activeforeground=FG,
                          bd=0)
            b.pack(side=tk.LEFT, padx=2, pady=4)
            return b

        def sep():
            tk.Frame(tb, bg=SEP, width=1).pack(side=tk.LEFT, fill=tk.Y,
                                                 pady=6, padx=3)

        tbtn("⊕ New",   self.new_project)
        tbtn("⌂ Open",  self.open_project)
        tbtn("💾 Save",  self.save)
        sep()
        tbtn("♪ Audio", self.import_audio)
        sep()
       #### Live Preview Toggle ###
        self.live_preview_var = tk.BooleanVar(value=False)
        self.live_preview_var.trace_add("write", lambda *_: self.update_live_preview(force=True))
        cb = tk.Checkbutton(tb, text="Live Preview", variable=self.live_preview_var,
                            bg=HEADER_BG, fg=FG, selectcolor=BTN_BG,
                            activebackground=HEADER_BG, activeforeground=FG,
                            anchor="w", cursor="hand2")
        cb.pack(side=tk.LEFT, padx=(6,2), pady=6)
       ############################
        self._play_btn = tbtn("▶ Play",  self.toggle_play)
        tbtn("⏹ Stop",  self.stop_playback)
        sep()
        tbtn("+ Segment", self._add_prompt_here)
        tbtn("+ Global",  self._add_global_here)
        sep()
        tbtn("⚙ Settings", self.open_settings)
        tbtn("$ Variables", self.open_variables)
        sep()

        # Zoom controls
        tk.Label(tb, text="Zoom:", bg=HEADER_BG, fg=FG_DIM,
                 font=("Helvetica", 8)).pack(side=tk.LEFT, padx=(4,2))
        tbtn("−", self.timeline.zoom_out)
        tbtn("+", self.timeline.zoom_in)
        tbtn("Fit", self.timeline.zoom_fit)
        sep()

        # Right side: generate button
        tk.Button(tb, text="▶▶ GENERATE VIDEOS",
                  command=self.run_processing,
                  bg=ACCENT, fg=BLOCK_FG,
                  font=("Helvetica", 9, "bold"),
                  relief=tk.FLAT, padx=14, pady=4,
                  cursor="hand2",
                  activebackground="#3355dd").pack(side=tk.RIGHT, padx=8, pady=4)
    def _setup_layout(self):
        # Main paned window (left sidebar | centre)
        main_pw = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=SEP,
                                  sashwidth=5, sashrelief=tk.FLAT,
                                  handlepad=0)
        main_pw.pack(fill=tk.BOTH, expand=True)

        # Left: variables panel
        self.vars_panel = VariablesPanel(main_pw, self)
        main_pw.add(self.vars_panel, width=210, minsize=150, sticky=tk.NSEW)

        # Right: vertical paned (timeline | block editor)
        right_pw = tk.PanedWindow(main_pw, orient=tk.VERTICAL, bg=SEP,
                                   sashwidth=5, sashrelief=tk.FLAT)
        main_pw.add(right_pw, minsize=400, sticky=tk.NSEW)

        # Timeline
        self.timeline = TimelineCanvas(right_pw, self)
        right_pw.add(self.timeline, minsize=180, sticky=tk.NSEW)

        # Block editor
        self.block_editor = BlockEditorPanel(right_pw, self)
        right_pw.add(self.block_editor, height=160, minsize=100, sticky=tk.NSEW)

        # Status bar
        self.statusbar = StatusBar(self.root, self)
        self.statusbar.pack(fill=tk.X, side=tk.BOTTOM)

    # ─────────────────────────────────────────── Status tick ──────────────────
    def _tick_status(self):
        self.statusbar.set_time()
        self.statusbar.set_zoom(self.timeline.zoom)
        self.statusbar.update_blocks()
        self.root.after(200, self._tick_status)
    # ─────────────────────────────────────────── Live Update ──────────────────
    def update_live_preview(self, force: bool = False):
        """If Live Preview is enabled, update the block editor with the prompt
        that would apply at the current playhead position. If not enabled, restore editor.
        """
        # Guard: if live_preview_var doesn't exist yet, nothing to do
        if not getattr(self, "live_preview_var", None):
                return

        live = bool(self.live_preview_var.get())
        t = self.player.position

        # If live preview is disabled, always restore the normal editor state and return.
        # 'force' must NOT skip this — turning the checkbox off or stopping playback
        # should always restore the editor, not re-run the preview.
        if not live:
                if self.block_editor._blk:
                        self.block_editor.load(self.block_editor._blk, self.block_editor._ti)
                try:
                        self.block_editor._prompt_frame.config(text=" Prompt ")
                        self.block_editor._neg_frame.config(text=" Negative Prompt ")
                        self.block_editor._prompt.config(state=tk.NORMAL, bg=ENTRY_BG)
                        self.block_editor._neg.config(state=tk.NORMAL, bg=ENTRY_BG)
                except Exception:
                        pass
                return

        # Build merged variables as they would be at time t
        proj = self.project
        current_vars = dict(proj.global_vars)
        for gb in proj.sorted_global_blocks():
                if gb.start <= t:
                        current_vars.update(gb.variable_overrides)

        # Find prompt block at time t (if any)
        blk_at_t = None
        for b in proj.prompt_blocks:
                if b.start <= t < b.end:
                        blk_at_t = b
                        break
        if blk_at_t:
                current_vars.update(blk_at_t.variable_overrides)

        # Build final prompt text
        if blk_at_t:
                final_prompt = self.engine._build_prompt(blk_at_t, proj, current_vars)
                neg = getattr(blk_at_t, "negative_prompt", "")
                for k, v in current_vars.items():
                        neg = neg.replace(f"{{{k}}}", v)
        else:
                parts = []
                for gb in proj.sorted_global_blocks():
                        if gb.start <= t < gb.end and gb.prompt.strip():
                                parts.append(gb.prompt.strip())
                final_prompt = ", ".join(parts)
                neg = ""

        # Update block editor text widgets read-only with a visual cue
        try:
                self.block_editor._prompt_frame.config(
                        text=" Live Preview. Read Only while playing/scrubbing... ")
                self.block_editor._neg_frame.config(
                        text=" Live Preview. Read Only while playing/scrubbing... ")
                preview_bg = _darken(ENTRY_BG, 1.6)   # lighten so read-only state is visible
                self.block_editor._prompt.config(state=tk.NORMAL)
                self.block_editor._prompt.delete("1.0", tk.END)
                self.block_editor._prompt.insert("1.0", final_prompt)
                self.block_editor._prompt.config(state=tk.DISABLED, bg=preview_bg)

                self.block_editor._neg.config(state=tk.NORMAL)
                self.block_editor._neg.delete("1.0", tk.END)
                self.block_editor._neg.insert("1.0", neg)
                self.block_editor._neg.config(state=tk.DISABLED, bg=preview_bg)
        except Exception:
                pass

    # ─────────────────────────────────────────── File ops ─────────────────────
    def new_project(self):
        if not self._confirm_unsaved():
            return
        self.player.stop()
        self.project = Project()
        self.timeline.selected = None
        self.block_editor.clear()
        self.vars_panel.refresh()
        self.timeline.redraw()
        self._path = None
        self._mod  = False
        self.root.title(f"{APP_NAME} — Untitled")

    def open_project(self):
        if not self._confirm_unsaved():
            return
        path = filedialog.askopenfilename(
            title="Open Project",
            filetypes=[("WanGP Project", f"*{FILE_EXT}"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            self.project = ProjectSerializer.load(path)
            self._path   = path
            self._mod    = False
            self.timeline.selected = None
            self.block_editor.clear()
            self.vars_panel.refresh()
            self.timeline.redraw()
            self.root.title(f"{APP_NAME} — {self.project.name}")
            # Reload audio
            if self.project.audio_file and os.path.exists(self.project.audio_file):
                self._load_audio(self.project.audio_file)
            self.statusbar.set_status("Project loaded.")
        except Exception as e:
            messagebox.showerror("Open Failed", str(e))

    def save(self) -> bool:
        if self._path is None:
            return self.save_as()
        return self._save_to(self._path)

    def save_as(self) -> bool:
        path = filedialog.asksaveasfilename(
            title="Save Project As",
            defaultextension=FILE_EXT,
            filetypes=[("WanGP Project", f"*{FILE_EXT}"),
                       ("All files", "*.*")])
        if not path:
            return False
        return self._save_to(path)

    def _save_to(self, path: str) -> bool:
        try:
            ProjectSerializer.save(self.project, path)
            self._path = path
            self._mod  = False
            self.root.title(f"{APP_NAME} — {self.project.name}")
            self.statusbar.set_status("Saved.")
            return True
        except Exception as e:
            messagebox.showerror("Save Failed", str(e))
            return False

    def mark_modified(self):
        self._mod = True
        self.statusbar.update_blocks()

    def _confirm_unsaved(self) -> bool:
        if not self._mod:
            return True
        r = messagebox.askyesnocancel("Unsaved Changes",
                                       "Save changes before continuing?")
        if r is None:
            return False
        if r:
            return self.save()
        return True

    def _on_close(self):
        if self._confirm_unsaved():
            self.timeline.stop_tick()
            self.player.stop()
            self.root.destroy()

    # ─────────────────────────────────────────── Audio ────────────────────────
    def import_audio(self):
        path = filedialog.askopenfilename(
            title="Import Audio",
            filetypes=[("Audio files", "*.wav *.mp3 *.ogg *.flac *.aac *.m4a"),
                       ("All files", "*.*")])
        if path:
            self._load_audio(path)

    def _load_audio(self, path: str):
        dur = self.player.load(path)
        self.project.audio_file     = path
        self.project.audio_duration = dur
        self.timeline.load_audio(path)
        self.statusbar.set_status(
            f"Audio: {os.path.basename(path)} ({dur:.1f}s)")
        self.mark_modified()

    # ─────────────────────────────────────────── Export File ──────────────────

    def export_timeline_json(self):
        path = filedialog.asksaveasfilename(
            title="Export Timeline as JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        data = {
            "project": {
                "name": self.project.name,
                "audio_file": self.project.audio_file,
                "audio_duration": self.project.audio_duration,
                "default_width": self.project.default_width,
                "default_height": self.project.default_height,
                "default_fps": self.project.default_fps,
            },
            "global_vars": self.project.global_vars,
            "global_blocks": [dataclasses.asdict(b) for b in self.project.global_blocks],
            "prompt_blocks": [dataclasses.asdict(b) for b in self.project.prompt_blocks],
        }
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            try:
                self.statusbar.set_status(f"Exported timeline → {os.path.basename(path)}")
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    def export_timeline_text(self):
        path = filedialog.asksaveasfilename(
            title="Export Timeline as Text",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        lines = []
        lines.append(f"Project: {self.project.name}")
        lines.append(f"Audio: {self.project.audio_file} ({self.project.audio_duration:.2f}s)")
        lines.append("")
        for b in sorted(self.project.prompt_blocks, key=lambda x: x.start):
            resolved = b.resolve_prompt(self.project.global_vars)
            lines.append(f"Start: {b.start:.3f}s\tDuration: {b.duration:.3f}s\tLabel: {b.label or '(none)'}")
            lines.append(f"Prompt: {resolved}")
            if getattr(b, "negative_prompt", "").strip():
                lines.append(f"Negative: {b.negative_prompt}")
            lines.append("-" * 60)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
            try:
                self.statusbar.set_status(f"Exported prompts → {os.path.basename(path)}")
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    # ─────────────────────────────────────────── Ollama Integration ───────────

    def _call_ollama_generate(self, prompt: str, max_tokens: int = 512, timeout: int = 60) -> str:
        """Call local Ollama-like endpoint and return raw text (no parsing here)."""
        ### Turn off live preview for generation ###
        try:
            if getattr(self, "live_preview_var", None):
                self.live_preview_var.set(False)
        except Exception:
            pass
        if not REQUESTS_OK:
            raise RuntimeError("The 'requests' library is not installed.")
        url = self.project.ollama_url.rstrip("/") + "/api/generate"
        payload = {
            "model": self.project.ollama_model,
            "prompt": prompt,
            "stream": False,
            "max_tokens": max_tokens,
        }
        r = _requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        atext, btext = r.text.split("done_reason")
        return atext

    def _sanitize_model_output(self, raw: str, prefer_longest: bool = True) -> str:
        """Tolerantly extract the most likely prompt text from raw model output.

        Strategy (in order):
          1) Try json.loads(raw) and look for common keys: 'text','response','content','choices'
          2) If JSON present but nested, search recursively for the longest string value
          3) If not JSON or JSON has no useful text, look for triple-backtick code blocks and prefer their contents
          4) Look for explicit 'Prompt:' lines or numbered lists '1. ...'
          5) Look for quoted strings (\"...\") and prefer the longest
          6) Fallback to the longest non-empty line or paragraph
        """
        import re, json

        def _longest_string_in_obj(obj):
            best = ""
            if isinstance(obj, str):
                return obj
            if isinstance(obj, dict):
                for v in obj.values():
                    s = _longest_string_in_obj(v)
                    if len(s) > len(best):
                        best = s
            elif isinstance(obj, list):
                for v in obj:
                    s = _longest_string_in_obj(v)
                    if len(s) > len(best):
                        best = s
            return best or ""

        txt = raw or ""
        txt = txt.strip()

        # 1) Try JSON parse
        try:
            parsed = json.loads(txt)
            # common keys
            for key in ("text", "response", "content", "result"):
                if isinstance(parsed, dict) and key in parsed and isinstance(parsed[key], str) and parsed[key].strip():
                    return parsed[key].strip()
            # choices array
            if isinstance(parsed, dict) and "choices" in parsed and isinstance(parsed["choices"], list) and parsed["choices"]:
                first = parsed["choices"][0]
                if isinstance(first, dict) and "text" in first and isinstance(first["text"], str) and first["text"].strip():
                    return first["text"].strip()
                if isinstance(first, str) and first.strip():
                    return first.strip()
            # fallback: find the longest string anywhere in the JSON
            longest = _longest_string_in_obj(parsed)
            if longest and len(longest) > 10:
                return longest.strip()
        except Exception:
            # not JSON — continue to heuristics
            pass

        # 2) Code block extraction (``` ... ```)
        if "```" in txt:
            parts = txt.split("```")
            # code blocks are odd-indexed parts
            blocks = [parts[i] for i in range(1, len(parts), 2)]
            if blocks:
                best = max((b.strip() for b in blocks if b.strip()), key=len, default="")
                if best:
                    return best

        # 3) Look for explicit "Prompt:" lines
        lines = [l.strip() for l in txt.splitlines() if l.strip()]
        for l in lines:
            if l.lower().startswith("prompt:"):
                return l.split(":", 1)[1].strip()

        # 4) Numbered list "1. ..." or "1) ..."
        for l in lines:
            if re.match(r"^\d+[\.\)]\s+", l):
                # return the first numbered item without the leading number
                return re.sub(r"^\d+[\.\)]\s+", "", l).strip()

        # 5) Quoted strings "..." or '...'
        quotes = re.findall(r'["\']([^"\']{10,})["\']', txt)
        if quotes:
            # prefer the longest quoted string
            return max(quotes, key=len).strip()

        # 6) Heuristic: longest non-global line (ignore lines starting with GLOBAL)
        non_global = [l for l in lines if not l.upper().startswith("GLOBAL")]
        if non_global:
            best = max(non_global, key=len)
            if len(best) > 6:
                return best

        # 7) Longest paragraph fallback
        paras = [p.strip() for p in re.split(r"\n\s*\n", txt) if p.strip()]
        if paras:
            return max(paras, key=len).strip()

        # 8) Last resort: return raw trimmed
        return txt.strip()

    # --- Sequential generator worker ------------------------------------------------
    def start_fill_timeline_sequential(self, segment_count: int, durations: List[float],
                                       user_instruction: str = "", commit_each: bool = True):
        """
        Start a background thread that generates `segment_count` prompts sequentially.
        If commit_each is True, each generated prompt is appended to project.prompt_blocks immediately.
        """
        self.stop_fill_timeline_sequential()

        # Shared control flags
        self._ollama_cancel = False
        self._ollama_running = True
        self._ollama_progress = 0

        def _worker():
            try:
                proj = self.project
                total = proj.audio_duration or sum(durations)
                story_so_far = []  # list of strings (prompts) generated so far
                 # If preserving, start after the last existing prompt block end
                if getattr(self, "project", None) and self.project.prompt_blocks:
                    last_end = max((b.end for b in self.project.prompt_blocks), default=0.0)
                    start_time = last_end
                else:
                    start_time = 0.0
                    proj.prompt_blocks = []

                for i in range(segment_count):
                    if getattr(self, "_ollama_cancel", False):
                        break

                    seg_dur = durations[i] if i < len(durations) else durations[-1]
                    # Build the prompt for this step, include story_so_far as context
                    context_text = "\n".join(f"{idx+1}. {s}" for idx, s in enumerate(story_so_far)) or "(none)"
                    step_prompt = (
                        f"You are writing a visual prompt for a music-video segment.\n"
                        f"Song length: {total:.1f}s. This is segment {i+1} of {segment_count}.\n"
                        f"Segment start: {start_time:.1f}s, duration: {seg_dur:.1f}s.\n"
                        f"High-level instruction: {user_instruction}\n"
                        f"Story so far (previous segments):\n{context_text}\n\n"
                        "Return a single concise prompt (1-2 sentences) for this segment only. "
                        "Do not return JSON. If you include extra commentary, put the prompt in a single line or a code block."
                    )

                    # Call Ollama (non-streaming). Use your r.text split trick if you prefer inside _call_ollama_generate.
                    try:
                        raw = self._call_ollama_generate(step_prompt, max_tokens=400, timeout=60)
                    except Exception as e:
                        # network/model error: stop and notify
                        self._ollama_running = False
                        self._ollama_progress = i
                        try:
                            messagebox.showerror("Fill Timeline Failed", f"Step {i+1} failed: {e}")
                        except Exception:
                            pass
                        return

                    # Sanitize the output (use your existing sanitizer)
                    try:
                        clean = self._sanitize_model_output(raw)
                    except Exception:
                        clean = raw.strip()

                    # Optionally apply your done_reason split if you prefer:
                    # try:
                    #     atext, _ = raw.split("done_reason", 1)
                    #     clean = atext.strip()
                    # except Exception:
                    #     pass

                    # Append to story and optionally commit as a PromptBlock
                    story_so_far.append(clean)
                    if commit_each:
                        bid = str(uuid.uuid4())
                        #pb = PromptBlock(bid=bid, start=start_time, duration=seg_dur, prompt=clean, label=f"Segment {i+1}")
                        # Use timeline helper to pick the next palette color
                        color = self.timeline._next_color() if hasattr(self, "timeline") else "#1e5a9e"
                        pb = PromptBlock(bid=bid, start=start_time, duration=seg_dur,
                                         prompt=clean, label=f"Segment {i+1}", color=color)
                        proj.prompt_blocks.append(pb)
                        # update UI on main thread
                        try:
                            self.root.after(0, self.timeline.redraw)
                            #self.timeline.redraw() # Unsafe b/c not on Main Thread
                        except Exception:
                            pass

                    # Update progress
                    self._ollama_progress = i + 1
                    try:
                        # update a status label if you have one
                        if hasattr(self, "statusbar"):
                            self.statusbar.set_status(f"Ollama: generated {self._ollama_progress}/{segment_count}")
                    except Exception:
                        pass

                    # Advance start time
                    start_time += seg_dur

                    # Small delay to avoid hammering the model (optional)
                    time.sleep(0.2)

                # finished
                self._ollama_running = False
                try:
                    self.mark_modified()
                except Exception:
                    pass
                try:
                    messagebox.showinfo("Fill Timeline", f"Generated {len(story_so_far)} segments.")
                except Exception:
                    pass
            finally:
                self._ollama_running = False
                if hasattr(self, "_preserve_flag"):
                    del self._preserve_flag

        # Start worker thread
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        self._ollama_thread = t

    def stop_fill_timeline_sequential(self):
        """Signal the running sequential generator to stop."""
        if getattr(self, "_ollama_running", False):
            self._ollama_cancel = True
            # Optionally wait a short time for thread to stop
            for _ in range(20):
                if not getattr(self, "_ollama_running", False):
                    break
                time.sleep(0.05)

    # ─────────────────────────────────────────── Ollama Call Helper ─────────
   
    def generate_prompts_with_ollama(self, blocks: List[PromptBlock], sequential: bool = True, video_description: str = ""):
        """
        Generate positive and negative prompts for each block using Ollama.
        If sequential=True, run one-by-one (stoppable via self._ollama_cancel).
        This runs in a background thread and updates blocks in-place.
        """
        # Ensure Live Preview is off to avoid conflict with prompt data
        try:
            if getattr(self, "live_preview_var", None):
                self.live_preview_var.set(False)
        except Exception:
            pass

        # control flags
        self._ollama_cancel = False
        self._ollama_running = True

        def _worker():
            try:
                for i, blk in enumerate(blocks):
                    if getattr(self, "_ollama_cancel", False):
                        break

                    total_dur = self.project.audio_duration or 60.0

                    # Build prompt including the user-provided video description
                    prompt = (
                        "You are a creative assistant that writes concise visual prompts for image/video generation.\n\n"
                        f"Project description: {video_description}\n\n"
                        f"Segment start: {blk.start:.1f}s; duration: {blk.duration:.1f}s; "
                        f"Song length: {total_dur:.1f}s.\n"
                        f"Project globals: {self.project.global_vars}\n"
                        f"Segment label: {blk.label}\n\n"
                        "Return a single concise positive prompt (1-2 sentences) suitable for image/video generation."
                    )

                    try:
                        raw_out = self._call_ollama_generate(prompt, max_tokens=400, timeout=60)
                        positive = self._sanitize_model_output(raw_out).strip()
                    except Exception as e:
                        # handle/log error, optionally continue
                        break

                    # Negative prompt
                    neg_prompt = (
                        "Given the following positive prompt, write a concise negative prompt "
                        "(things to avoid, undesired elements, artifacts) suitable for image/video generation.\n\n"
                        f"Positive prompt: {positive}\n\n"
                        "Return a short single-line negative prompt."
                    )
                    try:
                        raw_neg = self._call_ollama_generate(neg_prompt, max_tokens=200, timeout=60)
                        negative = self._sanitize_model_output(raw_neg).strip()
                    except Exception:
                        negative = ""

                    blk.prompt = positive
                    blk.negative_prompt = negative

                    # Update UI on main thread
                    try:
                        self.root.after(0, self.timeline.redraw)
                    except Exception:
                        pass

                    if sequential:
                        time.sleep(0.15)
            finally:
                self._ollama_running = False
                try:
                    self.mark_modified()
                except Exception:
                    pass

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        self._ollama_thread = t



    # ─────────────────────────────────────────── Playback ─────────────────────
    def toggle_play(self):
        if self.player.is_playing:
            self.player.pause()
            self._play_btn.config(text="▶ Play")
            # Restore Editor if live preview is off #
            self.update_live_preview(force=True)
        else:
            self.player.play()
            self._play_btn.config(text="⏸ Pause")
            # Update Preview immediately #
            self.update_live_preview(force=True)

    def stop_playback(self):
        self.player.stop()
        self._play_btn.config(text="▶ Play")
        self.timeline.redraw()

    # ─────────────────────────────────────────── Blocks ───────────────────────
    def _add_prompt_here(self):
        t = self.player.position
        self.timeline.add_prompt_block(t)

    def _add_global_here(self):
        t = self.player.position
        self.timeline.add_global_block(t)

    # ─────────────────────────────────────────── Dialogs ──────────────────────
    def open_settings(self):
        SettingsDialog(self.root, self)

    def open_variables(self):
        _VariablesDialog(self.root, self)

    # ─────────────────────────────────────────── Processing ───────────────────
    def run_processing(self):
        if not self.project.prompt_blocks:
            messagebox.showwarning("No Segments",
                "Add at least one Prompt Segment before generating.")
            return
        dlg = ProcessDialog(self.root, self)
        self.engine.run(dlg)

    def _test_api(self):
        if not REQUESTS_OK:
            messagebox.showerror("Missing Library",
                "The 'requests' library is not installed.\nRun: pip install requests")
            return
        url = self.project.wangp_url.rstrip("/") + "/info"
        try:
            r = _requests.get(url, timeout=5)
            messagebox.showinfo("Connection OK",
                f"Connected to WanGP.\nURL: {url}\nStatus: {r.status_code}")
        except Exception as e:
            messagebox.showerror("Connection Failed",
                f"Could not reach WanGP at:\n{url}\n\nError: {e}\n\n"
                "Check that WanGP is running and the URL is correct in "
                "Project Settings.")

    # ─────────────────────────────────────────── Help ─────────────────────────
    def _show_shortcuts(self):
        shortcuts = [
            ("Ctrl+N",        "New Project"),
            ("Ctrl+O",        "Open Project"),
            ("Ctrl+S",        "Save"),
            ("F5",            "Generate Videos"),
            ("Ctrl + Scroll", "Zoom in/out timeline"),
            ("Middle drag",   "Pan timeline"),
            ("Scroll",        "Scroll timeline"),
            ("Double-click",  "Add block / edit block"),
            ("Right-click",   "Context menu"),
            ("Delete",        "Delete selected block"),
            ("Ctrl+0",        "Zoom to fit"),
        ]
        dlg = tk.Toplevel(self.root)
        dlg.title("Keyboard Shortcuts")
        dlg.configure(bg=BG)
        dlg.geometry("380x340")
        dlg.transient(self.root)
        dlg.grab_set()

        for i, (k, v) in enumerate(shortcuts):
            bg = TRACK_EVEN if i % 2 == 0 else TRACK_ODD
            row = tk.Frame(dlg, bg=bg)
            row.pack(fill=tk.X)
            tk.Label(row, text=k, bg=bg, fg=WAVEFORM_C,
                     font=("Courier", 9, "bold"), width=18, anchor=tk.W,
                     padx=12, pady=4).pack(side=tk.LEFT)
            tk.Label(row, text=v, bg=bg, fg=FG,
                     font=("Helvetica", 9), anchor=tk.W,
                     padx=6, pady=4).pack(side=tk.LEFT)

        _dark_btn(dlg, "Close", dlg.destroy, accent=True).pack(pady=10)

    def _show_about(self):
        about = (
            f"{APP_NAME}  v{APP_VERSION}\n\n"
            "Prompt-driven video segment timeline editor\n"
            "for WanGP AI video generation.\n\n"
            "Dependencies:\n"
            f"  pygame   {'✔' if PYGAME_OK else '✗ (audio disabled)'}\n"
            f"  Pillow   {'✔' if PIL_OK else '✗ (optional)'}\n"
            f"  requests {'✔' if REQUESTS_OK else '✗ (API disabled)'}\n"
            f"  ffmpeg   (must be on PATH)\n\n"
            "Double-click empty timeline area to add blocks.\n"
            "Drag blocks to move, drag edges to resize."
        )
        messagebox.showinfo("About", about)

    # ─────────────────────────────────────────── Run ──────────────────────────
    def run(self):
        self.root.mainloop()


###############################################################################
# STANDALONE DIALOGS (helpers)
###############################################################################

class _VarEditDialog(tk.Toplevel):
    def __init__(self, parent, key: str, value: str):
        super().__init__(parent)
        self.result = None
        self.title("Edit Variable")
        self.configure(bg=BG)
        self.geometry("340x140")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        f = tk.Frame(self, bg=PANEL_BG)
        f.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(f, text="Name:", bg=PANEL_BG, fg=FG, width=8,
                 anchor=tk.E, font=("Helvetica", 9)).grid(row=0, column=0, pady=4)
        self._k = _dark_entry(f, width=22)
        self._k.insert(0, key)
        self._k.grid(row=0, column=1, padx=6, pady=4)

        tk.Label(f, text="Value:", bg=PANEL_BG, fg=FG, width=8,
                 anchor=tk.E, font=("Helvetica", 9)).grid(row=1, column=0, pady=4)
        self._v = _dark_entry(f, width=22)
        self._v.insert(0, value)
        self._v.grid(row=1, column=1, padx=6, pady=4)

        bot = tk.Frame(self, bg=BG)
        bot.pack(fill=tk.X, padx=10, pady=6)
        _dark_btn(bot, "Cancel", self.destroy).pack(side=tk.RIGHT, padx=4)
        _dark_btn(bot, "OK", self._ok, accent=True).pack(side=tk.RIGHT)

        self._k.focus_set()
        self.wait_window()

    def _ok(self):
        self.result = (self._k.get().strip(), self._v.get())
        self.destroy()


class _VariablesDialog(tk.Toplevel):
    """Standalone variables editor (mirrors VariablesPanel but in a window)."""
    def __init__(self, parent, app: "App"):
        super().__init__(parent)
        self.app = app
        self.title("Global Variables")
        self.configure(bg=BG)
        self.geometry("440x360")
        self.transient(parent)
        self.grab_set()
        self._build()
        self._refresh()
        self.wait_window()

    def _build(self):
        tk.Label(self, text="Global Variables", bg=BG, fg=FG,
                 font=("Helvetica", 11, "bold")).pack(pady=(12, 4))
        tk.Label(self,
                 text="Reference these in any prompt with {variable_name}",
                 bg=BG, fg=FG_DIM, font=("Helvetica", 8)).pack()

        cols = ("name", "value")
        self.tree = ttk.Treeview(self, columns=cols, show="headings",
                                  selectmode="browse", height=10)
        self.tree.heading("name",  text="Variable")
        self.tree.heading("value", text="Value")
        self.tree.column("name",  width=130)
        self.tree.column("value", width=240)
        _apply_tree_style(self.tree)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
        self.tree.bind("<Double-Button-1>", self._edit)

        bb = tk.Frame(self, bg=BG)
        bb.pack(fill=tk.X, padx=12, pady=(0, 8))
        _dark_btn(bb, "Add",    self._add).pack(side=tk.LEFT, padx=2)
        _dark_btn(bb, "Edit",   self._edit).pack(side=tk.LEFT, padx=2)
        _dark_btn(bb, "Delete", self._del).pack(side=tk.LEFT, padx=2)
        _dark_btn(bb, "Close",  self.destroy, accent=True).pack(side=tk.RIGHT)

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        for k, v in self.app.project.global_vars.items():
            self.tree.insert("", tk.END, values=(k, v))
        self.app.vars_panel.refresh()

    def _add(self):
        d = _VarEditDialog(self, "", "")
        if d.result:
            k, v = d.result
            if k:
                self.app.project.global_vars[k] = v
                self._refresh()
                self.app.mark_modified()

    def _edit(self, _e=None):
        sel = self.tree.selection()
        if not sel: return
        k, v = self.tree.item(sel[0])["values"]
        d = _VarEditDialog(self, k, v)
        if d.result:
            nk, nv = d.result
            if nk:
                del self.app.project.global_vars[k]
                self.app.project.global_vars[nk] = nv
                self._refresh()
                self.app.mark_modified()

    def _del(self):
        sel = self.tree.selection()
        if not sel: return
        k = self.tree.item(sel[0])["values"][0]
        del self.app.project.global_vars[k]
        self._refresh()
        self.app.mark_modified()


###############################################################################
# UI HELPERS
###############################################################################

def _dark_menu(parent) -> tk.Menu:
    return tk.Menu(parent, tearoff=0, bg=BTN_BG, fg=FG,
                   activebackground=BTN_HOV, activeforeground=FG,
                   relief=tk.FLAT, bd=0)

def _sub_menu(mb: tk.Menu, label: str) -> tk.Menu:
    m = _dark_menu(mb)
    mb.add_cascade(label=label, menu=m)
    return m

def _dark_btn(parent, text: str, command=None, accent=False,
              pad=8) -> tk.Button:
    bg = ACCENT if accent else BTN_BG
    ab = "#3355dd" if accent else BTN_HOV
    return tk.Button(parent, text=text, command=command,
                     bg=bg, fg=BLOCK_FG if accent else FG,
                     font=("Helvetica", 8),
                     relief=tk.FLAT, padx=pad, pady=3,
                     cursor="hand2",
                     activebackground=ab, activeforeground=BLOCK_FG,
                     bd=0)

def _dark_entry(parent, **kw) -> tk.Entry:
    kw.setdefault("bg", ENTRY_BG)
    kw.setdefault("fg", FG)
    kw.setdefault("insertbackground", FG)
    kw.setdefault("relief", tk.FLAT)
    kw.setdefault("font", ("Helvetica", 9))
    kw.setdefault("highlightthickness", 1)
    kw.setdefault("highlightbackground", SEP)
    kw.setdefault("highlightcolor", ACCENT)
    return tk.Entry(parent, **kw)

def _dark_text(parent, **kw) -> tk.Text:
    kw.setdefault("bg", ENTRY_BG)
    kw.setdefault("fg", FG)
    kw.setdefault("insertbackground", FG)
    kw.setdefault("relief", tk.FLAT)
    kw.setdefault("font", ("Helvetica", 9))
    kw.setdefault("wrap", tk.WORD)
    kw.setdefault("highlightthickness", 1)
    kw.setdefault("highlightbackground", SEP)
    kw.setdefault("highlightcolor", ACCENT)
    kw.setdefault("selectbackground", ACCENT)
    return tk.Text(parent, **kw)

def _lf_entry(parent, label: str, row: int) -> tk.StringVar:
    tk.Label(parent, text=label + ":", bg=PANEL_BG, fg=FG,
             font=("Helvetica", 9), width=18, anchor=tk.E).grid(
        row=row, column=0, padx=(12, 4), pady=5, sticky=tk.E)
    var = tk.StringVar()
    _dark_entry(parent, textvariable=var, width=28).grid(
        row=row, column=1, padx=(0, 12), pady=5, sticky=tk.EW)
    return var

def _apply_tree_style(tree: ttk.Treeview):
    tree.tag_configure("odd",  background=TRACK_ODD)
    tree.tag_configure("even", background=TRACK_EVEN)

def _apply_notebook_style(nb: ttk.Notebook):
    pass  # handled by ttk.Style globally

def _darken(hex_col: str, factor: float) -> str:
    """Return a darkened version of a hex colour."""
    try:
        hex_col = hex_col.lstrip("#")
        r, g, b = (int(hex_col[i:i+2], 16) for i in (0, 2, 4))
        r = int(r * factor); g = int(g * factor); b = int(b * factor)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_col

# Minimal 16×16 app icon (base64 PNG, blank purple square)
_ICON_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAABHNCSVQICAgIfAhkiAAAAAlwSFlz"
    "AAALEwAACxMBAJqcGAAAABZ0RVh0Q3JlYXRpb24gVGltZQAxMC8yOS8xMiKqq3kAAAAcdEVYdFNv"
    "ZnR3YXJlAEFkb2JlIEZpcmV3b3JrcyBDUzVxteM2AAABHklEQVQ4jZWTMU7DQBBF3ya2E4+dH4"
    "SKkBDiAFRcgYoTcAEOwAE4ABWlolTcgANQIYSQkBBCiB07jr2zFCsbaRM2ySujt/P+7M7MKmst"
    "SimllHPu3Xu/dc5Za+0ZERERkRljzMEYY9Zae0FERERERERERERERERERERERERERERERERERERE"
    "RERERERERERERERERERERERAAAD//wMAUEsDBBQAAAAIAAAAIQAAACcAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAABQAE8AQwBBAEwATABJAFMAVABBAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
)


###############################################################################
# ENTRY POINT
###############################################################################

if __name__ == "__main__":
    app = App()
    app.run()