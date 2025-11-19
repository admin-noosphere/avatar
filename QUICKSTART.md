# 🚀 Avatar Project - Quick Start Guide

## 📦 Installation Rapide

### Prérequis
- Python 3.10+ (3.11 recommandé)
- UV ou Poetry
- Git

### Étape 1: Cloner (si pas déjà fait)
```bash
cd /home/gieidi-prime/Agents/Avatar
# Le repo est déjà initialisé localement
```

### Étape 2: Installation avec Poetry
```bash
# Installer les dépendances
poetry install --all-extras

# Activer l'environnement
poetry shell
```

### Étape 3: Configuration
```bash
# Copier le template
cp .env.example .env

# Éditer avec vos clés API
nano .env  # ou vim, code, etc.
```

**Minimum requis dans .env**:
```bash
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
```

### Étape 4: Vérification
```bash
# Formater le code
poetry run black src/ tests/

# Linter
poetry run ruff check src/ tests/ --fix

# Type checking
poetry run mypy src/

# Tests
poetry run pytest
```

---

## 🎯 Prochaines Étapes (Par Ordre de Priorité)

### 1️⃣ Créer Mock Unreal Server (1h)
**Pourquoi**: Permet de tester sans Unreal Engine

**Fichier**: `claude_dev/mock_unreal_server.py`

```python
"""Mock Unreal WebSocket server for testing."""
import asyncio
import json

import websockets
from loguru import logger


async def handle_client(websocket: websockets.WebSocketServerProtocol) -> None:
    """Handle WebSocket client connection."""
    logger.info(f"Client connected: {websocket.remote_address}")
    try:
        async for message in websocket:
            data = json.loads(message)
            logger.info(f"Received: {data}")

            # Mock responses
            if data.get("type") == "start_speaking":
                logger.success(f"Avatar START speaking: {data.get('category')}")
            elif data.get("type") == "stop_speaking":
                logger.success("Avatar STOP speaking")

    except websockets.exceptions.ConnectionClosed:
        logger.warning("Client disconnected")


async def main() -> None:
    """Start mock WebSocket server."""
    logger.info("Starting mock Unreal WebSocket server on ws://localhost:8765")
    async with websockets.serve(handle_client, "localhost", 8765):
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())
```

**Test**:
```bash
# Terminal 1
poetry run python claude_dev/mock_unreal_server.py

# Terminal 2 (autre terminal)
pip install websockets
python -c "
import asyncio
import websockets
import json

async def test():
    async with websockets.connect('ws://localhost:8765') as ws:
        await ws.send(json.dumps({'type': 'start_speaking', 'category': 'SPEAKING_HAPPY'}))
        await asyncio.sleep(0.1)

asyncio.run(test())
"
```

---

### 2️⃣ Implémenter UnrealEventProcessor (2-3h)
**Fichier**: `src/avatar/processors/unreal_event_processor.py`

**Référence**: Voir `docs/CLAUDE.md` section 5.1 (lignes 196-247)

**Structure**:
```python
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import (
    Frame,
    TTSStartedFrame,
    TTSStoppedFrame,
    StartInterruptionFrame,
)
import websockets
import asyncio
import json

class UnrealEventProcessor(FrameProcessor):
    def __init__(self, uri: str = "ws://localhost:8765") -> None:
        super().__init__()
        self.uri = uri
        self.websocket = None
        # TODO: Implémenter _maintain_connection()

    async def process_frame(self, frame: Frame, direction) -> None:
        # TODO: Gérer TTSStartedFrame, TTSStoppedFrame, StartInterruptionFrame
        pass
```

**Tests**: `tests/unit/test_unreal_event_processor.py`

---

### 3️⃣ Implémenter UnrealAudioStreamer (2-3h)
**Fichier**: `src/avatar/processors/unreal_audio_streamer.py`

**Référence**: Voir `docs/CLAUDE.md` section 5.2 (lignes 250-282)

**Structure**:
```python
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import Frame, OutputAudioRawFrame
import socket

class UnrealAudioStreamer(FrameProcessor):
    def __init__(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        super().__init__()
        self.target = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

    async def process_frame(self, frame: Frame, direction) -> None:
        # TODO: Gérer OutputAudioRawFrame et envoyer UDP
        pass
```

**Tests**: `tests/unit/test_unreal_audio_streamer.py`

---

### 4️⃣ Tests Unitaires (2h)
Créer tests pour chaque processor avec mocks.

**Exemple** (`tests/unit/test_unreal_event_processor.py`):
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from avatar.processors.unreal_event_processor import UnrealEventProcessor
from pipecat.frames.frames import TTSStartedFrame, TTSStoppedFrame

@pytest.mark.asyncio
async def test_tts_started_sends_websocket():
    """Test that TTSStartedFrame triggers WebSocket message."""
    with patch('websockets.connect') as mock_connect:
        mock_ws = AsyncMock()
        mock_connect.return_value.__aenter__.return_value = mock_ws

        processor = UnrealEventProcessor()
        frame = TTSStartedFrame()

        await processor.process_frame(frame, None)

        # Vérifier que WebSocket a été appelé
        mock_ws.send.assert_called_once()
        # TODO: Vérifier le JSON envoyé
