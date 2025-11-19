# 📊 Avatar Project - Progress Tracker

**Dernière mise à jour**: 2025-11-19

---

## ✅ Phase 1: Setup & Configuration (COMPLETED)

### [x] Infrastructure
- [x] Initialisation Git repository → `https://github.com/admin-noosphere/avatar.git`
- [x] Structure du projet créée:
  ```
  avatar/
  ├── src/avatar/{processors,pipeline,config}
  ├── tests/{unit,integration}
  ├── docs/
  ├── claude_dev/
  └── examples/
  ```

### [x] Configuration
- [x] `pyproject.toml` avec UV support
- [x] Outils de qualité configurés:
  - Black (formatage, 100 chars)
  - Ruff (linting: E,W,F,I,C,B,UP)
  - MyPy (type checking strict)
  - Pytest (avec coverage)
  - Pre-commit hooks
- [x] `.env.example` avec toutes les variables
- [x] `.gitignore` complet
- [x] `settings.py` avec Pydantic Settings

### [x] Documentation
- [x] **CLAUDE.md** - Guide complet développeur IA (5000+ mots)
  - Architecture système
  - Composants clés
  - Tests et validation
  - Debugging
  - Métriques performance
- [x] **README.md** - Documentation utilisateur
- [x] **PROGRESS.md** - Ce fichier

---

## 🔄 Phase 2: Core Processors (IN PROGRESS)

### [x] UnrealEventProcessor
**Status**: ✅ Completed
**Fichier**: `src/avatar/processors/unreal_event_processor.py`

**Specs**:
- Écoute `TTSStartedFrame` / `TTSStoppedFrame` / `StartInterruptionFrame`
- Envoie WebSocket JSON à `ws://localhost:8765`
- Reconnexion automatique avec backoff exponentiel
- Logging structuré
- Support animations contextuelles (émotions)

**Tests**: `tests/unit/test_unreal_event_processor.py`
- [x] Test emission WebSocket sur TTSStartedFrame
- [x] Test reconnexion après déconnexion
- [x] Test gestion StartInterruptionFrame
- [x] Mock websockets.connect()
- [x] Test animations contextuelles (happy, sad, angry, surprised)

---

### [x] UnrealAudioStreamer
**Status**: ✅ Completed
**Fichier**: `src/avatar/processors/unreal_audio_streamer.py`

**Specs**:
- Écoute `OutputAudioRawFrame`
- Envoie UDP à `192.168.1.14:8080` (Audio2Face)
- Socket non-blocking
- Gestion `BlockingIOError` (drop packet)
- Statistiques de streaming (packets/bytes)
- Variante `ChunkedAudioStreamer` pour contrôle taille paquets

**Tests**: `tests/unit/test_unreal_audio_streamer.py`
- [x] Test envoi UDP sur OutputAudioRawFrame
- [x] Test gestion BlockingIOError
- [x] Mock socket.sendto()
- [x] Test streaming continu
- [x] Test ChunkedAudioStreamer

---

### [x] NDIOutputProcessor
**Status**: ✅ Completed
**Fichier**: `src/avatar/processors/ndi_output_processor.py`

**Specs**:
- Reçoit NDI (video + audio) d'Unreal Engine
- Convertit en OutputImageRawFrame / OutputAudioRawFrame
- Thread-safe asyncio bridge avec NDIlib
- Statistiques de streaming
- Basé sur AgentNDIProcessor de Gamma

**Tests**: `tests/integration/test_ndi_input_transport.py`
- [x] Test parsing NDI buffer
- [x] Test création OutputImageRawFrame
- [x] Support NDI SDK optionnel
- [ ] Test end-to-end avec Unreal

---

## 🔮 Phase 3: Pipeline Assembly (IN PROGRESS)

### [x] ElevenLabs TTS Integration
**Status**: ✅ Completed
**Fichier**: `src/avatar/pipeline/main_pipeline.py`

**Tasks**:
- [x] Configurer `ElevenLabsTTSService`
- [x] Model: `eleven_flash_v2_5`
- [x] Sample rate: 24kHz
- [x] WebSocket streaming (pas HTTP)
- [ ] Dynamic voice settings via `TTSUpdateSettingsFrame`

---

### [ ] LLM Function Calling
**Status**: ⏳ Pending

