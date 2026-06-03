#!/usr/bin/env python3
"""Floater: 原生 macOS 悬浮捕获（PyObjC + NSVisualEffectView）。
双击 Command 触发（任何场景：浏览器、输入框、全屏 app 都可）。
Enter 保存到 inbox/YYYY-MM-DD.md（按当天日期），Esc / 失焦取消。
悬浮框右下角有「框选文字」按钮：点击后整屏覆盖半透明遮罩，
拖拽选区，松手后用 macOS Vision (VNRecognizeTextRequest) 做 OCR，
识别结果自动回填到输入框，用户确认后再 Enter 入库。
全局热键基于 CGEventTap (kCGSessionEventTap + kCGHeadInsertEventTap)，
监听 flagsChanged 检测 Command 的「干净双击」——两次按下间隔 < 0.4s，且中间没有其他键。"""
import os
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")
import subprocess
import tempfile
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import objc
from AppKit import (
    NSAnimationContext,
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSButton,
    NSColor,
    NSCursor,
    NSEvent,
    NSEventModifierFlagShift,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSPasteboard,
    NSPasteboardTypeString,
    NSRectFillUsingOperation,
    NSScreen,
    NSScreenSaverWindowLevel,
    NSScrollView,
    NSTextView,
    NSView,
    NSViewHeightSizable,
    NSViewMaxYMargin,
    NSViewMinXMargin,
    NSViewWidthSizable,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialPopover,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindow,
    NSWindowStyleMaskBorderless,
    NSWorkspace,
)
from Foundation import (
    NSAttributedString,
    NSMakePoint,
    NSMakeRange,
    NSMakeRect,
    NSMakeSize,
    NSNotificationCenter,
    NSObject,
)
from CoreFoundation import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetMain,
    kCFRunLoopCommonModes,
)
from PyObjCTools import AppHelper
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventSetIntegerValueField,
    CGEventMaskBit,
    CGEventPost,
    CGEventSetFlags,
    CGEventTapCreate,
    CGEventTapEnable,
    CGRectMake,
    CGWindowListCreateImage,
    kCGEventFlagMaskCommand,
    kCGEventFlagsChanged,
    kCGEventKeyDown,
    kCGEventSourceUserData,
    kCGEventTapDisabledByTimeout,
    kCGEventTapOptionListenOnly,
    kCGHIDEventTap,
    kCGHeadInsertEventTap,
    kCGSessionEventTap,
    kCGWindowImageDefault,
    kCGWindowListOptionOnScreenBelowWindow,
)
from Vision import (
    VNImageRequestHandler,
    VNRecognizeTextRequest,
)

# 语音输入相关依赖：缺失时降级（按钮仍显示，但点击会打日志）
try:
    import numpy as np
    import sounddevice as sd
    _AUDIO_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    np = None  # type: ignore[assignment]
    sd = None  # type: ignore[assignment]
    _AUDIO_AVAILABLE = False
    print(f"[floater] 录音依赖缺失: {_exc}（pip install sounddevice numpy）", flush=True)

try:
    import mlx_whisper
    _WHISPER_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    mlx_whisper = None  # type: ignore[assignment]
    _WHISPER_AVAILABLE = False
    print(f"[floater] mlx_whisper 未安装: {_exc}（pip install mlx-whisper）", flush=True)

# URL 抓取相关依赖：缺失时降级，剪贴板 URL 还是会原样填入
try:
    import requests
    from bs4 import BeautifulSoup
    _URL_FETCH_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    requests = None  # type: ignore[assignment]
    BeautifulSoup = None  # type: ignore[assignment]
    _URL_FETCH_AVAILABLE = False
    print(f"[floater] URL 抓取依赖缺失: {_exc}（pip install requests beautifulsoup4）", flush=True)


INBOX_DIR = Path("/Users/rui/Projects/SciLink37/inbox")


def today_inbox_path() -> Path:
    """每次调用都基于当下日期计算路径，跨天后自动切换到新文件夹。"""
    return INBOX_DIR / datetime.now().strftime("%Y-%m-%d") / "raw.md"
WIDTH = 400.0
MIN_HEIGHT = 56.0
MAX_HEIGHT = 320.0
PAD = 14.0
CORNER = 12.0
FONT_SIZE = 15.0
PLACEHOLDER = "Fact Recording...   ! 直觉  ? 卡点  → 记录"
FADE_DURATION = 0.12
DOUBLE_TAP_INTERVAL = 0.4  # seconds, press-to-press
TRIPLE_TAP_WINDOW = 1.0    # 三击 Command 的总窗口（首拍到第三拍 < 1s）触发 Dashboard
DASHBOARD_URL = "http://localhost:8037"
# 给自己合成的 Cmd+C 事件打的标记（kCGEventSourceUserData）；事件 tap 见到它就跳过，
# 否则双击弹窗时合成的 Cmd+C 会被当成「其他键」清空三击序列，导致三击永远凑不齐。
SYNTHETIC_EVENT_TAG = 0x5C137
OCR_BTN_SIZE = 20.0
OCR_BTN_MARGIN = 6.0
MIC_BTN_SIZE = 20.0
BTN_GAP = 4.0
TEXT_RIGHT_GAP = OCR_BTN_SIZE + BTN_GAP + MIC_BTN_SIZE + 4.0  # OCR + 麦克风两个按钮的预留宽度
# NSCompositingOperation 常量值（避免依赖某些 PyObjC 版本不导出的别名）
NS_COMPOSITE_CLEAR = 0
NS_COMPOSITE_SOURCE_OVER = 2
NS_IMAGE_ONLY = 1  # NSCellImagePosition.imageOnly
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
WHISPER_SAMPLE_RATE = 16000
URL_FETCH_TIMEOUT = 8
URL_FETCH_PLACEHOLDER = "正在抓取..."
URL_FETCH_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# 备用 UA：L2 抓取失败时重试一次，许多反爬只针对某个浏览器指纹
URL_FETCH_UA_ALT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) "
    "Gecko/20100101 Firefox/124.0"
)
URL_BODY_FOR_LLM = 500
# 第一层：站点专用规则
ARXIV_DOMAINS = ("arxiv.org",)
GITHUB_DOMAINS = ("github.com",)
YOUTUBE_DOMAINS = ("youtube.com", "youtu.be")
# 其他学术 / 新闻站：优先吃 og:description
OG_PREFERRED_DOMAINS = (
    "nature.com", "science.org", "sciencedaily.com", "phys.org",
    "nytimes.com", "theguardian.com", "bbc.com", "bbc.co.uk",
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com",
    "economist.com", "medium.com", "substack.com",
    "techcrunch.com", "theverge.com", "arstechnica.com",
)
# 第三层：按需 Gemma 兜底
GEMMA_HEALTH_URL = "http://localhost:8080/v1/models"
GEMMA_CHAT_URL = "http://localhost:8080/v1/chat/completions"
GEMMA_MODEL = "mlx-community/gemma-4-e2b-it-4bit"
GEMMA_STARTUP_TIMEOUT = 30
GEMMA_CHAT_TIMEOUT = 60


