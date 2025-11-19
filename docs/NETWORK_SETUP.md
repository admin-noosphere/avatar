# 🌐 Network Setup - Audio2Face Remote Configuration

## Configuration Actuelle

### Audio2Face Server
- **IP**: `192.168.1.14`
- **Port UDP**: `8080`
- **Protocole**: UDP (non-bloquant, sans ACK)

### Avatar Pipeline (This Machine)
- **IP**: Variable (réseau local 192.168.1.x)
- **Rôle**: Client UDP (envoi audio streaming)

---

## ✅ Tests de Connectivité

### 1. Test Automatique (Recommandé)
```bash
python claude_dev/test_udp_connection.py
```

**Ce script teste**:
- ✅ Ping ICMP vers 192.168.1.14
- ✅ Envoi UDP sur port 8080
- ✅ Simulation stream audio (10 packets)

### 2. Test Manuel

#### Ping Test
```bash
ping -c 3 192.168.1.14
```

**Résultat attendu**:
```
64 bytes from 192.168.1.14: icmp_seq=1 ttl=64 time=0.5 ms
```

#### UDP Test avec netcat
```bash
# Envoyer un message UDP
echo "test" | nc -u 192.168.1.14 8080

# Ou avec Python
python3 -c "
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(b'TEST', ('192.168.1.14', 8080))
print('Packet sent!')
"
```

---

## 🔧 Configuration Réseau

### Sur la Machine Audio2Face (192.168.1.14)

#### 1. Vérifier Audio2Face écoute sur port 8080
```bash
# Linux
sudo netstat -ulnp | grep 8080
# Ou
sudo lsof -i UDP:8080

# Windows
netstat -an | findstr :8080
```

**Résultat attendu**:
```
udp    0.0.0.0:8080    0.0.0.0:*    LISTEN    <PID>/Audio2Face
```

#### 2. Ouvrir le Firewall (si nécessaire)

**Linux (Ubuntu/Debian)**:
```bash
# UFW
sudo ufw allow 8080/udp
sudo ufw status

# iptables
sudo iptables -A INPUT -p udp --dport 8080 -j ACCEPT
sudo iptables-save
```

**Windows**:
```powershell
# PowerShell (Admin)
New-NetFirewallRule -DisplayName "Audio2Face UDP" -Direction Inbound -Protocol UDP -LocalPort 8080 -Action Allow
```

#### 3. Vérifier Configuration Audio2Face

Dans Audio2Face:
- Ouvrir **Settings** → **Network**
- Vérifier **UDP Port**: `8080`
- Vérifier **Bind Address**: `0.0.0.0` (écoute toutes interfaces)

---

## 🚨 Troubleshooting

### Problème: "Host unreachable"

**Causes possibles**:
1. IP incorrecte
2. Machines sur réseaux différents
3. Câble/WiFi déconnecté

**Solutions**:
```bash
# Vérifier IP de la machine Audio2Face
# Sur 192.168.1.14:
ip addr show  # Linux
ipconfig      # Windows

# Vérifier route réseau
# Sur machine Avatar:
ip route get 192.168.1.14  # Linux
tracert 192.168.1.14       # Windows
```

---

### Problème: "Connection timed out"

**Causes possibles**:
1. Firewall bloque UDP
2. Audio2Face n'écoute pas sur 8080

**Solutions**:
```bash
# Désactiver temporairement firewall (TEST ONLY!)
sudo ufw disable  # Linux
# Ou
netsh advfirewall set allprofiles state off  # Windows (Admin)

# Si ça marche, rajouter règle spécifique
sudo ufw allow 8080/udp
```

---

### Problème: Packets envoyés mais pas de lip-sync

**Causes possibles**:
1. Sample rate incorrect (doit être 24kHz)
2. Format audio incorrect
3. Audio2Face reçoit mais ne traite pas

**Solutions**:
```bash
# Vérifier logs Audio2Face
# Chercher: "Received audio data" ou erreurs

# Tester avec fichier WAV connu
python claude_dev/test_udp_sender.py test_audio_24khz.wav
```

---

## 📊 Performance Réseau

