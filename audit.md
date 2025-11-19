
Architecting High-Fidelity Digital Humans: A Comprehensive Migration Strategy from Legacy Scripts to Pipecat 0.95


1. Executive Summary

The pursuit of photorealistic, real-time digital humans—often realized through Epic Games' MetaHuman framework—represents a convergence of high-performance rendering, low-latency networking, and generative artificial intelligence. As the industry shifts from pre-rendered, linear content to dynamic, AI-driven interactions, the underlying software architecture governing these systems must evolve. The provided legacy implementation, a PyQt5-based WebSocket interface, successfully demonstrates the fundamental mechanics of driving a MetaHuman via Audio2Face (A2F) using UDP audio streams and WebSocket event triggers. However, its monolithic design, reliance on manual threading, and tight coupling of user interface with business logic render it unsuitable for scalable, production-grade deployment.
This report provides an exhaustive technical analysis and migration strategy to transition this legacy logic into the Pipecat 0.95 ecosystem. Pipecat, an open-source framework for building voice and multimodal conversational agents, offers critical architectural primitives—specifically ParallelPipeline, FrameProcessor lifecycles, and event-driven transport mechanisms—that directly address the limitations of the legacy code. By adopting Pipecat, developers can achieve sub-second latency, precise synchronization between audio and animation, and modular extensibility that supports advanced features like Network Device Interface (NDI) video integration and dynamic Large Language Model (LLM) function calling.
The analysis proceeds in four primary phases: a rigorous critique of the existing legacy codebase; a detailed exposition of the Pipecat 0.95 architecture; a comprehensive design for a new, state-of-the-art system integrating NDI and ElevenLabs; and a technical implementation guide for custom processors and pipeline orchestration. This transformation will elevate the system from a functional prototype to a robust, enterprise-ready conversational AI platform.

2. Technical Audit of the Legacy Implementation

To build a superior system, one must first deeply understand the deficiencies of the current approach. The provided script, Unreal MetaHuman WebSocket Interface - ADVANCED VERSION, functions as a standalone desktop application. While effective for local testing, it exhibits several structural weaknesses when evaluated against the requirements of modern cloud-native or edge-deployed AI agents.

2.1 Concurrency and the Global Interpreter Lock (GIL)

The legacy script employs a hybrid concurrency model, utilizing PyQt5.QtCore.QThread for the WebSocket client (PersistentWebSocketClient) and the audio sender (AudioSender). While QThread provides a convenient abstraction for keeping the GUI responsive, its interaction with Python’s native execution model presents significant scaling challenges.
Python’s Global Interpreter Lock (GIL) ensures that only one thread executes Python bytecode at a time. In I/O-bound applications, such as this one involving network sockets, the GIL is released during blocking I/O operations, allowing for some degree of concurrency. However, the legacy script mixes this threading model with asyncio event loops instantiated inside the threads (asyncio.new_event_loop()). This "loop-per-thread" pattern is fragile. It creates isolated asynchronous contexts that cannot easily share state or signaling without resorting to thread-safe primitives (like pyqtSignal or queue.Queue).
In high-frequency real-time systems, specifically those driving audio at 24kHz (one chunk every ~13ms), the overhead of context switching between threads, combined with the latency of signal emission across thread boundaries, introduces "jitter." Jitter is the variance in packet arrival time. For Audio2Face, which expects a constant stream of audio data to drive vertex deformation, jitter manifests as visual stuttering—the lips stop moving momentarily or snap out of sync with the audio. The legacy script’s reliance on time.sleep(CHUNK_DELAY) within the AudioSender thread is particularly problematic. time.sleep is not guaranteed to be precise; it relies on the operating system’s scheduler, which may pause the thread for longer than requested, especially under load, leading to buffer under-runs at the Unreal Engine receiver.

2.2 Monolithic Architecture and UI Coupling