def _run_vision_ocr(cgimage):
    """同步跑 Vision 文本识别。失败/无结果返回空串。"""
    if cgimage is None:
        return ""
    try:
        handler = VNImageRequestHandler.alloc().initWithCGImage_options_(cgimage, {})
        request = VNRecognizeTextRequest.alloc().init()
        # VNRequestTextRecognitionLevelAccurate = 0
        request.setRecognitionLevel_(0)
        request.setUsesLanguageCorrection_(True)
        try:
            request.setRecognitionLanguages_(["zh-Hans", "en-US"])
        except Exception:
            pass
        ok, _err = handler.performRequests_error_([request], None)
        if not ok:
            return ""
        results = request.results() or []
        lines = []
        for obs in results:
            candidates = obs.topCandidates_(1)
            if candidates and len(candidates) > 0:
                lines.append(str(candidates[0].string()))
        return "\n".join(lines)
    except Exception as exc:
        print(f"OCR 失败: {exc}")
        return ""


class AudioRecorder:
    """sounddevice 输入流采样到内存，stop_to_wav 时把累计样本写成 16-bit PCM WAV。"""

    def __init__(self, sample_rate=WHISPER_SAMPLE_RATE):
        self._sr = sample_rate
        self._stream = None
        self._chunks = []

    def start(self):
        if not _AUDIO_AVAILABLE:
            raise RuntimeError("sounddevice / numpy 未安装")
        self._chunks = []

        def _cb(indata, frames, time_info, status):
            if status:
                # 不打断录音，只打个日志
                print(f"[floater] mic status: {status}", flush=True)
            self._chunks.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self._sr,
            channels=1,
            dtype="float32",
            callback=_cb,
        )
        self._stream.start()

    def stop_to_wav(self):
        if self._stream is None:
            return None
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None
        if not self._chunks:
            return None
        audio = np.concatenate(self._chunks, axis=0).flatten()
        if audio.size == 0:
            return None
        pcm = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="scilink_voice_")
        os.close(fd)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sr)
            wf.writeframes(pcm.tobytes())
        return path

    def abort(self):
        if self._stream is None:
            return
        try:
            self._stream.abort()
            self._stream.close()
        finally:
            self._stream = None
        self._chunks = []


def _run_whisper(wav_path):
    """同步跑 mlx-whisper。返回识别文本（已 strip）。首次调用会下载模型，可能要等几十秒。"""
    print(
        f"[whisper] _run_whisper enter; wav={wav_path}; available={_WHISPER_AVAILABLE}",
        flush=True,
    )
    if not _WHISPER_AVAILABLE:
        print("[whisper] mlx_whisper 不可用，跳过转写", flush=True)
        return ""
    t0 = time.monotonic()
    try:
        result = mlx_whisper.transcribe(
            wav_path,
            path_or_hf_repo=WHISPER_MODEL,
        )
        dt = time.monotonic() - t0
        result_keys = list(result.keys()) if hasattr(result, "keys") else None
        raw = result.get("text") if hasattr(result, "get") else None
        text = (raw or "").strip()
        print(
            f"[whisper] transcribe done in {dt:.2f}s; "
            f"result_type={type(result).__name__}; keys={result_keys}; "
            f"raw_text={raw!r}; stripped_text={text!r} (len={len(text)})",
            flush=True,
        )
        return text
    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"[whisper] transcribe 抛异常: {exc!r}", flush=True)
        traceback.print_exc()
        return ""


def _is_url(text):
    """判断剪贴板内容是不是单行的 http(s):// URL。"""
    if not text:
        return False
    s = text.strip()
    if not s or any(ch.isspace() for ch in s):
        return False
    return s.startswith("http://") or s.startswith("https://")


def _clean_text(s):
    if not s:
        return None
    out = " ".join(str(s).split()).strip()
    return out or None


def _host_matches(host, domains):
    """精确域名 + 子域名命中。github.com 命中 github.com / www.github.com，但不命中 github.io。"""
    if not host:
        return False
    h = host.lower()
    return any(h == d or h.endswith("." + d) for d in domains)


def _extract_site_specific(host, soup):
    """第一层 —— 已知站点专用规则。无规则命中返回 (None, None)。"""
    if not host:
        return (None, None)
    # arXiv：<meta name="citation_title"> + <blockquote class="abstract">
    if _host_matches(host, ARXIV_DOMAINS):
        cite = soup.find("meta", attrs={"name": "citation_title"})
        title = _clean_text(cite.get("content")) if cite else None
        if not title and soup.title and soup.title.string:
            title = _clean_text(soup.title.string)
        summary = None
        bq = soup.find("blockquote", class_="abstract")
        if bq:
            txt = _clean_text(bq.get_text(" ", strip=True))
            if txt:
                low = txt.lower()
                for prefix in ("abstract:", "abstract："):
                    if low.startswith(prefix):
                        txt = txt[len(prefix):].lstrip()
                        break
                summary = txt or None
        return (title, summary)
    # GitHub：<meta name="description">（YouTube 单独走 oEmbed，不进这里）
    if _host_matches(host, GITHUB_DOMAINS):
        title = _clean_text(soup.title.string) if (soup.title and soup.title.string) else None
        meta = soup.find("meta", attrs={"name": "description"})
        summary = _clean_text(meta.get("content")) if meta else None
        return (title, summary)
    # 学术 / 新闻：<meta property="og:title" | "og:description">
    if _host_matches(host, OG_PREFERRED_DOMAINS):
        og_t = soup.find("meta", attrs={"property": "og:title"})
        title = _clean_text(og_t.get("content")) if og_t else None
        if not title and soup.title and soup.title.string:
            title = _clean_text(soup.title.string)
        og_d = soup.find("meta", attrs={"property": "og:description"})
        summary = _clean_text(og_d.get("content")) if og_d else None
        return (title, summary)
    return (None, None)


def _extract_generic(soup):
    """第二层 —— 通用规则：<title> + <meta name='description'>。"""
    title = _clean_text(soup.title.string) if (soup.title and soup.title.string) else None
    meta = soup.find("meta", attrs={"name": "description"})
    summary = _clean_text(meta.get("content")) if meta else None
    return (title, summary)


