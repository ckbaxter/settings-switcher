# Bewusst mit '=' (nicht ':='): VERSION wird erst beim Verwenden gelesen, damit ein 'git pull' im selben
# Lauf die neue Version übernimmt.
VERSION = $(shell cat VERSION)

# Dienst: Wird hinter dem Ziel angegeben (make start recorder), Standard ist recorder. Editor und Recorder teilen
# sich Port und Containernamen, es läuft immer nur einer von beiden; start, stop, build und pull arbeiten deshalb
# mit genau einem Dienst. Die Namen sind leere Ziele, damit make sie als Wort hinter dem Ziel akzeptiert.
DIENSTE        := recorder editor
DIENST         := $(or $(filter $(DIENSTE),$(MAKECMDGOALS)),recorder)
PROFIL_recorder := record
PROFIL_editor   := editor
PROFIL          = $(PROFIL_$(DIENST))

define pruefe_dienst
@[ $(words $(filter $(DIENSTE),$(MAKECMDGOALS))) -le 1 ] \
	|| { echo "Fehler: Nur ein Dienst angeben (recorder oder editor)"; exit 1; }
endef

.DEFAULT_GOAL := help
.PHONY: help version test start stop build pull release $(DIENSTE)

$(DIENSTE): ; @:

# Hilfe: jedes Ziel mit einem "## Text" hinter dem Namen erscheint automatisch in "make help".
help: ## Diese Hilfe anzeigen
	@echo "Settings Switcher $(VERSION)"
	@echo ""
	@echo "Aufruf: make <Ziel> [Parameter]"
	@echo ""
	@echo "Ziele:"
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Parameter:"
	@echo "  V=X.Y.Z                      Version für 'make release' (optional). Ohne V gilt die Datei VERSION."
	@echo "  recorder | editor            Dienst für start, stop, build und pull, hinter dem Ziel angegeben (Standard: recorder)"
	@echo "                               recorder = Editor mit Live-Browser, editor = Editor ohne Browser"
	@echo "  SWITCHER_EDITOR_IMAGE        in der .env: Image des Editors (Standard: lokal gebaut, settings-switcher-editor)"
	@echo "  SWITCHER_RECORDER_IMAGE      in der .env: Image des Recorders (Standard: lokal gebaut, settings-switcher-recorder)"
	@echo ""
	@echo "Beispiele:"
	@echo "  make test                    Tests ausführen"
	@echo "  make start recorder          Recorder starten (Editor mit Live-Browser; Image wird bei Bedarf gebaut oder geholt)"
	@echo "  make stop recorder           Recorder beenden und den Container entfernen"
	@echo "  make start editor            Editor ohne Browser starten (stop und die anderen Ziele ebenso)"
	@echo "  make build recorder          Image lokal neu bauen (das Runner-Image baut run.sh selbst)"
	@echo "  make pull recorder           veröffentlichtes Image holen (vorher SWITCHER_RECORDER_IMAGE in der .env setzen, docs/betrieb.md)"
	@echo "  make release                 Release mit der Version aus der Datei VERSION (Tag vX.Y.Z daraus)"
	@echo "  make release V=1.1.0         Release 1.1.0: setzt VERSION selbst (Ablauf und Voraussetzungen: docs/betrieb.md)"

version: ## Aktuelle Version aus der Datei VERSION ausgeben
	@echo $(VERSION)

# Braucht pytest, httpx und Chromium für Playwright (requirements-dev.txt, python3 -m playwright install chromium)
test: ## Tests ausführen (pytest)
	python3 -m pytest

# Dienst starten bzw. beenden. Fehlt das Image, baut docker compose es lokal (oder holt es, wenn in der .env ein
# Registry-Name steht). Nach einem Update vorher 'make build' oder 'make pull'. Port und Token stehen in der .env.
start: ## Dienst starten: make start [recorder|editor] (Standard: recorder)
	$(pruefe_dienst)
	docker compose --profile $(PROFIL) up -d

stop: ## Dienst beenden: make stop [recorder|editor] (Standard: recorder)
	$(pruefe_dienst)
	docker compose --profile $(PROFIL) down

# Das Runner-Image braucht kein Make-Ziel: run.sh baut es selbst, wenn es fehlt oder sich die Quellen geändert haben
# (./run.sh --build <profil> erzwingt einen Neubau).
build: ## Image lokal bauen: make build [recorder|editor] (Standard: recorder)
	$(pruefe_dienst)
	docker compose --profile $(PROFIL) build

# Holt das Image, das in der .env unter SWITCHER_RECORDER_IMAGE bzw. SWITCHER_EDITOR_IMAGE steht
# (z. B. ghcr.io/<owner>/settings-switcher-recorder:latest; bei privatem Paket vorher: docker login ghcr.io).
# Ohne diese Variable würde compose den lokalen Namen bei Docker Hub suchen und scheitern.
pull: ## Image aus der GitHub Container Registry holen: make pull [recorder|editor] (Standard: recorder)
	$(pruefe_dienst)
	docker compose --profile $(PROFIL) pull

