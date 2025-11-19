#!/usr/bin/env python3
"""
Unreal MetaHuman WebSocket Interface - ADVANCED VERSION
Permet envoi asynchrone des événements:
- Speaking control (Start/Stop avec catégories)
- Contextual animations (PROSODY, INTENT, SEMANTIC)
- Audio + events combinés
"""

import sys
import json
import socket
import time
import wave
import asyncio
from pathlib import Path
from typing import Optional
import threading

import websockets

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QComboBox, QTextEdit, QGroupBox,
    QProgressBar, QCheckBox, QSpinBox, QDoubleSpinBox, QTabWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont

# Configuration
WEBSOCKET_HOST = "localhost"
WEBSOCKET_PORT = 8765
UDP_HOST = "localhost"
UDP_PORT = 8080

# Audio settings
TARGET_SAMPLE_RATE = 24000  # 24kHz
TARGET_CHANNELS = 1  # Mono
CHUNK_SIZE = 320  # 13.33ms at 24kHz for 75 FPS
CHUNK_DELAY = 0.01333  # 13.33ms = 75 FPS

# Audio folder
AUDIO_FOLDER = Path(__file__).parent.parent / "audio2face_webrtc" / "audio"

# Animation categories (from AnimationController)
SPEAKING_CATEGORIES = [
    "SPEAKING_NEUTRAL",
    "SPEAKING_EXPLAIN",
    "SPEAKING_ENTHUSIASTIC",
    "SPEAKING_SAD",
    "SPEAKING_ANGRY",
    "SPEAKING_REFLECTIVE",
    "SPEAKING_CONFUSED",
    "SPEAKING_CALM",
    "SEMANTIC_NEGATE"
]

CONTEXTUAL_CATEGORIES = [
    "PROSODY_EMPHASIS",
    "PROSODY_QUESTION",
    "INTENT_EXPLAIN",
    "INTENT_ENUMERATE",
    "SEMANTIC_SELF_REFERENCE",
    "SEMANTIC_ICONIC_SIZE",
    "SEMANTIC_ICONIC_SHAPE",
    "SEMANTIC_METAPHOR_GROUP",
    "SEMANTIC_NEGATE"
]