def _extract_body_text(soup, max_len):
    """正文前 max_len 字，给 Gemma 总结用。优先 <article>/<main> 容器里的 <p>。"""
    container = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    text = " ".join(p for p in paragraphs if p)
    if not text and container is not None:
        text = container.get_text(" ", strip=True)
    text = " ".join((text or "").split())
    return text[:max_len].strip()


def _is_gemma_alive(timeout=1):
    if not _URL_FETCH_AVAILABLE:
        return False
    try:
        r = requests.get(GEMMA_HEALTH_URL, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _start_gemma_async():
    """后台启动 ~/start_secretary.sh，不阻塞当前线程。"""
    try:
        subprocess.Popen(
            ["bash", "-lc", "nohup ~/start_secretary.sh >/tmp/secretary.log 2>&1 &"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[link/gemma] start_secretary.sh 启动失败: {exc!r}", flush=True)


def _wait_for_gemma_ready(timeout=GEMMA_STARTUP_TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_gemma_alive(timeout=1):
            return True
        time.sleep(0.5)
    return False


def _stop_gemma():
    """好邻居：pkill 自己启动的 mlx_lm.server。"""
    try:
        subprocess.run(
            ["pkill", "-f", "mlx_lm.server"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[link/gemma] pkill 失败: {exc!r}", flush=True)


def _summarize_with_gemma(body_text):
    """用本地 Gemma 把正文总结为一句话；Gemma 离线则按需启动并在结束时关掉。"""
    if not body_text or not _URL_FETCH_AVAILABLE:
        return None
    started_by_us = False
    if not _is_gemma_alive():
        print("[link/gemma] 未运行，按需启动 ~/start_secretary.sh", flush=True)
        _start_gemma_async()
        started_by_us = True
        if not _wait_for_gemma_ready():
            print("[link/gemma] 启动超时（30s）", flush=True)
            _stop_gemma()
            return None
        print("[link/gemma] 已就绪", flush=True)
    try:
        payload = {
            "model": GEMMA_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是网页摘要助手。用一句简短的中文（不超过80字）"
                        "总结下面的网页内容。直接输出摘要本身，不加任何前缀。"
                    ),
                },
                {"role": "user", "content": body_text},
            ],
            "temperature": 0.3,
            "max_tokens": 200,
        }
        r = requests.post(GEMMA_CHAT_URL, json=payload, timeout=GEMMA_CHAT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        msg = data["choices"][0]["message"]
        out = _clean_text(msg.get("content") or msg.get("reasoning") or "")
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"[link/gemma] 摘要失败: {exc!r}", flush=True)
        return None
    finally:
        if started_by_us:
            print("[link/gemma] 关闭按需启动的实例", flush=True)
            _stop_gemma()


def _fetch_youtube_oembed(url):
    """YouTube 走官方 oEmbed 端点，不解析 HTML —— 简单可靠还躲过反爬。"""
    if not _URL_FETCH_AVAILABLE:
        return (None, None)
    try:
        r = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            headers={"User-Agent": URL_FETCH_UA},
            timeout=URL_FETCH_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        title = _clean_text(data.get("title"))
        if not title:
            return (None, None)
        return (title, f"YouTube 视频：{title}")
    except Exception as exc:  # noqa: BLE001
        print(f"[link/youtube] oEmbed 失败: {exc!r}", flush=True)
        return (None, None)


def _http_get_soup(url, ua):
    """统一的 HTTP→BeautifulSoup；失败抛异常。"""
    resp = requests.get(
        url,
        timeout=URL_FETCH_TIMEOUT,
        headers={"User-Agent": ua},
        allow_redirects=True,
    )
    resp.raise_for_status()
    # 默认 ISO-8859-1 会把中文页面打成乱码
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return BeautifulSoup(resp.text, "html.parser")


def _fetch_url_summary(url):
    """三层抓取：站点专用 → 通用 <title>+description → Gemma 兜底。"""
    if not _URL_FETCH_AVAILABLE:
        print("[link] requests / bs4 未安装，跳过抓取", flush=True)
        return (None, None)

    host = (urlparse(url).hostname or "").lower()

    # YouTube 短路：用 oEmbed API，命中就直接返回，不啃 HTML
    if _host_matches(host, YOUTUBE_DOMAINS):
        yt_title, yt_summary = _fetch_youtube_oembed(url)
        if yt_title:
            print(f"[link] YouTube oEmbed hit; title={yt_title!r}", flush=True)
            return (yt_title, yt_summary)
        # oEmbed 失败则降级到通用 HTML 流程

    # 抓 HTML：先用 Chrome UA；失败时换 Firefox UA 重试一次
    soup = None
    last_exc = None
    for attempt, ua in enumerate((URL_FETCH_UA, URL_FETCH_UA_ALT), start=1):
        try:
            soup = _http_get_soup(url, ua)
            if attempt > 1:
                print(f"[link] fetch {url!r} 备用 UA 成功", flush=True)
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(
                f"[link] fetch {url!r} UA#{attempt} 失败: {exc!r}"
                + ("；换备用 UA 重试" if attempt == 1 else ""),
                flush=True,
            )
    if soup is None:
        print(f"[link] fetch {url!r} 两次都失败: {last_exc!r}", flush=True)
        return (None, None)

    # 第一层 —— 站点专用规则
    title, summary = _extract_site_specific(host, soup)
    if title and summary:
        print(f"[link] L1 site rule hit host={host!r}; title={title!r}; summary_len={len(summary)}", flush=True)
        return (title, summary)

    # 第二层 —— 通用 <title> + <meta description>
    gen_title, gen_summary = _extract_generic(soup)
    title = title or gen_title
    summary = summary or gen_summary
    if title and summary:
        print(f"[link] L2 generic; title={title!r}; summary_len={len(summary)}", flush=True)
        return (title, summary)

    # 第三层 —— Gemma 兜底（仅在缺摘要时）
    if not summary:
        body = _extract_body_text(soup, URL_BODY_FOR_LLM)
        if body:
            print(f"[link] L3 Gemma fallback; body_len={len(body)}", flush=True)
            ai = _summarize_with_gemma(body)
            if ai:
                summary = ai

    print(f"[link] final; title={title!r}; summary_len={len(summary or '')}", flush=True)
    return (title, summary)


class FloaterWindow(NSWindow):
    # borderless 窗口默认拒绝成为 key window，键盘焦点会拿不到——必须显式打开
    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True


class FloaterTextView(NSTextView):
    """拦截 Return / Esc，转给 window delegate；空内容时在 drawRect 里手画 placeholder。"""

    def keyDown_(self, event):
        flags = event.modifierFlags()
        chars = event.charactersIgnoringModifiers() or ""
        # Return (\r) 或 Numpad Enter (\x03)
        if chars in ("\r", "\x03"):
            if flags & NSEventModifierFlagShift:
                # Shift+Enter 走默认行为，正常插入换行
                objc.super(FloaterTextView, self).keyDown_(event)
            else:
                self.window().delegate().submit()
            return
        if chars == "\x1b":
            self.window().delegate().cancel()
            return
        objc.super(FloaterTextView, self).keyDown_(event)

    def drawRect_(self, dirty):
        objc.super(FloaterTextView, self).drawRect_(dirty)
        if len(self.string()) > 0:
            return
        font = self.font() or NSFont.systemFontOfSize_(FONT_SIZE)
        attrs = {
            NSFontAttributeName: font,
            NSForegroundColorAttributeName: NSColor.placeholderTextColor(),
        }
        ph = NSAttributedString.alloc().initWithString_attributes_(PLACEHOLDER, attrs)
        origin = self.textContainerOrigin()
        # textContainer 内部默认还有 lineFragmentPadding（一般 5px），placeholder 要对齐到那
        padding = self.textContainer().lineFragmentPadding()
        ph.drawAtPoint_(NSMakePoint(origin.x + padding, origin.y))


class OCROverlayView(NSView):
    """覆盖整屏的半透明遮罩；拖拽产生选区，松手交给 window delegate。"""

    def initWithFrame_(self, frame):
        self = objc.super(OCROverlayView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._start = None
        self._current = None
        return self

    def acceptsFirstResponder(self):
        return True

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        self._start = event.locationInWindow()
        self._current = self._start
        self.setNeedsDisplay_(True)

    def mouseDragged_(self, event):
        self._current = event.locationInWindow()
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        self._current = event.locationInWindow()
        self.setNeedsDisplay_(True)
        delegate = self.window().delegate()
        if delegate is None:
            return
        if self._start is None:
            delegate.selectionCancelled()
            return
        x = min(self._start.x, self._current.x)
        y = min(self._start.y, self._current.y)
        w = abs(self._start.x - self._current.x)
        h = abs(self._start.y - self._current.y)
        if w < 4 or h < 4:
            delegate.selectionCancelled()
            return
        delegate.selectionFinishedWithRect_(NSMakeRect(x, y, w, h))

    def keyDown_(self, event):
        chars = event.charactersIgnoringModifiers() or ""
        if chars == "\x1b":
            delegate = self.window().delegate()
            if delegate is not None:
                delegate.selectionCancelled()
            return
        objc.super(OCROverlayView, self).keyDown_(event)

    def drawRect_(self, dirty):
        # 整屏暗一点
        NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.32).set()
        NSRectFillUsingOperation(self.bounds(), NS_COMPOSITE_SOURCE_OVER)
        if self._start is None or self._current is None:
            return
        x = min(self._start.x, self._current.x)
        y = min(self._start.y, self._current.y)
        w = abs(self._start.x - self._current.x)
        h = abs(self._start.y - self._current.y)
        if w < 1 or h < 1:
            return
        sel_rect = NSMakeRect(x, y, w, h)
        # 用 Clear 操作在遮罩上挖出全透明的选区
        NSColor.clearColor().set()
        NSRectFillUsingOperation(sel_rect, NS_COMPOSITE_CLEAR)
        # 白色细边框
        NSColor.whiteColor().set()
        path = NSBezierPath.bezierPathWithRect_(sel_rect)
        path.setLineWidth_(1.5)
        path.stroke()


class OCROverlayWindow(NSWindow):
    def canBecomeKeyWindow(self):
        return True


class OCROverlayController(NSObject):
    """整屏选区取词的控制器：建窗 → 拖拽 → 截图 → 调用 completion(image_or_None)。"""

    def initWithCompletion_(self, completion):
        self = objc.super(OCROverlayController, self).init()
        if self is None:
            return None
        self._completion = completion
        self._fired = False
        screen = NSScreen.mainScreen() or NSScreen.screens()[0]
        self._screen_frame = screen.frame()
        win = OCROverlayWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            self._screen_frame,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        win.setLevel_(NSScreenSaverWindowLevel)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(False)
        win.setIgnoresMouseEvents_(False)
        win.setAcceptsMouseMovedEvents_(True)
        win.setReleasedWhenClosed_(False)
        win.setDelegate_(self)
        view = OCROverlayView.alloc().initWithFrame_(
            NSMakeRect(0, 0, self._screen_frame.size.width, self._screen_frame.size.height)
        )
        win.setContentView_(view)
        self.window = win
        self._view = view
        return self

    def show(self):
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeFirstResponder_(self._view)
        NSCursor.crosshairCursor().push()

    def _fire_completion(self, image):
        if self._fired:
            return
        self._fired = True
        NSCursor.pop()
        self.window.orderOut_(None)
        if self._completion is not None:
            cb = self._completion
            self._completion = None
            cb(image)

    def selectionFinishedWithRect_(self, rect_in_view):
        # rect 在 view 坐标，等于 window 坐标（view 满铺窗口），窗口又满铺整屏
        win_origin = self.window.frame().origin
        cocoa_x = win_origin.x + rect_in_view.origin.x
        cocoa_y = win_origin.y + rect_in_view.origin.y
        w = rect_in_view.size.width
        h = rect_in_view.size.height
        # Cocoa 全局坐标 → CG 全局坐标：以主屏 (screens()[0]) 顶部为 y=0，向下增
        primary_h = NSScreen.screens()[0].frame().size.height
        cg_y = primary_h - cocoa_y - h
        cg_rect = CGRectMake(cocoa_x, cg_y, w, h)
        win_id = self.window.windowNumber()
        # 用「在我下面的窗口」选项，把自己的遮罩从截图里排除（不依赖 orderOut 时序）
        img = CGWindowListCreateImage(
            cg_rect,
            kCGWindowListOptionOnScreenBelowWindow,
            win_id,
            kCGWindowImageDefault,
        )
        self._fire_completion(img)

    def selectionCancelled(self):
        self._fire_completion(None)

    def windowDidResignKey_(self, _notif):
        # 失焦视作取消（用户切到别处了）
        self._fire_completion(None)


class FloaterController(NSObject):
    def init(self):
        self = objc.super(FloaterController, self).init()
        if self is None:
            return None
        self._visible = False
        self._prev_app = None
        self._in_ocr = False
        self._ocr_overlay = None
        self._pb_old_count = 0
        self._recording = False
        self._transcribing = False
        self._url_fetching = False
        self._recorder = AudioRecorder()
        self._mic_button = None
        self._mic_icon_idle = None
        self._mic_icon_recording = None
        self._build()
        return self

    def _build(self):
        frame = NSMakeRect(0, 0, WIDTH, MIN_HEIGHT)
        self.window = FloaterWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setLevel_(NSFloatingWindowLevel)
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setHasShadow_(True)
        self.window.setReleasedWhenClosed_(False)
        self.window.setHidesOnDeactivate_(False)
        self.window.setMovableByWindowBackground_(True)
        self.window.setDelegate_(self)
        self.window.setAlphaValue_(0.0)

        # 毛玻璃背景：Popover material 会跟随系统深浅外观
        effect = NSVisualEffectView.alloc().initWithFrame_(frame)
        effect.setMaterial_(NSVisualEffectMaterialPopover)
        effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect.setState_(NSVisualEffectStateActive)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(CORNER)
        effect.layer().setMasksToBounds_(True)
        effect.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.window.setContentView_(effect)

        # 文本输入区（NSTextView 嵌在 NSScrollView 里，多行 + 超长时滚动）
        # 右边留 TEXT_RIGHT_GAP 给 OCR 按钮
        inner = NSMakeRect(
            PAD,
            PAD,
            WIDTH - 2 * PAD - TEXT_RIGHT_GAP,
            MIN_HEIGHT - 2 * PAD,
        )
        scroll = NSScrollView.alloc().initWithFrame_(inner)
        scroll.setBorderType_(0)  # NSNoBorder
        scroll.setDrawsBackground_(False)
        scroll.setHasVerticalScroller_(True)
        scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

        tv_frame = NSMakeRect(0, 0, inner.size.width, inner.size.height)
        self.text_view = FloaterTextView.alloc().initWithFrame_(tv_frame)
        self.text_view.setFont_(NSFont.systemFontOfSize_(FONT_SIZE))
        self.text_view.setTextColor_(NSColor.labelColor())
        self.text_view.setBackgroundColor_(NSColor.clearColor())
        self.text_view.setDrawsBackground_(False)
        self.text_view.setRichText_(False)
        self.text_view.setAllowsUndo_(True)
        self.text_view.setInsertionPointColor_(NSColor.labelColor())
        self.text_view.setMinSize_(NSMakeSize(0, inner.size.height))
        self.text_view.setMaxSize_(NSMakeSize(1e7, 1e7))
        self.text_view.setVerticallyResizable_(True)
        self.text_view.setHorizontallyResizable_(False)
        self.text_view.setAutoresizingMask_(NSViewWidthSizable)
        self.text_view.textContainer().setContainerSize_(
            NSMakeSize(inner.size.width, 1e7),
        )
        self.text_view.textContainer().setWidthTracksTextView_(True)
        scroll.setDocumentView_(self.text_view)
        effect.addSubview_(scroll)

        # 右下角「框选文字」按钮（SF Symbol "text.viewfinder"；不可用时退回文字）
        btn_frame = NSMakeRect(
            WIDTH - OCR_BTN_SIZE - OCR_BTN_MARGIN,
            OCR_BTN_MARGIN,
            OCR_BTN_SIZE,
            OCR_BTN_SIZE,
        )
        btn = NSButton.alloc().initWithFrame_(btn_frame)
        btn.setBordered_(False)
        btn.setBezelStyle_(0)
        btn.setTitle_("")
        icon = None
        try:
            icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "text.viewfinder",
                "框选文字识别",
            )
        except Exception:
            icon = None
        if icon is not None:
            icon.setSize_(NSMakeSize(16, 16))
            btn.setImage_(icon)
            btn.setImagePosition_(NS_IMAGE_ONLY)
        else:
            btn.setTitle_("OCR")
        btn.setToolTip_("框选文字识别")
        btn.setTarget_(self)
        btn.setAction_("ocrButtonClicked:")
        # 锚到右下角：左边距与上边距灵活
        btn.setAutoresizingMask_(NSViewMinXMargin | NSViewMaxYMargin)
        effect.addSubview_(btn)
        self._ocr_button = btn

        # 麦克风按钮：放在 OCR 按钮左边
        mic_frame = NSMakeRect(
            WIDTH - OCR_BTN_SIZE - OCR_BTN_MARGIN - BTN_GAP - MIC_BTN_SIZE,
            OCR_BTN_MARGIN,
            MIC_BTN_SIZE,
            MIC_BTN_SIZE,
        )
        mic_btn = NSButton.alloc().initWithFrame_(mic_frame)
        mic_btn.setBordered_(False)
        mic_btn.setBezelStyle_(0)
        mic_btn.setTitle_("")
        mic_idle = None
        mic_rec = None
        try:
            mic_idle = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "mic", "语音输入",
            )
            mic_rec = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "mic.fill", "录音中",
            )
        except Exception:
            mic_idle = None
            mic_rec = None
        if mic_idle is not None:
            mic_idle.setSize_(NSMakeSize(16, 16))
            mic_btn.setImage_(mic_idle)
            mic_btn.setImagePosition_(NS_IMAGE_ONLY)
        else:
            mic_btn.setTitle_("MIC")
        if mic_rec is not None:
            mic_rec.setSize_(NSMakeSize(16, 16))
        mic_btn.setToolTip_("语音输入（mlx-whisper）")
        mic_btn.setTarget_(self)
        mic_btn.setAction_("micButtonClicked:")
        mic_btn.setAutoresizingMask_(NSViewMinXMargin | NSViewMaxYMargin)
        effect.addSubview_(mic_btn)
        self._mic_button = mic_btn
        self._mic_icon_idle = mic_idle
        self._mic_icon_recording = mic_rec

        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self,
            "textDidChange:",
            "NSTextDidChangeNotification",
            self.text_view,
        )

    # ---- 入口（CGEventTap 的 callback 用 AppHelper.callAfter 推到下一个 runloop tick 后调用）----

    def show(self):
        if self._visible:
            return
        self._prev_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        prev_name = self._prev_app.localizedName() if self._prev_app is not None else "<none>"
        prev_pid = self._prev_app.processIdentifier() if self._prev_app is not None else -1
        # 触发前若有选中文字，发一次合成 Cmd+C 把选区抓到剪贴板；
        # 等 150ms 让源 app 把数据贴上 pasteboard，再读取并继续显示。
        pb = NSPasteboard.generalPasteboard()
        self._pb_old_count = pb.changeCount()
        print(
            f"[floater] trigger: prev_app={prev_name!r} (pid={prev_pid}), "
            f"pb.changeCount(pre)={self._pb_old_count}",
            flush=True,
        )
        self._send_cmd_c()
        # 注意：_continue_show 里【先读剪贴板再激活悬浮框】。如果反过来，本进程会变成
        # key window，源 app 失焦——但更糟的是 100ms 内合成事件还在飞，等 Cmd+C 落地时
        # 目标已经是我们自己空的 textview，pasteboard 永远不会更新。
        AppHelper.callLater(0.15, self._continue_show)

    def _continue_show(self):
        pb = NSPasteboard.generalPasteboard()
        cur_count = pb.changeCount()
        types = list(pb.types() or [])
        raw = pb.stringForType_(NSPasteboardTypeString)
        prefill = self._read_clipboard_text(self._pb_old_count)
        snippet = prefill if len(prefill) <= 80 else (prefill[:80] + "...")
        print(
            f"[floater] post-wait: pb.changeCount={cur_count} "
            f"(was {self._pb_old_count}, changed={cur_count != self._pb_old_count}); "
            f"pb.types={types}; "
            f"has_string_type={raw is not None}; "
            f"prefill={snippet!r}",
            flush=True,
        )
        # 是 URL → 先放占位符 + URL，后台线程抓取；否则原样填入
        if _is_url(prefill):
            url = prefill.strip()
            placeholder = f"{URL_FETCH_PLACEHOLDER}\n{url}"
            self.text_view.setString_(placeholder)
            self.text_view.setSelectedRange_(NSMakeRange(len(placeholder), 0))
            # 抓取（尤其是 Gemma 兜底）可能要 30s+，期间用户切走不能算取消
            self._url_fetching = True
            threading.Thread(
                target=self._url_fetch_worker,
                args=(url, placeholder),
                daemon=True,
            ).start()
        else:
            self.text_view.setString_(prefill)
            if prefill:
                self.text_view.setSelectedRange_(NSMakeRange(len(prefill), 0))
        self.text_view.setNeedsDisplay_(True)
        self._resize_to_content()
        self._position_near_cursor()
        # 读完剪贴板才激活：上面已经读过了，到这里激活才安全
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.text_view)
        self._visible = True
        self._fade_to_(1.0, None)

    def _url_fetch_worker(self, url, placeholder):
        tid = threading.get_ident()
        print(f"[link tid={tid}] fetching {url!r}", flush=True)
        title, summary = _fetch_url_summary(url)
        if title or summary:
            parts = []
            if title:
                parts.append(f"[链接] {title}")
            else:
                parts.append("[链接]")
            parts.append(url)
            if summary:
                parts.append(summary)
            result = "\n".join(parts)
        else:
            # 抓取失败 → 只留裸 URL
            result = url
        print(f"[link tid={tid}] result len={len(result)}; scheduling main-thread fill", flush=True)
        AppHelper.callAfter(self._onUrlFetchDone_, (placeholder, result))

    def _onUrlFetchDone_(self, payload):
        self._url_fetching = False
        placeholder, result = payload
        current = str(self.text_view.string())
        if current != placeholder:
            # 用户已经动过 textview（或悬浮框已 hide），放弃覆盖
            print("[link] textview 已被用户改写，丢弃抓取结果", flush=True)
            return
        if not self._visible:
            print("[link] _visible=False，丢弃抓取结果", flush=True)
            return
        self.text_view.setString_(result)
        self.text_view.setSelectedRange_(NSMakeRange(len(result), 0))
        self.text_view.setNeedsDisplay_(True)
        self._resize_to_content()
        # 抓取期间用户可能切走，把悬浮框拉回前台
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.text_view)
        print(f"[link] textview 已更新到 len={len(result)}", flush=True)

    def _send_cmd_c(self):
        KEY_C = 8  # macOS virtual keycode for 'c'
        ev_down = CGEventCreateKeyboardEvent(None, KEY_C, True)
        ev_up = CGEventCreateKeyboardEvent(None, KEY_C, False)
        if ev_down is None or ev_up is None:
            print(
                f"[floater] WARN: CGEventCreateKeyboardEvent 失败 "
                f"(down={ev_down}, up={ev_up})",
                flush=True,
            )
            return
        CGEventSetFlags(ev_down, kCGEventFlagMaskCommand)
        CGEventSetFlags(ev_up, kCGEventFlagMaskCommand)
        # 打标记：让全局事件 tap 认出这是「自己发的」Cmd+C，不要拿它清空三击序列
        CGEventSetIntegerValueField(ev_down, kCGEventSourceUserData, SYNTHETIC_EVENT_TAG)
        CGEventSetIntegerValueField(ev_up, kCGEventSourceUserData, SYNTHETIC_EVENT_TAG)
        CGEventPost(kCGHIDEventTap, ev_down)
        CGEventPost(kCGHIDEventTap, ev_up)
        print("[floater] sent synthetic Cmd+C via kCGHIDEventTap (tagged)", flush=True)

    def _read_clipboard_text(self, old_count):
        pb = NSPasteboard.generalPasteboard()
        # 只在 Cmd+C 真正写入了新内容时才采用，避免拉到陈旧的剪贴板文本
        if pb.changeCount() == old_count:
            return ""
        # 只取纯文字；图片或其它非文本类型一律忽略
        s = pb.stringForType_(NSPasteboardTypeString)
        if not s:
            return ""
        return str(s)

    def hide(self):
        if not self._visible:
            return
        # 录音中被取消：丢弃缓冲，不走转写
        if self._recording:
            try:
                self._recorder.abort()
            except Exception:
                pass
            self._recording = False
            self._setMicRecordingVisual_(False)
        # 先把 _visible 置否，防止 windowDidResignKey 在动画中再次进入 hide
        self._visible = False
        prev = self._prev_app

        def after_fade():
            self.window.orderOut_(None)
            self.text_view.setString_("")
            self.text_view.setNeedsDisplay_(True)
            if prev is not None:
                prev.activateWithOptions_(0)

        self._fade_to_(0.0, after_fade)

    def submit(self):
        text = str(self.text_view.string()).strip()
        if text:
            inbox = today_inbox_path()
            inbox.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            with inbox.open("a", encoding="utf-8") as f:
                f.write(f"[{timestamp}]\n{text}\n\n")
        self.hide()

    def cancel(self):
        self.hide()

    def open_dashboard(self):
        """三击 Command：唤起本地 Web Dashboard。若悬浮框正显示（双击已弹出），先收起再开浏览器。"""
        print(f"[dashboard] 三击 Command → 打开 {DASHBOARD_URL}", flush=True)
        if self._visible:
            self.hide()
        try:
            subprocess.Popen(
                ["open", DASHBOARD_URL],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[dashboard] open 失败: {exc!r}", flush=True)

    # ---- OCR 流程 ----

    def ocrButtonClicked_(self, _sender):
        if self._in_ocr:
            return
        self._in_ocr = True
        # 把现有输入文本缓存下来，OCR 结束后追加到这后面
        self._pre_ocr_text = str(self.text_view.string())
        # 暂时下线悬浮框（直接 orderOut，不走 hide，不要把 prev_app 还回去也不要 fade）
        self.window.orderOut_(None)
        self._visible = False
        self._ocr_overlay = OCROverlayController.alloc().initWithCompletion_(
            self._onOcrImage_
        )
        self._ocr_overlay.show()

    def _onOcrImage_(self, cgimage):
        self._ocr_overlay = None
        self._in_ocr = False
        prev = getattr(self, "_pre_ocr_text", "") or ""
        if cgimage is None:
            # 取消 → 还原原文本
            self._reshow_floater(prev)
            return
        recognized = _run_vision_ocr(cgimage)
        if prev and recognized:
            new_text = prev + "\n" + recognized
        else:
            new_text = prev + recognized
        self._reshow_floater(new_text)

    def _reshow_floater(self, prefill):
        self.text_view.setString_(prefill or "")
        if prefill:
            self.text_view.setSelectedRange_(NSMakeRange(len(prefill), 0))
        self.text_view.setNeedsDisplay_(True)
        self._resize_to_content()
        self._position_near_cursor()
        self.window.setAlphaValue_(1.0)
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.text_view)
        self._visible = True

    # ---- 语音输入流程 ----

    def micButtonClicked_(self, _sender):
        if self._recording:
            self._stop_recording_and_transcribe()
        else:
            self._start_recording()

    def _start_recording(self):
        if not _AUDIO_AVAILABLE:
            print("[floater] sounddevice 未安装，无法录音", flush=True)
            return
        try:
            self._recorder.start()
        except Exception as exc:  # noqa: BLE001
            print(f"[floater] 录音启动失败（首次可能需要麦克风权限）: {exc}", flush=True)
            return
        self._recording = True
        self._setMicRecordingVisual_(True)
        print("[floater] 开始录音", flush=True)

    def _stop_recording_and_transcribe(self):
        if not self._recording:
            return
        self._recording = False
        self._setMicRecordingVisual_(False)
        try:
            wav_path = self._recorder.stop_to_wav()
        except Exception as exc:  # noqa: BLE001
            print(f"[floater] 录音停止失败: {exc}", flush=True)
            return
        if not wav_path:
            print("[floater] 没有采到音频", flush=True)
            return
        print(f"[floater] 录音保存 {wav_path}，开始转写...", flush=True)
        # 关键：转写期间禁止「失焦即 hide」，否则模型下载/推理一长，用户切到别处就会丢结果
        self._transcribing = True
        if self._mic_button is not None:
            self._mic_button.setEnabled_(False)

        def worker():
            tid = threading.get_ident()
            text = ""
            try:
                print(f"[worker tid={tid}] starting _run_whisper", flush=True)
                text = _run_whisper(wav_path)
                print(f"[worker tid={tid}] _run_whisper returned text len={len(text)}", flush=True)
            except Exception as exc:  # noqa: BLE001
                import traceback
                print(f"[worker tid={tid}] uncaught: {exc!r}", flush=True)
                traceback.print_exc()
            finally:
                try:
                    os.unlink(wav_path)
                    print(f"[worker tid={tid}] unlinked {wav_path}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"[worker tid={tid}] unlink 失败: {exc!r}", flush=True)
            print(
                f"[worker tid={tid}] scheduling AppHelper.callAfter(_onTranscriptionDone_, text len={len(text)})",
                flush=True,
            )
            AppHelper.callAfter(self._onTranscriptionDone_, text)
            print(f"[worker tid={tid}] callAfter scheduled, worker exiting", flush=True)

        threading.Thread(target=worker, daemon=True).start()

    def _onTranscriptionDone_(self, text):
        self._transcribing = False
        tid = threading.get_ident()
        print(
            f"[done tid={tid}] _onTranscriptionDone_ ENTERED; "
            f"text={text!r} (len={len(text)}); "
            f"_visible={self._visible}; _in_ocr={self._in_ocr}; _recording={self._recording}",
            flush=True,
        )
        if self._mic_button is not None:
            self._mic_button.setEnabled_(True)
        if not text:
            print("[done] empty text → 返回", flush=True)
            return
        if not self._visible:
            # 用户在转写期间显式按了 Esc / 提交，悬浮框已被销毁——丢弃结果
            print("[done] _visible=False → 结果丢弃（用户已显式取消）", flush=True)
            return
        current = str(self.text_view.string())
        print(f"[done] current textview content: {current!r} (len={len(current)})", flush=True)
        if current:
            sep = "" if current.endswith("\n") else "\n"
            new_text = current + sep + text
        else:
            new_text = text
        self.text_view.setString_(new_text)
        self.text_view.setSelectedRange_(NSMakeRange(len(new_text), 0))
        self.text_view.setNeedsDisplay_(True)
        self._resize_to_content()
        # 转写期间用户可能切到别的 app，悬浮框被推到后面——把它拉回前台并取回焦点
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.text_view)
        print(f"[done] textview 已更新到 len={len(new_text)}", flush=True)

    def _setMicRecordingVisual_(self, is_recording):
        if self._mic_button is None:
            return
        if is_recording:
            try:
                self._mic_button.setContentTintColor_(NSColor.systemRedColor())
            except Exception:
                pass
            if self._mic_icon_recording is not None:
                self._mic_button.setImage_(self._mic_icon_recording)
        else:
            try:
                self._mic_button.setContentTintColor_(None)
            except Exception:
                pass
            if self._mic_icon_idle is not None:
                self._mic_button.setImage_(self._mic_icon_idle)

    # ---- delegate / observer ----

    def windowDidResignKey_(self, _notif):
        print(
            f"[focus] windowDidResignKey fired; _in_ocr={self._in_ocr}; "
            f"_visible={self._visible}; _recording={self._recording}; "
            f"_transcribing={self._transcribing}",
            flush=True,
        )
        if self._in_ocr:
            # OCR 过程中悬浮框被 orderOut 掉了，这次 resignKey 不算用户失焦取消
            return
        if self._transcribing:
            # 转写可能要几十秒（首次还要拉模型），期间用户切到别处不能算取消
            print("[focus] 转写中，忽略本次失焦", flush=True)
            return
        if self._url_fetching:
            # URL 抓取（尤其 Gemma 兜底）也是长流程，同样不算取消
            print("[focus] 链接抓取中，忽略本次失焦", flush=True)
            return
        if self._visible:
            self.hide()

    def textDidChange_(self, _notif):
        self.text_view.setNeedsDisplay_(True)
        self._resize_to_content()

    # ---- helpers ----

    def _fade_to_(self, target_alpha, completion):
        NSAnimationContext.beginGrouping()
        ctx = NSAnimationContext.currentContext()
        ctx.setDuration_(FADE_DURATION)
        if completion is not None:
            ctx.setCompletionHandler_(completion)
        self.window.animator().setAlphaValue_(target_alpha)
        NSAnimationContext.endGrouping()

    def _resize_to_content(self):
        lm = self.text_view.layoutManager()
        tc = self.text_view.textContainer()
        lm.ensureLayoutForTextContainer_(tc)
        used_h = lm.usedRectForTextContainer_(tc).size.height
        content_h = max(MIN_HEIGHT - 2 * PAD, used_h + 6)
        win_h = min(MAX_HEIGHT, content_h + 2 * PAD)
        f = self.window.frame()
        # 反向调整 origin.y 让窗口顶部不抖动（Cocoa 坐标系原点在屏幕左下）
        new_y = f.origin.y + (f.size.height - win_h)
        self.window.setFrame_display_animate_(
            NSMakeRect(f.origin.x, new_y, WIDTH, win_h),
            True,
            False,
        )

    def _position_near_cursor(self):
        loc = NSEvent.mouseLocation()
        screen = NSScreen.mainScreen().visibleFrame()
        win_h = self.window.frame().size.height
        x = loc.x + 14
        y = loc.y - win_h - 14
        # 防出屏
        right_edge = screen.origin.x + screen.size.width
        if x + WIDTH > right_edge - 14:
            x = right_edge - WIDTH - 14
        if y < screen.origin.y + 14:
            y = loc.y + 14
        self.window.setFrameOrigin_(NSMakePoint(x, y))