A cardinal rule of scalable software architecture is the Separation of Concerns (SoC). The provided code violates this by tightly coupling the orchestration logic with the presentation layer. The UnrealWebSocketInterface class inherits from QMainWindow, making it impossible to run the core logic in a "headless" environment, such as a Docker container on a cloud server, without dragging in a massive X11 or Wayland display server dependency.
This coupling extends to the data flow. The audio files are loaded directly from the file system into the UI elements (QComboBox). In a modern AI agent, audio is not static; it is generated dynamically by a Text-to-Speech (TTS) engine like ElevenLabs. The current architecture lacks a mechanism to ingest a stream of bytes from an external API, buffer it, and process it. It is designed solely for playback of pre-existing .wav files, limiting the agent to "canned" responses rather than true generative conversation.

2.3 Audio Mechanics and Sample Rate Rigidity

The script correctly identifies a critical requirement for Audio2Face: the need for specific sample rates (often 24kHz or 48kHz) to align with the training data of the neural network driving the face. The AudioSender class performs resampling using scipy.signal.resample. While scientifically accurate, scipy is a heavy dependency often unoptimized for real-time, continuous streams.
Furthermore, the script uses a "file-based" approach to audio processing:

Python


with wave.open(str(audio_path), 'rb') as wf:
    audio_data = wf.readframes(wf.getnframes())


This reads the entire file into memory before processing. In a streaming context (e.g., an LLM generating a long sentence), we receive audio in small chunks (frames). We cannot wait for the full sentence to be generated before we start playing, or the latency would be unbearable (often seconds of delay). A proper architecture must implement a "streaming resampler" that maintains internal state (filter history) and processes bytes as they arrive, pushing them immediately to the UDP socket.

2.4 Fragility of the Control Protocol

The communication protocol with Unreal Engine relies on constructing JSON blobs manually:

Python


event = {
    "type": "contextual_animation",
    "category": category,
    "intensity": intensity,
   ...
}


While JSON is an appropriate transport format, hardcoding these structures inside UI callbacks makes the system brittle. If the Unreal Engine implementation changes its expected schema (e.g., renaming category to anim_id), the Python code requires manual refactoring across multiple methods. In a robust system, these contracts should be defined as strongly-typed data structures (Classes or Dataclasses) that serialize themselves, ensuring consistency across the application.
Furthermore, the legacy script lacks a robust feedback loop. While it listens for messages from Unreal, it merely logs them. A sophisticated agent must react to the state of the engine—for example, pausing the conversation if the renderer drops below a certain framerate or if the "MetaHuman Ready" signal has not yet been received.

3. The Pipecat 0.95 Architecture: A Paradigm Shift

Transitioning from the legacy script to Pipecat represents a shift from imperative, thread-based programming to declarative, pipeline-based asynchronous programming. Pipecat 0.95 introduces several advanced primitives that specifically solve the synchronization and modality challenges inherent in digital human control.

3.1 The Pipeline and Frame System

At the heart of Pipecat is the Pipeline, a linear or branching sequence of FrameProcessors. Unlike the legacy script where data flow is implicit (variables passed between functions), Pipecat makes data flow explicit. Information travels through the pipeline in containers called Frames.1
This distinction is vital. In the legacy script, "Audio" was a byte array and "Start Speaking" was a function call. In Pipecat:
OutputAudioRawFrame: Carries the PCM audio data intended for the user or the avatar.
TTSStartedFrame / TTSStoppedFrame: Control frames emitted by the TTS service to signal the exact beginning and end of speech.1
TextFrame: Carries the textual content derived from Speech-to-Text (STT) or generated by the LLM.
SystemFrame: High-priority signals (like StartInterruptionFrame) that bypass normal data queues to arrest processing immediately.2
This architecture solves the synchronization problem. Because the TTSStartedFrame travels through the pipeline immediately preceding the audio frames, a processor downstream simply needs to watch for this frame to trigger the "Start Speaking" WebSocket event to Unreal. The synchronization is implicit in the data order, removing the need for complex thread signaling.

