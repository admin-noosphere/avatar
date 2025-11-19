# CLAUDE.md - Documentation Développeur IA

## 📋 Vue d'ensemble du Projet

**Avatar MetaHuman Pipeline** - Système conversationnel IA temps réel pour contrôler un MetaHuman dans Unreal Engine via Audio2Face, utilisant Pipecat 0.95.

### Objectif
Migrer un script PyQt5 legacy vers une architecture moderne basée sur Pipecat pour :
- Streaming audio/vidéo NDI
- Synchronisation labiale parfaite (Audio2Face)
- Contrôle émotionnel via LLM (Function Calling)
- Latence sub-seconde (<500ms)
- Support barge-in (interruption gracieuse)

---

## 🏗️ Architecture du Système

```
┌─────────────────────────────────────────────────────────────────┐
│                    INPUT LAYER (NDI)                            │
│  GStreamer → NDIInputTransport → InputImageRawFrame            │
│              (1 fps decimation)   InputAudioRawFrame           │
└─────────────────────┬───────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────────┐
│                 COGNITIVE LAYER (LLM)                           │
│  STT → ContextAggregator → OpenAI/Anthropic LLM                │
│                             (Function Calling: animate_avatar)  │
└─────────────────────┬───────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────────┐
│              SYNTHESIS LAYER (TTS)                              │
│  ElevenLabs WebSocket TTS (eleven_flash_v2_5, 24kHz)           │
└─────────────────────┬───────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────────┐
│           OUTPUT LAYER (ParallelPipeline)                       │
│  ┌──────────────────────┐  ┌──────────────────────────────────┐│
│  │ Branch A: User       │  │ Branch B: Unreal MetaHuman       ││
│  │ WebRTC Transport     │  │ UnrealEventProcessor (WebSocket) ││
│  │ (User hears voice)   │  │ UnrealAudioStreamer (UDP 8080)   ││
│  └──────────────────────┘  └──────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## 📂 Structure du Projet

```
avatar/
├── src/avatar/
│   ├── processors/
│   │   ├── __init__.py
│   │   ├── unreal_event_processor.py    # WebSocket control (start/stop speaking)
│   │   ├── unreal_audio_streamer.py     # UDP audio streaming (24kHz → A2F)
│   │   └── ndi_input_transport.py       # GStreamer NDI → Pipecat frames
│   ├── pipeline/
│   │   ├── __init__.py
│   │   └── main_pipeline.py             # ParallelPipeline assembly
│   └── config/
│       ├── __init__.py
│       └── settings.py                  # Configuration centralisée
├── tests/
│   ├── unit/
│   │   ├── test_unreal_event_processor.py
│   │   ├── test_unreal_audio_streamer.py
│   │   └── test_ndi_input_transport.py
│   └── integration/
│       ├── test_pipeline.py
│       └── test_mock_unreal.py
├── claude_dev/                          # Scripts de développement pour Claude
│   ├── test_websocket.py
│   ├── test_udp_sender.py
│   └── mock_unreal_server.py
├── examples/
│   └── simple_demo.py
├── docs/
│   ├── CLAUDE.md                        # Ce fichier
│   ├── ARCHITECTURE.md
│   └── API.md
├── pyproject.toml                       # UV + Poetry compatible
├── .env.example
├── .gitignore
└── README.md
```

---

## 🔑 Composants Clés

### 1. UnrealEventProcessor
**Rôle:** Écoute `TTSStartedFrame` / `TTSStoppedFrame` et envoie WebSocket events à Unreal.

**Frames gérés:**
- `TTSStartedFrame` → `{"type": "start_speaking", "category": "SPEAKING_NEUTRAL"}`
- `TTSStoppedFrame` → `{"type": "stop_speaking"}`
- `StartInterruptionFrame` → `{"type": "stop_speaking"}` (barge-in)

**WebSocket URI:** `ws://localhost:8765`

### 2. UnrealAudioStreamer
**Rôle:** Envoie audio brut via UDP vers Audio2Face.

**Specs:**
- Sample rate: **24kHz** (requis par Audio2Face)
- Format: PCM raw bytes
- Transport: UDP non-blocking (`socket.SOCK_DGRAM`)
- Target: `127.0.0.1:8080`