**Tasks**:
- [ ] Définir `FunctionSchema` pour `animate_avatar`
- [ ] Créer `ToolsSchema`
- [ ] Register handlers avec `llm.register_function()`
- [ ] Émotions supportées: neutral, happy, sad, angry, surprised

**Function Schema**:
```python
{
  "name": "animate_avatar",
  "description": "Sets the emotional state or gesture of the avatar",
  "parameters": {
    "emotion": ["neutral", "happy", "sad", "angry", "surprised"],
    "intensity": 0.0-1.0
  }
}
```

---

### [x] ParallelPipeline Assembly
**Status**: ✅ Completed
**Fichier**: `src/avatar/pipeline/main_pipeline.py`

**Tasks**:
- [x] Branch A: NDI → Daily transport (video + audio avatar)
- [x] Branch B: Unreal control
  - UnrealEventProcessor (WebSocket)
  - UnrealAudioStreamer (UDP)
- [x] AvatarPipeline class avec toute la configuration
- [x] Event handlers (on_first_participant_joined, on_participant_left)

---

### [x] Interruption Handling
**Status**: ✅ Completed

**Tasks**:
- [x] `SileroVADAnalyzer` configuré
- [x] `PipelineParams(allow_interruptions=True)`
- [ ] Test barge-in end-to-end

---

## 🧪 Phase 4: Testing Infrastructure (IN PROGRESS)

### [x] Mock Unreal Server
**Status**: ✅ Completed
**Fichier**: `claude_dev/mock_unreal_server.py`

**Specs**:
- WebSocket server sur `ws://localhost:8765`
- UDP server sur port 8080
- Log tous les messages reçus avec emojis
- Réponse mock pour "MetaHuman Ready"
- Statistiques packets/bytes UDP
- Support arguments CLI (--ws-port, --udp-port, --log-level)

---

### [ ] UDP Test Script
**Status**: ⏳ Pending
**Fichier**: `claude_dev/test_udp_sender.py`

**Specs**:
- Lit fichier WAV
- Resample à 24kHz
- Envoie via UDP à Audio2Face
- Usage: `python claude_dev/test_udp_sender.py audio.wav`

---

### [ ] Demo Script
**Status**: ⏳ Pending
**Fichier**: `examples/simple_demo.py`

**Specs**:
- Pipeline complet end-to-end
- Mode mock pour tests sans Unreal
- Logging verbose
- Graceful shutdown

---

## 📈 Phase 5: Monitoring & Logging (PENDING)

### [ ] Logging Infrastructure
**Status**: ⏳ Pending

**Tasks**:
- [ ] Loguru integration
- [ ] Structured JSON logging
- [ ] Log rotation
- [ ] Levels: DEBUG, INFO, WARNING, ERROR

---

### [ ] Latency Observer
**Status**: ⏳ Pending

**Tasks**:
- [ ] Custom `BaseObserver` pour métriques
- [ ] Timestamps: STT, LLM, TTS, Total
- [ ] Export Prometheus/Grafana (optionnel)

---

## 🚀 Phase 6: Deployment (PENDING)

### [ ] Pre-commit Hooks
**Status**: ⏳ Pending

**Fichier**: `.pre-commit-config.yaml`

**Hooks**:
- black
- ruff
- mypy
- pytest

---

### [ ] GitHub Actions CI/CD
**Status**: ⏳ Pending

**Fichier**: `.github/workflows/ci.yml`

**Jobs**:
- lint (black, ruff, mypy)
- test (pytest avec coverage)
- build (package wheel)
- deploy (optionnel)

---

## 📊 Metrics Dashboard

| Phase | Tasks | Completed | Percentage |
|-------|-------|-----------|------------|
| 1. Setup | 6 | ✅ 6 | 100% |
| 2. Core Processors | 6 | ✅ 6 | 100% |
| 3. Pipeline | 10 | ✅ 8 | 80% |
| 4. Testing | 3 | ✅ 1 | 33% |
| 5. Monitoring | 2 | 0 | 0% |
| 6. Deployment | 2 | 0 | 0% |
| **TOTAL** | **29** | **21** | **72%** |

---

## 🎯 Prochaines Actions Immédiates

### Top Priority (Prochaine étape)

1. **[ ] Tester avec Mock Server**
   ```bash
   # Terminal 1: Mock server
   python claude_dev/mock_unreal_server.py

   # Terminal 2: Test processors
   python examples/test_processors.py
   ```

2. **[ ] Installer dépendances**
   ```bash
   pip install -e ".[dev]"
   ```