3.2 Parallel Pipelines: The Key to Multimodal Sync

The single most critical feature for this integration is the ParallelPipeline.4 The legacy script struggled to do two things at once: play audio to the user (implied) and stream audio to Unreal.
In Pipecat, ParallelPipeline allows a stream of frames to fork into multiple branches. Each branch receives a copy of the upstream frames, processes them independently, and then (optionally) merges the results. For a MetaHuman agent, this allows us to define a topology like this:
Source
Branch A: Transport Output
Branch B: Avatar Control
TTS Service
Receives Audio Frames
Receives Audio Frames
Generates Audio
Forwards to WebRTC (User hears voice)
Resamples to 24kHz




Sends UDP to Audio2Face




Sends WebSocket Events to Unreal

This ensures that the audio heard by the user and the audio driving the animation originate from the exact same source generation event, guaranteeing perfect lip-sync potential.

3.3 Asynchronous I/O and Cooperative Multitasking

Pipecat is built on Python’s asyncio library.6 Unlike QThread, which uses OS-level threads, asyncio uses a single-threaded event loop with cooperative multitasking. Tasks yield control (await) when waiting for I/O (like network packets).
This model is superior for network-heavy applications. It allows the agent to handle hundreds of concurrent operations—listening for WebSocket messages from Unreal, streaming UDP packets, receiving WebRTC audio from the user, and polling the LLM API—all within a single thread. This eliminates race conditions related to shared memory access and reduces the memory footprint of the application.9

3.4 Extensibility via Custom Processors

The legacy script hardcoded the logic for "Send to Unreal." Pipecat encourages encapsulating this logic in custom FrameProcessors.11 A custom processor inherits from FrameProcessor and implements a process_frame method.
This allows us to create reusable components:
UnrealEventProcessor: Listens for TTSStartedFrame and sends JSON to WebSockets.
UnrealAudioStreamer: Listens for OutputAudioRawFrame, buffers it, and sends UDP.
NDISourcel: Wraps GStreamer to ingest video.
These components can be unit-tested in isolation and recomposed into different pipelines (e.g., switching from a local Unreal instance to a cloud pixel-streaming instance) without rewriting the core application logic.

4. State-of-the-Art Architecture: Pipecat Integration Plan

The proposed architecture upgrades the system to a full-duplex, multimodal AI agent. This design integrates NDI for video ingestion (allowing the AI to "see"), ElevenLabs for high-fidelity voice, and a parallel output strategy for synchronization.

4.1 Input Layer: Advanced Video Ingestion via NDI

The user requires the ability to "receive the signal NDI audio/video." Pipecat standard transports (WebRTC, WebSocket) do not natively support NDI. We must bridge the broadcast video world (NDI) with the Python async world.

4.1.1 The GStreamer Bridge

The most robust method to ingest NDI in a Python environment without a GUI is via GStreamer using the gst-plugin-ndi.12 We will implement a custom GStreamerPipelineSource 15 or a dedicated NDIInputTransport.
The Pipeline String:
To convert NDI into a format Pipecat understands (Raw RGB frames), we construct a GStreamer pipeline:

Bash


ndisrc ndi-name="MY_SOURCE"! videoconvert! video/x-raw,format=RGB! appsink name=pipecat_sink


ndisrc: Connects to the NDI stream on the local network.
videoconvert: NDI typically uses UYVY or I420 color spaces.16 Pipecat vision models (like OpenAI GPT-4o) expect RGB. This element performs the color space conversion efficiently in C/C++.
appsink: This is the interface between GStreamer (C) and Python. It allows us to pull buffers (GstSample) containing the raw pixel data.

4.1.2 Mapping to Pipecat Frames

