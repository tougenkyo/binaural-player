#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
binaural_player.py  -  Spatial Multi Player
対応フォーマット: WAV / FLAC / OGG / AIFF / MP3 / AAC(M4A) / OPUS
"""
from __future__ import annotations

# ──────────────────────────────────────────────────────
# Bootstrap: 初回起動時に必要なライブラリを自動インストールする
# ──────────────────────────────────────────────────────
# 標準ライブラリだけで動く必要があるため、ここでは import を最小限にする

import subprocess
import sys


def _bootstrap() -> None:
    """
    必要なサードパーティライブラリが揃っているか確認し、
    不足している場合は pip install を実行してから再起動する。
    tkinter は標準ライブラリなので pip 不要。
    """
    REQUIRED = [
        ("numpy",       "numpy"),
        ("sounddevice", "sounddevice"),
        ("soundfile",   "soundfile"),
        ("tkinterdnd2", "tkinterdnd2"),
    ]
    missing = []
    for import_name, pip_name in REQUIRED:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)

    if not missing:
        return  # 全て揃っている

    # tkinter だけは常に使える想定（Python 標準バンドル）
    try:
        import tkinter as _tk
        import tkinter.messagebox as _mb
        root = _tk.Tk()
        root.withdraw()
        answer = _mb.askyesno(
            "初回セットアップ / First-time Setup",
            "必要なライブラリが見つかりません。\n"
            "今すぐインストールしますか？\n\n"
            "Missing libraries:\n  " + "\n  ".join(missing) + "\n\n"
            "Required libraries not found.\n"
            "Install them now?",
        )
        root.destroy()
        if not answer:
            sys.exit(0)
    except Exception:
        # tkinter も使えない環境はコンソールで確認
        print(f"Missing: {missing}")
        ans = input("Install now? [y/N]: ").strip().lower()
        if ans != "y":
            sys.exit(0)

    print(f"Installing: {missing}")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install"] + missing,
        stdout=subprocess.PIPE,
    )

    # インストール後に再起動してクリーンな状態で動かす
    print("Restarting...")
    import os
    os.execv(sys.executable, [sys.executable] + sys.argv)


_bootstrap()

# ──────────────────────────────────────────────────────
# 通常の import（bootstrap 後は必ず揃っている）
# ──────────────────────────────────────────────────────

import json
import os
import platform
import random
import shutil
import threading
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional
from urllib.request import urlretrieve

import numpy as np
import sounddevice as sd
import soundfile as sf
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinterdnd2 import TkinterDnD, DND_FILES


# ──────────────────────────────────────────────────────
# i18n  /  Theme
# ──────────────────────────────────────────────────────

# language フォルダのパス（スクリプトと同階層）
_LANG_DIR = Path(__file__).parent / "language"

# 起動時に _LANG_DIR 内の *.json を全て読み込んで STRINGS に格納する
# ファイル名（拡張子なし）がキー（例: "en", "ja", "fr"）になる
STRINGS: dict[str, dict[str, str]] = {}

# ハードコードされたフォールバック（language フォルダが存在しない場合用）
_FALLBACK: dict[str, str] = {
    "ch1": "Channel 1", "ch2": "Channel 2",
    "btn_play": "▶  Play", "btn_stop": "⏹  Stop",
    "btn_seq": "🔁  Sequential", "btn_rnd": "🔀  Random",
    "btn_del": "🗑 Delete", "drop_hint": "Drop files here",
    "drop_label": "▲ Drop files  |  Del",
    "elevation": "Elevation", "az_random": "Azimuth Random",
    "rnd_header": "Random", "volume": "Volume", "speed": "Speed%",
    "loading": "⏳ Loading...",
    "btn_both": "⏯  Play Both", "btn_stop_all": "⏹  Stop All",
    "btn_new": "🆕  New", "btn_save": "💾  Save", "btn_load": "📂  Load",
    "status_init": "Drop audio files to start",
    "dark_mode": "Dark Mode", "language": "Language",
    "dlg_stop_title": "Stop", "dlg_stop_msg": "Stop playback?",
    "dlg_new_title": "Confirm", "dlg_new_msg": "Reset all settings?",
    "dlg_no_file": "No Files", "dlg_no_file_msg": "Drop files first.",
    "dlg_load_err": "Error", "dlg_save_err": "Error",
    "dlg_save_err_msg": "Save failed.", "dlg_load_warn": "Warning",
    "dlg_load_warn_msg": "Invalid file.", "dlg_no_added": "Nothing Added",
    "dlg_no_added_msg": "No valid files.", "ffmpeg_ready": "FFmpeg Ready",
    "ffmpeg_ready_msg": "FFmpeg installed.", "status_saved": "Saved: ",
    "status_loaded": "Loaded: ", "status_failed": "Save failed",
    "status_stopped": "Stopped", "status_both": "Playing both...",
    "status_reset": "Reset to defaults", "restart_msg": "Restart to apply.",
}


def _load_language_files() -> None:
    """
    language/ フォルダ内の *.json をすべて読み込み STRINGS を更新する。
    ファイル名（小文字・拡張子なし）が言語コードになる。
    例: language/en.json → STRINGS["en"]
        language/ja.json → STRINGS["ja"]
        language/fr.json → STRINGS["fr"]  ← 追加するだけで自動認識
    """
    global STRINGS
    if not _LANG_DIR.is_dir():
        _LANG_DIR.mkdir(parents=True, exist_ok=True)
    for json_file in sorted(_LANG_DIR.glob("*.json")):
        lang_code = json_file.stem.lower()
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                STRINGS[lang_code] = data
        except Exception as exc:
            print(f"[i18n] Failed to load {json_file.name}: {exc}")

    # フォールバック: en が読み込めなかった場合にハードコードを使う
    if "en" not in STRINGS:
        STRINGS["en"] = _FALLBACK


def get_available_langs() -> list[str]:
    """language/ フォルダにある言語コードの一覧を大文字で返す。"""
    return sorted(k.upper() for k in STRINGS)


# 起動時に読み込む
_load_language_files()


THEMES: dict[str, dict[str, str]] = {
    "light": {
        "bg":         "SystemButtonFace",
        "fg":         "#000000",
        "listbox_bg": "white",
        "listbox_fg": "#000000",
        "hint_fg":    "#aaaaaa",
        "sub_fg":     "#555555",
        "dim_fg":     "#888888",
    },
    "dark": {
        "bg":         "#1e1e2e",
        "fg":         "#cdd6f4",
        "listbox_bg": "#181825",
        "listbox_fg": "#cdd6f4",
        "hint_fg":    "#585b70",
        "sub_fg":     "#a6adc8",
        "dim_fg":     "#6c7086",
    },
}

# 起動時に settings から読み込む（デフォルト: en / light）
_CURRENT_LANG:  str = "en"
_CURRENT_THEME: str = "light"


def _t(key: str) -> str:
    """現在の言語設定で文字列を返す。キーが存在しない場合は en にフォールバック。"""
    return STRINGS.get(_CURRENT_LANG, STRINGS.get("en", _FALLBACK)).get(
        key, STRINGS.get("en", _FALLBACK).get(key, key)
    )


def _th(key: str) -> str:
    """現在のテーマで色を返す。"""
    return THEMES.get(_CURRENT_THEME, THEMES["light"]).get(key, "")


def _apply_globals(saved: dict) -> None:
    """settings から言語・テーマ設定を読み込んでグローバルに反映する。"""
    global _CURRENT_LANG, _CURRENT_THEME
    lang = saved.get("lang", "en").lower()
    # 保存された言語が存在しない場合は en にフォールバック
    _CURRENT_LANG  = lang if lang in STRINGS else "en"
    _CURRENT_THEME = saved.get("theme", "light")


def _restart_app() -> None:
    """現在の Python インタープリターでスクリプトを再起動する。"""
    os.execv(sys.executable, [sys.executable] + sys.argv)



# ──────────────────────────────────────────────────────

SF_NATIVE_EXT     = {".wav", ".flac", ".ogg", ".aif", ".aiff"}
FFMPEG_EXT        = {".mp3", ".m4a", ".aac", ".opus"}
ALL_SUPPORTED_EXT = SF_NATIVE_EXT | FFMPEG_EXT


# ──────────────────────────────────────────────────────
# パス定義
# ──────────────────────────────────────────────────────

_BASE_DIR     = Path(__file__).parent
_CONFIG_DIR   = _BASE_DIR / "config"
_FFMPEG_DIR   = _BASE_DIR / "ffmpeg_bin"
_FFMPEG_EXE   = _FFMPEG_DIR / ("ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg")
SETTINGS_PATH = _CONFIG_DIR / "spatial_multi_player_setting.json"
FFMPEG_DL_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


# ──────────────────────────────────────────────────────
# Enum / Dataclasses
# ──────────────────────────────────────────────────────

class PlayMode(Enum):
    SEQUENTIAL = "sequential"
    RANDOM     = "random"


@dataclass
class BinauralPosition:
    azimuth:  float
    distance: float


@dataclass(frozen=True)
class AudioFile:
    path: Path

    @property
    def display_name(self) -> str:
        return self.path.name


# ──────────────────────────────────────────────────────
# FFmpeg 管理
# ──────────────────────────────────────────────────────

def get_ffmpeg_path() -> Optional[str]:
    if _FFMPEG_EXE.is_file():
        return str(_FFMPEG_EXE)
    return shutil.which("ffmpeg")


def ffmpeg_available() -> bool:
    return get_ffmpeg_path() is not None


def verify_ffmpeg(exe: str) -> bool:
    try:
        r = subprocess.run([exe, "-version"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def download_ffmpeg_windows(progress_cb=None) -> bool:
    if platform.system() != "Windows":
        return False
    _FFMPEG_DIR.mkdir(parents=True, exist_ok=True)

    def _report(msg):
        if progress_cb:
            progress_cb(msg)
        print(f"[FFmpeg] {msg}")

    try:
        _report("Downloading FFmpeg... (approx 100MB, may take a few minutes)")
        tmp_zip = _FFMPEG_DIR / "ffmpeg_dl.zip"

        def _hook(count, block_size, total_size):
            if total_size > 0 and progress_cb:
                progress_cb(f"Downloading... {min(int(count*block_size*100/total_size),100)}%")

        urlretrieve(FFMPEG_DL_URL, str(tmp_zip), reporthook=_hook)
        _report("Extracting ZIP...")

        with zipfile.ZipFile(str(tmp_zip), "r") as zf:
            for name in zf.namelist():
                if name.endswith("bin/ffmpeg.exe"):
                    (_FFMPEG_DIR / Path(name).name).write_bytes(zf.read(name))

        tmp_zip.unlink(missing_ok=True)

        if _FFMPEG_EXE.is_file() and verify_ffmpeg(str(_FFMPEG_EXE)):
            _report("FFmpeg installed and verified")
            return True
        _report("ffmpeg.exe not found after extraction")
        return False
    except Exception as exc:
        _report(f"Download failed: {exc}")
        return False


class FFmpegSetupDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title(_t("ffmpeg_title"))
        self.resizable(False, False)
        self.grab_set()
        self.result = False
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_skip)

    def _build(self):
        is_win = platform.system() == "Windows"
        tk.Label(self, text=_t("ffmpeg_subtitle"),
                 font=("", 11, "bold"), justify=tk.CENTER).pack(padx=16, pady=(12, 4))
        tk.Label(self, text=_t("ffmpeg_not_found"),
                 justify=tk.LEFT).pack(padx=16, pady=(0, 6))
        if is_win:
            af = tk.LabelFrame(self, text=_t("ffmpeg_auto_label"), padx=8, pady=6)
            af.pack(fill=tk.X, padx=16, pady=(0, 6))
            tk.Label(af, text=f"{_t('ffmpeg_dl_url_label')}\n{FFMPEG_DL_URL}",
                     fg="#444", font=("", 9), justify=tk.LEFT, wraplength=420).pack(anchor="w", pady=(0, 6))
            self._progress_var = tk.StringVar(value="")
            tk.Label(af, textvariable=self._progress_var, fg="#1565C0", font=("", 9)).pack(anchor="w")
            self._dl_btn = tk.Button(af, text=_t("ffmpeg_dl_btn"),
                                     command=self._auto_download, bg="#1565C0", fg="white",
                                     font=("", 10, "bold"), relief=tk.FLAT, padx=12, pady=5, cursor="hand2")
            self._dl_btn.pack(pady=(6, 0))
        num = "②" if is_win else "①"
        mf = tk.LabelFrame(self, text=f"{num} {_t('ffmpeg_manual_label')}", padx=8, pady=6)
        mf.pack(fill=tk.X, padx=16, pady=(0, 6))

        # 編集不可・選択可のテキストエリア
        manual_text = _t("ffmpeg_manual_win") if is_win else _t("ffmpeg_manual_other")
        txt = tk.Text(mf, height=6, font=("", 9), relief=tk.FLAT, bd=1,
                      wrap=tk.WORD, cursor="arrow",
                      bg="#f5f5f5", fg="#333")
        txt.insert("1.0", manual_text)
        txt.configure(state=tk.DISABLED)   # 編集不可・選択はできる
        txt.pack(fill=tk.X, pady=(0, 6))

        # クリック可能なリンク
        links_frame = tk.Frame(mf)
        links_frame.pack(anchor="w")
        tk.Label(links_frame, text="🔗 ", font=("", 9)).pack(side=tk.LEFT)
        link = tk.Label(links_frame,
                        text="https://ffmpeg.org/download.html",
                        font=("", 9, "underline"), fg="#1565C0", cursor="hand2")
        link.pack(side=tk.LEFT)
        link.bind("<Button-1>", lambda _: __import__("webbrowser").open("https://ffmpeg.org/download.html"))
        tk.Label(self, text=_t("ffmpeg_skip_note"),
                 fg="#888", font=("", 8), justify=tk.LEFT).pack(padx=16, pady=(0, 4))
        tk.Button(self, text=_t("ffmpeg_skip_btn"), command=self._on_skip,
                  relief=tk.FLAT, padx=12, pady=4).pack(pady=(0, 12))

    def _auto_download(self):
        self._dl_btn.config(state=tk.DISABLED, text=_t("ffmpeg_downloading"))

        def _cb(msg: str) -> None:
            self.after(0, lambda m=msg: self._progress_var.set(m))

        def _run() -> None:
            ok = download_ffmpeg_windows(progress_cb=_cb)
            self.after(0, lambda: self._on_download_done(ok))

        threading.Thread(target=_run, daemon=True).start()

    def _on_download_done(self, ok):
        if ok:
            self.result = True
            messagebox.showinfo(_t("ffmpeg_done_title"), _t("ffmpeg_done_msg"), parent=self)
            self.destroy()
        else:
            self._progress_var.set(_t("ffmpeg_failed_msg"))
            self._dl_btn.config(state=tk.NORMAL, text=_t("ffmpeg_retry_btn"))

    def _on_skip(self):
        self.result = False
        self.destroy()


def check_and_setup_ffmpeg(parent) -> bool:
    if ffmpeg_available():
        return True
    dlg = FFmpegSetupDialog(parent)
    parent.wait_window(dlg)
    return dlg.result


# ──────────────────────────────────────────────────────
# 音声読み込み
# ──────────────────────────────────────────────────────

def _read_via_ffmpeg(path: Path) -> tuple[np.ndarray, int]:
    exe = get_ffmpeg_path()
    if exe is None:
        raise RuntimeError("FFmpeg が見つかりません。")
    if not verify_ffmpeg(exe):
        raise RuntimeError(f"FFmpeg の実行に失敗しました: {exe}")
    TARGET_SR = 44100
    cmd = [exe, "-y", "-i", str(path), "-vn",
           "-ar", str(TARGET_SR), "-ac", "2", "-f", "f32le", "pipe:1"]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"FFmpeg がタイムアウトしました: {path.name}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError(f"FFmpeg 実行ファイルが見つかりません: {exe}") from exc
    if result.returncode != 0:
        err_tail = "\n".join(result.stderr.decode("utf-8", errors="replace").strip().splitlines()[-5:])
        raise RuntimeError(f"FFmpeg デコード失敗 (code {result.returncode}):\n{err_tail}")
    if len(result.stdout) == 0:
        raise RuntimeError(f"FFmpeg の出力が空でした: {path.name}")
    return np.frombuffer(result.stdout, dtype="<f4").reshape(-1, 2), TARGET_SR


def read_audio(path: Path) -> tuple[np.ndarray, int]:
    suffix = path.suffix.lower()
    if suffix in SF_NATIVE_EXT:
        data, sr = sf.read(str(path), always_2d=True)
        return data.astype(np.float32), sr
    if suffix in FFMPEG_EXT:
        return _read_via_ffmpeg(path)
    raise ValueError(f"非対応の拡張子: {suffix}")


# ──────────────────────────────────────────────────────
# バイノーラル計算ユーティリティ
# ──────────────────────────────────────────────────────

_REF_DIST = 0.5


def _apply_rear_lpf(signal: np.ndarray, rear_amount: float, sr: int) -> np.ndarray:
    """
    後方定位のための高域減衰フィルター（1次 IIR ローパス）。

    rear_amount: 0.0（真正面）〜 1.0（真後方）
    後方ほど高域が減衰し「こもった感じ」になる。

    scipy を使わず numpy で実装することで：
    ・チャンク処理で zi 状態を持つ必要がない
    ・金属音（位相歪み・コムフィルター）が発生しない
    ・バッファ全体に一括適用するためクリックが出ない
    """
    if rear_amount < 0.05:
        return signal

    # カットオフ周波数: 前方 = ほぼ素通し / 後方 = 4000Hz 程度
    # RC フィルター係数 α = dt / (RC + dt), dt = 1/sr
    cutoff_hz = 16000 - rear_amount * 12000   # 16kHz〜4kHz
    rc = 1.0 / (2.0 * np.pi * cutoff_hz)
    dt = 1.0 / sr
    alpha = float(dt / (rc + dt))            # 0 に近いほどカット強い

    # 1次 IIR: y[n] = alpha * x[n] + (1 - alpha) * y[n-1]
    # numpy の cumsum を使ったベクトル実装（ループなしで高速）
    # 参考: y = α * x の累積和を (1-α)^k で重み付けすると等価
    out = np.empty_like(signal)
    prev = signal[0]
    beta = 1.0 - alpha
    for i in range(len(signal)):
        prev = alpha * signal[i] + beta * prev
        out[i] = prev
    return out.astype(np.float32)


def compute_stereo(
    mono:   np.ndarray,
    pos:    BinauralPosition,
    volume: int,
    sr:     int = 44100,
) -> np.ndarray:
    """
    モノラル音声をステレオに変換する。

    左右定位: sin(アジマス) によるゲイン差
    前後定位:
      ・後方（|az| > 90°）は音量を最大 20% 下げる
      ・後方は高域を緩やかにカット（1次 IIR LPF、金属音なし）
    これにより -20° と -160° の聞こえ方が異なるようになる。
    """
    az   = np.radians(np.clip(pos.azimuth, -180, 180))
    dist = max(0.05, pos.distance)

    # ── 左右パンニング ──────────────────────────────
    pan_r = float(np.clip(0.5 + 0.5 * np.sin(az), 0.0, 1.0))
    pan_l = float(np.clip(0.5 - 0.5 * np.sin(az), 0.0, 1.0))

    dist_gain = float(np.clip(_REF_DIST / dist, 0.1, 3.0)) * (volume / 100.0)

    # ── 前後判定 ────────────────────────────────────
    # cos(az): 前方=+1, 真横=0, 後方=-1
    cos_az = float(np.cos(az))
    # rear_amount: 0（前方・真横）〜 1（真後方）
    rear_amount = float(np.clip(-cos_az, 0.0, 1.0))

    # ── 後方の音量減衰（後方ほど小さく聞こえる）────
    rear_vol_factor = 1.0 - rear_amount * 0.20   # 最大 20% 減

    # ── 後方の高域カット（こもり感）────────────────
    processed = _apply_rear_lpf(mono, rear_amount, sr)

    l_out = (processed * pan_l * dist_gain * rear_vol_factor).astype(np.float32)
    r_out = (processed * pan_r * dist_gain * rear_vol_factor).astype(np.float32)

    return np.column_stack([l_out, r_out])


# ──────────────────────────────────────────────────────
# Audio engine
# ──────────────────────────────────────────────────────

class AudioEngine:
    """
    シンプルなステレオ再生エンジン。
    フィルター・遅延処理を一切行わず、
    compute_stereo() のゲイン差だけで定位を表現する。
    """

    def __init__(self) -> None:
        self._lock      = threading.Lock()
        self.is_playing = False
        self.is_loading = False
        self._stream: Optional[sd.OutputStream] = None
        self._data: Optional[np.ndarray] = None   # stereo float32
        self._mono: Optional[np.ndarray] = None   # mono source（update_position 用）
        self._samplerate: int = 44100
        self._pos: int = 0
        # リアルタイム更新用ゲイン（位置変更で差し替え）
        self._l_gain: float = 0.5
        self._r_gain: float = 0.5

    def load(
        self, audio: AudioFile, pos: BinauralPosition,
        volume: int, speed: int,
    ) -> bool:
        self.is_loading = True
        try:
            raw, sr = read_audio(audio.path)
        except Exception as exc:
            print(f"[AudioEngine] load failed: {exc}")
            self.is_loading = False
            return False

        mono = raw.mean(axis=1).astype(np.float32)

        # 速度変更: np.interp による線形リサンプリング
        # librosa の phase vocoder は金属音（フェーズ歪み）を生じさせるため使用しない
        if speed != 100:
            factor  = speed / 100.0
            orig_len = len(mono)
            new_len  = max(1, int(orig_len / factor))
            xs_orig  = np.arange(orig_len, dtype=np.float64)
            xs_new   = np.linspace(0.0, orig_len - 1, new_len)
            mono     = np.interp(xs_new, xs_orig, mono).astype(np.float32)

        stereo = compute_stereo(mono, pos, volume, sr)

        with self._lock:
            self._mono       = mono
            self._data       = stereo
            self._samplerate = sr

        self.is_loading = False
        return True

    def update_position(self, pos: BinauralPosition, volume: int) -> None:
        """再生中の位置・音量変更を次チャンクから反映する。"""
        with self._lock:
            if self._data is None or self._mono is None:
                return
            self._data = compute_stereo(self._mono, pos, volume, self._samplerate)

    def play(self) -> None:
        if self._data is None:
            return
        self.stop()
        with self._lock:
            self._pos       = 0
            self.is_playing = True
        self._stream = sd.OutputStream(
            samplerate=self._samplerate, channels=2, dtype="float32",
            callback=self._stream_callback,
            finished_callback=self._on_stream_finished,
        )
        self._stream.start()

    def stop(self) -> None:
        with self._lock:
            self.is_playing = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _stream_callback(self, outdata, frames, time, status) -> None:
        with self._lock:
            if not self.is_playing or self._data is None:
                outdata[:] = 0
                raise sd.CallbackStop()

            remaining = len(self._data) - self._pos
            chunk     = min(frames, remaining)

            outdata[:chunk] = self._data[self._pos: self._pos + chunk]
            if chunk < frames:
                outdata[chunk:] = 0

            self._pos += chunk
            if remaining <= frames:
                self.is_playing = False
                raise sd.CallbackStop()

    def _on_stream_finished(self) -> None:
        with self._lock:
            self.is_playing = False


# ──────────────────────────────────────────────────────
# Variation helpers
# ──────────────────────────────────────────────────────

def vary_int(base: int, var: int, lo: int, hi: int, step: int = 1) -> int:
    if var <= 0:
        return base
    return max(lo, min(hi, base + random.randint(-max(1, var // step), max(1, var // step)) * step))


def vary_float(base: float, var: float, lo: float, hi: float) -> float:
    if var <= 0:
        return base
    return max(lo, min(hi, base + random.uniform(-var, var)))


# ──────────────────────────────────────────────────────
# Settings persistence
# ──────────────────────────────────────────────────────

def load_settings_from(path: Path) -> dict:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[Settings] load failed ({path}): {exc}")
    return {}


def save_settings_to(path: Path, data: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as exc:
        print(f"[Settings] save failed: {exc}")
        return False


# ──────────────────────────────────────────────────────
# Position canvas
# ──────────────────────────────────────────────────────

class PositionCanvas(tk.Canvas):
    SIZE   = 158
    RADIUS = 66

    def __init__(self, parent, az_var, dist_var, az_rnd_var=None) -> None:
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         bg="#10101e", highlightthickness=1, highlightbackground="#555",
                         cursor="crosshair")
        self._az_var     = az_var
        self._dist_var   = dist_var
        self._az_rnd_var = az_rnd_var  # 変動幅（扇形表示に使用）
        self._cx = self.SIZE // 2
        self._cy = self.SIZE // 2
        self._draw_grid()
        self.update_marker()
        self.bind("<Button-1>",  self._on_click)
        self.bind("<B1-Motion>", self._on_click)
        az_var.trace_add(  "write", lambda *_: self.after(10, self.update_marker))
        dist_var.trace_add("write", lambda *_: self.after(10, self.update_marker))
        if az_rnd_var is not None:
            az_rnd_var.trace_add("write", lambda *_: self.after(10, self.update_marker))

    def _draw_grid(self) -> None:
        cx, cy, r = self._cx, self._cy, self.RADIUS
        self.create_oval(cx-r, cy-r, cx+r, cy+r, outline="#555", width=1)
        for frac in (0.25, 0.5, 0.75):
            rr = int(r * frac)
            self.create_oval(cx-rr, cy-rr, cx+rr, cy+rr, outline="#252535", width=1)
        self.create_line(cx, cy-r, cx, cy+r, fill="#252535", width=1)
        self.create_line(cx-r, cy, cx+r, cy, fill="#252535", width=1)
        d = int(r / np.sqrt(2))
        for dx, dy in ((d, d), (d, -d), (-d, d), (-d, -d)):
            self.create_line(cx, cy, cx+dx, cy+dy, fill="#1a1a28", width=1)
        for txt, tx, ty in (("前", cx, cy-r-10), ("後", cx, cy+r+10),
                             ("左", cx-r-10, cy), ("右", cx+r+10, cy)):
            self.create_text(tx, ty, text=txt, fill="#666", font=("", 8))
        self.create_oval(cx-5, cy-5, cx+5, cy+5, fill="#607D8B", outline="#90A4AE", width=1)

    def update_marker(self) -> None:
        self.delete("marker")
        az_deg = float(self._az_var.get())
        dist   = float(self._dist_var.get())
        cx, cy, r = self._cx, self._cy, self.RADIUS
        az_r = np.radians(az_deg)
        mx = int(cx + np.sin(az_r) * dist * r)
        my = int(cy - np.cos(az_r) * dist * r)

        # ── アジマス変動幅を扇形で描画 ──────────────────
        if self._az_rnd_var is not None:
            try:
                rnd_deg = float(self._az_rnd_var.get())
            except (ValueError, tk.TclError):
                rnd_deg = 0.0

            if rnd_deg > 0:
                arc_r = int(r * max(dist, 0.15))
                # tkinter の create_arc は「時計 12 時を 90°、反時計回り」の座標系なので変換する
                # アプリ座標系: 0°=前(上) 時計回り正  → tkinter: start=90-az-rnd extent=2*rnd
                start_tk = 90 - az_deg - rnd_deg
                extent_tk = rnd_deg * 2
                self.create_arc(
                    cx - arc_r, cy - arc_r, cx + arc_r, cy + arc_r,
                    start=start_tk, extent=extent_tk,
                    fill="",
                    outline="#00BCD4",
                    width=2,
                    style=tk.ARC,
                    tags="marker",
                )
                # 変動幅の端の線
                for sign in (-1, 1):
                    edge_r = np.radians(az_deg + sign * rnd_deg)
                    ex = int(cx + np.sin(edge_r) * dist * r)
                    ey = int(cy - np.cos(edge_r) * dist * r)
                    self.create_line(cx, cy, ex, ey,
                                     fill="#00BCD4", width=1, dash=(3, 4), tags="marker")

        # ── メインマーカー ──────────────────────────────
        self.create_line(cx, cy, mx, my, fill="#00BCD4", width=1, dash=(4, 3), tags="marker")
        self.create_oval(mx-7, my-7, mx+7, my+7,
                         fill="#00BCD4" if az_deg >= 0 else "#FF7043",
                         outline="white", width=1, tags="marker")
        self.create_text(mx, my - 13 if my > cy else my + 13,
                         text=f"{az_deg:.0f}°", fill="white", font=("", 7), tags="marker")

    def _on_click(self, event: tk.Event) -> None:
        dx, dy = event.x - self._cx, event.y - self._cy
        self._az_var.set(  round(float(np.degrees(np.arctan2(dx, -dy))), 1))
        self._dist_var.set(round(float(np.clip(np.sqrt(dx**2 + dy**2) / self.RADIUS, 0.0, 1.0)), 3))

    def show_actual_pos(self, az_deg: float, dist: float) -> None:
        """
        実際の再生アジマス（ランダム後の確定値）を小さい◯で表示する。
        設定値マーカーと区別するため白抜きの小◯で描画する。
        """
        self.delete("actual")
        cx, cy, r = self._cx, self._cy, self.RADIUS
        az_r = np.radians(az_deg)
        px = int(cx + np.sin(az_r) * dist * r)
        py = int(cy - np.cos(az_r) * dist * r)
        # 外側の白◯
        self.create_oval(px-5, py-5, px+5, py+5,
                         fill="", outline="white", width=1, tags="actual")
        # 内側の小◯（色でランダム値であることを示す）
        self.create_oval(px-2, py-2, px+2, py+2,
                         fill="#FFC107", outline="", tags="actual")

    def clear_actual_pos(self) -> None:
        self.delete("actual")


# ──────────────────────────────────────────────────────
# Player panel
# ──────────────────────────────────────────────────────

DEFAULT_VOL  = 80
DEFAULT_SPD  = 100
DEFAULT_DIST = 0.6
DEFAULT_RND  = 0
DEFAULT_AZ   = {"left": -45.0, "right": 45.0}
POLL_MS      = 150
WINDOW_SIZE  = "1040x780"
APP_VERSION  = "1.0.1"


class PlayerPanel(tk.Frame):

    _MODE_CONFIG: dict   # __init__ で設定する（_t() は起動時グローバルが確定後に呼ぶ）

    @property
    def _BTN_PLAY_TEXT(self) -> str: return _t("btn_play")
    @property
    def _BTN_STOP_TEXT(self) -> str: return _t("btn_stop")
    _BTN_PLAY_BG = "#43A047"
    _BTN_STOP_BG = "#E53935"

    def __init__(self, parent, side, title, saved, root_ref) -> None:
        super().__init__(parent, relief=tk.RIDGE, borderwidth=2, padx=6, pady=6)
        # _t() が使えるようになってから MODE_CONFIG を設定する
        self._MODE_CONFIG = {
            PlayMode.SEQUENTIAL: {"text": _t("btn_seq"), "bg": "#5E35B1"},
            PlayMode.RANDOM:     {"text": _t("btn_rnd"), "bg": "#F57C00"},
        }
        self.side            = side
        self.engine          = AudioEngine()
        self._files: list[AudioFile] = []
        self._current_idx    = 0
        self._keep_playing   = False
        self._generation     = 0   # ポーリングチェーンの世代番号（ダブルクリック競合防止）
        self._play_mode      = PlayMode(saved.get("play_mode", PlayMode.SEQUENTIAL.value))
        self._root_ref       = root_ref
        self._rt_update_job: Optional[str] = None

        default_az = DEFAULT_AZ[side]
        self._az_var   = tk.DoubleVar(value=saved.get("azimuth",   default_az))
        self._dist_var = tk.DoubleVar(value=saved.get("distance",  DEFAULT_DIST))
        self._az_rnd   = tk.IntVar(   value=saved.get("az_rnd",    DEFAULT_RND))
        self._vol_var  = tk.IntVar(   value=saved.get("volume",    DEFAULT_VOL))
        self._spd_var  = tk.IntVar(   value=saved.get("speed",     DEFAULT_SPD))
        self._vol_rnd  = tk.IntVar(   value=saved.get("vol_rnd",   DEFAULT_RND))
        self._spd_rnd  = tk.IntVar(   value=saved.get("spd_rnd",   DEFAULT_RND))

        self._vol_entry: Optional[tk.StringVar] = None  # Spinbox 表示値（保存に使う）
        self._spd_entry: Optional[tk.StringVar] = None

        self._build_ui(title)
        self._register_drag_and_drop()
        self._register_rt_traces()
        self._restore_files(saved.get("files", []))

    def _build_ui(self, title: str) -> None:
        tk.Label(self, text=title, font=("", 12, "bold")).pack(pady=(2, 4))

        # ── ファイルリスト ────────────────────────────
        list_frame = tk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self._file_listbox = tk.Listbox(
            list_frame,
            yscrollcommand=sb.set,
            selectmode=tk.EXTENDED,
            height=1,           # 最小高さ。expand=True で実際はウィンドウに追従する
            activestyle="dotbox",
            exportselection=False,
        )
        sb.config(command=self._file_listbox.yview)
        self._file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._file_listbox.bind("<Double-Button-1>", self._on_double_click)
        self._file_listbox.bind("<Delete>", self._on_delete_key)

        # リストが空のときに表示するヒントラベル
        self._empty_hint = tk.Label(
            list_frame,
            text=_t("drop_hint"),
            fg=_th("hint_fg"), font=("", 8),
            wraplength=180, justify=tk.CENTER,
        )
        # ファイルが追加・削除されるたびに表示切替する
        self._file_listbox.bind("<<ListboxSelect>>", lambda _: self._update_empty_hint())
        self._update_empty_hint()  # 初回表示

        ctrl_row = tk.Frame(self)
        ctrl_row.pack(fill=tk.X, pady=(2, 4))
        tk.Label(
            ctrl_row,
            text=_t("drop_label"),
            fg="#888", font=("", 7),
        ).pack(side=tk.LEFT)
        tk.Button(
            ctrl_row, text=_t("btn_del"), command=self._delete_selected,
            bg="#B71C1C", fg="white",
            font=("", 8, "bold"), relief=tk.FLAT, padx=8, pady=2, cursor="hand2",
        ).pack(side=tk.RIGHT)

        # ── バイノーラル位置 + 音量・速度（横並び） ────────
        pos_frame = tk.Frame(self, padx=4, pady=3)
        pos_frame.pack(fill=tk.X, pady=(0, 4))

        # 左：キャンバス + 仰角スライダー / 右：音量・速度
        pos_cols = tk.Frame(pos_frame)
        pos_cols.pack(fill=tk.X)

        # 左カラム：俯瞰マップ
        left_col = tk.Frame(pos_cols)
        left_col.pack(side=tk.LEFT, fill=tk.Y)

        self._pos_canvas = PositionCanvas(left_col, self._az_var, self._dist_var, self._az_rnd)
        self._pos_canvas.pack(padx=(0, 4))

        az_row = tk.Frame(left_col)
        az_row.pack(fill=tk.X, pady=(3, 0))
        tk.Label(az_row, text=_t("az_random"), font=("", 8), fg="#555").pack(side=tk.LEFT)
        tk.Spinbox(
            az_row, textvariable=self._az_rnd,
            from_=0, to=180, increment=10, width=4, font=("", 9),
        ).pack(side=tk.LEFT, padx=(4, 0))

        # 右カラム：音量・速度 + 再生/モードボタン
        right_col = tk.Frame(pos_cols, padx=4, pady=4)
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))


        self._vol_entry = self._make_setting_row(right_col, _t("volume"), self._vol_var, self._vol_rnd,  0, 100, 10, 50, show_header=True)
        self._spd_entry = self._make_setting_row(right_col, _t("speed"),  self._spd_var, self._spd_rnd, 50, 200,  1, 50)
        # 再生 / モードボタン（速度% の直下）
        btn_frame = tk.Frame(right_col)
        btn_frame.pack(fill=tk.X, pady=(6, 0))

        self._play_btn = tk.Button(
            btn_frame,
            text=self._BTN_PLAY_TEXT,
            command=self._toggle_playback,
            bg=self._BTN_PLAY_BG, fg="white",
            font=("", 10, "bold"), relief=tk.FLAT, padx=10, pady=6, cursor="hand2",
        )
        self._play_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        cfg = self._MODE_CONFIG[self._play_mode]
        self._mode_btn = tk.Button(
            btn_frame,
            text=cfg["text"],
            command=self._toggle_play_mode,
            bg=cfg["bg"], fg="white",
            font=("", 9, "bold"), relief=tk.FLAT, padx=8, pady=6, cursor="hand2",
        )
        self._mode_btn.pack(side=tk.LEFT)

        # ── ローディング表示（ボタンの下）──────────────
        self._loading_var = tk.StringVar(value="")
        tk.Label(right_col, textvariable=self._loading_var,
                 fg="#F57F17", font=("", 8)).pack(anchor="w", pady=(2, 0))

    def _make_setting_row(
        self, parent, label, val_var, rnd_var,
        from_, to, val_step=10, rnd_max=50, show_header=False,
    ) -> None:
        # 最初の行だけ列ヘッダーを表示する
        if show_header:
            hdr = tk.Frame(parent)
            hdr.pack(fill=tk.X, pady=(0, 1))
            tk.Label(hdr, text=_t("rnd_header"), fg="#888", font=("", 8)).pack(side=tk.RIGHT)

        row = tk.Frame(parent)
        row.pack(fill=tk.X, pady=1)
        tk.Label(row, text=label, width=5, anchor="w", font=("", 9)).pack(side=tk.LEFT)

        # Scale は IntVar に直結（スライダー操作は即反映）
        tk.Scale(
            row, variable=val_var, from_=from_, to=to, resolution=val_step,
            orient=tk.HORIZONTAL, showvalue=False, length=80,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Spinbox は専用の StringVar で管理する。
        # IntVar と Scale を共有すると1文字入力のたびに Scale が値を丸めてしまう。
        # from_/to は矢印ボタンの動作に必要なので渡す。確定時だけ IntVar へ書き戻す。
        entry_var = tk.StringVar(value=str(val_var.get()))

        # Scale が変化したとき（スライダー操作）は entry_var も追従させる
        def _sync_to_entry(*_):
            entry_var.set(str(val_var.get()))
        val_var.trace_add("write", _sync_to_entry)

        # 確定時に entry_var → val_var へクランプして書き戻す
        def _commit(_event=None):
            try:
                v = int(float(entry_var.get()))
            except (ValueError, tk.TclError):
                v = val_var.get()
            clamped = max(from_, min(to, v))
            val_var.set(clamped)
            entry_var.set(str(clamped))

        val_sb = tk.Spinbox(
            row, textvariable=entry_var,
            from_=from_, to=to, increment=val_step,
            width=5, font=("", 9),
        )
        val_sb.pack(side=tk.LEFT)
        val_sb.bind("<FocusOut>",        _commit)
        val_sb.bind("<Return>",          _commit)
        # 矢印ボタンは Spinbox 内部で entry_var を書き換えた後 ButtonRelease が来る
        val_sb.bind("<ButtonRelease-1>", _commit)

        tk.Label(row, text="±", font=("", 9), fg="#555").pack(side=tk.LEFT, padx=(6, 0))

        rnd_entry = tk.StringVar(value=str(rnd_var.get()))

        def _sync_rnd(*_):
            rnd_entry.set(str(rnd_var.get()))
        rnd_var.trace_add("write", _sync_rnd)

        def _commit_rnd(_event=None):
            try:
                v = int(float(rnd_entry.get()))
            except (ValueError, tk.TclError):
                v = rnd_var.get()
            clamped = max(0, min(rnd_max, v))
            rnd_var.set(clamped)
            rnd_entry.set(str(clamped))

        rnd_sb = tk.Spinbox(
            row, textvariable=rnd_entry,
            from_=0, to=rnd_max, increment=10,
            width=4, font=("", 9),
        )
        rnd_sb.pack(side=tk.LEFT)
        rnd_sb.bind("<FocusOut>",        _commit_rnd)
        rnd_sb.bind("<Return>",          _commit_rnd)
        rnd_sb.bind("<ButtonRelease-1>", _commit_rnd)

        # entry_var を呼び出し元が保持できるよう返す
        return entry_var

    @staticmethod
    def _bind_clamp(widget: tk.Spinbox, var: tk.IntVar, lo: int, hi: int) -> None:
        # _make_setting_row 内で直接処理するため現在は未使用（互換のため残す）
        pass

    def _set_button_state(self, *, playing: bool) -> None:
        self._play_btn.config(
            text=self._BTN_STOP_TEXT if playing else self._BTN_PLAY_TEXT,
            bg  =self._BTN_STOP_BG   if playing else self._BTN_PLAY_BG,
        )

    def _register_rt_traces(self) -> None:
        for var in (self._az_var, self._dist_var, self._vol_var):
            var.trace_add("write", lambda *_: self._schedule_rt_update())

    def _schedule_rt_update(self) -> None:
        if self._rt_update_job is not None:
            self.after_cancel(self._rt_update_job)
        self._rt_update_job = self.after(30, self._apply_rt_update)

    def _apply_rt_update(self) -> None:
        self._rt_update_job = None
        if self._keep_playing or self.engine.is_playing:
            self.engine.update_position(self._current_position(), self._vol_var.get())

    def _current_position(self) -> BinauralPosition:
        return BinauralPosition(
            azimuth=float(self._az_var.get()),
            distance=float(self._dist_var.get()),
        )

    def _register_drag_and_drop(self) -> None:
        self._file_listbox.drop_target_register(DND_FILES)
        self._file_listbox.dnd_bind("<<Drop>>", self._handle_drop)

    def _restore_files(self, paths: list[str]) -> None:
        for p in paths:
            path = Path(p)
            if path.is_file() and path.suffix.lower() in ALL_SUPPORTED_EXT:
                audio = AudioFile(path)
                if audio not in self._files:
                    self._files.append(audio)
                    self._file_listbox.insert(tk.END, audio.display_name)
        self._update_empty_hint()

    # ── Event handlers ────────────────────────────────

    def _update_empty_hint(self) -> None:
        """リストが空なら中央にヒントテキストを表示、ファイルがあれば非表示にする。"""
        if self._files:
            self._empty_hint.place_forget()
        else:
            # Listbox の中央に配置する
            self._empty_hint.place(relx=0.5, rely=0.5, anchor="center")
            self._empty_hint.lift()

    def _collect_audio_paths(self, raw_paths: list[str]) -> list[Path]:
        """
        ドロップされたパスリストを展開して音声ファイルの Path を返す。
        フォルダが含まれる場合はその中を再帰検索して対応拡張子のファイルをすべて収集する。
        """
        result: list[Path] = []
        for raw in raw_paths:
            path = Path(raw)
            if path.is_dir():
                # フォルダ内を再帰的に検索する
                for ext in ALL_SUPPORTED_EXT:
                    result.extend(sorted(path.rglob(f"*{ext}")))
            elif path.is_file():
                result.append(path)
        return result

    def _handle_drop(self, event) -> None:
        added = 0
        need_ffmpeg = False
        for path in self._collect_audio_paths(self._parse_dnd_paths(event.data)):
            suffix = path.suffix.lower()
            if suffix not in ALL_SUPPORTED_EXT:
                continue
            if suffix in FFMPEG_EXT and not ffmpeg_available():
                need_ffmpeg = True
                continue
            audio = AudioFile(path)
            if audio in self._files:
                continue
            self._files.append(audio)
            self._file_listbox.insert(tk.END, audio.display_name)
            added += 1

        self._update_empty_hint()

        if need_ffmpeg:
            ok = check_and_setup_ffmpeg(self._root_ref)
            if ok:
                messagebox.showinfo(_t("ffmpeg_ready"), _t("ffmpeg_ready_msg"))
            return
        if added == 0:
            messagebox.showinfo(_t("dlg_no_added"), _t("dlg_no_added_msg"))

    def _on_delete_key(self, _event=None) -> None:
        self._delete_selected()

    def _delete_selected(self) -> None:
        sel = list(self._file_listbox.curselection())
        if not sel:
            return

        # 再生中は停止確認ダイアログを出し、停止のみ行う（削除はしない）
        if self._keep_playing or self.engine.is_playing:
            if messagebox.askyesno(_t("dlg_stop_title"), _t("dlg_stop_msg")):
                self._stop()
            return

        # 逆順に削除することでインデックスのずれを防ぐ
        for idx in sorted(sel, reverse=True):
            self._files.pop(idx)
            self._file_listbox.delete(idx)
        new_count = len(self._files)
        if new_count > 0:
            self._file_listbox.selection_set(min(min(sel), new_count - 1))
        if self._current_idx >= new_count > 0:
            self._current_idx = new_count - 1
        self._update_empty_hint()

    def _on_double_click(self, _event=None) -> None:
        sel = self._file_listbox.curselection()
        if not sel:
            return
        # _stop() で古いポーリングチェーンを完全に無効化してから再生する。
        # _stop() 内で _keep_playing=False にするため、その後すぐ True に戻す前に
        # engine.stop() が完了している必要がある。
        # ここで _generation を進めることで古い _poll_and_advance が
        # 「自分の世代ではない」と判断して即座に終了する。
        self._generation += 1
        self.engine.stop()
        self._keep_playing   = False
        self._set_button_state(playing=False)

        self._current_idx  = sel[0]
        self._keep_playing = True
        self._play_index(self._current_idx)

    def _toggle_playback(self) -> None:
        if self._keep_playing or self.engine.is_playing:
            self._stop()
        else:
            self._play_from_selection()

    def _toggle_play_mode(self) -> None:
        self._play_mode = (PlayMode.RANDOM if self._play_mode == PlayMode.SEQUENTIAL
                           else PlayMode.SEQUENTIAL)
        cfg = self._MODE_CONFIG[self._play_mode]
        self._mode_btn.config(text=cfg["text"], bg=cfg["bg"])
    # ── Playback control ──────────────────────────────

    def _play_from_selection(self) -> None:
        sel = self._file_listbox.curselection()
        if not sel:
            if not self._files:
                messagebox.showwarning(_t("dlg_no_file"), _t("dlg_no_file_msg"))
                return
            start = 0
        else:
            start = sel[0]
        self._current_idx  = start
        self._keep_playing = True
        self._play_index(self._current_idx)

    def _play_index(self, idx: int) -> None:
        if not self._files:
            self._stop()
            return
        idx = idx % len(self._files)
        self._current_idx = idx
        self._file_listbox.selection_clear(0, tk.END)
        self._file_listbox.selection_set(idx)
        self._file_listbox.see(idx)

        audio = self._files[idx]
        if audio.path.suffix.lower() in FFMPEG_EXT and not ffmpeg_available():
            if not check_and_setup_ffmpeg(self._root_ref):
                self._stop()
                return

        # この再生セッションの世代番号を記録する。
        # ダブルクリックなどで別の曲が開始された場合は世代が進むため
        # 古いポーリングチェーンが自動的に終了する。
        my_gen = self._generation

        pos, vol, spd = self._effective_settings()
        self._loading_var.set(_t("loading"))
        self._play_btn.config(state=tk.DISABLED)

        def _load_and_play():
            ok = self.engine.load(audio, pos, vol, spd)
            self.after(0, lambda: self._on_load_done(ok, audio, my_gen))

        threading.Thread(target=_load_and_play, daemon=True).start()

    def _on_load_done(self, ok: bool, audio: AudioFile, gen: int) -> None:
        # 世代が変わっていたら（別の曲が開始済み）この結果を捨てる
        if gen != self._generation:
            return
        self._loading_var.set("")
        self._play_btn.config(state=tk.NORMAL)
        if not ok:
            extra = ("\n\nFFmpeg のセットアップが必要な場合は再生ボタンを押してください。"
                     if audio.path.suffix.lower() in FFMPEG_EXT else "")
            messagebox.showerror(_t("dlg_load_err"),
                                 f"ファイルを読み込めませんでした:\n{audio.path}{extra}")
            self._stop()
            return
        if not self._keep_playing:
            return
        self.engine.play()
        self._set_button_state(playing=True)
        self._poll_and_advance(gen)

    def _poll_and_advance(self, gen: int) -> None:
        # 世代が変わっていたらこのポーリングチェーンを終了する
        if gen != self._generation:
            return
        if self.engine.is_playing:
            self.after(POLL_MS, lambda: self._poll_and_advance(gen))
            return
        if not self._keep_playing:
            self._set_button_state(playing=False)
            return
        self._play_index(self._resolve_next_index())

    def _effective_settings(self) -> tuple[BinauralPosition, int, int]:
        az   = vary_float(self._az_var.get(), float(self._az_rnd.get()), -180.0, 180.0)
        dist = float(self._dist_var.get())
        vol  = vary_int(self._vol_var.get(), self._vol_rnd.get(),  0, 100, step=10)
        spd  = vary_int(self._spd_var.get(), self._spd_rnd.get(), 50, 200, step=1)
        self._pos_canvas.show_actual_pos(az, dist)
        return BinauralPosition(azimuth=az, distance=dist), vol, spd

    def _resolve_next_index(self) -> int:
        if self._play_mode == PlayMode.RANDOM:
            if len(self._files) <= 1:
                return 0
            return random.choice([i for i in range(len(self._files)) if i != self._current_idx])
        return (self._current_idx + 1) % len(self._files)

    def _stop(self) -> None:
        self._generation    += 1   # 古いポーリングチェーンを無効化する
        self._keep_playing   = False
        self.engine.stop()
        self._set_button_state(playing=False)
        self._pos_canvas.clear_actual_pos()

    # ── External interface ────────────────────────────

    def cancel_pending(self) -> None:
        """after() でスケジュールされた pending なコールバックをすべてキャンセルする。"""
        if self._rt_update_job is not None:
            try:
                self.after_cancel(self._rt_update_job)
            except Exception:
                pass
            self._rt_update_job = None

    def start_if_selected(self) -> None:
        self._play_from_selection()

    def force_stop(self) -> None:
        self._stop()

    def reset_to_default(self) -> None:
        """ファイルリストと全設定を初期値にリセットする。"""
        self._stop()
        self._files.clear()
        self._file_listbox.delete(0, tk.END)
        self._update_empty_hint()
        # 位置・音量・速度を初期値に戻す
        self._az_var.set(DEFAULT_AZ[self.side])
        self._dist_var.set(DEFAULT_DIST)
        self._az_rnd.set(DEFAULT_RND)
        self._vol_var.set(DEFAULT_VOL)
        self._spd_var.set(DEFAULT_SPD)
        self._vol_rnd.set(DEFAULT_RND)
        self._spd_rnd.set(DEFAULT_RND)
        # 再生モードを順番再生に戻す
        self._play_mode = PlayMode.SEQUENTIAL
        cfg = self._MODE_CONFIG[self._play_mode]
        self._mode_btn.config(text=cfg["text"], bg=cfg["bg"])

    def get_save_data(self) -> dict:
        # 保存前に Spinbox の表示値（entry_var）を確定させる
        def _read_entry(entry_var: Optional[tk.StringVar], fallback: int) -> int:
            if entry_var is None:
                return fallback
            try:
                return int(float(entry_var.get()))
            except (ValueError, tk.TclError):
                return fallback

        return {
            "files":     [str(f.path) for f in self._files],
            "azimuth":   self._az_var.get(),
            "distance":  self._dist_var.get(),
            "az_rnd":    self._az_rnd.get(),
            "volume":    _read_entry(self._vol_entry, self._vol_var.get()),
            "speed":     _read_entry(self._spd_entry, self._spd_var.get()),
            "vol_rnd":   self._vol_rnd.get(),
            "spd_rnd":   self._spd_rnd.get(),
            "play_mode": self._play_mode.value,
        }

    def apply_saved(self, saved: dict) -> None:
        self._stop()
        default_az = DEFAULT_AZ[self.side]
        self._az_var.set(  saved.get("azimuth",   default_az))
        self._dist_var.set(saved.get("distance",  DEFAULT_DIST))
        self._az_rnd.set(  saved.get("az_rnd",    DEFAULT_RND))
        self._vol_var.set( saved.get("volume",    DEFAULT_VOL))
        self._spd_var.set( saved.get("speed",     DEFAULT_SPD))
        self._vol_rnd.set( saved.get("vol_rnd",   DEFAULT_RND))
        self._spd_rnd.set( saved.get("spd_rnd",   DEFAULT_RND))
        # entry_var（Spinbox 表示）も明示的に更新する
        if self._vol_entry is not None:
            self._vol_entry.set(str(saved.get("volume", DEFAULT_VOL)))
        if self._spd_entry is not None:
            self._spd_entry.set(str(saved.get("speed",  DEFAULT_SPD)))
        self._play_mode = PlayMode(saved.get("play_mode", PlayMode.SEQUENTIAL.value))
        cfg = self._MODE_CONFIG[self._play_mode]
        self._mode_btn.config(text=cfg["text"], bg=cfg["bg"], fg="white")
        self._files.clear()
        self._file_listbox.delete(0, tk.END)
        self._restore_files(saved.get("files", []))

    # ── Helpers ───────────────────────────────────────

    @staticmethod
    def _parse_dnd_paths(raw: str) -> list[str]:
        result: list[str] = []
        token = raw.strip()
        while token:
            if token.startswith("{"):
                close = token.index("}")
                result.append(token[1:close])
                token = token[close + 1:].strip()
            else:
                space = token.find(" ")
                if space == -1:
                    result.append(token)
                    break
                result.append(token[:space])
                token = token[space:].strip()
        return result


# ──────────────────────────────────────────────────────
# Application root
# ──────────────────────────────────────────────────────

class StereoWavPlayerApp:

    _DEFAULT_CH = 2
    _MIN_CH     = 1
    _MAX_CH     = 16

    def __init__(self) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        saved = load_settings_from(SETTINGS_PATH)

        _apply_globals(saved)

        self._root = TkinterDnD.Tk()
        self._root.title("Spatial Multi Player  [ WAV / FLAC / OGG / AIFF / MP3 / AAC / OPUS ]")
        self._root.geometry(saved.get("window_geometry", WINDOW_SIZE))
        self._root.resizable(True, True)

        self._last_save_path: Optional[Path] = None
        self._panels: list[PlayerPanel] = []
        self._closing = False  # 終了処理中は全コールバックを無効化する
        self._ch_count = int(saved.get("ch_count", self._DEFAULT_CH))

        self._build_layout(saved)

        if _CURRENT_THEME == "dark":
            self._apply_dark(self._root)

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    @staticmethod
    def _apply_dark(widget: tk.Widget) -> None:
        bg   = _th("bg")
        fg   = _th("fg")
        w_bg = _th("listbox_bg")

        KEEP_BG = {
            "#1565C0", "#616161", "#B45309", "#00695C", "#4527A0",
            "#1B5E20", "#43A047", "#E53935", "#5E35B1", "#F57C00", "#B71C1C",
        }

        def _walk(w: tk.Widget) -> None:
            cls = w.winfo_class()
            try:
                if cls in ("Frame", "Toplevel"):
                    w.configure(bg=bg)
                elif cls == "Label":
                    w.configure(bg=bg, fg=fg)
                elif cls == "LabelFrame":
                    w.configure(bg=bg, fg=fg)
                elif cls == "Checkbutton":
                    w.configure(bg=bg, fg=fg,
                                activebackground=bg, activeforeground=fg,
                                selectcolor=w_bg)
                elif cls == "Button":
                    cur_bg = str(w.cget("bg")).upper()
                    if cur_bg not in {c.upper() for c in KEEP_BG}:
                        w.configure(bg=bg, fg=fg,
                                    activebackground=w_bg, activeforeground=fg)
                elif cls == "Scale":
                    w.configure(bg=bg, fg=fg,
                                troughcolor=w_bg, activebackground=fg)
                elif cls == "Spinbox":
                    w.configure(bg=w_bg, fg=fg,
                                insertbackground=fg, buttonbackground=bg)
                elif cls == "Listbox":
                    w.configure(bg=w_bg, fg=fg)
                elif cls in ("Menubutton", "OptionMenu"):
                    w.configure(bg=w_bg, fg=fg,
                                activebackground=bg, activeforeground=fg)
                elif cls == "Menu":
                    w.configure(bg=w_bg, fg=fg,
                                activebackground=_th("dim_fg"),
                                activeforeground=fg)
                elif cls == "Text":
                    w.configure(bg=w_bg, fg=fg, insertbackground=fg)
                elif cls == "Canvas":
                    pass  # PositionCanvas は専用デザインなので変えない
            except tk.TclError:
                pass

            if isinstance(w, ttk.Scrollbar):
                try:
                    s = ttk.Style()
                    s.configure("Vertical.TScrollbar",
                                background=w_bg, troughcolor=bg,
                                arrowcolor=fg, borderwidth=0)
                    s.configure("Horizontal.TScrollbar",
                                background=w_bg, troughcolor=bg,
                                arrowcolor=fg, borderwidth=0)
                except Exception:
                    pass

            for child in w.winfo_children():
                _walk(child)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Vertical.TScrollbar",
                        background=w_bg, troughcolor=bg,
                        arrowcolor=fg, borderwidth=0)
        style.configure("Horizontal.TScrollbar",
                        background=w_bg, troughcolor=bg,
                        arrowcolor=fg, borderwidth=0)
        style.configure("TSeparator", background=_th("dim_fg"))
        style.configure("Lang.TCombobox",
                        fieldbackground=w_bg, background=w_bg,
                        foreground=fg, selectforeground=fg,
                        selectbackground=bg, arrowcolor=fg)

        widget.configure(bg=bg)
        _walk(widget)

    def _build_layout(self, saved: dict) -> None:
        # ── パネルエリア（水平スクロール対応）──────────
        # Canvas でスクロール可能な領域を作る（expand=True でウィンドウ高さに追従）
        self._scroll_canvas = tk.Canvas(self._root, highlightthickness=0)
        self._scroll_canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 0))

        # 水平スクロールバー（パネルの下・ボタンの上。コンテンツ幅超えた時のみ表示）
        self._h_scroll = ttk.Scrollbar(self._root, orient=tk.HORIZONTAL)
        # 初期は非表示にして _update_scrollbar_visibility で制御する
        self._h_scroll.pack_forget()
        self._h_scroll.config(command=self._scroll_canvas.xview)
        self._scroll_canvas.config(xscrollcommand=self._h_scroll.set)

        # Canvas 内にパネルを並べるフレーム
        self._panels_frame = tk.Frame(self._scroll_canvas)
        self._canvas_window = self._scroll_canvas.create_window(
            (0, 0), window=self._panels_frame, anchor="nw"
        )

        # パネルフレームのサイズ変更時に Canvas の scrollregion を更新
        self._panels_frame.bind("<Configure>", self._on_panels_resize)
        # Canvas サイズ変更時: scrollregion 更新 + スクロールバー表示切替 + 高さを panels_frame に伝える
        self._scroll_canvas.bind("<Configure>", self._on_canvas_resize)

        # チャンネルパネルを生成
        self._panels = []
        ch_data_list = saved.get("channels", [])
        for i in range(self._ch_count):
            ch_saved = ch_data_list[i] if i < len(ch_data_list) else {}
            self._add_panel(i, ch_saved)

        # ── ボトムバー ────────────────────────────────
        bottom = tk.Frame(self._root, pady=6)
        bottom.pack(fill=tk.X, padx=10)

        tk.Button(
            bottom, text=_t("btn_both"),
            command=self._play_all,
            bg="#1565C0", fg="white",
            font=("", 11, "bold"), relief=tk.FLAT, padx=14, pady=8, cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(
            bottom, text=_t("btn_stop_all"),
            command=self._stop_all,
            bg="#616161", fg="white",
            font=("", 11, "bold"), relief=tk.FLAT, padx=14, pady=8, cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 16))

        ttk.Separator(bottom, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)

        tk.Button(
            bottom, text=_t("btn_new"),
            command=self._new,
            bg="#B45309", fg="white",
            font=("", 10, "bold"), relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
        ).pack(side=tk.LEFT, padx=(4, 6))

        tk.Button(
            bottom, text=_t("btn_save"),
            command=self._save,
            bg="#00695C", fg="white",
            font=("", 10, "bold"), relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 2))

        tk.Button(
            bottom, text=_t("btn_overwrite"),
            command=self._overwrite,
            bg="#1B5E20", fg="white",
            font=("", 10, "bold"), relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(
            bottom, text=_t("btn_load"),
            command=self._load,
            bg="#4527A0", fg="white",
            font=("", 10, "bold"), relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
        ).pack(side=tk.LEFT)

        self._status_var = tk.StringVar(value=_t("status_init"))

        # ステータス行
        status_bar = tk.Frame(self._root)
        status_bar.pack(fill=tk.X, padx=12, pady=(0, 4))

        tk.Label(
            status_bar,
            textvariable=self._status_var,
            fg="#555", font=("", 8), anchor="w",
        ).pack(side=tk.LEFT)

        # バージョン（右端）
        tk.Label(
            status_bar, text=f"v{APP_VERSION}",
            fg="#999", font=("", 7),
        ).pack(side=tk.RIGHT, padx=(2, 4))

        # ダークモード
        self._dark_var = tk.BooleanVar(value=(_CURRENT_THEME == "dark"))
        dark_frame = tk.Frame(status_bar, relief=tk.GROOVE, bd=1)
        dark_frame.pack(side=tk.RIGHT, padx=(6, 0))
        tk.Checkbutton(
            dark_frame, text=_t("dark_mode"),
            variable=self._dark_var, command=self._on_theme_change,
            font=("", 8), padx=4, pady=1,
        ).pack()

        # 言語選択
        lang_frame = tk.Frame(status_bar)
        lang_frame.pack(side=tk.RIGHT, padx=(0, 4))
        tk.Label(lang_frame, text=_t("language") + ":", font=("", 8)).pack(side=tk.LEFT, padx=(0, 2))
        self._lang_var = tk.StringVar(value=_CURRENT_LANG.upper())
        langs = get_available_langs()
        lang_menu = tk.OptionMenu(
            lang_frame, self._lang_var, *langs,
            command=lambda _: self._on_lang_change(),
        )
        lang_menu.configure(font=("", 8), relief=tk.GROOVE, bd=1, padx=4, pady=1)
        lang_menu["menu"].configure(font=("", 8))
        lang_menu.pack(side=tk.LEFT)

        # チャンネル数コンボボックス（言語の左）
        ch_frame = tk.Frame(status_bar)
        ch_frame.pack(side=tk.RIGHT, padx=(0, 8))
        tk.Label(ch_frame, text=_t("ch_count") + ":", font=("", 8)).pack(side=tk.LEFT, padx=(0, 2))
        self._ch_count_var = tk.StringVar(value=str(self._ch_count))
        ch_cb = ttk.Combobox(
            ch_frame, textvariable=self._ch_count_var,
            values=[str(i) for i in range(self._MIN_CH, self._MAX_CH + 1)],
            state="readonly", width=3, font=("", 8),
        )
        ch_cb.pack(side=tk.LEFT)
        ch_cb.bind("<<ComboboxSelected>>", self._on_ch_count_change)

    def _add_panel(self, idx: int, ch_saved: dict) -> None:
        """インデックス idx のチャンネルパネルを生成して panels_frame に追加する。"""
        title = f"{_t('ch_label')} {idx + 1}"
        side  = "left" if idx % 2 == 0 else "right"
        panel = PlayerPanel(
            self._panels_frame, side=side,
            title=title, saved=ch_saved, root_ref=self._root,
        )
        panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0 if idx == 0 else 5, 5))
        self._panels.append(panel)

    def _on_panels_resize(self, _event=None) -> None:
        if self._closing:
            return
        self._scroll_canvas.configure(
            scrollregion=self._scroll_canvas.bbox("all")
        )
        self._update_scrollbar_visibility()

    def _on_canvas_resize(self, event=None) -> None:
        if self._closing:
            return
        self._update_scrollbar_visibility()
        if event:
            self._scroll_canvas.itemconfigure(
                self._canvas_window, height=event.height
            )

    def _update_scrollbar_visibility(self) -> None:
        """コンテンツ幅が Canvas 幅を超えている時だけスクロールバーをパネルの直下に表示する。"""
        try:
            content_w = self._panels_frame.winfo_reqwidth()
            canvas_w  = self._scroll_canvas.winfo_width()
            if content_w > canvas_w:
                # bottom バーの直前（パネルの下）に挿入する
                self._h_scroll.pack(fill=tk.X, padx=10, pady=(0, 2),
                                    before=self._root.winfo_children()[-2])
            else:
                self._h_scroll.pack_forget()
        except Exception:
            pass

    def _on_ch_count_change(self, _event=None) -> None:
        """チャンネル数コンボボックスの変更を反映する。"""
        try:
            new_count = int(self._ch_count_var.get())
        except ValueError:
            return
        if new_count == len(self._panels):
            return

        if new_count < len(self._panels):
            # 減らす: 末尾から削除
            for panel in self._panels[new_count:]:
                panel.force_stop()
                panel.destroy()
            self._panels = self._panels[:new_count]
        else:
            # 増やす: 末尾に追加
            for i in range(len(self._panels), new_count):
                self._add_panel(i, {})

        self._ch_count = new_count
        self._status_var.set(_t("status_ch_changed") + str(new_count))

    # ── Actions ───────────────────────────────────────

    def _new(self) -> None:
        if not messagebox.askyesno(_t("dlg_new_title"), _t("dlg_new_msg")):
            return
        for panel in self._panels:
            panel.force_stop()
            panel.reset_to_default()
        self._status_var.set(_t("status_reset"))

    def _play_all(self) -> None:
        for panel in self._panels:
            panel.start_if_selected()
        self._status_var.set(_t("status_both"))

    def _stop_all(self) -> None:
        for panel in self._panels:
            panel.force_stop()
        self._status_var.set(_t("status_stopped"))

    # 旧名を互換エイリアスとして残す
    def _play_both(self) -> None: self._play_all()
    def _stop_both(self) -> None: self._stop_all()

    def _on_lang_change(self, _event=None) -> None:
        global _CURRENT_LANG
        lang = self._lang_var.get().lower()
        if lang == _CURRENT_LANG:
            return
        _CURRENT_LANG = lang if lang in STRINGS else "en"
        self._rebuild_ui()

    def _on_theme_change(self) -> None:
        global _CURRENT_THEME
        theme = "dark" if self._dark_var.get() else "light"
        if theme == _CURRENT_THEME:
            return
        _CURRENT_THEME = theme
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        if self._closing:
            return
        saved = self._collect_data()
        save_settings_to(SETTINGS_PATH, saved)
        for panel in self._panels:
            panel.force_stop()
        for widget in self._root.winfo_children():
            widget.destroy()
        self._panels = []
        self._build_layout(saved)
        if _CURRENT_THEME == "dark":
            self._apply_dark(self._root)

    def _save_pref_and_restart(self, lang=None, theme=None) -> None:
        if lang:
            global _CURRENT_LANG; _CURRENT_LANG = lang
        if theme:
            global _CURRENT_THEME; _CURRENT_THEME = theme
        self._rebuild_ui()

    def _collect_data(self) -> dict:
        return {
            "window_geometry": self._root.geometry(),
            "lang":     _CURRENT_LANG,
            "theme":    _CURRENT_THEME,
            "ch_count": len(self._panels),
            "channels": [p.get_save_data() for p in self._panels],
        }

    def _save(self) -> None:
        path_str = filedialog.asksaveasfilename(
            title=_t("btn_save"), defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("*", "*.*")],
            initialfile="spatial_multi_player_setting.json",
        )
        if not path_str:
            return
        path = Path(path_str)
        ok = save_settings_to(path, self._collect_data())
        if ok:
            self._last_save_path = path
        self._status_var.set(
            _t("status_saved") + path.name if ok else _t("status_failed")
        )
        if not ok:
            messagebox.showerror(_t("dlg_save_err"), _t("dlg_save_err_msg"))

    def _overwrite(self) -> None:
        if self._last_save_path is None:
            self._status_var.set(_t("status_no_save_path"))
            return
        ok = save_settings_to(self._last_save_path, self._collect_data())
        self._status_var.set(
            _t("status_saved") + self._last_save_path.name if ok else _t("status_failed")
        )
        if not ok:
            messagebox.showerror(_t("dlg_save_err"), _t("dlg_save_err_msg"))

    def _load(self) -> None:
        path_str = filedialog.askopenfilename(
            title=_t("btn_load"),
            filetypes=[("JSON", "*.json"), ("*", "*.*")],
        )
        if not path_str:
            return
        data = load_settings_from(Path(path_str))
        if not data:
            messagebox.showwarning(_t("dlg_load_warn"), _t("dlg_load_warn_msg"))
            return
        if "window_geometry" in data:
            self._root.geometry(data["window_geometry"])
        # チャンネル数を復元してから各パネルにデータを適用する
        self._ch_count = int(data.get("ch_count", self._DEFAULT_CH))
        self._rebuild_ui()
        ch_data_list = data.get("channels", [])
        for i, panel in enumerate(self._panels):
            if i < len(ch_data_list):
                panel.apply_saved(ch_data_list[i])
        self._last_save_path = Path(path_str)
        self._status_var.set(_t("status_loaded") + Path(path_str).name)

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._root.protocol("WM_DELETE_WINDOW", lambda: None)
        self._root.withdraw()

        # after コールバックを全キャンセル
        try:
            for after_id in self._root.tk.eval("after info").split():
                try:
                    self._root.after_cancel(after_id)
                except Exception:
                    pass
        except Exception:
            pass

        for panel in self._panels:
            panel.force_stop()

        save_settings_to(SETTINGS_PATH, self._collect_data())

        # quit() でメインループを停止してから強制終了する
        # destroy() は WM イベントを再発火させる場合があるため使わない
        self._root.quit()
        sys.exit(0)

    def run(self) -> None:
        self._root.mainloop()


# ──────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────

if __name__ == "__main__":
    app = StereoWavPlayerApp()
    app.run()


# ──────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────

if __name__ == "__main__":
    app = StereoWavPlayerApp()
    app.run()