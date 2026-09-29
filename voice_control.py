"""Ameba LED 語音控制台：自動重連、GUI 測試與雙路音訊回饋。"""
from __future__ import annotations

import queue
import gc
import threading
import time
import tkinter as tk
from tkinter import ttk

import pyttsx3
import serial
from serial.tools import list_ports
import speech_recognition as sr

BAUD_RATE = 115200


class SerialManager:
    """持續維護序列埠；拔除 USB 後會關閉舊物件並重新掃描。"""

    def __init__(self, events: queue.Queue):
        self.events = events
        self.preferred_port = "自動偵測"
        self.ser: serial.Serial | None = None
        self.running = True
        self.lock = threading.Lock()
        threading.Thread(target=self._worker, daemon=True).start()

    @staticmethod
    def ports() -> list[str]:
        return [p.device for p in list_ports.comports()]

    def set_port(self, port: str) -> None:
        self.preferred_port = port
        self.disconnect("切換連接埠")

    def _candidates(self) -> list[str]:
        items = list(list_ports.comports())
        if self.preferred_port != "自動偵測":
            return [self.preferred_port] if self.preferred_port in [p.device for p in items] else []
        keys = ("ameba", "realtek", "ch340", "cp210", "usb serial")
        likely = [p.device for p in items if any(k in (p.description or "").lower() for k in keys)]
        return likely + [p.device for p in items if p.device not in likely]

    @property
    def connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def _worker(self) -> None:
        while self.running:
            if not self.connected:
                self.events.put(("connection", "重連中", "正在尋找 Ameba…"))
                for port in self._candidates():
                    try:
                        candidate = serial.Serial(port, BAUD_RATE, timeout=.25, write_timeout=1)
                        time.sleep(1.8)  # UART 開啟時開發板可能重啟
                        candidate.reset_input_buffer()
                        # 只接管會回覆協定的 Ameba，避免誤連藍牙或其他 COM 裝置。
                        candidate.write(b"Q\n")
                        candidate.flush()
                        deadline = time.monotonic() + 1.2
                        verified = False
                        while time.monotonic() < deadline:
                            if "PONG" in candidate.readline().decode("utf-8", errors="replace"):
                                verified = True
                                break
                        if not verified:
                            candidate.close()
                            continue
                        with self.lock:
                            self.ser = candidate
                        self.events.put(("connection", "已連線", port))
                        self.events.put(("log", f"已連接 {port} @ {BAUD_RATE}"))
                        break
                    except (serial.SerialException, OSError):
                        continue
                if not self.connected:
                    time.sleep(1.5)
                    continue
            try:
                current = self.ser
                if current is None:
                    continue
                raw = current.readline()
                if raw:
                    self.events.put(("board", raw.decode("utf-8", errors="replace").strip()))
            except (serial.SerialException, OSError) as exc:
                self.disconnect(f"通訊中斷：{exc}")

    def send(self, command: str) -> bool:
        try:
            with self.lock:
                if not self.connected:
                    raise serial.SerialException("Ameba 尚未連線")
                assert self.ser is not None
                self.ser.write((command + "\n").encode("ascii"))
                self.ser.flush()
            self.events.put(("log", f"送出指令：{command}"))
            return True
        except (serial.SerialException, OSError) as exc:
            self.disconnect(f"傳送失敗：{exc}")
            return False

    def disconnect(self, reason: str) -> None:
        with self.lock:
            old, self.ser = self.ser, None
            if old:
                try:
                    old.close()
                except (serial.SerialException, OSError):
                    pass
        self.events.put(("connection", "已斷線", reason))
        self.events.put(("log", reason))

    def close(self) -> None:
        self.running = False
        self.disconnect("程式關閉")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Ameba 語音與 LED 控制台")
        root.geometry("900x720")
        root.minsize(800, 650)
        root.configure(bg="#F3F6FA")
        self.events: queue.Queue = queue.Queue()
        self.serial = SerialManager(self.events)
        self.recognizer = sr.Recognizer()
        self.listening = threading.Event()
        self.tts_queue: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._tts_worker, daemon=True).start()

        self.connection = tk.StringVar(value="重連中")
        self.detail = tk.StringVar(value="正在尋找 Ameba…")
        self.led = tk.StringVar(value="未知")
        self.voice = tk.StringVar(value="尚未啟用")
        self.last = tk.StringVar(value="—")
        self.output = tk.StringVar(value="筆電喇叭（語音）")
        self.port = tk.StringVar(value="自動偵測")
        self.language = tk.StringVar(value="中英文自動")
        self.recognition_mode = "中英文自動"
        self._build()
        self._refresh_ports()
        root.after(100, self._events)
        root.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        font = "Microsoft JhengHei UI"
        style.configure("TCombobox", padding=7, font=(font, 10), fieldbackground="#FFFFFF")
        style.map("TCombobox", fieldbackground=[("readonly", "#FFFFFF")],
                  selectbackground=[("readonly", "#FFFFFF")], selectforeground=[("readonly", "#172033")])
        style.configure("Action.TButton", font=(font, 10, "bold"), padding=(12, 10),
                        foreground="#FFFFFF", background="#2563EB", borderwidth=0)
        style.map("Action.TButton", background=[("active", "#1D4ED8"), ("pressed", "#1E40AF")])
        style.configure("Success.TButton", font=(font, 10, "bold"), padding=(12, 10),
                        foreground="#FFFFFF", background="#059669", borderwidth=0)
        style.map("Success.TButton", background=[("active", "#047857"), ("pressed", "#065F46")])
        style.configure("Warning.TButton", font=(font, 10, "bold"), padding=(12, 10),
                        foreground="#FFFFFF", background="#D97706", borderwidth=0)
        style.map("Warning.TButton", background=[("active", "#B45309"), ("pressed", "#92400E")])
        style.configure("Soft.TButton", font=(font, 10), padding=(10, 8),
                        foreground="#1E40AF", background="#E8EFFF", borderwidth=0)
        style.map("Soft.TButton", background=[("active", "#D7E3FF"), ("pressed", "#C7D7FE")])

        # 頂部品牌與說明區
        header = tk.Frame(self.root, bg="#173B75", height=105)
        header.pack(fill="x")
        header.pack_propagate(False)
        header_inner = tk.Frame(header, bg="#173B75")
        header_inner.pack(fill="both", expand=True, padx=28, pady=19)
        tk.Label(header_inner, text="AMEBA CONTROL", bg="#173B75", fg="#93C5FD",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Label(header_inner, text="語音與 LED 控制台", bg="#173B75", fg="#FFFFFF",
                 font=(font, 22, "bold")).pack(anchor="w")
        tk.Label(header_inner, text="即時監控 · 自動重連 · 中英文語音控制", bg="#173B75", fg="#D6E4FF",
                 font=(font, 10)).pack(anchor="w", pady=(2, 0))

        main = tk.Frame(self.root, bg="#F3F6FA")
        main.pack(fill="both", expand=True, padx=24, pady=18)

        # 狀態卡片
        status_wrap = tk.Frame(main, bg="#F3F6FA")
        status_wrap.pack(fill="x")
        status_wrap.columnconfigure(0, weight=1)
        status_wrap.columnconfigure(1, weight=1)
        status_wrap.columnconfigure(2, weight=1)

        def status_card(column: int, title: str, variable: tk.StringVar, accent: str) -> tk.Label:
            card = tk.Frame(status_wrap, bg="#FFFFFF", highlightbackground="#E2E8F0",
                            highlightthickness=1, padx=16, pady=12)
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6,
                                                                 0 if column == 2 else 6))
            tk.Frame(card, bg=accent, width=4).pack(side="left", fill="y", padx=(0, 12))
            content = tk.Frame(card, bg="#FFFFFF")
            content.pack(side="left", fill="both", expand=True)
            tk.Label(content, text=title, bg="#FFFFFF", fg="#64748B", font=(font, 9)).pack(anchor="w")
            label = tk.Label(content, textvariable=variable, bg="#FFFFFF", fg="#172033",
                             font=(font, 12, "bold"), anchor="w")
            label.pack(anchor="w", pady=(3, 0))
            return label

        self.connection_value = status_card(0, "連線狀態", self.connection, "#2563EB")
        status_card(1, "LED 狀態", self.led, "#10B981")
        status_card(2, "語音辨識", self.voice, "#F59E0B")

        info = tk.Frame(main, bg="#FFFFFF", highlightbackground="#E2E8F0", highlightthickness=1)
        info.pack(fill="x", pady=(12, 0))
        info.columnconfigure(1, weight=1)
        tk.Label(info, text="裝置訊息", bg="#FFFFFF", fg="#64748B", font=(font, 9)).grid(row=0, column=0, sticky="w", padx=(16, 8), pady=(11, 3))
        tk.Label(info, textvariable=self.detail, bg="#FFFFFF", fg="#172033", font=(font, 10, "bold")).grid(row=0, column=1, sticky="w", pady=(11, 3))
        tk.Label(info, text="最後指令", bg="#FFFFFF", fg="#64748B", font=(font, 9)).grid(row=1, column=0, sticky="w", padx=(16, 8), pady=(3, 11))
        tk.Label(info, textvariable=self.last, bg="#FFFFFF", fg="#172033", font=(font, 10, "bold")).grid(row=1, column=1, sticky="w", pady=(3, 11))

        content = tk.Frame(main, bg="#F3F6FA")
        content.pack(fill="both", expand=True, pady=(12, 0))
        content.columnconfigure(0, weight=5)
        content.columnconfigure(1, weight=6)
        content.rowconfigure(0, weight=1)

        left = tk.Frame(content, bg="#FFFFFF", highlightbackground="#E2E8F0", highlightthickness=1, padx=16, pady=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tk.Label(left, text="連線與語音設定", bg="#FFFFFF", fg="#172033", font=(font, 12, "bold")).pack(anchor="w", pady=(0, 10))
        tk.Label(left, text="序列埠", bg="#FFFFFF", fg="#64748B", font=(font, 9)).pack(anchor="w")
        port_row = tk.Frame(left, bg="#FFFFFF")
        port_row.pack(fill="x", pady=(4, 10))
        self.port_combo = ttk.Combobox(port_row, textvariable=self.port, state="readonly")
        self.port_combo.pack(side="left", fill="x", expand=True)
        self.port_combo.bind("<<ComboboxSelected>>", lambda _e: self.serial.set_port(self.port.get()))
        ttk.Button(port_row, text="重新掃描", style="Soft.TButton", command=self._refresh_ports).pack(side="left", padx=(8, 0))
        tk.Label(left, text="回饋輸出", bg="#FFFFFF", fg="#64748B", font=(font, 9)).pack(anchor="w")
        ttk.Combobox(left, textvariable=self.output, state="readonly",
                     values=("筆電喇叭（語音）", "Ameba 喇叭／蜂鳴器（提示音）", "兩者")).pack(fill="x", pady=(4, 10))
        tk.Label(left, text="辨識語言", bg="#FFFFFF", fg="#64748B", font=(font, 9)).pack(anchor="w")
        ttk.Combobox(left, textvariable=self.language, state="readonly",
                     values=("中英文自動", "中文（繁體）", "English (US)")).pack(fill="x", pady=(4, 12))
        self.listen_btn = ttk.Button(left, text="開始語音辨識", style="Action.TButton", command=self._toggle_listen)
        self.listen_btn.pack(fill="x")

        right = tk.Frame(content, bg="#FFFFFF", highlightbackground="#E2E8F0", highlightthickness=1, padx=16, pady=14)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.columnconfigure(0, weight=1)
        right.columnconfigure(1, weight=1)
        right.rowconfigure(4, weight=1)
        tk.Label(right, text="快速測試", bg="#FFFFFF", fg="#172033", font=(font, 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Button(right, text="左邊藍燈", style="Action.TButton", command=lambda: self.process("左邊開燈")).grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=4)
        ttk.Button(right, text="右邊綠燈", style="Success.TButton", command=lambda: self.process("右邊開燈")).grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=4)
        ttk.Button(right, text="閃爍三次", style="Warning.TButton", command=lambda: self.process("閃爍三次")).grid(row=2, column=0, sticky="ew", padx=(0, 4), pady=4)
        ttk.Button(right, text="連線測試", style="Soft.TButton", command=self._ping).grid(row=2, column=1, sticky="ew", padx=(4, 0), pady=4)
        ttk.Button(right, text="播放測試", style="Soft.TButton", command=lambda: self._feedback("播放測試成功", "0")).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 10))

        log_header = tk.Frame(right, bg="#172033")
        log_header.grid(row=4, column=0, columnspan=2, sticky="nsew")
        tk.Label(log_header, text="執行紀錄", bg="#172033", fg="#E2E8F0", font=(font, 9, "bold")).pack(anchor="w", padx=11, pady=(8, 4))
        log_body = tk.Frame(log_header, bg="#172033")
        log_body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.log = tk.Text(log_body, height=7, state="disabled", wrap="word", relief="flat",
                           bg="#172033", fg="#CBD5E1", insertbackground="#FFFFFF",
                           selectbackground="#334155", font=("Cascadia Mono", 9), padx=3, pady=3)
        scroll = ttk.Scrollbar(log_body, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _refresh_ports(self) -> None:
        values = ["自動偵測"] + SerialManager.ports()
        self.port_combo["values"] = values
        if self.port.get() not in values: self.port.set("自動偵測")

    def _write_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _events(self) -> None:
        try:
            while True:
                kind, *data = self.events.get_nowait()
                if kind == "connection":
                    self.connection.set(data[0]); self.detail.set(data[1])
                    colors = {"已連線": "#059669", "重連中": "#D97706", "已斷線": "#DC2626"}
                    self.connection_value.configure(fg=colors.get(data[0], "#172033"))
                elif kind == "board": self._board(data[0])
                elif kind == "voice": self.voice.set(data[0])
                elif kind == "recognized": self.process(data[0])
                elif kind == "stopped": self.listen_btn.configure(text="開始語音辨識", style="Action.TButton")
                elif kind == "log": self._write_log(data[0])
        except queue.Empty:
            pass
        self.root.after(100, self._events)

    def _board(self, message: str) -> None:
        self._write_log(f"Ameba：{message}")
        if "Blue LED ON" in message: self.led.set("左邊藍燈亮")
        elif "Green LED ON" in message: self.led.set("右邊綠燈亮")
        elif "Flashed 3 times" in message: self.led.set("已閃爍三次（目前熄滅）")
        elif "PONG" in message: self.detail.set("連線測試成功")

    def _ping(self) -> None:
        self.last.set("連線測試")
        if not self.serial.send("Q"): self._write_log("測試失敗；背景仍會繼續重連。")

    def process(self, text: str) -> None:
        normalized = text.lower().replace(" ", "")
        english = not any("\u4e00" <= char <= "\u9fff" for char in text)
        self.last.set(text)
        self._write_log(f"辨識／測試指令：{text}")
        command = self._command_for(normalized)
        if command == "B":
            reply, tone_id = ("The left blue light is on" if english else "已開啟左邊藍燈"), "1"
        elif command == "G":
            reply, tone_id = ("The right green light is on" if english else "已開啟右邊綠燈"), "2"
        elif command == "F":
            reply, tone_id = ("Flashing the lights three times" if english else "正在閃爍三次"), "3"
        elif command == "EXIT":
            self._close(); return
        else:
            self._feedback("Command not recognized" if english else "無法辨識這個控制指令", "4"); return
        if self.serial.send(command): self._feedback(reply, tone_id)
        else: self._feedback("Ameba 尚未連線，請稍候自動重連", "4")

    @staticmethod
    def _command_for(normalized: str) -> str | None:
        """將中英文的自然說法對應到 Ameba 單字元指令。"""
        if any(x in normalized for x in ("左邊開燈", "開左燈", "藍燈", "turnonleft", "switchonleft",
                                         "leftlight", "leftled", "turnonblue", "bluelight", "blueled")):
            return "B"
        if any(x in normalized for x in ("右邊開燈", "開右燈", "綠燈", "turnonright", "switchonright",
                                         "rightlight", "rightled", "turnongreen", "greenlight", "greenled")):
            return "G"
        if any(x in normalized for x in ("閃爍3次", "閃爍三次", "閃三次", "blink", "flash")):
            return "F"
        if any(x in normalized for x in ("退出", "結束", "exit", "quit", "closeprogram", "stopeverything")):
            return "EXIT"
        return None

    def _feedback(self, text: str, tone_id: str) -> None:
        target = self.output.get()
        if target in ("筆電喇叭（語音）", "兩者"):
            self.events.put(("log", f"語音已排入播放：{text}"))
            self.tts_queue.put(text)
        if target in ("Ameba 喇叭／蜂鳴器（提示音）", "兩者") and not self.serial.send("T" + tone_id):
            self._write_log("Ameba 提示音無法播放：裝置未連線。")

    def _tts_worker(self) -> None:
        # Windows SAPI/pyttsx3 的同一個事件迴圈有時只能正常播放第一段。
        # 每次重新建立並釋放引擎，讓後續每一條控制指令都能發聲。
        while True:
            text = self.tts_queue.get()
            if text is None:
                return
            engine = None
            try:
                self.events.put(("log", f"開始播放語音：{text}"))
                engine = pyttsx3.init()
                engine.setProperty("rate", 180)
                engine.say(text)
                engine.runAndWait()
                self.events.put(("log", "語音播放完成"))
            except Exception as exc:
                # 單次播放失敗不能終止工作執行緒，下一條指令仍可再試。
                self.events.put(("log", f"筆電語音播放錯誤：{exc}"))
            finally:
                if engine is not None:
                    try:
                        engine.stop()
                    except Exception:
                        pass
                del engine
                gc.collect()
                self.tts_queue.task_done()

    def _toggle_listen(self) -> None:
        if self.listening.is_set():
            self.listening.clear(); self.voice.set("正在停止…")
            self.listen_btn.configure(text="正在停止…", style="Soft.TButton")
        else:
            # Tk 變數只在主執行緒讀取，再將純字串交給背景辨識執行緒。
            self.recognition_mode = self.language.get()
            self.listening.set(); self.listen_btn.configure(text="停止語音辨識", style="Warning.TButton")
            threading.Thread(target=self._listen_worker, daemon=True).start()

    def _listen_worker(self) -> None:
        try:
            with sr.Microphone() as source:
                self.events.put(("voice", "校正環境噪音中…"))
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                while self.listening.is_set():
                    self.events.put(("voice", "聆聽中"))
                    try:
                        audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=5)
                        text = self._recognize(audio)
                        self.events.put(("voice", f"辨識到：{text}")); self.events.put(("recognized", text))
                    except sr.WaitTimeoutError: continue
                    except sr.UnknownValueError: self.events.put(("voice", "沒有聽清楚，繼續聆聽"))
                    except sr.RequestError as exc:
                        self.events.put(("voice", "語音服務無法使用")); self.events.put(("log", f"語音服務錯誤：{exc}")); break
        except (OSError, AttributeError) as exc:
            self.events.put(("voice", "找不到可用的麥克風")); self.events.put(("log", f"麥克風錯誤：{exc}"))
        finally:
            self.listening.clear(); self.events.put(("stopped",))

    def _recognize(self, audio: sr.AudioData) -> str:
        mode = self.recognition_mode
        if mode == "中文（繁體）":
            return self.recognizer.recognize_google(audio, language="zh-TW")
        if mode == "English (US)":
            return self.recognizer.recognize_google(audio, language="en-US")

        # 自動模式同時比較兩種辨識結果，優先使用能匹配控制指令的文字。
        results: list[str] = []
        for code in ("en-US", "zh-TW"):
            try:
                candidate = self.recognizer.recognize_google(audio, language=code)
                results.append(candidate)
                normalized = candidate.lower().replace(" ", "")
                if self._command_for(normalized) is not None:
                    self.events.put(("log", f"自動辨識採用 {code}：{candidate}"))
                    return candidate
            except sr.UnknownValueError:
                continue
        if results:
            return results[0]
        raise sr.UnknownValueError()

    def _close(self) -> None:
        self.listening.clear(); self.serial.close(); self.tts_queue.put(None); self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk(); App(root); root.mainloop()