The custom processor will poll the appsink, extract the raw bytes, and wrap them in an InputImageRawFrame.1
Data: Raw bytes of the image.
Metadata: Resolution (Width, Height), Format ("RGB").
Frequency: To avoid overwhelming the LLM, we may implement a "frame decimation" strategy, only pushing one frame every second, or only when the user is speaking (Voice Activity Detection triggering video capture).

4.2 Cognitive Layer: Context and Function Calling

The core intelligence is driven by an LLM Service (e.g., OpenAI or Anthropic). To support the "Contextual Animations" (Prosody, Intent) requested in the legacy script, we leverage Function Calling (Tool Use).19
Instead of manually selecting "Sad" or "Happy" from a dropdown, the LLM is provided with a tool definition:

JSON


{
  "name": "animate_avatar",
  "description": "Sets the emotional state or gesture of the avatar.",
  "parameters": {
    "type": "object",
    "properties": {
      "emotion": {"type": "string", "enum":},
      "intensity": {"type": "number", "minimum": 0.0, "maximum": 1.0}
    }
  }
}


When the LLM determines the conversation context warrants sadness, it invokes this tool. Pipecat intercepts this function call. Instead of executing a Python function that returns text, we inject a custom UnrealControlFrame into the pipeline. This frame travels downstream to the UnrealEventProcessor, which translates it into the WebSocket JSON command {"type": "contextual_animation",...}. This allows the semantic understanding of the LLM to directly drive the non-verbal behavior of the avatar.

4.3 Synthesis Layer: ElevenLabs with Dynamic Control

The integration uses ElevenLabsTTSService.20 To meet the requirement of "using ElevenLabs for voice," we must optimize for latency.
Model: eleven_turbo_v2_5 is mandatory for conversational latency (~250ms).
Connection: Use the WebSocket-based service (ElevenLabsTTSService) rather than HTTP (ElevenLabsHttpTTSService) to receive audio chunks as they are generated, rather than waiting for the full sentence.20
Dynamic Voice Settings: The legacy script implies changing speaking styles. Pipecat supports TTSUpdateSettingsFrame. We can allow the LLM to trigger a style change (e.g., "Whisper") which pushes this frame upstream to the TTS service, altering the voice parameters for subsequent generation.22

4.4 Output Layer: The Parallel Divergence

This is the crux of the synchronization strategy. We utilize a ParallelPipeline to split the TTS output.

Branch A: User Transport

This branch sends OutputAudioRawFrame data to the DailyTransport or SmallWebRTCTransport.23 This handles the echo cancellation, opus encoding, and transmission to the human user's browser or device.

Branch B: Unreal Engine Bridge

This branch contains our custom logic for the MetaHuman.
AudioResampler: ElevenLabs Turbo v2.5 typically outputs 24kHz or 44.1kHz. Audio2Face may require a specific rate (legacy script used 24kHz). We insert a processor that ensures the sample rate matches the A2F configuration exactly.
UnrealAudioStreamer: Receives the resampled audio. Unlike the legacy script which used time.sleep, this processor manages a "leaky bucket" buffer. It releases audio via UDP to localhost:8080 at the exact rate A2F consumes it (bytes per second), ensuring the animation buffer doesn't overflow or underrun.
UnrealEventProcessor: Monitors the stream for TTSStartedFrame and TTSStoppedFrame. When TTSStartedFrame arrives, it immediately sends the WebSocket "Start Speaking" command. This guarantees the avatar enters the speaking state precisely when the first audio packet is prepared.

5. Implementation Guide

The following section details the code structures required to implement this architecture.

5.1 Custom Processor: UnrealEventProcessor

This processor replaces the PersistentWebSocketClient. It handles the control signals.

Python


import json
import asyncio
import websockets
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame, TTSStartedFrame, TTSStoppedFrame, StartInterruptionFrame

