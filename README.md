# 📊 LoL Custom Match Tracker

Recopilador de datos de partidas personalizadas de League of Legends. Genera un JSON estructurado **100% compatible con el formato de la API de Riot (Match V5)** para que puedas directamente sin necesidad de programar funciones duplicadas.

Este sistema utiliza un método **híbrido** sin necesidad de API Keys:
1. **Live Client Data API (En vivo):** Para recolectar el farmeo (CS) y eventos minuto a minuto mientras juegas.
2. **Archivos `.rofl` (Post-partida):** Para fusionar el Daño a Campeones, Visión y estadísticas perfectas de fin de partida (bloqueadas por el anti-cheat).

---

## 🚀 Instalación

### 1. Requisitos previos
- **Python 3.10+** instalado
- **League of Legends** instalado (funciona en cualquier región)
- *No necesitas Riot API Key.*

### 2. Instalar dependencias
Abre la consola en esta carpeta y ejecuta:
```bash
pip install requests urllib3
```

---

## ▶️ Uso / Flujo de trabajo

### 1. Lanza el script
Antes de empezar a jugar o estando en la pantalla de carga, ejecuta:
```bash
python collector.py
```

### 2. Juega la partida
El script detectará automáticamente cuándo empieza la partida y se quedará capturando datos en segundo plano (1 snapshot por minuto).

### 3. Al terminar (¡Paso Importante!)
Cuando la partida termine (explote el nexo), verás que el script se pausa y te pide que descargues la repetición.
1. Ve al historial de tu cliente de LoL.
2. Haz clic en el botón de **Descargar Repetición**.
3. *¡Listo!* El script detectará el archivo `.rofl` automáticamente, fusionará el Daño Total con tu farmeo, y generará el JSON final en la carpeta `./matches`.

*(Nota: Si no descargas la repetición en 2 minutos, el script guardará el JSON igualmente, pero sin los datos de daño).*

### 4. Sube el JSON a Discord
Arrastra el archivo JSON a Discord y usa el comando de tu bot (ej: `/review`) adjuntando el archivo. El bot lo leerá como si fuera una partida de la API Oficial de Riot.

---

## ⚙️ Configuración

Puedes editar el archivo `config.py` si necesitas ajustar algo:
- `POLLING_INTERVAL_SECONDS`: Cada cuántos segundos captura datos en local (por defecto `60`).
- `OUTPUT_DIR`: Carpeta donde se guardarán los archivos JSON (por defecto `./matches`).

---

## 📁 Estructura del JSON de salida

El JSON simula a la perfección el formato de la API Match V5. Algunos datos se ocultan por limitaciones del Anti-Cheat en local, pero la estructura permanece intacta para no romper parsers:

```json
{
  "info": {
    "gameDuration": 1805,
    "gameMode": "CLASSIC",
    "teams": [
      {
        "teamId": 100,
        "win": true,
        "kills": 25,
        "objectives": {
          "dragon": { "kills": 3 },
          "tower": { "kills": 7 },
          "baron": { "kills": 1 }
        }
      }
    ],
    "participants": [
      {
        "participantId": 1,
        "puuid": "Jugador#EUW",
        "riotIdGameName": "Jugador",
        "riotIdTagLine": "EUW",
        "teamId": 100,
        "teamPosition": "TOP",
        "championName": "Aatrox",
        "kills": 5,
        "deaths": 2,
        "assists": 8,
        "totalMinionsKilled": 185,
        "challenges": {
          "damagePerMinute": 850.5,
          "visionScorePerMinute": 0.85,
          "teamDamagePercentage": 0.28,
          "kda": 6.5
        }
      }
    ]
  },
  "timeline": {
    "info": {
      "frames": [
        {
          "timestamp": 600000,
          "participantFrames": {
            "1": { "minionsKilled": 85 }
          }
        }
      ]
    }
  }
}
```

---

## ⚠️ Notas de Privacidad y Anti-Cheat
- **El script es 100% legal y no es baneable.** Lee archivos legítimos (`.rofl`) descargados por el cliente, y usa la Live Client Data API, que es una herramienta oficial documentada por Riot Games.
- No inyecta código, no lee memoria (RAM) y no intercepta paquetes de red.
- Las **coordenadas X/Y** del mapa y el oro de los rivales no se pueden extraer en las partidas personalizadas sin vulnerar las reglas del Anti-Cheat (Vanguard), por lo que **no se incluyen** en los cálculos de proximidad al jungla.

