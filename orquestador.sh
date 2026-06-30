#!/usr/bin/env bash
# ============================================================================
# Orquestador del proyecto Anki-MIR
# ============================================================================
# Script que coordina todos los pasos del pipeline:
#   1. Crawling de documentación médica
#   2. Conversión de exámenes MIR originales a PDFs fusionados
#   3. Extracción de preguntas MIR a JSONL
#   4. Generación de preguntas desde documentación médica vía DeepSeek
#   5. Conversión de JSONL a mazo .apkg para Anki
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON="python3"
ACTIVATE="$VENV_DIR/bin/activate"

# ─── Colores ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# ─── Funciones auxiliares ────────────────────────────────────────────────────

check_venv() {
    if [ ! -f "$ACTIVATE" ]; then
        echo -e "${YELLOW}⚠  Entorno virtual no encontrado. Creándolo...${NC}"
        $PYTHON -m venv "$VENV_DIR"
        echo -e "${GREEN}✓ Entorno virtual creado en $VENV_DIR${NC}"
    fi
    source "$ACTIVATE"
}

check_deps() {
    echo -e "${BLUE}📦 Instalando dependencias...${NC}"
    pip install -q -r requirements.txt
    # Dependencias adicionales para generación LLM
    pip install -q openai tiktoken python-dotenv 2>/dev/null || true
    # Dependencia para conversión a Anki
    pip install -q genanki 2>/dev/null || true
    echo -e "${GREEN}✓ Dependencias instaladas${NC}"
}

check_env() {
    if [ ! -f ".env" ]; then
        echo -e "${RED}✗ No se encuentra el archivo .env con DEEPSEEK_API_KEY${NC}"
        echo -e "   Crea un archivo .env con:"
        echo -e "   ${BOLD}DEEPSEEK_API_KEY=tu-api-key${NC}"
        exit 1
    fi
    # shellcheck source=/dev/null
    source .env
    if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
        echo -e "${RED}✗ DEEPSEEK_API_KEY no está definida en .env${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ API Key encontrada${NC}"
}

print_banner() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════╗"
    echo "║         🏥  MIR-ANKI  ·  Pipeline completo      ║"
    echo "║  Exámenes MIR → Flashcards → DeepSeek           ║"
    echo "╚══════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_menu() {
    echo ""
    echo -e "${BOLD}Selecciona una opción:${NC}"
    echo "  ┌─────────────────────────────────────────────────────┐"
    echo "  │  ${BOLD}1${NC}  Crawlear documentación médica (NICE, MSD, etc.) │"
    echo "  │  ${BOLD}2${NC}  Convertir exámenes MIR originales a PDF       │"
    echo "  │  ${BOLD}3${NC}  Extraer preguntas MIR de PDFs a JSONL        │"
    echo "  │  ${BOLD}4${NC}  Generar preguntas desde docs médicos (LLM)   │"
    echo "  │  ${BOLD}5${NC}  Convertir JSONL a mazo .apkg para Anki       │"
    echo "  │  ${BOLD}6${NC}  Ejecutar TODO el pipeline                     │"
    echo "  │  ${BOLD}0${NC}  Salir                                         │"
    echo "  └─────────────────────────────────────────────────────┘"
    echo ""
    read -rp "Opción: " OPT
    echo ""
}

# ─── Pasos del pipeline ──────────────────────────────────────────────────────

step_crawl() {
    echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  1. Crawleando documentación médica         ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
    python3 src/crawl_docs.py "$@"
}

step_convert() {
    echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  2. Convirtiendo exámenes MIR a PDF         ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
    python3 src/convert_mir_to_pdf.py "$@"
}

step_extract() {
    echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  3. Extrayendo preguntas MIR a JSONL        ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
    python3 src/extract_preguntas.py "$@"
}

step_generate() {
    echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  4. Generando preguntas con DeepSeek (LLM)  ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
    check_env
    python3 src/generate_preguntas_llm.py "$@"
}

step_anki() {
    echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  5. Convirtiendo JSONL a mazo .apkg         ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
    python3 src/convert_to_anki.py "$@"
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    print_banner
    check_venv
    check_deps

    # Si hay argumentos de línea de comandos, ejecutar paso directo
    if [ $# -gt 0 ]; then
        case "$1" in
            crawl)    shift; step_crawl "$@";;
            convert)  shift; step_convert "$@";;
            extract)  shift; step_extract "$@";;
            generate) shift; step_generate "$@";;
            anki)     shift; step_anki "$@";;
            all)      shift
                     step_crawl "$@"
                     step_convert "$@"
                     step_extract "$@"
                     step_generate "$@"
                     step_anki "$@"
                     ;;
            *)
                echo -e "${RED}Uso: $0 {crawl|convert|extract|generate|anki|all} [opciones]${NC}"
                exit 1
                ;;
        esac
        exit 0
    fi

    # Menú interactivo
    while true; do
        print_menu
        case "$OPT" in
            1) step_crawl;;
            2) step_convert;;
            3) step_extract;;
            4) step_generate;;
            5) step_anki;;
            6)
                step_crawl
                step_convert
                step_extract
                step_generate
                step_anki
                echo -e "${GREEN}${BOLD}✅ Pipeline completo ejecutado.${NC}"
                ;;
            0)
                echo -e "${GREEN}¡Hasta luego!${NC}"
                exit 0
                ;;
            *) echo -e "${RED}Opción no válida${NC}";;
        esac
        echo ""
        read -rp "Presiona Enter para continuar..."
    done
}

main "$@"