# Release: prüft die Voraussetzungen, holt vorher mit "git pull --ff-only" den Stand von origin/main,
# setzt den annotierten Tag vX.Y.Z und pusht Branch und Tag.
# VERSION wird erst nach dem Pull gelesen (die Make-Variable VERSION oben ist beim Start bereits eingelesen).
# Die Version ist V, falls angegeben (dann wird VERSION darauf gesetzt), sonst der Inhalt von VERSION.
# Den CHANGELOG schreibt das Ziel nur um, wenn dort noch kein Abschnitt "## [X.Y.Z]" steht.
# Den Tag-Push baut der GitHub-Workflow zu den Images X.Y.Z (und latest).
# V kommt über die Umgebung ($$V), nicht in den Shell-Text.
release: export V := $(V)
release: ## Release erstellen: make release [V=X.Y.Z] (ohne V: Version aus der Datei VERSION)
	@set -eu; \
	[ "$$(git rev-parse --abbrev-ref HEAD)" = "main" ] \
		|| { echo "Fehler: Releases werden nur auf dem Branch main erstellt"; exit 1; }; \
	[ -z "$$(git status --porcelain)" ] \
		|| { echo "Fehler: Der Arbeitsbaum hat uncommittete Änderungen (git status)"; exit 1; }; \
	before="$$(git rev-parse HEAD)"; \
	git pull --ff-only --quiet --tags origin main \
		|| { echo "Fehler: git pull --ff-only origin main ist nicht möglich (lokale Commits, die nicht auf origin/main liegen, oder keine Verbindung)"; exit 1; }; \
	[ "$$(git rev-parse HEAD)" = "$$before" ] \
		|| echo "main per git pull aktualisiert: $$(git rev-parse --short "$$before")..$$(git rev-parse --short HEAD)"; \
	cur="$$(cat VERSION)"; new="$${V:-$$cur}"; \
	if [ -n "$$V" ]; then src="Parameter V"; else src="Datei VERSION"; fi; \
	echo "$$new" | grep -Eq '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$$' \
		|| { echo "Fehler: '$$new' ($$src) ist keine Version der Form X.Y.Z"; exit 1; }; \
	[ "$$(printf '%s\n%s\n' "$$cur" "$$new" | sort -V | tail -n 1)" = "$$new" ] \
		|| { echo "Fehler: $$new ist niedriger als die Datei VERSION ($$cur)"; exit 1; }; \
	! git rev-parse -q --verify "refs/tags/v$$new" >/dev/null \
		|| { echo "Fehler: Der Tag v$$new existiert schon (Version in VERSION erhöhen oder V angeben)"; exit 1; }; \
	last="$$(git tag -l 'v[0-9]*' | sed 's/^v//' | sort -V | tail -n 1)"; \
	if [ -n "$$last" ] && [ "$$(printf '%s\n%s\n' "$$last" "$$new" | sort -V | tail -n 1)" != "$$new" ]; then \
		echo "Fehler: $$new ist nicht höher als der letzte Tag v$$last"; exit 1; \
	fi; \
	grep -q '^## \[Unreleased\]' CHANGELOG.md \
		|| { echo "Fehler: CHANGELOG.md hat keinen Abschnitt '## [Unreleased]'"; exit 1; }; \
	if grep -q "^## \[$$new\]" CHANGELOG.md; then rewrite=0; else \
		awk '/^## \[Unreleased\]/ {f=1; next} /^## \[/ {f=0} f && /^- / {n++} END {exit n ? 0 : 1}' CHANGELOG.md \
			|| { echo "Fehler: Unter '## [Unreleased]' im CHANGELOG.md steht kein Eintrag"; exit 1; }; \
		rewrite=1; \
	fi; \
	echo "Release v$$new (Version aus: $$src; aktuelle Datei VERSION: $$cur)"; \
	echo "$$new" > VERSION; \
	if [ "$$rewrite" = 1 ]; then \
		awk -v v="$$new" -v d="$$(date +%F)" \
			'/^## \[Unreleased\]/ && !done {print; print ""; print "## [" v "] - " d; done=1; next} {print}' \
			CHANGELOG.md > CHANGELOG.md.tmp; \
		mv CHANGELOG.md.tmp CHANGELOG.md; \
	fi; \
	git add VERSION CHANGELOG.md; \
	committed=0; \
	if ! git diff --cached --quiet; then git commit -q -m "Settings Switcher $$new"; committed=1; fi; \
	git tag -a "v$$new" -m "Settings Switcher $$new"; \
	git push --follow-tags origin main \
		|| { if [ "$$committed" = 1 ]; then undo="git tag -d v$$new && git reset --hard HEAD~1"; else undo="git tag -d v$$new"; fi; \
			echo "Fehler beim Push. Lokal sind der Tag v$$new und gegebenenfalls der Release-Commit angelegt. Zurücknehmen: $$undo"; exit 1; }; \
	echo "Release v$$new gepusht. Workflow-Lauf abwarten (veröffentlicht $$new und latest), danach auf dem Host: make pull"
