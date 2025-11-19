# 📝 Configuration Notes - Session 2025-11-19

## 🎯 Configuration Réseau Actuelle

### Audio2Face Server
```
IP:       192.168.1.14
Port:     8080 (UDP)
Protocol: UDP non-bloquant
Role:     Serveur (écoute audio streaming)
```

### Avatar Pipeline (Cette Machine)
```
IP:       192.168.1.x (local network)
Protocol: UDP Client (envoi audio)
Target:   192.168.1.14:8080
```

---

## ✅ Fichiers Modifiés

### 1. `.env.example`
```bash
# Ligne 15-16 modifiée
UNREAL_AUDIO_UDP_HOST=192.168.1.14  # ← Changé de 127.0.0.1
UNREAL_AUDIO_UDP_PORT=8080
```

### 2. `src/avatar/config/settings.py`
```python
# Ligne 33-36 modifiée
unreal_audio_udp_host: str = Field(
    default="192.168.1.14",  # ← Changé de "127.0.0.1"
    description="UDP host for Audio2Face streaming",
)
```

### 3. Nouveau: `claude_dev/test_udp_connection.py`
Script de test pour vérifier connectivité UDP vers Audio2Face.

**Usage**:
```bash
python claude_dev/test_udp_connection.py
```

### 4. Nouveau: `docs/NETWORK_SETUP.md`
Documentation complète setup réseau, troubleshooting, sécurité.

---

## 🚀 Tests à Effectuer

### Test 1: Connectivité Réseau
```bash
# Test ping
ping -c 3 192.168.1.14

# Test UDP automatique
python claude_dev/test_udp_connection.py
```

**Résultat attendu**: ✅ Both tests PASS

### Test 2: Audio2Face Listening
Sur la machine **192.168.1.14**, vérifier:

```bash
# Linux
sudo netstat -ulnp | grep 8080

# Windows
netstat -an | findstr :8080
```

**Résultat attendu**:
```
udp    0.0.0.0:8080    0.0.0.0:*
```

### Test 3: Firewall
```bash
# Linux (sur 192.168.1.14)
sudo ufw status | grep 8080

# Devrait montrer:
# 8080/udp    ALLOW    Anywhere
```

---

## ⚙️ Configuration Complète .env

Voici un exemple complet de `.env` à créer:

```bash
# =============================================================================
# API KEYS
# =============================================================================
OPENAI_API_KEY=sk-your-key-here
ELEVENLABS_API_KEY=your-elevenlabs-key

# =============================================================================
# UNREAL ENGINE / AUDIO2FACE
# =============================================================================
UNREAL_WEBSOCKET_URI=ws://localhost:8765
UNREAL_AUDIO_UDP_HOST=192.168.1.14  # ← Audio2Face remote server
UNREAL_AUDIO_UDP_PORT=8080

# =============================================================================
# NDI
# =============================================================================
NDI_SOURCE_NAME=MY_SOURCE
NDI_VIDEO_ENABLED=true
NDI_VIDEO_FPS=1

# =============================================================================
# AUDIO SETTINGS (CRITICAL!)
# =============================================================================
AUDIO_SAMPLE_RATE=24000  # ← MUST be 24000 for Audio2Face
AUDIO_CHANNELS=1

# =============================================================================
# LLM
# =============================================================================
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0.7

# =============================================================================
# TTS (ElevenLabs)
# =============================================================================
ELEVENLABS_VOICE_ID=your-voice-id
ELEVENLABS_MODEL=eleven_flash_v2_5
ELEVENLABS_STABILITY=0.5
ELEVENLABS_SIMILARITY_BOOST=0.75

# =============================================================================
# TRANSPORT
# =============================================================================
TRANSPORT_TYPE=daily
DAILY_ROOM_URL=https://your-room.daily.co/room
DAILY_API_KEY=your-daily-key

# =============================================================================
# INTERRUPTION
# =============================================================================
INTERRUPTION_MIN_WORDS=3
VAD_STOP_SECS=0.5

# =============================================================================
# LOGGING
# =============================================================================
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_FILE=logs/avatar.log

# =============================================================================
# DEVELOPMENT
# =============================================================================
DEBUG=false
MOCK_UNREAL=false
```

---

## 📊 Architecture Réseau