```

---

## 📚 Fichiers de Référence

### Documentation
| Fichier | Description | Taille |
|---------|-------------|--------|
| `docs/CLAUDE.md` | Guide développeur complet | 15KB |
| `docs/PROGRESS.md` | Tracker 29 tâches | 8KB |
| `docs/SESSION_SUMMARY.md` | Résumé session | 12KB |
| `README.md` | Documentation utilisateur | 6KB |
| `audit.md` | Analyse legacy code | 30KB |

### Code Déjà Écrit
- ✅ `src/avatar/config/settings.py` - Pydantic Settings complet
- ✅ `pyproject.toml` - Configuration complète (Black, Ruff, MyPy, Pytest)
- ✅ `.env.example` - 50+ variables documentées

### À Implémenter
- ⏳ `src/avatar/processors/unreal_event_processor.py`
- ⏳ `src/avatar/processors/unreal_audio_streamer.py`
- ⏳ `src/avatar/processors/ndi_input_transport.py`
- ⏳ `src/avatar/pipeline/main_pipeline.py`

---

## 🛠️ Commandes Utiles

### Développement
```bash
# Formater tout le code
poetry run black src/ tests/

# Linter avec auto-fix
poetry run ruff check src/ tests/ --fix

# Type checking
poetry run mypy src/

# Tests avec coverage
poetry run pytest --cov

# Tests unitaires seulement
poetry run pytest tests/unit -v

# Tout d'un coup (pre-commit)
poetry run pre-commit run --all-files
```

### Git
```bash
# Premier commit
git add .
git commit -m "feat: initial project setup with Pipecat 0.95

- Add project structure
- Configure tools (Black, Ruff, MyPy, Pytest)
- Add comprehensive documentation
- Setup Pydantic Settings"

git branch -M main
git push -u origin main
```

### Debugging
```bash
# Tester WebSocket
python claude_dev/mock_unreal_server.py

# Tester settings
python -c "from avatar.config import get_settings; print(get_settings())"

# Vérifier imports
python -c "import pipecat; print(pipecat.__version__)"
```

---

## 🎓 Ressources Externes

### Documentation Pipecat
- [Docs officiels](https://docs.pipecat.ai)
- [API Reference](https://reference-server.pipecat.ai)
- [GitHub](https://github.com/pipecat-ai/pipecat)
- [Examples](https://github.com/pipecat-ai/pipecat/tree/main/examples)

### Documentation Technique
- [Audio2Face](https://docs.omniverse.nvidia.com/audio2face)
- [NDI SDK](https://ndi.tv/sdk/)
- [GStreamer NDI Plugin](https://github.com/teltek/gst-plugin-ndi)
- [WebSockets Python](https://websockets.readthedocs.io/)

---

## ❓ FAQ

### Q: UV ou Poetry?
**R**: Le projet supporte les deux via `pyproject.toml` standard. Utilisez Poetry si déjà installé.

### Q: Comment tester sans Unreal?
**R**: Utilisez `MOCK_UNREAL=true` dans `.env` et lancez `claude_dev/mock_unreal_server.py`

### Q: Pourquoi 24kHz pour l'audio?
**R**: Audio2Face requiert spécifiquement 24kHz. Autres sample rates = pas de lip-sync.

### Q: Comment débugger le pipeline?
**R**: Activez `LOG_LEVEL=DEBUG` dans `.env` et utilisez loguru pour logs structurés.

### Q: NDI ne fonctionne pas?
**R**: Vérifiez `gst-inspect-1.0 ndisrc`. Si absent, installer `gst-plugin-ndi`.

---

## 📊 Progression

**Phase actuelle**: Core Processors (0/6)
**Complétion globale**: 21% (6/29 tâches)

**Prochaine session (11h estimé)**:
1. Mock Unreal Server (1h)
2. UnrealEventProcessor + tests (4h)
3. UnrealAudioStreamer + tests (4h)
4. Premier test end-to-end (2h)

---

## 🎯 Objectif Final

Pipeline complet fonctionnel:
```
NDI Video/Audio → Deepgram STT → GPT-4o → ElevenLabs TTS
                                              ↓
                                    ParallelPipeline
                                              ↓
                                  User ←──────┴──────→ Unreal MetaHuman
                                (WebRTC)            (WebSocket + UDP)
```

**Critères de succès**:
- ✅ Latence end-to-end <1 seconde
- ✅ Lip-sync parfait (Audio2Face)
- ✅ Interruption gracieuse (barge-in)
- ✅ LLM contrôle émotions automatiquement
- ✅ Tests coverage >80%

---

**Bon courage! 🚀**

Pour toute question, consultez `docs/CLAUDE.md` qui contient toutes les réponses.