### Latence Réseau
```bash
# Mesurer latency
ping -c 100 192.168.1.14 | tail -1

# Résultat idéal:
# rtt min/avg/max = 0.5/1.2/3.0 ms
```

**Recommandations**:
- **<5ms**: Excellent (réseau Gigabit local)
- **5-20ms**: Bon (réseau 100Mbps ou WiFi 5GHz)
- **>20ms**: Latence visible, vérifier réseau

### Bande Passante Audio

**Calcul**:
```
Sample Rate: 24000 Hz
Channels: 1 (mono)
Bit Depth: 16-bit (2 bytes)

Bandwidth = 24000 * 1 * 2 = 48 KB/s = 384 kbps
```

**Avec overhead UDP/IP**: ~400 kbps

**Réseau requis**: Minimum 1 Mbps (confortable: 10 Mbps)

---

## 🔐 Sécurité

### ⚠️ UDP est Non-Sécurisé

**Risques**:
- Pas de chiffrement (audio en clair)
- Pas d'authentification
- Spoofing possible

**Recommandations Production**:

1. **Isoler sur VLAN**:
   ```bash
   # Mettre Audio2Face et Avatar sur VLAN privé
   # 192.168.100.x par exemple
   ```

2. **Firewall règles strictes**:
   ```bash
   # Autoriser UNIQUEMENT IP de la machine Avatar
   sudo ufw allow from 192.168.1.X to any port 8080 proto udp
   ```

3. **VPN pour accès distant**:
   - WireGuard ou OpenVPN
   - Éviter exposition Internet directe

---

## 📝 Configuration Multi-Machines

### Scénario: Plusieurs Avatars → 1 Audio2Face

**Option 1: Ports différents**
```bash
# Avatar 1 → 192.168.1.14:8080
# Avatar 2 → 192.168.1.14:8081
# Avatar 3 → 192.168.1.14:8082
```

**.env** pour chaque instance:
```bash
# Avatar 1
UNREAL_AUDIO_UDP_PORT=8080

# Avatar 2
UNREAL_AUDIO_UDP_PORT=8081
```

**Option 2: Audio2Face instances**
```bash
# Audio2Face 1 → 192.168.1.14:8080
# Audio2Face 2 → 192.168.1.15:8080
# Audio2Face 3 → 192.168.1.16:8080
```

**.env** pour chaque Avatar:
```bash
# Avatar 1
UNREAL_AUDIO_UDP_HOST=192.168.1.14

# Avatar 2
UNREAL_AUDIO_UDP_HOST=192.168.1.15
```

---

## 🧪 Script de Test Avancé

### Test avec Audio Réel (24kHz)

```bash
# Générer audio de test 24kHz
ffmpeg -f lavfi -i "sine=frequency=440:duration=5" \
  -ar 24000 -ac 1 -f wav test_24khz.wav

# Envoyer via UDP
python claude_dev/test_udp_sender.py test_24khz.wav
```

### Monitoring Réseau

```bash
# Capturer trafic UDP sur port 8080
sudo tcpdump -i any udp port 8080 -v

# Voir packets en temps réel
sudo tcpdump -i any udp port 8080 -X | grep -A5 "UDP"
```

---

## ✅ Checklist Finale

Avant de lancer le pipeline, vérifier:

- [ ] Ping vers 192.168.1.14 fonctionne
- [ ] Audio2Face écoute sur 0.0.0.0:8080
- [ ] Firewall autorise UDP 8080
- [ ] `test_udp_connection.py` passe ✅
- [ ] Variables `.env` configurées:
  - `UNREAL_AUDIO_UDP_HOST=192.168.1.14`
  - `UNREAL_AUDIO_UDP_PORT=8080`
  - `AUDIO_SAMPLE_RATE=24000`

---

## 📞 Support

Si problèmes persistent:

1. **Logs Audio2Face**: Vérifier console Audio2Face
2. **Wireshark**: Capturer trafic pour debug
3. **Simplify**: Tester avec `nc -u` simple d'abord

**Documentation Audio2Face**:
https://docs.omniverse.nvidia.com/audio2face

---

**Dernière mise à jour**: 2025-11-19
**IP Audio2Face**: 192.168.1.14:8080
