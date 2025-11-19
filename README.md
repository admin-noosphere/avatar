# Avatar MetaHuman Pipeline 🎭

Real-time AI conversational agent for Unreal Engine MetaHuman control using **Pipecat 0.95**.

## 🌟 Features

- 🎙️ **NDI Audio/Video Input** - GStreamer-based NDI ingestion for multimodal AI
- 🗣️ **ElevenLabs TTS** - High-fidelity voice synthesis with streaming latency <250ms
- 🤖 **LLM Function Calling** - GPT-4o/Claude control of MetaHuman emotions via tools
- 🎬 **Audio2Face Integration** - Perfect lip-sync via UDP audio streaming (24kHz)
- ⚡ **ParallelPipeline** - Dual audio output (User + Avatar) with frame-perfect sync
- 🚫 **Barge-in Support** - Graceful interruption handling with MinWordsInterruptionStrategy

## 🏗️ Architecture

```
NDI Input → STT → LLM (Function Calling) → TTS (ElevenLabs)
                                              ↓
                                    ┌─────────┴──────────┐
                                    ↓                    ↓
                              User (WebRTC)      Unreal MetaHuman
                                                 (WebSocket + UDP)
```

## 📦 Installation

### Prerequisites

- Python 3.10+ (3.11 recommended)
- UV package manager
- GStreamer + NDI plugin (for video input)
- Unreal Engine with Audio2Face plugin

### Quick Start

```bash
# Clone repository
git clone https://github.com/admin-noosphere/avatar.git
cd avatar

# Install UV (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e ".[dev,ndi]"

# Copy environment template
cp .env.example .env
# Edit .env with your API keys

# Run tests
pytest

# Format and lint
black src/ tests/
ruff check src/ tests/ --fix
mypy src/
```

## 🚀 Usage

### Basic Example

```python
from avatar.pipeline.main_pipeline import create_pipeline
from avatar.config.settings import get_settings

settings = get_settings()
pipeline = create_pipeline(settings)

# Run pipeline
await pipeline.run()
```

### With Mock Unreal (Testing)

```bash
# Terminal 1: Start mock Unreal WebSocket server
python claude_dev/mock_unreal_server.py

# Terminal 2: Run pipeline with mock mode
MOCK_UNREAL=true python examples/simple_demo.py
```

## 📁 Project Structure

```
avatar/
├── src/avatar/
│   ├── processors/          # Custom Pipecat processors
│   │   ├── unreal_event_processor.py
│   │   ├── unreal_audio_streamer.py
│   │   └── ndi_input_transport.py
│   ├── pipeline/            # Pipeline assembly
│   └── config/              # Configuration management
├── tests/
│   ├── unit/                # Unit tests
│   └── integration/         # Integration tests
├── claude_dev/              # Development scripts
├── examples/                # Usage examples
└── docs/                    # Documentation
```

## 🧪 Development

### Code Quality Tools

```bash
# Format code
poetry run black src/ tests/

# Lint code
poetry run ruff check src/ tests/ --fix

# Type checking
poetry run mypy src/

# Run tests with coverage
poetry run pytest --cov

# Run all checks (pre-commit)
poetry run pre-commit run --all-files
```

### Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit -v

# Integration tests
pytest tests/integration -v

# Skip slow tests
pytest -m "not slow"

# With coverage
pytest --cov --cov-report=html
```

## 📖 Documentation

- **[CLAUDE.md](docs/CLAUDE.md)** - Developer guide for AI (Claude)
- **[audit.md](audit.md)** - Technical audit of legacy implementation
- **[API Documentation](docs/API.md)** - API reference (TODO)

## 🔧 Configuration

All configuration is managed via environment variables (`.env` file). See [`.env.example`](.env.example) for all available options.

Key settings:

```bash
# API Keys
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=...

# Unreal Integration
UNREAL_WEBSOCKET_URI=ws://localhost:8765
UNREAL_AUDIO_UDP_PORT=8080

# Audio Settings (MUST be 24000 for Audio2Face)
AUDIO_SAMPLE_RATE=24000
```

## 🐛 Troubleshooting

### Avatar not moving lips

1. Check UDP connection: `netstat -an | grep 8080`
2. Verify sample rate is 24kHz
3. Test with: `python claude_dev/test_udp_sender.py audio.wav`

### WebSocket connection failed

1. Check Unreal WebSocket server is running on port 8765
2. Test with: `python claude_dev/mock_unreal_server.py`
3. Verify `UNREAL_WEBSOCKET_URI` in `.env`

### High latency

1. Ensure ElevenLabs model is `eleven_flash_v2_5`
2. Reduce NDI video FPS: `NDI_VIDEO_FPS=1`
3. Enable interruption: `INTERRUPTION_MIN_WORDS=3`

## 📊 Performance Metrics

| Metric | Target | Measured |
|--------|--------|----------|
| STT Latency | <200ms | TBD |
| LLM Latency | <500ms | TBD |
| TTS Latency | <250ms | TBD |
| **Total (End-to-End)** | **<1000ms** | **TBD** |

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Ensure all tests pass (`pytest`)
5. Run code quality checks (`pre-commit run --all-files`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **[Pipecat](https://github.com/pipecat-ai/pipecat)** - Voice and multimodal AI framework
- **[ElevenLabs](https://elevenlabs.io)** - High-fidelity TTS
- **[Audio2Face](https://www.nvidia.com/en-us/omniverse/apps/audio2face/)** - NVIDIA facial animation
- **[NDI](https://ndi.tv)** - Network Device Interface

## 📧 Contact

- **GitHub**: [admin-noosphere/avatar](https://github.com/admin-noosphere/avatar)
- **Issues**: [Report a bug](https://github.com/admin-noosphere/avatar/issues)

---

**Status**: 🚧 In Development | **Version**: 0.1.0 | **Last Updated**: 2025-11-19
