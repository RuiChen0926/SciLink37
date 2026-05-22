#!/usr/bin/env python3
"""Floater: 原生 macOS 悬浮捕获（PyObjC + NSVisualEffectView）。
双击 Command 触发（任何场景：浏览器、输入框、全屏 app 都可），Enter 保存到 inbox.md，Esc / 失焦取消。
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
    NSColor,
    NSEvent,
    NSEventModifierFlagShift,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSScreen,
    NSScrollView,
    NSTextView,
    NSViewHeightSizable,
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
    CGEventGetFlags,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCGEventFlagMaskCommand,
    kCGEventFlagsChanged,
    kCGEventKeyDown,
    kCGEventTapDisabledByTimeout,
    kCGEventTapOptionListenOnly,
    kCGHeadInsertEventTap,
    kCGSessionEventTap,
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


class FloaterController(NSObject):
    def init(self):
        self = objc.super(FloaterController, self).init()
        if self is None:
            return None
        self._visible = False
        self._prev_app = None
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

        # 文本输入区（NSTextView 嵌在 NSScrollView 里，支持多行 + 超长时滚动）
        inner = NSMakeRect(PAD, PAD, WIDTH - 2 * PAD, MIN_HEIGHT - 2 * PAD)
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
        self.text_view.setString_("")
        self.text_view.setNeedsDisplay_(True)
        self._resize_to_content()
        self._position_near_cursor()
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.text_view)
        self._visible = True
        self._fade_to_(1.0, None)

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

    # ---- delegate / observer ----

    def windowDidResignKey_(self, _notif):
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