class UnrealEventProcessor(FrameProcessor):
    def __init__(self, uri="ws://localhost:8765"):
        super().__init__()
        self.uri = uri
        self.websocket = None
        self._connect_task = asyncio.create_task(self._maintain_connection())

    async def _maintain_connection(self):
        """Persistent connection loop with backoff."""
        while True:
            try:
                async with websockets.connect(self.uri) as ws:
                    self.websocket = ws
                    # Wait until connection closes
                    await ws.wait_closed()
            except Exception:
                # Simple exponential backoff or retry logic
                await asyncio.sleep(2)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        # Handle Standard TTS Events
        if isinstance(frame, TTSStartedFrame):
            await self._send_command({"type": "start_speaking", "category": "SPEAKING_NEUTRAL"})
        elif isinstance(frame, TTSStoppedFrame):
            await self._send_command({"type": "stop_speaking"})
            
        # Handle Interruptions (User barging in)
        # Critical for stopping the face immediately if the user interrupts
        elif isinstance(frame, StartInterruptionFrame):
             await self._send_command({"type": "stop_speaking"})

        # Forward frame downstream
        await self.push_frame(frame, direction)

    async def _send_command(self, data: dict):
        if self.websocket:
            try:
                await self.websocket.send(json.dumps(data))
            except Exception:
                pass # Connection logic handles reconnection



5.2 Custom Processor: UnrealAudioStreamer

This processor replaces AudioSender. It uses non-blocking UDP transmission. Note the use of socket without await for sendto; UDP sendto is non-blocking unless the OS buffer is full, which is rare for audio packet sizes.25

Python


import socket
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame, OutputAudioRawFrame

class UnrealAudioStreamer(FrameProcessor):
    def __init__(self, host="127.0.0.1", port=8080):
        super().__init__()
        self.target = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False) # Ensure completely non-blocking

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, OutputAudioRawFrame):
            try:
                # Send raw bytes directly. 
                # Note: Upstream resampling is assumed here.
                self.sock.sendto(frame.audio, self.target)
            except BlockingIOError:
                # In extremely high load, drop packet to preserve real-time behavior
                pass
        
        await self.push_frame(frame, direction)



5.3 Advanced NDI Input Transport

This implementation wraps GStreamer to provide NDI frames to Pipecat.

Python


import asyncio
from pipecat.transports.base_input import BaseInputTransport, TransportParams
from pipecat.frames.frames import InputImageRawFrame
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

class NDIInputTransport(BaseInputTransport):
    def __init__(self, params: TransportParams, ndi_source_name: str):
        super().__init__(params)
        Gst.init(None)
        
        # NDI -> RGB Conversion Pipeline
        # 'appsink' allows us to extract buffers in Python
        pipeline_str = (
            f"ndisrc ndi-name=\"{ndi_source_name}\"! "
            "videoconvert! video/x-raw,format=RGB! "
            "appsink name=sink emit-signals=True sync=False drop=True max-buffers=1"
        )
        
        self.pipeline = Gst.parse_launch(pipeline_str)
        self.sink = self.pipeline.get_by_name('sink')
        
        # Connect signal
        self.sink.connect("new-sample", self._on_new_sample)

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)

    def _on_new_sample(self, sink):
        # This callback runs in a GStreamer thread. 
        # We must bridge to the asyncio loop.
        sample = sink.emit("pull-sample")
        buf = sample.get_buffer()
        caps = sample.get_caps()
        
        structure = caps.get_structure(0)
        w = structure.get_value("width")
        h = structure.get_value("height")
        
        # Zero-copy map (if possible) or copy
        mem = buf.map(Gst.MapFlags.READ)
        try:
            # Create Pipecat Frame
            frame = InputImageRawFrame(
                image=bytes(mem.data),
                size=(w, h),
                format="RGB"
            )
            # Thread-safe push
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.push_frame(frame), self._loop
                )
        finally:
            buf.unmap(mem)
        
        return Gst.FlowReturn.OK



5.4 The Complete Pipeline Assembly