**Frames gérés:**
- `OutputAudioRawFrame` → UDP packet

### 3. NDIInputTransport
**Rôle:** Ingestion NDI via GStreamer → Pipecat frames.

**GStreamer Pipeline:**
```bash
ndisrc ndi-name="MY_SOURCE" ! \
  videoconvert ! video/x-raw,format=RGB ! \
  videorate ! video/x-raw,framerate=1/1 ! \
  appsink name=sink
```

**Frame Decimation:** 1 fps (évite surcharge CPU/GIL)

### 4. ParallelPipeline
**Rôle:** Fork audio TTS vers 2 destinations simultanées.

**Implémentation:**
```python
ParallelPipeline(
    [transport.output()],           # Branch A: User WebRTC
    [
        UnrealEventProcessor(),     # Branch B: Unreal control
        SoxrResampler(24000),       # Resample to 24kHz
        UnrealAudioStreamer()       # UDP to Audio2Face
    ]
)
```

---

## 🧪 Tests et Validation

### Structure de Tests

#### Unit Tests (`tests/unit/`)
- **test_unreal_event_processor.py:**
  - Vérifie emission WebSocket sur `TTSStartedFrame`
  - Vérifie reconnexion automatique
  - Mock `websockets.connect()`

- **test_unreal_audio_streamer.py:**
  - Vérifie envoi UDP sur `OutputAudioRawFrame`
  - Vérifie gestion `BlockingIOError`
  - Mock `socket.sendto()`

- **test_ndi_input_transport.py:**
  - Vérifie parsing GStreamer buffer
  - Vérifie création `InputImageRawFrame`
  - Mock GStreamer pipeline

#### Integration Tests (`tests/integration/`)
- **test_pipeline.py:**
  - Test pipeline complet end-to-end
  - Vérifie synchronisation branches parallèles

- **test_mock_unreal.py:**
  - Serveur WebSocket mock pour simuler Unreal
  - Vérifie réception des commands

### Scripts de Développement (`claude_dev/`)

#### mock_unreal_server.py
```python
# Serveur WebSocket qui simule Unreal Engine
# Usage: python claude_dev/mock_unreal_server.py
# Écoute sur ws://localhost:8765
# Affiche tous les messages reçus
```

#### test_udp_sender.py
```python
# Envoie un fichier WAV via UDP vers Audio2Face
# Usage: python claude_dev/test_udp_sender.py audio.wav
# Permet de tester l'intégration Audio2Face indépendamment
```

---

## ⚙️ Configuration

### Variables d'Environnement (.env)

```bash
# API Keys
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=...

# Unreal Integration
UNREAL_WEBSOCKET_URI=ws://localhost:8765
UNREAL_AUDIO_UDP_HOST=127.0.0.1
UNREAL_AUDIO_UDP_PORT=8080

# NDI
NDI_SOURCE_NAME=MY_SOURCE

# Audio Settings
AUDIO_SAMPLE_RATE=24000
AUDIO_CHANNELS=1

# LLM Settings
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0.7

# TTS Settings
ELEVENLABS_VOICE_ID=...
ELEVENLABS_MODEL=eleven_flash_v2_5
```

---

## 🛠️ Outils de Qualité de Code

### 1. Black - Formatage
```bash
poetry run black src/ tests/
```
Config: 100 caractères, Python 3.10+

### 2. Ruff - Linting
```bash
poetry run ruff check src/ tests/ --fix
```
Règles: E, W, F, I, C, B, UP

### 3. MyPy - Type Checking
```bash
poetry run mypy src/
```
Strict mode activé

### 4. Pytest - Tests avec Couverture
```bash
poetry run pytest --cov
poetry run pytest tests/unit -v
poetry run pytest -m "not slow"
```

### 5. Pre-commit Hooks
```bash
poetry run pre-commit run --all-files
```

---

## 🚀 Workflow de Développement

### Ajout d'une Nouvelle Feature

1. **Créer une branche:**
   ```bash
   git checkout -b feature/nouvelle-feature
   ```

2. **Développer avec tests:**
   ```bash
   # Écrire le code dans src/
   # Écrire les tests dans tests/unit/
   ```

