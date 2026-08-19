"""
LoL Custom Match Tracker — collector.py
========================================
Script principal que recopila datos de partidas personalizadas de LoL
usando la Live Client Data API (127.0.0.1:2999).

Uso:
    python collector.py

Ejecutar ANTES o DURANTE una partida activa. El script esperará
automáticamente hasta detectar que hay una partida en curso.
"""

import json
import os
import sys
import time
import urllib3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Fix encoding para consola de Windows (soportar emojis y caracteres especiales)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

import config

# Suprimir warnings de SSL (certificado autofirmado de Riot)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ═══════════════════════════════════════════════════════════
#  LIVE CLIENT API — Comunicación con el cliente de LoL
# ═══════════════════════════════════════════════════════════

def api_get(endpoint: str) -> dict | list | None:
    """
    Realiza una petición GET a la Live Client API.
    Retorna el JSON parseado o None si la API no está disponible.
    """
    url = f"{config.LIVE_CLIENT_BASE_URL}{endpoint}"
    try:
        response = requests.get(url, verify=config.SSL_VERIFY, timeout=5)
        response.raise_for_status()
        return response.json()
    except (requests.ConnectionError, requests.Timeout):
        return None
    except requests.HTTPError as e:
        print(f"  [!] Error HTTP en {endpoint}: {e}")
        return None
    except requests.exceptions.JSONDecodeError:
        return None


def get_all_game_data() -> dict | None:
    """Obtiene todos los datos del juego en una sola petición."""
    return api_get("/allgamedata")


def get_player_list() -> list | None:
    """Obtiene la lista de todos los jugadores en la partida."""
    return api_get("/playerlist")


def get_event_data() -> dict | None:
    """Obtiene todos los eventos de la partida."""
    return api_get("/eventdata")


def get_game_stats() -> dict | None:
    """Obtiene las estadísticas generales del juego (timer, modo, etc.)."""
    return api_get("/gamestats")


def get_active_player() -> dict | None:
    """Obtiene los datos del jugador local activo."""
    return api_get("/activeplayer")



# ═══════════════════════════════════════════════════════════
#  SNAPSHOTS — Captura periódica de datos de jugadores
# ═══════════════════════════════════════════════════════════

def capture_player_snapshot(player: dict) -> dict:
    """
    Extrae los datos relevantes de un jugador para un snapshot.

    Args:
        player: Objeto de jugador del endpoint /playerlist

    Returns:
        Diccionario con los datos del snapshot.
    """
    scores = player.get("scores", {})
    # El oro y XP no están expuestos públicamente por la API para todos los jugadores.
    # Se dejan en None (null en JSON) por decisión de diseño.
    gold = None
    xp = None

    # La Live Client API NO expone coordenadas de mapa para todos los jugadores
    # (razones de anti-cheat). Se guarda None para mantener compatibilidad
    # estructural con la función cordenadas() del bot.
    position = None

    return {
        "gold": gold,
        "xp": xp,
        "cs": int(scores.get("creepScore", 0)),
        "kills": int(scores.get("kills", 0)),
        "deaths": int(scores.get("deaths", 0)),
        "assists": int(scores.get("assists", 0)),
        "level": int(player.get("level", 0)),
        "position": position,  # {"x": float, "y": float} | None
    }