class PersistentWebSocketClient(QThread):
    """
    Persistent WebSocket connection in background thread
    Always connected, ready to send events instantly
    """
    connected_signal = pyqtSignal(bool)
    status_update = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.websocket = None
        self.running = True
        self.loop = None
        self.ready_to_send = False

    def run(self):
        """Run async event loop in thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.maintain_connection())

    async def maintain_connection(self):
        """Maintain persistent WebSocket connection"""
        while self.running:
            try:
                uri = f"ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}"
                self.status_update.emit(f"🔌 Connecting to {uri}...")

                async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as websocket:
                    self.websocket = websocket
                    self.ready_to_send = True
                    self.status_update.emit("✅ WebSocket connected and ready!")
                    self.connected_signal.emit(True)

                    # Wait for ready from Unreal
                    try:
                        ready_msg = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                        ready_data = json.loads(ready_msg)
                        if ready_data.get("type") == "ready":
                            fps = ready_data.get("fps", 0)
                            self.status_update.emit(f"🎮 Unreal ready (FPS: {fps:.1f})")
                    except asyncio.TimeoutError:
                        pass  # No ready event, that's ok

                    # Keep connection alive
                    while self.running:
                        try:
                            # Just wait for messages (or until connection closes)
                            msg = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                            # Process any messages from Unreal
                            try:
                                data = json.loads(msg)
                                msg_type = data.get("type", "unknown")
                                self.status_update.emit(f"📨 From Unreal: {msg_type}")
                            except:
                                pass
                        except asyncio.TimeoutError:
                            continue  # Timeout is ok, just keep alive

            except websockets.exceptions.ConnectionClosed:
                self.status_update.emit("⚠️  Connection closed, reconnecting...")
                self.ready_to_send = False
                self.connected_signal.emit(False)
                await asyncio.sleep(2)  # Wait before reconnect
            except Exception as e:
                self.status_update.emit(f"❌ Connection error: {e}")
                self.ready_to_send = False
                self.connected_signal.emit(False)
                await asyncio.sleep(2)  # Wait before reconnect

        # Cleanup
        if self.websocket:
            await self.websocket.close()

    async def send_event_async(self, event_data: dict):
        """Send event via WebSocket (async)"""
        if self.websocket and self.ready_to_send:
            await self.websocket.send(json.dumps(event_data))
        else:
            raise ConnectionError("WebSocket not ready")

    def send_event(self, event_data: dict):
        """Send event via WebSocket (sync wrapper)"""
        if self.loop and self.websocket and self.ready_to_send:
            future = asyncio.run_coroutine_threadsafe(
                self.send_event_async(event_data),
                self.loop
            )
            future.result(timeout=1.0)  # Wait max 1 second
        else:
            raise ConnectionError("WebSocket not ready")

    def stop(self):
        """Stop the connection"""
        self.running = False
        self.wait()


class AudioSender(QThread):
    """
    Audio sender with optional start/stop speaking events
    """
    status_update = pyqtSignal(str)
    progress_update = pyqtSignal(int)
    finished_signal = pyqtSignal(bool)

    def __init__(self, ws_client: PersistentWebSocketClient,
                 audio_file_path: Optional[Path],
                 send_speaking_events: bool,
                 speaking_category: str):
        super().__init__()
        self.ws_client = ws_client
        self.audio_file_path = audio_file_path
        self.send_speaking_events = send_speaking_events
        self.speaking_category = speaking_category
        self.running = True

    def run(self):
        """Send audio with optional speaking events"""
        try:
            success = True

            if self.audio_file_path:
                # Send START_SPEAKING event
                if self.send_speaking_events:
                    self.status_update.emit(f"🎤 START_SPEAKING ({self.speaking_category})")
                    start_event = {
                        "type": "start_speaking",
                        "category": self.speaking_category,
                        "timestamp": time.time()
                    }
                    self.ws_client.send_event(start_event)
                    self.status_update.emit("✅ Start speaking event sent")

                # Send START_AUDIO_STREAM
                self.status_update.emit("🎬 START_AUDIO_STREAM")
                start_audio_event = {
                    "type": "start_audio_stream",
                    "timestamp": time.time()
                }
                self.ws_client.send_event(start_audio_event)
                self.status_update.emit("✅ Start audio event sent")

                # Send audio via UDP
                time.sleep(0.05)  # Small delay for Unreal to process
                self.status_update.emit("🎵 Sending audio via UDP...")
                audio_data = self.convert_audio_to_pcm16(self.audio_file_path)
                chunks_sent = self.send_udp_chunks(audio_data)
                self.status_update.emit(f"✅ Audio sent: {chunks_sent} chunks")

                # Send END_AUDIO_STREAM
                self.status_update.emit("🛑 END_AUDIO_STREAM")
                end_audio_event = {
                    "type": "end_audio_stream",
                    "timestamp": time.time(),
                    "chunks_sent": chunks_sent
                }
                self.ws_client.send_event(end_audio_event)
                self.status_update.emit("✅ End audio event sent")

                # Send STOP_SPEAKING event
                if self.send_speaking_events:
                    self.status_update.emit("🛑 STOP_SPEAKING")
                    stop_event = {
                        "type": "stop_speaking",
                        "timestamp": time.time()
                    }
                    self.ws_client.send_event(stop_event)
                    self.status_update.emit("✅ Stop speaking event sent")

            self.status_update.emit("=" * 60)
            self.status_update.emit("✅ AUDIO SENT SUCCESSFULLY")
            self.status_update.emit("=" * 60)

        except Exception as e:
            self.status_update.emit(f"❌ Error: {e}")
            success = False

        self.finished_signal.emit(success)

    def convert_audio_to_pcm16(self, audio_path: Path) -> bytes:
        """Convert audio to PCM16 24kHz mono"""
        self.status_update.emit(f"📂 File: {audio_path.name}")

        with wave.open(str(audio_path), 'rb') as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()

            self.status_update.emit(f"🔄 Converting from {sample_rate}Hz, {channels}ch, {sample_width*8}bit")

            audio_data = wf.readframes(wf.getnframes())

            # Resample if needed
            if sample_rate != TARGET_SAMPLE_RATE:
                import numpy as np
                from scipy import signal

                audio_array = np.frombuffer(audio_data, dtype=np.int16)

                # Convert to mono if stereo
                if channels == 2:
                    audio_array = audio_array.reshape(-1, 2).mean(axis=1).astype(np.int16)

                # Resample
                num_samples = int(len(audio_array) * TARGET_SAMPLE_RATE / sample_rate)
                audio_array = signal.resample(audio_array, num_samples).astype(np.int16)

                audio_data = audio_array.tobytes()

            self.status_update.emit(f"✅ Converted: {len(audio_data)} bytes")
            return audio_data

    def send_udp_chunks(self, audio_data: bytes) -> int:
        """Send audio chunks via UDP"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        total_chunks = len(audio_data) // (CHUNK_SIZE * 2)
        chunks_sent = 0

        self.status_update.emit(f"📡 Sending {len(audio_data) / 1024:.1f} KB ({total_chunks} chunks)")

        for i in range(0, len(audio_data), CHUNK_SIZE * 2):
            if not self.running:
                break

            chunk = audio_data[i:i + CHUNK_SIZE * 2]

            if len(chunk) < CHUNK_SIZE * 2:
                chunk = chunk + b'\x00' * (CHUNK_SIZE * 2 - len(chunk))

            sock.sendto(chunk, (UDP_HOST, UDP_PORT))
            chunks_sent += 1

            if chunks_sent % 75 == 0:
                progress = int((chunks_sent / total_chunks) * 100)
                self.progress_update.emit(progress)
                self.status_update.emit(f"📊 Progress: {chunks_sent}/{total_chunks} chunks ({progress}%)")

            time.sleep(CHUNK_DELAY)

        # Add 2 seconds silence
        self.status_update.emit("🔇 Sending 2s silence...")
        silence_chunk = b'\x00' * (CHUNK_SIZE * 2)
        for _ in range(150):  # 2 seconds at 75 FPS
            sock.sendto(silence_chunk, (UDP_HOST, UDP_PORT))
            time.sleep(CHUNK_DELAY)

        sock.close()
        return chunks_sent


