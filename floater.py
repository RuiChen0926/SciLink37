#!/usr/bin/env python3
"""Floater: 原生 macOS 悬浮捕获（PyObjC + NSVisualEffectView）。
双击 Command 触发（任何场景：浏览器、输入框、全屏 app 都可）。
Enter 保存到 inbox.md，Esc / 失焦取消。
悬浮框右下角有「框选文字」按钮：点击后整屏覆盖半透明遮罩，
拖拽选区，松手后用 macOS Vision (VNRecognizeTextRequest) 做 OCR，
识别结果自动回填到输入框，用户确认后再 Enter 入库。
全局热键基于 CGEventTap (kCGSessionEventTap + kCGHeadInsertEventTap)，
监听 flagsChanged 检测 Command 的「干净双击」——两次按下间隔 < 0.4s，且中间没有其他键。"""
import time
from datetime import datetime
from pathlib import Path

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


INBOX = Path("/Users/rui/Projects/SciLink37/inbox.md")
WIDTH = 400.0
MIN_HEIGHT = 56.0
MAX_HEIGHT = 320.0
PAD = 14.0
CORNER = 12.0
FONT_SIZE = 15.0
PLACEHOLDER = "记录想法..."
FADE_DURATION = 0.12
DOUBLE_TAP_INTERVAL = 0.4  # seconds, press-to-press
OCR_BTN_SIZE = 20.0
OCR_BTN_MARGIN = 6.0
TEXT_RIGHT_GAP = OCR_BTN_SIZE + 4.0  # 留出右下角按钮的位置，避免文本盖到上面
# NSCompositingOperation 常量值（避免依赖某些 PyObjC 版本不导出的别名）
NS_COMPOSITE_CLEAR = 0
NS_COMPOSITE_SOURCE_OVER = 2
NS_IMAGE_ONLY = 1  # NSCellImagePosition.imageOnly


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
        CGEventPost(kCGHIDEventTap, ev_down)
        CGEventPost(kCGHIDEventTap, ev_up)
        print("[floater] sent synthetic Cmd+C via kCGHIDEventTap", flush=True)

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
            INBOX.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            with INBOX.open("a", encoding="utf-8") as f:
                f.write(f"[{timestamp}]\n{text}\n\n")
        self.hide()

    def cancel(self):
        self.hide()

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

    # ---- delegate / observer ----

    def windowDidResignKey_(self, _notif):
        if self._in_ocr:
            # OCR 过程中悬浮框被 orderOut 掉了，这次 resignKey 不算用户失焦取消
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
    """识别「干净的 Command 双击」：

    - 「按下」用 flagsChanged 上 Command flag 由 0→1 的瞬间识别。
    - 「干净」= 这次 Command 按住期间没有任何 keyDown（即不是 Cmd+S / Cmd+Tab 这类组合键）。
    - 「双击」= 两次干净按下的时间差 < DOUBLE_TAP_INTERVAL（press-to-press，跟第二次按住多久无关）。
    - 中间出现任何 keyDown 都把上一次按下作废（用户在打字途中 Cmd 拍一下不应算第一拍）。
    """

    def __init__(self, on_trigger):
        self._on_trigger = on_trigger
        self._cmd_held = False
        self._dirty = False               # 当前 Cmd 按住期间是否出现过其他键
        self._cmd_press_time = None       # 当前 Cmd 按下的时刻
        self._last_clean_press_time = None  # 上一次干净 Cmd 按下的时刻

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
                # Cmd 当过修饰键，不算 tap，并把窗口清掉
                self._last_clean_press_time = None
                return
            if (self._last_clean_press_time is not None
                    and (press_time - self._last_clean_press_time) < DOUBLE_TAP_INTERVAL):
                self._last_clean_press_time = None
                self._on_trigger()
            else:
                self._last_clean_press_time = press_time

    def handle_other_key(self):
        if self._cmd_held:
            self._dirty = True
        # 即便 Cmd 没按住，任何其他键的 keyDown 也作废上一次 tap——
        # 否则「Cmd-拍、打字、Cmd-拍」会被误判为双击。
        self._last_clean_press_time = None


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
        )

    def _on_event(self, proxy, event_type, cgevent, refcon):
        # 系统会因 callback 超时把 tap 关掉，自己重开
        if event_type == kCGEventTapDisabledByTimeout:
            if self._tap is not None:
                CGEventTapEnable(self._tap, True)
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

    print(f"✅ floater 已启动，双击 Command 唤起。inbox: {INBOX}")

    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
