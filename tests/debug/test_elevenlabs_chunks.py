#!/usr/bin/env python3
"""Test ElevenLabs directly to analyze audio chunks.

This script calls ElevenLabs WITHOUT Pipecat to see exactly what audio is returned.
"""

import asyncio
import os
import sys
import time
import wave
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs import AsyncElevenLabs

load_dotenv()

# Test phrases
TEST_PHRASES = [
    "Bonjour! Comment puis-je vous aider aujourd'hui?",
    "Bien sûr! Je suis là pour répondre à vos questions.",
    "C'est une excellente question. Laissez-moi vous expliquer en détail.",
]


async def test_elevenlabs_streaming():
    """Test ElevenLabs streaming to see chunk details."""

    api_key = os.getenv("ELEVENLABS_API_KEY")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID")

    if not api_key or not voice_id:
        print("❌ Missing ELEVENLABS_API_KEY or ELEVENLABS_VOICE_ID")
        sys.exit(1)

    client = AsyncElevenLabs(api_key=api_key)

    print("=" * 70)
    print("  ElevenLabs Chunk Analysis")
    print("=" * 70)
    print(f"Voice ID: {voice_id}")
    print(f"Model: eleven_flash_v2_5")
    print("=" * 70)

    for i, phrase in enumerate(TEST_PHRASES, 1):
        print(f"\n{'='*70}")
        print(f"Test {i}: {phrase}")
        print("=" * 70)

        chunks = []
        chunk_sizes = []
        total_bytes = 0
        start_time = time.time()
        first_chunk_time = None

        try:
            # Stream audio
            audio_stream = client.text_to_speech.convert(
                voice_id=voice_id,
                text=phrase,
                model_id="eleven_flash_v2_5",
                output_format="pcm_24000",  # 24kHz PCM
            )

            chunk_num = 0
            async for chunk in audio_stream:
                chunk_num += 1
                chunk_size = len(chunk)
                total_bytes += chunk_size
                chunks.append(chunk)
                chunk_sizes.append(chunk_size)

                if first_chunk_time is None:
                    first_chunk_time = time.time() - start_time

                # Calculate duration (24kHz, 16-bit = 2 bytes per sample)
                duration_ms = (chunk_size / 2) / 24000 * 1000

                print(f"  Chunk {chunk_num:3d}: {chunk_size:6d} bytes ({duration_ms:6.1f}ms)")

            elapsed = time.time() - start_time

            # Summary
            print(f"\n  📊 Summary:")
            print(f"     Total chunks: {len(chunks)}")
            print(f"     Total bytes: {total_bytes:,}")
            print(f"     Total duration: {(total_bytes / 2) / 24000 * 1000:.0f}ms")
            print(f"     Time to first chunk: {first_chunk_time*1000:.0f}ms")
            print(f"     Total stream time: {elapsed*1000:.0f}ms")
            print(f"     Min chunk: {min(chunk_sizes):,} bytes")
            print(f"     Max chunk: {max(chunk_sizes):,} bytes")
            print(f"     Avg chunk: {sum(chunk_sizes)/len(chunk_sizes):,.0f} bytes")

            # Save audio for verification
            output_dir = Path(__file__).parent / "output"
            output_dir.mkdir(exist_ok=True)
            output_file = output_dir / f"elevenlabs_test_{i}.wav"

            all_audio = b''.join(chunks)
            with wave.open(str(output_file), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(24000)
                wf.writeframes(all_audio)

            print(f"     Saved to: {output_file}")

        except Exception as e:
            print(f"  ❌ Error: {e}")

    print("\n" + "=" * 70)
    print("  Test Complete - Check audio files to verify full phrases")
    print("=" * 70)


async def test_websocket_streaming():
    """Test ElevenLabs WebSocket streaming (what Pipecat uses)."""

    import websockets
    import json

    api_key = os.getenv("ELEVENLABS_API_KEY")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID")

    print("\n" + "=" * 70)
    print("  ElevenLabs WebSocket Streaming Test")
    print("=" * 70)

    uri = f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input?model_id=eleven_flash_v2_5&output_format=pcm_24000"

    phrase = "Bonjour! Comment puis-je vous aider aujourd'hui?"

    chunks = []
    total_bytes = 0

    async with websockets.connect(uri) as ws:
        # Send initial config
        await ws.send(json.dumps({
            "text": " ",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            },
            "xi_api_key": api_key,
        }))

        # Send text
        await ws.send(json.dumps({
            "text": phrase,
            "flush": True
        }))

        # Send end signal
        await ws.send(json.dumps({
            "text": ""
        }))

        # Receive audio
        chunk_num = 0
        while True:
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=5.0)

                if isinstance(response, bytes):
                    chunk_num += 1
                    chunk_size = len(response)
                    total_bytes += chunk_size
                    chunks.append(response)
                    duration_ms = (chunk_size / 2) / 24000 * 1000
                    print(f"  Chunk {chunk_num:3d}: {chunk_size:6d} bytes ({duration_ms:6.1f}ms)")
                else:
                    data = json.loads(response)
                    if "audio" in data:
                        import base64
                        audio = base64.b64decode(data["audio"])
                        chunk_num += 1
                        chunk_size = len(audio)
                        total_bytes += chunk_size
                        chunks.append(audio)
                        duration_ms = (chunk_size / 2) / 24000 * 1000
                        print(f"  Chunk {chunk_num:3d}: {chunk_size:6d} bytes ({duration_ms:6.1f}ms)")

                    if data.get("isFinal"):
                        break

            except asyncio.TimeoutError:
                break

    print(f"\n  📊 WebSocket Summary:")
    print(f"     Total chunks: {len(chunks)}")
    print(f"     Total bytes: {total_bytes:,}")
    print(f"     Total duration: {(total_bytes / 2) / 24000 * 1000:.0f}ms")

    # Save
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "elevenlabs_websocket_test.wav"

    all_audio = b''.join(chunks)
    with wave.open(str(output_file), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(all_audio)

    print(f"     Saved to: {output_file}")


if __name__ == "__main__":
    print("\n🔬 ElevenLabs Direct Test - No Pipecat\n")

    asyncio.run(test_elevenlabs_streaming())
    # asyncio.run(test_websocket_streaming())