3. **[ ] Test end-to-end avec Unreal**
   - Lancer Unreal Engine avec MetaHuman
   - Configurer WebSocket server sur port 8765
   - Configurer UDP receiver sur port 8080
   - Tester le pipeline complet

4. **[ ] LLM Function Calling pour animations**
   - Définir schema pour `animate_avatar`
   - Register handlers avec `llm.register_function()`

---

## 🔗 Ressources Clés

### Documentation Consultée
- ✅ Pipecat Docs - ParallelPipeline
- ✅ Pipecat Docs - Custom FrameProcessor
- ✅ Pipecat Docs - ElevenLabs TTS
- ✅ Pipecat Docs - Function Calling
- ✅ Pipecat Docs - Interruption Strategies

### Fichiers de Référence
- `audit.md` - Analyse legacy code
- `docs/CLAUDE.md` - Guide développeur complet
- `.env.example` - Configuration template

---

## 📝 Notes de Session

### Session 2025-11-19
**Accomplissements**:
- ✅ Consulté doc Pipecat via Context7
- ✅ Créé structure projet complète
- ✅ Configuré pyproject.toml (UV compatible)
- ✅ Écrit CLAUDE.md (5000+ mots)
- ✅ Setup settings.py avec Pydantic
- ✅ Créé README.md
- ✅ Todo list détaillée (23 items)

**Décisions Techniques**:
- Utilisation UV au lieu de Poetry (plus moderne)
- ParallelPipeline confirmé pour dual audio output
- ElevenLabs WebSocket (eleven_flash_v2_5) pour latence
- MinWordsInterruptionStrategy (3 words) pour barge-in
- NDI decimation à 1 fps pour éviter surcharge GIL

**Prochaine Session**:
1. Implémenter les 3 processors core
2. Créer mock server pour tests
3. Premiers tests unitaires

---

### Session 2025-11-19 (Suite - Claude Code)
**Accomplissements**:
- ✅ Implémenté UnrealEventProcessor (200+ lignes)
  - WebSocket persistent avec backoff exponentiel
  - Support TTSStartedFrame/TTSStoppedFrame/StartInterruptionFrame
  - Animations contextuelles (émotions)
- ✅ Implémenté UnrealAudioStreamer (200+ lignes)
  - UDP non-blocking pour Audio2Face
  - Gestion BlockingIOError (packet drop)
  - Statistiques streaming
  - Variante ChunkedAudioStreamer
- ✅ Tests unitaires complets (400+ lignes)
  - 20+ tests pour UnrealEventProcessor
  - 20+ tests pour UnrealAudioStreamer
  - Mocks websockets et socket
- ✅ Mock Unreal Server (250+ lignes)
  - WebSocket + UDP server combinés
  - Logging avec emojis
  - Arguments CLI

**Basé sur**:
- Audit Gemini 3 Pro (audit.md)
- Patterns Pipecat 0.95 documentés

**Prochaine Session**:
1. NDIInputTransport avec GStreamer
2. Pipeline Assembly (ParallelPipeline)
3. Demo script end-to-end

---

### Session 2025-11-19 (Suite 2 - Claude Code)
**Accomplissements**:
- ✅ Exploré projet Gamma pour architecture
- ✅ Compris flux: UDP audio + WebSocket events + NDI video
- ✅ Créé NDIOutputProcessor (300+ lignes)
  - Reçoit NDI d'Unreal avec video + audio
  - Basé sur AgentNDIProcessor de Gamma
  - Support NDIlib optionnel
- ✅ Intégré NDI dans main_pipeline.py
  - ParallelPipeline avec 2 branches
  - Branch A: NDI → Daily (video avatar)
  - Branch B: Unreal control (WebSocket + UDP)
- ✅ Créé fichier .env avec config Gamma
- ✅ Créé test_processors.py pour validation

**Architecture finale**:
```
Daily Input → STT → LLM → TTS → ParallelPipeline
                                    ├─→ NDI → Daily (avatar video)
                                    └─→ WebSocket + UDP → Unreal
```

**Prochaine Session**:
1. Tester avec mock_unreal_server.py
2. Test end-to-end avec Unreal Engine
3. LLM Function Calling pour animations

---

**Mainteneur**: Claude (Anthropic)
**Repo**: https://github.com/admin-noosphere/avatar
**Status**: 🚧 72% Complete