def get_game_minute(game_data: dict) -> int:
    """
    Extrae el minuto actual de juego.

    Args:
        game_data: Respuesta completa de /allgamedata

    Returns:
        Minuto actual (entero).
    """
    game_time = game_data.get("gameData", {}).get("gameTime", 0)
    return int(game_time // 60)


def get_game_time_seconds(game_data: dict) -> float:
    """Extrae el tiempo de juego en segundos."""
    return float(game_data.get("gameData", {}).get("gameTime", 0))


# ═══════════════════════════════════════════════════════════
#  LANE MATCHING — Emparejamiento por posición
# ═══════════════════════════════════════════════════════════

def identify_lane_opponents(players: list) -> dict:
    """
    Empareja jugadores por posición entre los dos equipos.

    La Live Client API puede o no dar la posición del jugador.
    Si no la da, usamos el orden (que tiende a ser TOP→SUP por equipo).

    Args:
        players: Lista de jugadores del /playerlist

    Returns:
        Dict {summonerName: opponent_summonerName}
    """
    team_order = {}  # team -> [jugadores en orden]
    team_blue = []  # ORDER
    team_red = []   # CHAOS

    for player in players:
        team = player.get("team", "")
        name = player.get("riotIdGameName", player.get("summonerName", "unknown"))
        tag = player.get("riotIdTagLine", "")
        riot_id = f"{name}#{tag}" if tag else name

        position = player.get("position", "")

        entry = {"riot_id": riot_id, "position": position}

        if team == "ORDER":
            team_blue.append(entry)
        elif team == "CHAOS":
            team_red.append(entry)

    # Emparejar por posición si está disponible
    opponents = {}
    position_map_blue = {p["position"]: p["riot_id"] for p in team_blue if p["position"]}
    position_map_red = {p["position"]: p["riot_id"] for p in team_red if p["position"]}

    if position_map_blue and position_map_red:
        for pos, blue_id in position_map_blue.items():
            red_id = position_map_red.get(pos)
            if red_id:
                opponents[blue_id] = red_id
                opponents[red_id] = blue_id
    else:
        # Fallback: emparejar por orden en la lista (generalmente TOP→SUP)
        for i in range(min(len(team_blue), len(team_red))):
            b_id = team_blue[i]["riot_id"]
            r_id = team_red[i]["riot_id"]
            opponents[b_id] = r_id
            opponents[r_id] = b_id

    return opponents


# ═══════════════════════════════════════════════════════════
#  CÁLCULOS — Métricas derivadas
# ═══════════════════════════════════════════════════════════

def calculate_diffs(snapshot_buffer: dict, opponents: dict, minute: int | str) -> dict:
    """
    Calcula los diferenciales vs rival de línea para un snapshot dado.

    Args:
        snapshot_buffer: {riot_id: snapshot_data} para ese minuto
        opponents: {riot_id: opponent_riot_id}
        minute: El minuto (int o "final")

    Returns:
        {riot_id: {goldDiff_vs_opponent, xpDiff_vs_opponent, csDiff_vs_opponent}}
    """
    diffs = {}

    for riot_id, snapshot in snapshot_buffer.items():
        opponent_id = opponents.get(riot_id)
        if opponent_id and opponent_id in snapshot_buffer:
            opp = snapshot_buffer[opponent_id]
            diffs[riot_id] = {
                "goldDiff_vs_opponent": None,
                "xpDiff_vs_opponent": None,
                "csDiff_vs_opponent": snapshot["cs"] - opp["cs"],
            }
        else:
            diffs[riot_id] = {
                "goldDiff_vs_opponent": None,
                "xpDiff_vs_opponent": None,
                "csDiff_vs_opponent": 0,
            }

    return diffs


def build_final_stats(player: dict, game_time_seconds: float, team_total_damage: float) -> dict:
    """
    Construye las estadísticas finales de un jugador.

    Args:
        player: Objeto de jugador del /playerlist (última captura)
        game_time_seconds: Duración total de la partida en segundos
        team_total_damage: Daño total del equipo (para calcular Team DMG%)

    Returns:
        Diccionario con las stats finales.
    """
    scores = player.get("scores", {})
    champion_stats = player.get("championStats", {})
    minutes = game_time_seconds / 60 if game_time_seconds > 0 else 1

    kills = int(scores.get("kills", 0))
    deaths = int(scores.get("deaths", 0))
    assists = int(scores.get("assists", 0))
    # El oro total y XP no se exponen para todos los jugadores
    gold = None
    cs = int(scores.get("creepScore", 0))
    # wardScore es el vision score acumulado
    vision = int(scores.get("wardScore", 0) if scores.get("wardScore") else 0)

    # KDA: (K+A)/D, si D=0 → perfect KDA
    kda = round((kills + assists) / max(deaths, 1), 2)

    # Daño
    # La Live Client API no separa "daño a campeones" de forma directa en scores,
    # pero sí en el campo "championStats" del active player.
    # Para los demás jugadores, usamos lo disponible.
    total_damage = 0
    total_damage_taken = 0

    # Intentar obtener de items/stats disponibles
    champion_stats = player.get("championStats", {})
    if champion_stats:
        total_damage = champion_stats.get("totalDamageDealtToChampions", 0)
        total_damage_taken = champion_stats.get("totalDamageTaken", 0)

    # Si no hay champion_stats (jugadores no-activos), usar lo que haya
    if total_damage == 0:
        total_damage = scores.get("totalDamageDealtToChampions", 0)
    if total_damage_taken == 0:
        total_damage_taken = scores.get("totalDamageTaken", 0)

    # Team DMG%
    team_dmg_pct = round((total_damage / max(team_total_damage, 1)) * 100, 1)

    return {
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "kda": kda,
        "kp_percent": 0,  # Se calcula después con el total de kills del equipo
        "total_damage_dealt_to_champions": int(total_damage),
        "damage_per_minute": round(total_damage / minutes, 1),
        "total_damage_taken": int(total_damage_taken),
        "team_dmg_percent": team_dmg_pct,
        "gold_per_minute": None,
        "cs_per_minute": round(cs / minutes, 1),
        "vision_score": vision,
        "vision_per_minute": round(vision / minutes, 2),
        "control_wards_placed": int(scores.get("controlWardsPlaced", 0)),
        "total_gold_earned": None,
        "total_cs": cs,
    }


# ═══════════════════════════════════════════════════════════
#  EVENTOS — Procesamiento de eventos del juego
# ═══════════════════════════════════════════════════════════

def process_events(events: list) -> tuple[list, bool, dict | None]:
    """
    Procesa los eventos del juego.

    Args:
        events: Lista de eventos de /eventdata

    Returns:
        Tupla de:
        - Lista de eventos filtrados relevantes
        - bool indicando si el juego terminó
        - Datos del evento GameEnd (si existe)
    """
    relevant_events = []
    game_ended = False
    game_end_data = None

    for event in events:
        event_name = event.get("EventName", "")

        if event_name == "GameEnd":
            game_ended = True
            game_end_data = event
            continue

        # Filtrar eventos relevantes
        if event_name in ("ChampionKill", "DragonKill", "BaronKill",
                          "HeraldKill", "TurretKilled", "InhibKilled",
                          "FirstBlood", "Multikill", "Ace"):
            relevant_events.append({
                "EventName": event_name,
                "EventTime": round(event.get("EventTime", 0), 1),
                "KillerName": event.get("KillerName", ""),
                "VictimName": event.get("VictimName", ""),
                "Assisters": event.get("Assisters", []),
                # Campos específicos de algunos eventos
                **({"DragonType": event["DragonType"]} if "DragonType" in event else {}),
                **({"TurretKilled": event["TurretKilled"]} if "TurretKilled" in event else {}),
                **({"KillStreak": event["KillStreak"]} if "KillStreak" in event else {}),
            })

    return relevant_events, game_ended, game_end_data


def count_team_objectives(events: list, team_players: set) -> dict:
    """
    Cuenta los objetivos conseguidos por un equipo basándose en los eventos.

    Args:
        events: Lista de eventos procesados
        team_players: Set de riot_ids del equipo

    Returns:
        Dict con contadores de objetivos.
    """
    objectives = {"dragons": 0, "baron": 0, "herald": 0, "towers": 0, "inhibitors": 0}

    for event in events:
        killer = event.get("KillerName", "")
        # El killer puede venir como "nombre" sin tag en algunos eventos
        killer_in_team = any(killer in p for p in team_players)

        if not killer_in_team:
            continue

        event_name = event["EventName"]
        if event_name == "DragonKill":
            objectives["dragons"] += 1
        elif event_name == "BaronKill":
            objectives["baron"] += 1
        elif event_name == "HeraldKill":
            objectives["herald"] += 1
        elif event_name == "TurretKilled":
            objectives["towers"] += 1
        elif event_name == "InhibKilled":
            objectives["inhibitors"] += 1

    return objectives


# ═══════════════════════════════════════════════════════════
#  MAIN — Bucle principal del collector
# ═══════════════════════════════════════════════════════════

def wait_for_game():
    """Espera hasta que se detecte una partida activa."""
    print("\n╔══════════════════════════════════════════════╗")
    print("║   LoL Custom Match Tracker v{}          ║".format(config.COLLECTOR_VERSION))
    print("╠══════════════════════════════════════════════╣")
    print("║  Esperando partida activa...                ║")
    print("║  Abre LoL y entra en una partida.           ║")
    print("║  Pulsa Ctrl+C para cancelar.                ║")
    print("╚══════════════════════════════════════════════╝\n")

    while True:
        data = get_game_stats()
        if data:
            print("  [✓] ¡Partida detectada!")
            return data
        time.sleep(3)



# ═══════════════════════════════════════════════════════════
#  LECTURA DE REPETICIONES (.rofl)
# ═══════════════════════════════════════════════════════════

def _pick(obj: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in obj:
            return obj[key]
    return None

def _to_int(value: Any, default: int = 0) -> int:
    if value is None or value == "": return default
    try: return int(float(value))
    except (TypeError, ValueError): return default

def _to_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "": return default
    try: return float(value)
    except (TypeError, ValueError): return default

def _parse_new_tail_metadata(data: bytes) -> dict[str, Any]:
    if len(data) < 8: raise ValueError("Archivo muy pequeño.")
    metadata_length = int.from_bytes(data[-4:], byteorder="little", signed=False)
    if metadata_length <= 0 or metadata_length > len(data) - 4:
        raise ValueError(f"Longitud inválida: {metadata_length}")
    start = len(data) - 4 - metadata_length
    raw = data[start : len(data) - 4]
    return json.loads(raw.decode("utf-8"))

def _parse_old_offset_metadata(data: bytes) -> dict[str, Any]:
    file_info_pos = 262
    file_info_len = 26
    if len(data) < file_info_pos + file_info_len:
        raise ValueError("No se pudo leer la info del archivo antiguo.")
    info = data[file_info_pos : file_info_pos + file_info_len]
    metadata_offset = int.from_bytes(info[6:10], byteorder="little", signed=False)
    metadata_length = int.from_bytes(info[10:14], byteorder="little", signed=False)
    payload_header_offset = int.from_bytes(info[14:18], byteorder="little", signed=False)
    candidates = []
    if 0 <= metadata_offset < payload_header_offset <= len(data):
        candidates.append(data[metadata_offset:payload_header_offset])
    if 0 <= metadata_offset < len(data) and metadata_length > 0:
        candidates.append(data[metadata_offset : metadata_offset + metadata_length])
    for raw in candidates:
        try:
            return json.loads(raw.decode("utf-8").strip("\x00\r\n\t "))
        except: pass
    raise ValueError("Fallo parseando old metadata.")

def parse_rofl_stats(rofl_path: Path) -> list[dict[str, Any]]:
    data = rofl_path.read_bytes()
    if data[:4] != b"RIOT": raise ValueError("No es un .rofl válido.")
    
    metadata = None
    for parser in (_parse_new_tail_metadata, _parse_old_offset_metadata):
        try:
            m = parser(data)
            if isinstance(m, dict) and ("statsJson" in m or "gameLength" in m):
                metadata = m
                break
        except: pass
        
    if not metadata: return []
    
    stats_raw = metadata.get("statsJson")
    if isinstance(stats_raw, str):
        stats_raw = json.loads(stats_raw) if stats_raw.strip() and stats_raw.strip() != "[]" else []
    if not isinstance(stats_raw, list) or not stats_raw: return []

    game_length_ms = _to_float(metadata.get("gameLength"))
    game_minutes = game_length_ms / 60000 if game_length_ms and game_length_ms > 0 else None

    result = []
    for player in stats_raw:
        game_name = _pick(player, "RIOT_ID_GAME_NAME", "riotIdGameName")
        tag_line = _pick(player, "RIOT_ID_TAG_LINE", "riotIdTagline", "riotIdTagLine")
        summoner_name = f"{game_name}#{tag_line}" if (game_name and tag_line) else str(game_name or _pick(player, "NAME", "summonerName", "SUMMONER_NAME"))

        kills = _to_int(_pick(player, "CHAMPIONS_KILLED", "kills"), 0)
        deaths = _to_int(_pick(player, "NUM_DEATHS", "deaths"), 0)
        assists = _to_int(_pick(player, "ASSISTS", "assists"), 0)
        damage = _to_int(_pick(player, "TOTAL_DAMAGE_DEALT_TO_CHAMPIONS", "totalDamageDealtToChampions", "damageToChampions"), 0)
        dpm = round(damage / game_minutes, 1) if game_minutes else 0
        kda_ratio = round((kills + assists) / deaths, 2) if deaths > 0 else float((kills + assists))

        win_raw = _pick(player, "WIN", "win")
        win = str(win_raw).lower() in ("win", "true", "1") if win_raw is not None else None

        result.append({
            "summoner_name": summoner_name,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "kda_ratio": kda_ratio,
            "damage": damage,
            "dpm": dpm,
            "win": win,
        })
    return result

def wait_for_rofl_file(timeout=120):
    replays_dir = Path(os.path.expanduser("~")) / "Documents" / "League of Legends" / "Replays"
    if not replays_dir.exists():
        replays_dir = Path(os.path.expanduser("~")) / "OneDrive" / "Documents" / "League of Legends" / "Replays"
        if not replays_dir.exists():
            return None

    def get_latest_rofl():
        files = list(replays_dir.glob("*.rofl"))
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
    
    initial_latest = get_latest_rofl()
    initial_mtime = initial_latest.stat().st_mtime if initial_latest else 0
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        current_latest = get_latest_rofl()
        if current_latest:
            current_mtime = current_latest.stat().st_mtime
            if current_mtime > initial_mtime or (time.time() - current_mtime < 120 and current_latest != initial_latest):
                time.sleep(2)  # Wait for file to finish writing
                try:
                    return parse_rofl_stats(current_latest)
                except:
                    return None
        time.sleep(2)
    return None


def run_collector():
    """Bucle principal del collector."""

    # ── Esperar a que haya una partida activa ─────────────
    wait_for_game()

    # ── Obtener datos iniciales ───────────────────────────
    game_data = get_all_game_data()
    if not game_data:
        print("  [✗] No se pudo obtener los datos del juego. Abortando.")
        sys.exit(1)

    players = game_data.get("allPlayers", [])
    game_info = game_data.get("gameData", {})

    print(f"  [i] Modo: {game_info.get('gameMode', 'DESCONOCIDO')}")
    print(f"  [i] Jugadores detectados: {len(players)}")
    for p in players:
        name = p.get("riotIdGameName", p.get("summonerName", "?"))
        tag = p.get("riotIdTagLine", "")
        champ = p.get("championName", "?")
        team = "🔵" if p.get("team") == "ORDER" else "🔴"
        print(f"      {team} {name}#{tag} — {champ}")

    # ── Identificar rivales de línea ──────────────────────
    opponents = identify_lane_opponents(players)

    # ── Preparar buffer de snapshots ──────────────────────
    # {minuto: {riot_id: snapshot_data}}
    snapshot_buffer = {}
    captured_minutes = set()
    last_players_data = None
    last_game_time = 0

    print(f"\n  [▶] Capturando snapshots cada {config.POLLING_INTERVAL_SECONDS}s...")
    print(f"  [i] Snapshots a guardar: {config.SNAPSHOT_KEEP_MINUTES or 'TODOS'}")
    print()

    # ── Bucle principal ───────────────────────────────────
    game_ended = False
    all_events = []

    while not game_ended:
        time.sleep(config.POLLING_INTERVAL_SECONDS)

        # Intentar obtener datos
        game_data = get_all_game_data()
        if game_data is None:
            # La API dejó de responder → la partida probablemente terminó
            print("\n  [!] La API dejó de responder. La partida puede haber terminado.")
            game_ended = True
            break

        # Extraer tiempo y minuto
        current_time = get_game_time_seconds(game_data)
        current_minute = int(current_time // 60)
        last_game_time = current_time

        # Obtener jugadores actualizados
        players = game_data.get("allPlayers", [])
        last_players_data = players

        # ── Capturar snapshot del minuto actual ────────────
        if current_minute not in captured_minutes and current_minute > 0:
            minute_snapshot = {}

            for player in players:
                name = player.get("riotIdGameName", player.get("summonerName", "?"))
                tag = player.get("riotIdTagLine", "")
                riot_id = f"{name}#{tag}" if tag else name

                minute_snapshot[riot_id] = capture_player_snapshot(player)

            snapshot_buffer[current_minute] = minute_snapshot
            captured_minutes.add(current_minute)

            # Indicador visual
            marker = " ★" if (config.SNAPSHOT_KEEP_MINUTES and
                              current_minute in config.SNAPSHOT_KEEP_MINUTES) else ""
            print(f"  [📸] Snapshot minuto {current_minute:3d} capturado "
                  f"({len(players)} jugadores){marker}")

        # ── Procesar eventos ──────────────────────────────
        event_data = game_data.get("events", {}).get("Events", [])
        processed_events, ended_by_event, end_data = process_events(event_data)
        all_events = processed_events  # Reemplazamos, ya que /eventdata da todos los eventos

        if ended_by_event:
            print("\n  [🏁] ¡Partida terminada detectada por evento GameEnd!")
            game_ended = True

            # Capturar snapshot final inmediatamente
            final_snapshot = {}
            for player in players:
                name = player.get("riotIdGameName", player.get("summonerName", "?"))
                tag = player.get("riotIdTagLine", "")
                riot_id = f"{name}#{tag}" if tag else name
                final_snapshot[riot_id] = capture_player_snapshot(player)

            snapshot_buffer["final"] = final_snapshot
            print("  [📸] Snapshot FINAL capturado.")

    # ── Si terminó por desconexión, usar último snapshot como final ──
    if "final" not in snapshot_buffer and snapshot_buffer:
        last_min = max(k for k in snapshot_buffer if isinstance(k, int))
        snapshot_buffer["final"] = snapshot_buffer[last_min]
        print(f"  [📸] Usando snapshot del minuto {last_min} como FINAL.")

    print("\n  [📝] Partida terminada. Esperando datos avanzados (.rofl)...")
    print("  [!] Por favor, ve al cliente de LoL y presiona 'Descargar Repetición' en el historial.")
    print("  [!] Tienes 2 minutos para hacerlo. El script detectará el archivo automáticamente...")
    
    rofl_stats = wait_for_rofl_file(timeout=120)
    
    if rofl_stats:
        print("  [✓] ¡Archivo .rofl detectado! Fusionando el daño y estadísticas avanzadas...")
    else:
        print("  [⚠] Tiempo agotado o repetición no encontrada. Guardando JSON sin daño...")

    print("\n  [📝] Construyendo JSON de salida...")
    output = build_output_json(
        game_data=game_data,
        game_info=game_info,
        players=last_players_data or players,
        snapshot_buffer=snapshot_buffer,
        opponents=opponents,
        all_events=all_events,
        game_time_seconds=last_game_time,
        rofl_stats=rofl_stats
    )

    # ── Guardar archivo ───────────────────────────────────
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"match_{timestamp}.json"
    filepath = os.path.join(config.OUTPUT_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n  [✓] ¡Partida guardada en: {filepath}")
    print(f"  [i] Sube este archivo a Discord con tu comando para procesarlo.\n")

    return filepath


def build_output_json(
    game_data: dict,
    game_info: dict,
    players: list,
    snapshot_buffer: dict,
    opponents: dict,
    all_events: list,
    game_time_seconds: float,
    rofl_stats: list = None,
) -> dict:
    """
    Construye el JSON final de salida con la estructura acordada.
    """
    game_duration = int(game_time_seconds)
    minutes = game_time_seconds / 60 if game_time_seconds > 0 else 1

    # ── Separar jugadores por equipo ──────────────────────
    team_blue_players = []
    team_red_players = []
    team_blue_ids = set()
    team_red_ids = set()

    for player in players:
        name = player.get("riotIdGameName", player.get("summonerName", "?"))
        tag = player.get("riotIdTagLine", "")
        riot_id = f"{name}#{tag}" if tag else name

        if player.get("team") == "ORDER":
            team_blue_players.append(player)
            team_blue_ids.add(riot_id)
            team_blue_ids.add(name)  # Algunos eventos usan solo el nombre
        else:
            team_red_players.append(player)
            team_red_ids.add(riot_id)
            team_red_ids.add(name)

    # ── Calcular daño total por equipo ────────────────────
    def get_player_rofl_stats(pid_name, pid_tag, pid_full):
        if not rofl_stats: return None
        return next((r for r in rofl_stats if r["summoner_name"] == pid_full or r["summoner_name"] == pid_name), None)

    blue_total_dmg = 0
    red_total_dmg = 0
    
    if rofl_stats:
        for p in team_blue_players:
            n = p.get("riotIdGameName", p.get("summonerName", "?"))
            full = f"{n}#{p.get('riotIdTagLine', '')}" if p.get('riotIdTagLine') else n
            rs = get_player_rofl_stats(n, p.get('riotIdTagLine'), full)
            if rs: blue_total_dmg += rs["damage"]
            
        for p in team_red_players:
            n = p.get("riotIdGameName", p.get("summonerName", "?"))
            full = f"{n}#{p.get('riotIdTagLine', '')}" if p.get('riotIdTagLine') else n
            rs = get_player_rofl_stats(n, p.get('riotIdTagLine'), full)
            if rs: red_total_dmg += rs["damage"]
    else:
        def team_total_dmg(team_players):
            total = 0
            for p in team_players:
                scores = p.get("scores", {})
                total += scores.get("totalDamageDealtToChampions", 0)
            return total
        blue_total_dmg = team_total_dmg(team_blue_players)
        red_total_dmg = team_total_dmg(team_red_players)

    # ── Calcular kills totales por equipo (para KP%) ─────
    blue_total_kills = sum(p.get("scores", {}).get("kills", 0) for p in team_blue_players)
    red_total_kills = sum(p.get("scores", {}).get("kills", 0) for p in team_red_players)

    # ── Contar objetivos por equipo ───────────────────────
    blue_objectives = count_team_objectives(all_events, team_blue_ids)
    red_objectives = count_team_objectives(all_events, team_red_ids)

    # ── Determinar ganador ────────────────────────────────
    # Si hay evento GameEnd con Result, usarlo; si no, heurística por torres tiradas
    blue_towers = blue_objectives["towers"]
    red_towers = red_objectives["towers"]
    blue_wins = blue_towers >= red_towers  # Heurística (se reemplaza si hay evento GameEnd)

    # ── Asignar participantId (ORDER: 1-5, CHAOS: 6-10) ──────────────────
    pid_counters = {"ORDER": 1, "CHAOS": 6}
    player_pid_map = {}
    for player in players:
        name = player.get("riotIdGameName", player.get("summonerName", "?"))
        tag = player.get("riotIdTagLine", "")
        riot_id = f"{name}#{tag}" if tag else name
        team = player.get("team", "ORDER")
        pid = pid_counters.get(team, 1)
        player_pid_map[riot_id] = pid
        pid_counters[team] = pid + 1

    # ── Construir teams (Riot Match V5 format) ────────────────────────
    teams_v5 = [
        {
            "teamId": 100,
            "win": blue_wins,
            "kills": blue_total_kills,
            "objectives": {
                "dragon": {"kills": blue_objectives["dragons"]},
                "tower": {"kills": blue_objectives["towers"]},
                "baron": {"kills": blue_objectives["baron"]},
            }
        },
        {
            "teamId": 200,
            "win": not blue_wins,
            "kills": red_total_kills,
            "objectives": {
                "dragon": {"kills": red_objectives["dragons"]},
                "tower": {"kills": red_objectives["towers"]},
                "baron": {"kills": red_objectives["baron"]},
            }
        }
    ]

    # ── First Blood ───────────────────────────────────────────────────
    first_blood_killer = None
    for e in all_events:
        if e.get("EventName") == "ChampionKill":
            first_blood_killer = e.get("KillerName")
            break

    # ── Construir participantes (Riot Match V5 format) ───────────────
    participants_v5 = []
    for player in players:
        name = player.get("riotIdGameName", player.get("summonerName", "?"))
        tag = player.get("riotIdTagLine", "")
        riot_id = f"{name}#{tag}" if tag else name

        team = player.get("team", "")
        team_id = 100 if team == "ORDER" else 200
        is_blue = team == "ORDER"
        team_dmg = blue_total_dmg if is_blue else red_total_dmg
        
        final_stats = build_final_stats(player, game_time_seconds, team_dmg)
        pid = player_pid_map.get(riot_id, 0)
        
        fb = False
        if first_blood_killer:
            fb = (first_blood_killer in name) or (first_blood_killer in riot_id)

        p_v5 = {
            "participantId": pid,
            "puuid": riot_id,  # Fallback
            "riotIdGameName": name,
            "riotIdTagLine": tag,
            "teamId": team_id,
            "teamPosition": player.get("position", ""),
            "championName": player.get("championName", ""),
            "win": blue_wins if is_blue else not blue_wins,
            "kills": final_stats["kills"],
            "deaths": final_stats["deaths"],
            "assists": final_stats["assists"],
            "firstBloodKill": fb,
            "totalMinionsKilled": final_stats["total_cs"],
            "detectorWardsPlaced": final_stats["control_wards_placed"] or 0,
            "challenges": {
                "damagePerMinute": final_stats["damage_per_minute"] or 0,
                "visionScorePerMinute": final_stats["vision_per_minute"] or 0,
                "teamDamagePercentage": (final_stats["team_dmg_percent"] or 0) / 100.0,
                "kda": final_stats["kda"] or 0
            }
        }
        
        # Merge ROFL stats if available
        rs = get_player_rofl_stats(name, tag, riot_id)
        if rs:
            p_v5["kills"] = rs["kills"]
            p_v5["deaths"] = rs["deaths"]
            p_v5["assists"] = rs["assists"]
            p_v5["challenges"]["damagePerMinute"] = rs["dpm"]
            p_v5["challenges"]["kda"] = rs["kda_ratio"]
            if rs["win"] is not None:
                p_v5["win"] = rs["win"]
            
            # Calculate team damage percentage properly since we now have real damage
            if is_blue and blue_total_dmg > 0:
                p_v5["challenges"]["teamDamagePercentage"] = rs["damage"] / blue_total_dmg
            elif not is_blue and red_total_dmg > 0:
                p_v5["challenges"]["teamDamagePercentage"] = rs["damage"] / red_total_dmg
        
        # Solo agregar totalDamageTaken si tenemos el dato (a veces disponible para el local player)
        if final_stats["total_damage_taken"]:
            p_v5["totalDamageTaken"] = final_stats["total_damage_taken"]
            
        participants_v5.append(p_v5)

    # ── Construir frames (Riot Match V5 format) ──────────────────────
    max_min = int(game_time_seconds // 60)
    frames_v5 = []
    for m in range(max_min + 1):
        minute_data = snapshot_buffer.get(m, {})
        p_frames = {}
        for player in players:
            name = player.get("riotIdGameName", player.get("summonerName", "?"))
            tag = player.get("riotIdTagLine", "")
            riot_id = f"{name}#{tag}" if tag else name
            pid = str(player_pid_map.get(riot_id, 0))
            
            snap = minute_data.get(riot_id, {})
            
            p_frame_data = {
                "minionsKilled": snap.get("cs") or 0,
            }
            # Solo añadir oro, xp o posicion si por algun motivo la API los devolvió
            if snap.get("gold"):
                p_frame_data["totalGold"] = snap["gold"]
            if snap.get("xp"):
                p_frame_data["xp"] = snap["xp"]
            if isinstance(snap.get("position"), dict) and snap["position"].get("x") is not None:
                p_frame_data["position"] = snap["position"]
                
            p_frames[pid] = p_frame_data

        frames_v5.append({
            "timestamp": m * 60 * 1000,
            "participantFrames": p_frames
        })

    # ── JSON final ────────────────────────────────────────────────────
    output = {
        "info": {
            "gameDuration": game_duration,
            "gameMode": game_info.get("gameMode", "CLASSIC"),
            "gameVersion": game_info.get("gameVersion", ""),
            "teams": teams_v5,
            "participants": participants_v5
        },
        "timeline": {
            "info": {
                "frames": frames_v5
            }
        }
    }

    return output


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        while True:
            filepath = run_collector()
            print("\n  [zZz] Esperando 5 segundos antes de buscar la siguiente partida...")
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n\n  [!] Captura cancelada por el usuario.")
        sys.exit(0)
    except Exception as e:
        print(f"\n  [✗] Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
