#!/usr/bin/env bash
# Startet für ein Profil einen frischen, gehärteten Runner-Container,
# führt das Profil aus und entfernt den Container danach wieder.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${SWITCHER_IMAGE:-settings-switcher-runner}"
ENV_FILE="${SWITCHER_ENV_FILE:-$DIR/runner.env}"

usage() {
  cat <<EOF
Aufruf: $(basename "$0") [Optionen] <profil>

  -l, --list         vorhandene Profile anzeigen
  -b, --build        Runner-Image neu bauen (sonst nur bei fehlendem Image oder geänderten Quellen)
  -s, --screenshots  Screenshot nach jedem Schritt (sonst nur bei Fehlern)
  -r, --retries <n>  bei Exit 1 den ganzen Lauf bis zu n-mal wiederholen (0-5, Standard 0;
                     oder SWITCHER_RETRIES in der Shell). Pause: SWITCHER_RETRY_DELAY_S (Standard 15)
  -h, --help         diese Hilfe

Exit-Codes: 0 = erfolgreich, 1 = Lauf fehlgeschlagen, 2 = Aufruf-/Konfigurationsfehler
EOF
}

die() {
  echo "FEHLER: $*" >&2
  exit 2
}

build=0
screenshots=0
retries="${SWITCHER_RETRIES:-0}"
profile=""

while (($#)); do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    -l | --list)
      shopt -s nullglob
      for f in "$DIR"/profiles/*.json; do basename "$f" .json; done
      exit 0
      ;;
    -b | --build) build=1 ;;
    -s | --screenshots) screenshots=1 ;;
    -r | --retries)
      (($# >= 2)) || die "$1 braucht eine Zahl."
      retries="$2"
      shift
      ;;
    -*) usage >&2; die "Unbekannte Option: $1" ;;
    *)
      [[ -z "$profile" ]] || die "Nur ein Profil pro Aufruf."
      profile="$1"
      ;;
  esac
  shift
done

[[ -n "$profile" ]] || { usage >&2; exit 2; }
[[ "$profile" =~ ^[a-z0-9][a-z0-9_-]{0,63}$ ]] || die "Ungültiger Profilname: $profile"

retry_delay="${SWITCHER_RETRY_DELAY_S:-15}"
[[ "$retries" =~ ^[0-5]$ ]] || die "Wiederholungen (-r / SWITCHER_RETRIES) müssen eine Zahl von 0 bis 5 sein."
[[ "$retry_delay" =~ ^[0-9]{1,3}$ ]] && ((retry_delay <= 300)) \
  || die "SWITCHER_RETRY_DELAY_S muss eine Zahl von 0 bis 300 sein."
[[ -f "$DIR/profiles/$profile.json" ]] || die "Profil nicht gefunden: profiles/$profile.json"
[[ -f "$ENV_FILE" ]] || die "$ENV_FILE fehlt (cp runner.env.example runner.env und ausfüllen)."

mode="$(stat -c '%a' "$ENV_FILE")"
[[ "${mode: -2}" == "00" ]] || die "$ENV_FILE ist für Gruppe/Andere lesbar ($mode). Bitte: chmod 600 $ENV_FILE"

# Nur ein Lauf gleichzeitig
exec 9>"$DIR/.run.lock"
flock -n 9 || die "Es läuft bereits ein Lauf."

# Prüfsumme über alles, was ins Runner-Image kopiert wird (siehe runner/Dockerfile).
# Sie steht als Label am Image; weicht sie ab, wird das Image automatisch neu gebaut.
source_hash() {
  (
    cd "$DIR"
    {
      printf '%s\0' runner/Dockerfile runner/requirements.txt runner/runner.py
      find shared -type f ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 | LC_ALL=C sort -z
    } | xargs -0 sha256sum | sha256sum | cut -d' ' -f1
  )
}

src_hash="$(source_hash)"
image_hash="$(docker image inspect --format '{{ index .Config.Labels "ss.source-hash" }}' "$IMAGE" 2>/dev/null || true)"

if ((build)) || [[ "$image_hash" != "$src_hash" ]]; then
  if ((build)); then
    echo "Baue Image $IMAGE (angefordert) ..."
  elif [[ -z "$image_hash" ]]; then
    echo "Baue Image $IMAGE (noch nicht vorhanden oder ohne Prüfsumme) ..."
  else
    echo "Baue Image $IMAGE (Quellen haben sich geändert) ..."
  fi
  docker build -q --label "ss.source-hash=$src_hash" -f "$DIR/runner/Dockerfile" -t "$IMAGE" "$DIR" >/dev/null \
    || die "Image-Build fehlgeschlagen."
fi

extra=()
[[ -z "${SWITCHER_DOCKER_NETWORK:-}" ]] || extra+=(--network "$SWITCHER_DOCKER_NETWORK")
((screenshots)) && extra+=(-e SWITCHER_SCREENSHOTS=all)

mkdir -p "$DIR/artifacts"

run_once() {
  docker run --rm --init \
    --name "ss-run-${profile}-$$" \
    --user "$(id -u):$(id -g)" \
    --read-only --tmpfs /tmp:rw,size=256m \
    --cap-drop ALL --security-opt no-new-privileges \
    --pids-limit 512 --memory 1g --shm-size 256m \
    --env-file "$ENV_FILE" \
    -v "$DIR/profiles:/profiles:ro" \
    -v "$DIR/artifacts:/artifacts" \
    ${extra[@]+"${extra[@]}"} \
    "$IMAGE" "$profile"
}

# Jeder Versuch ist ein kompletter Lauf in einem frischen Container (neuer Browser, neuer Login).
# Wiederholt wird nur bei Exit 1 (Schritt oder Prüfung fehlgeschlagen). Exit 2 (Konfiguration) und
# Docker-Fehler (>= 125) sind keine Zufallsfehler, danach wird nicht erneut gestartet. Der Lock bleibt
# über alle Versuche gehalten.
attempts=$((retries + 1))
attempt=1
while true; do
  ((attempts == 1)) || echo "=== Versuch $attempt von $attempts ==="
  set +e
  run_once
  rc=$?
  set -e

  if ((rc >= 125)); then
    echo "FEHLER: Docker konnte den Container nicht starten oder wurde abgebrochen (Exit $rc)." >&2
  fi
  ((rc == 1 && attempt < attempts)) || break
  echo "Versuch $attempt fehlgeschlagen, neuer Versuch in ${retry_delay}s ..." >&2
  sleep "$retry_delay"
  attempt=$((attempt + 1))
done

if ((rc == 1 && attempts > 1)); then
  echo "FEHLER: Lauf nach $attempts Versuchen fehlgeschlagen." >&2
fi
exit "$rc"