class UnrealWebSocketInterface(QMainWindow):
    """Advanced interface with separate controls for speaking and contextual animations"""

    def __init__(self):
        super().__init__()
        self.audio_files = []
        self.send_thread = None
        self.speaking_active = False

        # Start persistent WebSocket client
        self.ws_client = PersistentWebSocketClient()
        self.ws_client.status_update.connect(self.log)
        self.ws_client.connected_signal.connect(self.on_connection_status)
        self.ws_client.start()

        self.init_ui()
        self.load_audio_files()

    def init_ui(self):
        self.setWindowTitle("Unreal MetaHuman WebSocket Interface - Advanced Control")
        self.setGeometry(100, 100, 1600, 900)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()

        # Header
        header = QLabel("🎮 Unreal Engine - Advanced WebSocket Control")
        header.setFont(QFont("Arial", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("QLabel { background-color: #8e44ad; color: white; padding: 20px; }")
        main_layout.addWidget(header)

        # Connection status
        self.conn_status = QLabel("🔴 Disconnected")
        self.conn_status.setFont(QFont("Arial", 12, QFont.Bold))
        self.conn_status.setStyleSheet("QLabel { background-color: #e74c3c; color: white; padding: 10px; }")
        main_layout.addWidget(self.conn_status)

        # Tabs for different control modes
        tabs = QTabWidget()

        # Tab 1: Speaking Control
        speaking_tab = self.create_speaking_tab()
        tabs.addTab(speaking_tab, "🎤 Speaking Control")

        # Tab 2: Contextual Animations
        contextual_tab = self.create_contextual_tab()
        tabs.addTab(contextual_tab, "🎭 Contextual Animations")

        # Tab 3: Audio + Full Control
        full_tab = self.create_full_control_tab()
        tabs.addTab(full_tab, "🎵 Audio + Full Control")

        main_layout.addWidget(tabs)

        # Log panel
        log_panel = QGroupBox("📋 Output Log")
        log_panel.setStyleSheet("QGroupBox { font-weight: bold; font-size: 12pt; }")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("QTextEdit { font-family: 'Courier New'; font-size: 10pt; }")
        log_layout.addWidget(self.log_text)
        log_panel.setLayout(log_layout)
        main_layout.addWidget(log_panel)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        central_widget.setLayout(main_layout)

    def create_speaking_tab(self):
        """Tab for speaking control (start/stop with categories)"""
        tab = QWidget()
        layout = QVBoxLayout()

        # Speaking category selection
        category_group = QGroupBox("🎤 Speaking Category")
        category_layout = QVBoxLayout()
        category_layout.addWidget(QLabel("Select speaking style:"))
        self.speaking_category_combo = QComboBox()
        self.speaking_category_combo.addItems(SPEAKING_CATEGORIES)
        category_layout.addWidget(self.speaking_category_combo)
        category_group.setLayout(category_layout)
        layout.addWidget(category_group)

        # Control buttons
        buttons_layout = QHBoxLayout()

        self.start_speaking_btn = QPushButton("▶️ START SPEAKING")
        self.start_speaking_btn.setFont(QFont("Arial", 12, QFont.Bold))
        self.start_speaking_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                padding: 15px;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """)
        self.start_speaking_btn.clicked.connect(self.start_speaking)
        self.start_speaking_btn.setEnabled(False)
        buttons_layout.addWidget(self.start_speaking_btn)

        self.stop_speaking_btn = QPushButton("⏹️ STOP SPEAKING")
        self.stop_speaking_btn.setFont(QFont("Arial", 12, QFont.Bold))
        self.stop_speaking_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                padding: 15px;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """)
        self.stop_speaking_btn.clicked.connect(self.stop_speaking)
        self.stop_speaking_btn.setEnabled(False)
        buttons_layout.addWidget(self.stop_speaking_btn)

        layout.addLayout(buttons_layout)

        # Status indicator
        self.speaking_status = QLabel("⚪ Speaking: OFF")
        self.speaking_status.setFont(QFont("Arial", 14, QFont.Bold))
        self.speaking_status.setStyleSheet("QLabel { background-color: #95a5a6; color: white; padding: 10px; }")
        layout.addWidget(self.speaking_status)

        layout.addStretch()

        tab.setLayout(layout)
        return tab

    def create_contextual_tab(self):
        """Tab for contextual animations (async sending)"""
        tab = QWidget()
        layout = QVBoxLayout()

        # Contextual animation selection
        anim_group = QGroupBox("🎭 Contextual Animation")
        anim_layout = QVBoxLayout()

        anim_layout.addWidget(QLabel("Select contextual category:"))
        self.contextual_category_combo = QComboBox()
        self.contextual_category_combo.addItems(CONTEXTUAL_CATEGORIES)
        anim_layout.addWidget(self.contextual_category_combo)

        # Intensity slider
        anim_layout.addWidget(QLabel("Intensity:"))
        self.contextual_intensity = QSlider(Qt.Horizontal)
        self.contextual_intensity.setMinimum(0)
        self.contextual_intensity.setMaximum(100)
        self.contextual_intensity.setValue(80)
        self.contextual_intensity_label = QLabel("0.80")
        anim_layout.addWidget(self.contextual_intensity)
        anim_layout.addWidget(self.contextual_intensity_label)
        self.contextual_intensity.valueChanged.connect(
            lambda v: self.contextual_intensity_label.setText(f"{v/100:.2f}")
        )

        # Duration slider
        anim_layout.addWidget(QLabel("Duration (seconds):"))
        self.contextual_duration = QDoubleSpinBox()
        self.contextual_duration.setMinimum(0.5)
        self.contextual_duration.setMaximum(10.0)
        self.contextual_duration.setValue(2.0)
        self.contextual_duration.setSingleStep(0.5)
        anim_layout.addWidget(self.contextual_duration)

        anim_group.setLayout(anim_layout)
        layout.addWidget(anim_group)

        # Send button
        self.send_contextual_btn = QPushButton("⚡ SEND CONTEXTUAL ANIMATION")
        self.send_contextual_btn.setFont(QFont("Arial", 12, QFont.Bold))
        self.send_contextual_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                padding: 15px;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """)
        self.send_contextual_btn.clicked.connect(self.send_contextual_animation)
        self.send_contextual_btn.setEnabled(False)
        layout.addWidget(self.send_contextual_btn)

        layout.addStretch()

        tab.setLayout(layout)
        return tab

    def create_full_control_tab(self):
        """Tab for audio with speaking events"""
        tab = QWidget()
        layout = QVBoxLayout()

        # Audio selection
        audio_group = QGroupBox("🎵 Audio Selection")
        audio_layout = QVBoxLayout()
        audio_layout.addWidget(QLabel("Select audio file:"))
        self.audio_combo = QComboBox()
        audio_layout.addWidget(self.audio_combo)
        audio_group.setLayout(audio_layout)
        layout.addWidget(audio_group)

        # Speaking options
        speaking_group = QGroupBox("🎤 Speaking Options")
        speaking_layout = QVBoxLayout()

        self.send_speaking_check = QCheckBox("Send speaking events with audio")
        self.send_speaking_check.setChecked(True)
        speaking_layout.addWidget(self.send_speaking_check)

        speaking_layout.addWidget(QLabel("Speaking category:"))
        self.full_speaking_category = QComboBox()
        self.full_speaking_category.addItems(SPEAKING_CATEGORIES)
        speaking_layout.addWidget(self.full_speaking_category)

        speaking_group.setLayout(speaking_layout)
        layout.addWidget(speaking_group)

        # Send button
        self.send_audio_btn = QPushButton("🎵 SEND AUDIO")
        self.send_audio_btn.setFont(QFont("Arial", 12, QFont.Bold))
        self.send_audio_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                padding: 15px;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """)
        self.send_audio_btn.clicked.connect(self.send_audio)
        self.send_audio_btn.setEnabled(False)
        layout.addWidget(self.send_audio_btn)

        layout.addStretch()

        tab.setLayout(layout)
        return tab

    def on_connection_status(self, connected: bool):
        """Update UI when connection status changes"""
        if connected:
            self.conn_status.setText("🟢 Connected and Ready!")
            self.conn_status.setStyleSheet("QLabel { background-color: #27ae60; color: white; padding: 10px; }")
            self.start_speaking_btn.setEnabled(True)
            self.send_contextual_btn.setEnabled(True)
            self.send_audio_btn.setEnabled(True)
        else:
            self.conn_status.setText("🔴 Disconnected")
            self.conn_status.setStyleSheet("QLabel { background-color: #e74c3c; color: white; padding: 10px; }")
            self.start_speaking_btn.setEnabled(False)
            self.stop_speaking_btn.setEnabled(False)
            self.send_contextual_btn.setEnabled(False)
            self.send_audio_btn.setEnabled(False)

    def load_audio_files(self):
        """Load audio files from folder"""
        if AUDIO_FOLDER.exists():
            self.audio_files = sorted(AUDIO_FOLDER.glob("*.wav"))
            for audio_file in self.audio_files:
                self.audio_combo.addItem(audio_file.name, audio_file)
            self.log(f"✅ Loaded {len(self.audio_files)} audio files")
        else:
            self.log(f"⚠️  Audio folder not found: {AUDIO_FOLDER}")

    def start_speaking(self):
        """Start speaking mode"""
        if not self.ws_client.ready_to_send:
            self.log("❌ WebSocket not ready")
            return

        category = self.speaking_category_combo.currentText()

        try:
            event = {
                "type": "start_speaking",
                "category": category,
                "timestamp": time.time()
            }
            self.ws_client.send_event(event)
            self.log(f"✅ START_SPEAKING sent: {category}")

            self.speaking_active = True
            self.speaking_status.setText(f"🟢 Speaking: {category}")
            self.speaking_status.setStyleSheet("QLabel { background-color: #27ae60; color: white; padding: 10px; }")
            self.start_speaking_btn.setEnabled(False)
            self.stop_speaking_btn.setEnabled(True)

        except Exception as e:
            self.log(f"❌ Error sending start_speaking: {e}")

    def stop_speaking(self):
        """Stop speaking mode"""
        if not self.ws_client.ready_to_send:
            self.log("❌ WebSocket not ready")
            return

        try:
            event = {
                "type": "stop_speaking",
                "timestamp": time.time()
            }
            self.ws_client.send_event(event)
            self.log("✅ STOP_SPEAKING sent")

            self.speaking_active = False
            self.speaking_status.setText("⚪ Speaking: OFF")
            self.speaking_status.setStyleSheet("QLabel { background-color: #95a5a6; color: white; padding: 10px; }")
            self.start_speaking_btn.setEnabled(True)
            self.stop_speaking_btn.setEnabled(False)

        except Exception as e:
            self.log(f"❌ Error sending stop_speaking: {e}")

    def send_contextual_animation(self):
        """Send contextual animation event"""
        if not self.ws_client.ready_to_send:
            self.log("❌ WebSocket not ready")
            return

        category = self.contextual_category_combo.currentText()
        intensity = self.contextual_intensity.value() / 100.0
        duration = self.contextual_duration.value()

        try:
            event = {
                "type": "contextual_animation",
                "category": category,
                "intensity": intensity,
                "duration": duration,
                "timestamp": time.time()
            }
            self.ws_client.send_event(event)
            self.log(f"✅ Contextual animation sent: {category} (intensity={intensity:.2f}, duration={duration}s)")

        except Exception as e:
            self.log(f"❌ Error sending contextual animation: {e}")

    def send_audio(self):
        """Send audio with optional speaking events"""
        if self.send_thread and self.send_thread.isRunning():
            self.log("⚠️  Already sending...")
            return

        if not self.ws_client.ready_to_send:
            self.log("❌ WebSocket not ready")
            return

        # Get selections
        audio_index = self.audio_combo.currentIndex()
        audio_file = self.audio_files[audio_index] if audio_index >= 0 and self.audio_files else None

        if not audio_file:
            self.log("❌ No audio file selected")
            return

        send_speaking = self.send_speaking_check.isChecked()
        speaking_category = self.full_speaking_category.currentText()

        self.log("=" * 60)
        self.log(f"🎵 Sending audio: {audio_file.name}")
        if send_speaking:
            self.log(f"🎤 With speaking events: {speaking_category}")
        self.log("=" * 60)

        # Create sender thread
        self.send_thread = AudioSender(
            self.ws_client,
            audio_file,
            send_speaking,
            speaking_category
        )
        self.send_thread.status_update.connect(self.log)
        self.send_thread.progress_update.connect(self.progress_bar.setValue)
        self.send_thread.finished_signal.connect(self.on_send_finished)
        self.send_thread.start()

    def on_send_finished(self, success: bool):
        """Called when send is finished"""
        self.progress_bar.setValue(100 if success else 0)

    def log(self, message: str):
        """Add message to log"""
        self.log_text.append(message)

    def closeEvent(self, event):
        """Cleanup on close"""
        self.ws_client.stop()
        if self.send_thread and self.send_thread.isRunning():
            self.send_thread.running = False
            self.send_thread.wait()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = UnrealWebSocketInterface()
    window.show()
    sys.exit(app.exec_())