3. **Valider la qualité:**
   ```bash
   poetry run black src/ tests/
   poetry run ruff check src/ tests/ --fix
   poetry run mypy src/
   poetry run pytest
   ```

4. **Commit et push:**
   ```bash
   git add .
   git commit -m "feat: description"
   git push origin feature/nouvelle-feature
   ```

### Résolution de Bugs

1. **Écrire un test qui reproduit le bug** (test_bug.py)
2. **Corriger le code**
3. **Vérifier que le test passe**
4. **Valider avec pre-commit**

---

## 📊 Métriques de Performance

### Objectifs de Latence

| Étape | Cible | Mesure |
|-------|-------|--------|
| STT (user → text) | <200ms | `time(UserStoppedSpeaking) - time(UserStartedSpeaking)` |
| LLM (text → response) | <500ms | `time(LLMResponse) - time(STTComplete)` |
| TTS (text → audio) | <250ms | `time(FirstAudioChunk) - time(TTSStart)` |
| **Total (user → avatar)** | **<1000ms** | End-to-end measurement |

### Monitoring

```python
# Dans le pipeline, utiliser des Observers
from pipecat.observers.base_observer import BaseObserver

class LatencyObserver(BaseObserver):
    async def on_push_frame(self, src, dst, frame, direction, timestamp):
        # Log timestamps pour analyse
        logger.debug(f"{timestamp}: {type(frame).__name__}")
```

---

## 🔐 Sécurité

### API Keys
- **Jamais** commit `.env` dans Git
- Utiliser `.env.example` comme template
- Rotation régulière des clés

### WebSocket
- En production, utiliser `wss://` (TLS)
- Authentification par token si exposé

### UDP
- Audio2Face local uniquement (pas d'exposition publique)
- Firewall: bloquer port 8080 en ingress

---

## 🐛 Debugging

### Problèmes Courants

#### 1. Avatar ne bouge pas les lèvres
**Causes possibles:**
- Audio UDP non reçu → Vérifier `netstat -an | grep 8080`
- Sample rate incorrect → Doit être 24kHz
- WebSocket non connecté → Vérifier logs `UnrealEventProcessor`

**Debug:**
```bash
# Tester UDP directement
python claude_dev/test_udp_sender.py audio_24khz.wav

# Tester WebSocket
python claude_dev/mock_unreal_server.py
# Dans un autre terminal: tester avec wscat
```

#### 2. Audio désynchronisé
**Cause:** Branches parallèles pas au même sample rate

**Fix:** Vérifier `SoxrResampler(24000)` dans Branch B

#### 3. Latence élevée
**Causes:**
- NDI à 30fps au lieu de 1fps → CPU/GIL saturé
- ElevenLabs HTTP au lieu de WebSocket → Utiliser `ElevenLabsTTSService`
- Pas de `MinWordsInterruptionStrategy` → Faux positifs VAD

---

## 📚 Ressources

### Documentation Pipecat
- [Pipecat Docs](https://docs.pipecat.ai)
- [API Reference](https://reference-server.pipecat.ai)
- [GitHub](https://github.com/pipecat-ai/pipecat)

### Documentation Technique
- [Audio2Face](https://docs.omniverse.nvidia.com/audio2face)
- [NDI SDK](https://ndi.tv/sdk/)
- [GStreamer NDI Plugin](https://github.com/teltek/gst-plugin-ndi)

### Audit Original
Voir `/home/gieidi-prime/Agents/Avatar/audit.md` pour analyse détaillée du legacy code.

---

## 🎯 Prochaines Étapes (Roadmap)

- [ ] **Phase 1: Core Processors** (Semaine 1)
  - UnrealEventProcessor
  - UnrealAudioStreamer
  - Tests unitaires

- [ ] **Phase 2: NDI Integration** (Semaine 2)
  - NDIInputTransport
  - GStreamer pipeline
  - Tests intégration

- [ ] **Phase 3: Pipeline Assembly** (Semaine 3)
  - ParallelPipeline
  - ElevenLabs TTS
  - LLM Function Calling

- [ ] **Phase 4: Polish** (Semaine 4)
  - Monitoring
  - Documentation
  - CI/CD

---

**Dernière mise à jour:** 2025-11-19
**Mainteneur:** Claude (Anthropic)
**Statut:** 🚧 En Développement