class DoubleCommandDetector:
    """识别「干净的 Command 双击 / 三击」：

    - 「按下」用 flagsChanged 上 Command flag 由 0→1 的瞬间识别。
    - 「干净」= 这次 Command 按住期间没有任何 keyDown（即不是 Cmd+S / Cmd+Tab 这类组合键）。
    - 「双击」= 两次干净按下的时间差 < DOUBLE_TAP_INTERVAL（press-to-press）→ 唤起悬浮框。
    - 「三击」= 1 秒内三次干净按下（TRIPLE_TAP_WINDOW）→ 打开 Web Dashboard。
    - 中间出现任何 keyDown 都把累积的按下序列作废（打字途中 Cmd 拍一下不应算进来）。

    双击仍然在第二拍就「零延迟」触发悬浮框；若紧接着第三拍落在 1 秒窗口内，会再升级成
    三击触发 Dashboard（open_dashboard 会先把刚弹出的悬浮框收起）。这样常用的双击捕获
    手感不变，三击只是它的罕见叠加态。
    """

    def __init__(self, on_trigger, on_triple=None):
        self._on_trigger = on_trigger
        self._on_triple = on_triple
        self._cmd_held = False
        self._dirty = False               # 当前 Cmd 按住期间是否出现过其他键
        self._cmd_press_time = None       # 当前 Cmd 按下的时刻
        self._press_times = []            # 近期干净 Cmd 按下时刻（裁剪到 1 秒窗口内）

    def handle_flags_changed(self, cmd_now_held, now):
        if cmd_now_held and not self._cmd_held:
            self._cmd_held = True
            self._dirty = False
            self._cmd_press_time = now
        elif not cmd_now_held and self._cmd_held:
            self._cmd_held = False
            press_time = self._cmd_press_time
            self._cmd_press_time = None
            if self._dirty:
                # Cmd 当过修饰键，不算 tap，并把序列清掉
                self._press_times = []
                return
            self._register_clean_press(press_time)

    def _register_clean_press(self, t):
        # 只保留 1 秒窗口内的干净按下
        self._press_times = [p for p in self._press_times if (t - p) < TRIPLE_TAP_WINDOW]
        self._press_times.append(t)
        if len(self._press_times) >= 3:
            # 三击：1 秒内三次干净 Command → Dashboard，并清空序列
            self._press_times = []
            if self._on_triple is not None:
                self._on_triple()
            return
        if (len(self._press_times) == 2
                and (self._press_times[1] - self._press_times[0]) < DOUBLE_TAP_INTERVAL):
            # 双击：立刻触发悬浮框（保持零延迟）。不清空序列——若第三拍仍在 1 秒内会升级成三击。
            self._on_trigger()

    def handle_other_key(self):
        if self._cmd_held:
            self._dirty = True
        # 即便 Cmd 没按住，任何其他键的 keyDown 也作废累积序列——
        # 否则「Cmd-拍、打字、Cmd-拍」会被误判为双击。
        self._press_times = []


