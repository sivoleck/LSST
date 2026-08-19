# 📊 Lol Scrim Stats Tracker

Recopilador de datos de partidas personalizadas de League of Legends usando la **Live Client Data API**. Genera un JSON estructurado para para luego ser procesado, por ejemplo por un bot de Discord.

## 🚀 Instalación

### 1. Requisitos previos
- **Python 3.10+** instalado
- **League of Legends** instalado

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

## ▶️ Uso

### 1. Lanza el script
```bash
python collector.py
```

### 2. Abre LoL y entra en una partida personalizada

El script detectará automáticamente cuando empiece la partida.

### 3. Juega normalmente

El script captura un snapshot por minuto en segundo plano.

### 4. Al terminar la partida

El script genera automáticamente un archivo `matches/match_FECHA_HORA.json`.

### 5. Sube el JSON a Discord

Usa tu comando del bot de Discord para procesar el archivo.

## ⚙️ Configuración

Edita `config.py` para ajustar:

| Parámetro | Default | Descripción |
|---|---|---|
| `POLLING_INTERVAL_SECONDS` | `60` | Intervalo de captura (segundos) |
| `SNAPSHOT_KEEP_MINUTES` | `[5, 10, 15, 20]` | Minutos a incluir en el JSON. `None` = todos |
| `OUTPUT_DIR` | `./matches` | Carpeta de salida |

## 📁 Estructura del JSON de salida

```
{
  "info": {
    "gameDuration": 1805,
    "gameMode": "CLASSIC",
    "gameVersion": "14.13.1",
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
      },
      {
        "teamId": 200,
        "win": false,
        "kills": 12,
        "objectives": {
          "dragon": { "kills": 1 },
          "tower": { "kills": 2 },
          "baron": { "kills": 0 }
        }
      }
    ],
    "participants": [
      {
        "participantId": 1,
        "puuid": "Faker#T1",
        "riotIdGameName": "Faker",
        "riotIdTagLine": "T1",
        "teamId": 100,
        "teamPosition": "MIDDLE",
        "championName": "Azir",
        "win": true,
        "kills": 8,
        "deaths": 1,
        "assists": 12,
        "firstBloodKill": false,
        "totalMinionsKilled": 245,
        "detectorWardsPlaced": 4,
        "challenges": {
          "damagePerMinute": 950.2,
          "visionScorePerMinute": 1.1,
          "teamDamagePercentage": 0.32,
          "kda": 20.0
        }
      }
      // ... aquí irían los otros 9 participantes
    ]
  },
  "timeline": {
    "info": {
      "frames": [
        {
          "timestamp": 900000,           // MS (ej: 900000 = minuto 15)
          "participantFrames": {
            "1": {
              "minionsKilled": 135       // Único dato 100% fiable en local
            },
            "2": {
              "minionsKilled": 80
            }
            // ... así para los participantes del 3 al 10
          }
        }
        // ... esto se repite para el minuto 0, 1, 2, 3... hasta que acabe la partida
      ]
    }
  }
}
```

## ⚠️ Notas importantes

- El script **no es baneable** — usa la API oficial de Riot expuesta localmente.
- El certificado SSL es autofirmado, el script lo maneja automáticamente.