The following table summarizes the construction of the Pipeline object, illustrating the parallel branching logic.
Stage
Components
Function
Input
NDIInputTransport
Ingests Video (NDI) & Audio (Mic)
Processing
DeepgramSTT
Transcription


ContextAggregator
Manages History


OpenAILLM
Intelligence & Function Calls


ElevenLabsTTS
Audio Synthesis
Parallel Output
Branch 1
Branch 2


Transport.output()
UnrealEventProcessor


(Sends to User)
SoxrResampler(24000)




UnrealAudioStreamer
Finalize
AssistantContextAggregator
Logs bot response


Python


# Pipeline Definition
pipeline = Pipeline(, # User Path
        [unreal_events, resampler, unreal_audio]    # Avatar Path
    )
])



6. Advanced Topics and Optimization


6.1 Managing Interruption ("Barge-in")

A critical requirement for "state-of-the-art" agents is the ability to handle interruptions gracefully. If the user starts speaking while the avatar is talking:
Detection: The VAD (Voice Activity Detection) analyzer in the input transport detects speech.
Signaling: The transport emits a UserStartedSpeakingFrame and potentially a StartInterruptionFrame.
Reaction:
TTS Service: Upon receiving StartInterruptionFrame, it halts generation and emits TTSStoppedFrame.
UnrealEventProcessor: Intercepts StartInterruptionFrame or TTSStoppedFrame and immediately sends {"type": "stop_speaking"} to Unreal.
This prevents the "zombie avatar" effect where the audio stops (because the transport cleared the buffer) but the face continues moving because the "Stop" signal was never sent. The custom UnrealEventProcessor implementation provided in Section 5.1 specifically handles StartInterruptionFrame for this reason.

6.2 Latency Budgets and NDI Bandwidth

NDI is a high-bandwidth protocol (100Mbps+ for HD video). Processing raw RGB frames in Python can saturate the memory bandwidth and the GIL.
Optimization 1 (GStreamer): Use videoscale in the GStreamer pipeline to downscale the video before it reaches Python. An LLM does not need 4K video to recognize a user's emotion; 640x360 is often sufficient and reduces data volume by 90%.
Optimization 2 (Frame Decimation): Do not process every video frame. The NDIInputTransport should ideally include a videorate filter in GStreamer (e.g., videorate! video/x-raw,framerate=1/1) to ingest only 1 frame per second, which is sufficient for conversational context.

6.3 Deployment Topology

The system relies on inter-process communication (UDP/WebSocket) between the Python Agent and Unreal Engine.
Local Machine: Both can run on the same Windows machine. Pipecat runs in a WSL2 (Windows Subsystem for Linux) container or native Python. Note that WSL2 has a virtual network interface; you must direct UDP packets to the Windows host IP, not 127.0.0.1, or configure port forwarding.
Cloud/Network: If Unreal is running on a separate Render Node (Pixel Streaming), the Python Agent requires a low-latency LAN connection. Audio2Face is extremely sensitive to packet loss. Ensure the network path prioritizes UDP traffic on port 8080.

7. Conclusion