class GlobalTrigger:
    """CGEventTap-based 全局双击 Command 监听。

    钩在 kCGSessionEventTap + kCGHeadInsertEventTap 上，浏览器 / Electron / 全屏 app
    的 keyDown handler 之前就拿到事件。需要「辅助功能」权限。"""

    def __init__(self, controller):
        self._controller = controller
        self._tap = None
        self._source = None
        self._detector = DoubleCommandDetector(
            on_trigger=lambda: AppHelper.callAfter(controller.show),
            on_triple=lambda: AppHelper.callAfter(controller.open_dashboard),
        )

    def _on_event(self, proxy, event_type, cgevent, refcon):
        # 系统会因 callback 超时把 tap 关掉，自己重开
        if event_type == kCGEventTapDisabledByTimeout:
            if self._tap is not None:
                CGEventTapEnable(self._tap, True)
            return cgevent
        # 跳过自己合成的 Cmd+C：否则双击弹窗时它会被当成「其他键」清空三击序列
        if CGEventGetIntegerValueField(cgevent, kCGEventSourceUserData) == SYNTHETIC_EVENT_TAG:
            return cgevent
        now = time.monotonic()
        if event_type == kCGEventFlagsChanged:
            flags = CGEventGetFlags(cgevent)
            cmd_held = bool(flags & kCGEventFlagMaskCommand)
            self._detector.handle_flags_changed(cmd_held, now)
        elif event_type == kCGEventKeyDown:
            self._detector.handle_other_key()
        return cgevent

    def start(self):
        mask = (CGEventMaskBit(kCGEventKeyDown)
                | CGEventMaskBit(kCGEventFlagsChanged))
        self._tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            mask,
            self._on_event,
            None,
        )
        if not self._tap:
            return False
        self._source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), self._source, kCFRunLoopCommonModes)
        CGEventTapEnable(self._tap, True)
        return True


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = FloaterController.alloc().init()
    trigger = GlobalTrigger(controller)
    if not trigger.start():
        print("❌ 创建 CGEventTap 失败。这一步硬性需要「辅助功能」权限。")
        print("   到「系统设置 → 隐私与安全性 → 辅助功能」给当前运行 floater 的终端")
        print("   （Terminal / iTerm2 / VS Code 等）打勾后，重新启动这个脚本。")
        return

    print(f"✅ floater 已启动，双击 Command 唤起悬浮框；三击 Command 打开 {DASHBOARD_URL}。")
    print(f"   inbox: {INBOX_DIR}/YYYY-MM-DD/raw.md")

    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
