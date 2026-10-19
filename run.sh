#!/usr/bin/env bash
# Startet für ein Profil einen frischen, gehärteten Runner-Container,
# führt das Profil aus und entfernt den Container danach wieder.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${SS_IMAGE:-settings-switcher-runner}"
ENV_FILE="${SS_ENV_FILE:-$DIR/runner.env}"

usage() {
  cat <<EOF
Aufruf: $(basename "$0") [Optionen] <profil>

  -l, --list         vorhandene Profile anzeigen
  -b, --build        Runner-Image (neu) bauen
  -s, --screenshots  Screenshot nach jedem Schritt (sonst nur bei Fehlern)
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
[[ -f "$DIR/profiles/$profile.json" ]] || die "Profil nicht gefunden: profiles/$profile.json"
[[ -f "$ENV_FILE" ]] || die "$ENV_FILE fehlt (cp runner.env.example runner.env und ausfüllen)."

mode="$(stat -c '%a' "$ENV_FILE")"
[[ "${mode: -2}" == "00" ]] || die "$ENV_FILE ist für Gruppe/Andere lesbar ($mode). Bitte: chmod 600 $ENV_FILE"

# Nur ein Lauf gleichzeitig
exec 9>"$DIR/.run.lock"
flock -n 9 || die "Es läuft bereits ein Lauf."

if ((build)) || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Baue Image $IMAGE ..."
  docker build -q -f "$DIR/runner/Dockerfile" -t "$IMAGE" "$DIR" >/dev/null
fi

extra=()
[[ -z "${SS_DOCKER_NETWORK:-}" ]] || extra+=(--network "$SS_DOCKER_NETWORK")
((screenshots)) && extra+=(-e SS_SCREENSHOTS=all)

mkdir -p "$DIR/artifacts"

set +e
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
rc=$?
set -e

if ((rc >= 125)); then
  echo "FEHLER: Docker konnte den Container nicht starten oder wurde abgebrochen (Exit $rc)." >&2
fi
exit "$rc"