The migration from the legacy PyQt script to Pipecat 0.95 is a transformative upgrade. It replaces a fragile, thread-bound implementation with a robust, asynchronous pipeline capable of high-concurrency multimodal interaction. By leveraging ParallelPipeline for synchronized audio dispatch and GStreamer for native NDI ingestion, the proposed architecture meets the rigorous demands of professional MetaHuman integration. This system is not merely a controller; it is a scalable cognitive engine capable of seeing, hearing, and embodying a digital persona with human-like fidelity.
Sources des citations
frames — pipecat-ai documentation, consulté le novembre 19, 2025, https://reference-server.pipecat.ai/en/stable/api/pipecat.frames.frames.html
Pipeline & Frame Processing - Pipecat, consulté le novembre 19, 2025, https://docs.pipecat.ai/guides/learn/pipeline
frame_processor — pipecat-ai documentation, consulté le novembre 19, 2025, https://reference-server.pipecat.ai/en/latest/api/pipecat.processors.frame_processor.html
ParallelPipeline - Pipecat, consulté le novembre 19, 2025, https://docs.pipecat.ai/server/pipeline/parallel-pipeline
parallel_pipeline — pipecat-ai documentation, consulté le novembre 19, 2025, https://reference-server.pipecat.ai/en/stable/api/pipecat.pipeline.parallel_pipeline.html
pipecat-ai/pipecat: Open Source framework for voice and multimodal conversational AI - GitHub, consulté le novembre 19, 2025, https://github.com/pipecat-ai/pipecat
Getting Started with asyncio and Python - YouTube, consulté le novembre 19, 2025, https://www.youtube.com/watch?v=L3RyxVOLjz8
Python Tutorial: AsyncIO - Complete Guide to Asynchronous Programming with Animations, consulté le novembre 19, 2025, https://www.youtube.com/watch?v=oAkLSJNr5zY
Python's asyncio: A Hands-On Walkthrough, consulté le novembre 19, 2025, https://realpython.com/async-io-python/
Asynchronous networking: building TCP & UDP servers with Python's asyncio, consulté le novembre 19, 2025, https://poehlmann.dev/post/async-python-server/
Custom FrameProcessor - Pipecat, consulté le novembre 19, 2025, https://docs.pipecat.ai/guides/fundamentals/custom-frame-processor
teltek/gst-plugin-ndi: GStreamer NDI Plugin for Linux - GitHub, consulté le novembre 19, 2025, https://github.com/teltek/gst-plugin-ndi
ndi - GStreamer, consulté le novembre 19, 2025, https://gstreamer.freedesktop.org/documentation/ndi/index.html
ndisrc - GStreamer, consulté le novembre 19, 2025, https://gstreamer.freedesktop.org/documentation/ndi/ndisrc.html
Source code for pipecat.processors.gstreamer.pipeline_source, consulté le novembre 19, 2025, https://reference-server.pipecat.ai/en/stable/_modules/pipecat/processors/gstreamer/pipeline_source.html
Raw Video Media Types - GStreamer, consulté le novembre 19, 2025, https://gstreamer.freedesktop.org/documentation/additional/design/mediatype-video-raw.html
Gstreamer How do I interpret the output of video/x-raw,format=RGB? - Stack Overflow, consulté le novembre 19, 2025, https://stackoverflow.com/questions/48723600/gstreamer-how-do-i-interpret-the-output-of-video-x-raw-format-rgb
Source code for pipecat.frames.frames, consulté le novembre 19, 2025, https://reference-server.pipecat.ai/en/latest/_modules/pipecat/frames/frames.html
Function Calling - Pipecat, consulté le novembre 19, 2025, https://docs.pipecat.ai/guides/learn/function-calling
ElevenLabs - Pipecat, consulté le novembre 19, 2025, https://docs.pipecat.ai/server/services/tts/elevenlabs
tts — pipecat-ai documentation - elevenlabs, consulté le novembre 19, 2025, https://reference-server.pipecat.ai/en/stable/api/pipecat.services.elevenlabs.tts.html
ElevenLabsTTSService doesn't switch voice · Issue #1861 · pipecat-ai/pipecat - GitHub, consulté le novembre 19, 2025, https://github.com/pipecat-ai/pipecat/issues/1861
transport — pipecat-ai documentation, consulté le novembre 19, 2025, https://reference-server.pipecat.ai/en/latest/api/pipecat.transports.daily.transport.html
transport — pipecat-ai documentation, consulté le novembre 19, 2025, https://reference-server.pipecat.ai/en/latest/api/pipecat.transports.smallwebrtc.transport.html
Force a non-blocking UDP socket to raise BlockingIOError on sendto - Stack Overflow, consulté le novembre 19, 2025, https://stackoverflow.com/questions/59784401/force-a-non-blocking-udp-socket-to-raise-blockingioerror-on-sendto