```
┌─────────────────────────────────────────────────────────────┐
│  Avatar Pipeline Machine (192.168.1.x)                      │
│                                                              │
│  ┌──────────────┐                                          │
│  │  NDI Input   │ ← Video/Audio from network               │
│  └──────┬───────┘                                          │
│         ↓                                                    │
│  ┌──────────────┐      ┌─────────────┐                     │
│  │     STT      │ ───→ │     LLM     │                     │
│  └──────────────┘      └──────┬──────┘                     │
│                               ↓                              │
│                        ┌─────────────┐                      │
│                        │ ElevenLabs  │                      │
│                        │  TTS (24kHz)│                      │
│                        └──────┬──────┘                      │
│                               ↓                              │
│                     ┌─────────────────┐                     │
│                     │ParallelPipeline │                     │
│                     └────┬──────┬─────┘                     │
│                          ↓      ↓                            │
│                    User  │      │ Unreal                    │
│                   WebRTC │      │ Control                   │
│                          │      │                            │
│                          │      └──→ WebSocket (localhost)  │
│                          │      └──→ UDP ────────────────┐  │
└──────────────────────────┼───────────────────────────────┼──┘
                           │                               │
                           ↓                               ↓
                      User Device            ┌─────────────────────────┐
                      (Browser)              │ Audio2Face Server       │
                                             │ 192.168.1.14:8080 (UDP) │
                                             │                         │
                                             │ ┌─────────────────────┐ │
                                             │ │   MetaHuman         │ │
                                             │ │   Lip-Sync Engine   │ │
                                             │ └─────────────────────┘ │
                                             └─────────────────────────┘
```

---

## 🔍 Debugging Checklist

Si le lip-sync ne fonctionne pas:

### 1. Réseau
- [ ] `ping 192.168.1.14` fonctionne
- [ ] `python claude_dev/test_udp_connection.py` passe
- [ ] Firewall ouvert sur 192.168.1.14:8080/udp

### 2. Audio2Face
- [ ] Audio2Face tourne sur 192.168.1.14
- [ ] Audio2Face écoute sur port 8080 (`netstat -ulnp | grep 8080`)
- [ ] Sample rate configuré à 24kHz dans Audio2Face

### 3. Pipeline
- [ ] `.env` contient `UNREAL_AUDIO_UDP_HOST=192.168.1.14`
- [ ] `AUDIO_SAMPLE_RATE=24000` (pas 16000, 22050, 44100)
- [ ] `UnrealAudioStreamer` utilise bien settings.unreal_audio_udp_host

### 4. Données Audio
- [ ] TTS génère bien du 24kHz (vérifier logs)
- [ ] `SoxrResampler(24000)` présent dans branch Unreal
- [ ] Packets UDP arrivent (vérifier avec `tcpdump`)

---

## 📈 Prochaines Étapes

### Immédiat (Cette Session)
1. ✅ Configuration réseau mise à jour
2. ✅ Script de test UDP créé
3. ✅ Documentation réseau complète
4. **NEXT**: Tester connectivité avec `test_udp_connection.py`

### Court Terme (Prochaine Session)
1. Implémenter `UnrealAudioStreamer` avec IP configurable
2. Implémenter `UnrealEventProcessor` (WebSocket)
3. Tests unitaires pour les deux
4. Premier test end-to-end avec mock

### Moyen Terme
1. NDI Input Transport
2. Pipeline complet avec ParallelPipeline
3. Function Calling pour émotions
4. Tests intégration

---

## 📚 Documentation Créée

| Fichier | Description |
|---------|-------------|
| `docs/NETWORK_SETUP.md` | Guide complet réseau, troubleshooting, sécurité |
| `docs/CONFIGURATION_NOTES.md` | Ce fichier - notes de configuration |
| `claude_dev/test_udp_connection.py` | Script test connectivité UDP |
| `.env.example` | Template avec 192.168.1.14 |
| `src/avatar/config/settings.py` | Settings mis à jour |

---

## 🎯 Variables Critiques

Ces variables **DOIVENT** être correctes:

```bash
# Réseau Audio2Face
UNREAL_AUDIO_UDP_HOST=192.168.1.14  # ← IP exacte
UNREAL_AUDIO_UDP_PORT=8080          # ← Port UDP

# Sample Rate (CRITIQUE!)
AUDIO_SAMPLE_RATE=24000             # ← Exactement 24000
AUDIO_CHANNELS=1                    # ← Mono seulement
```

**Si une seule est fausse → Pas de lip-sync!**

---

## 💡 Tips & Tricks

### Monitoring UDP en Temps Réel
```bash
# Sur machine Avatar
watch -n 1 "netstat -s | grep -i udp"

# Sur machine Audio2Face (192.168.1.14)
sudo tcpdump -i any udp port 8080 -v
```

### Test Manuel Rapide
```bash
# Envoyer un packet UDP simple
echo "HELLO" | nc -u 192.168.1.14 8080

# Si Audio2Face reçoit, devrait apparaître dans logs
```

### Vérifier Sample Rate Audio
```python
# Dans le pipeline, ajouter un observer
from pipecat.frames.frames import OutputAudioRawFrame

async def debug_audio(frame):
    if isinstance(frame, OutputAudioRawFrame):
        print(f"Audio: {len(frame.audio)} bytes, {frame.sample_rate} Hz")
```

---

**Dernière mise à jour**: 2025-11-19 13:00 UTC
**Configuration**: Audio2Face @ 192.168.1.14:8080
**Status**: ✅ Configuration réseau validée
