#!/usr/bin/env python3
"""
Genera preguntas médicas tipo test desde PDFs de documentación médica
 usando DeepSeek (API compatible con OpenAI).

Proceso:
  1. Escanea docs/ (excluyendo examen_mir) buscando PDFs
  2. Extrae texto de cada PDF con pypdf
  3. Divide el texto en chunks con ventana deslizante (sliding window)
  4. Para cada chunk, llama a DeepSeek para generar una pregunta tipo test
  5. Guarda las preguntas en data/preguntas_medicas.jsonl

Resume automáticamente: si se interrumpe, no reprocesa lo ya generado.

Uso:
  python3 src/generate_preguntas_llm.py
  python3 src/generate_preguntas_llm.py --max-pdfs 5          # Solo 5 PDFs
  python3 src/generate_preguntas_llm.py --dry-run              # Solo listar PDFs
  python3 src/generate_preguntas_llm.py --reset                # Ignorar progreso
"""

import os
import re
import json
import time
import hashlib
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import tiktoken
from pypdf import PdfReader
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Configuración ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "docs"
EXCLUDE_DIRS = {"examen_mir"}
OUTPUT_FILE = BASE_DIR / "data" / "preguntas_medicas.jsonl"
STATE_FILE = BASE_DIR / "data" / ".generation_state.json"
MIR_EXAMPLES_FILE = BASE_DIR / "data" / "preguntas_mir.jsonl"

# Cuántos ejemplos de MIR incluir como few-shot en el prompt
FEW_SHOT_COUNT = 3

# DeepSeek
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    # Intentar leer desde .env
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    DEEPSEEK_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = "deepseek-chat"  # deepseek-v4-pro se puede mapear a deepseek-chat

# Parámetros de chunking
CHUNK_SIZE = 1500      # tokens por chunk
CHUNK_OVERLAP = 300    # tokens de solapamiento

# Parámetros de rate limiting
DELAY_BETWEEN_CALLS = 1.5   # segundos entre llamadas API
MAX_RETRIES = 3
BASE_RETRY_DELAY = 5        # segundos para backoff exponencial

# Límite de caracteres mínimos para un chunk válido
MIN_CHUNK_CHARS = 200

# ─── Carga de ejemplos few-shot desde MIR ────────────────────────────────────

def load_mir_examples(count: int = FEW_SHOT_COUNT) -> str:
    """
    Carga ejemplos de preguntas reales del MIR desde preguntas_mir.jsonl
    para usarlos como few-shot learning. Excluye imágenes (solo texto).
    Retorna un string formateado con los ejemplos.
    """
    if not MIR_EXAMPLES_FILE.exists():
        log.warning("  ⚠ No se encontró preguntas_mir.jsonl para few-shot examples")
        return ""

    examples = []
    # Leer todas y seleccionar algunas variadas (sin imágenes)
    all_no_img = []
    with open(MIR_EXAMPLES_FILE) as f:
        for line in f:
            try:
                obj = json.loads(line)
                if "imagen" not in obj or not obj.get("imagen"):
                    # Clonar sin imagen por si acaso
                    clean = {k: v for k, v in obj.items() if k != "imagen"}
                    all_no_img.append(clean)
            except json.JSONDecodeError:
                continue

    # Tomar algunas del principio, medio y final para variar
    if len(all_no_img) >= count:
        step = len(all_no_img) // count
        indices = [i * step for i in range(count)]
        examples = [all_no_img[i] for i in indices[:count]]
    else:
        examples = all_no_img[:count]

    if not examples:
        return ""

    lines = ["Aquí tienes ejemplos de preguntas reales del examen MIR. IMITA ESTE ESTILO, FORMATO Y NIVEL DE DIFICULTAD:\n"]
    for i, ex in enumerate(examples, 1):
        lines.append(f"--- EJEMPLO MIR {i} ---")
        lines.append(f"Pregunta: {ex['pregunta']}")
        for j in range(1, 5):
            lines.append(f"Opción {j}: {ex[f'opcion_{j}']}")
        lines.append(f"Respuesta correcta: {ex['respuesta_correcta']}")
        lines.append("")

    return "\n".join(lines)


# ─── Prompt para DeepSeek ─────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """Eres un profesor de medicina que crea preguntas de examen tipo test para el MIR español.

Genera UNA pregunta tipo test con 4 opciones basada ESTRICTAMENTE en el texto proporcionado.
La pregunta debe ser clínicamente relevante y estar claramente respondida por el contenido.

{few_shot}

REGLAS:
1. La pregunta debe poder responderse únicamente con la información del texto dado.
2. Las 4 opciones deben ser plausibles pero solo una correcta.
3. Usa terminología médica precisa en español.
4. No incluyas "Todas las anteriores" ni "Ninguna de las anteriores".
5. La respuesta correcta debe ser la opción 1, 2, 3 o 4.
6. Responde SOLO con un objeto JSON válido, sin explicaciones ni markdown.
7. Si el texto no contiene suficiente información médica para generar una pregunta, responde con {{"skip": true}}.

Formato JSON requerido:
{{
  "pregunta": "texto de la pregunta",
  "opcion_1": "primera opción",
  "opcion_2": "segunda opción",
  "opcion_3": "tercera opción",
  "opcion_4": "cuarta opción",
  "respuesta_correcta": 1,
  "skip": false
}}"""

USER_PROMPT_TEMPLATE = """Aquí tienes un fragmento de un documento médico. Genera una pregunta tipo test MIR basada en este contenido. La pregunta debe tener el MISMO ESTILO que los ejemplos de MIR que te mostré:

--- INICIO DEL TEXTO ---
{chunk_text}
--- FIN DEL TEXTO ---

IMPORTANTE: La respuesta debe poder deducirse directamente del texto anterior."""


# ─── Utilidades ───────────────────────────────────────────────────────────────

def count_tokens(text: str, model: str = "gpt-4") -> int:
    """Cuenta tokens aproximados usando tiktoken."""
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def chunk_text(text: str, chunk_size=None, overlap=None):
    if chunk_size is None:
        chunk_size = CHUNK_SIZE
    if overlap is None:
        overlap = CHUNK_OVERLAP
    """
    Divide el texto en chunks con solapamiento (sliding window).
    Cada chunk tiene aproximadamente `chunk_size` tokens.
    """
    if not text or len(text.strip()) < MIN_CHUNK_CHARS:
        return []

    try:
        enc = tiktoken.encoding_for_model("gpt-4")
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")

    tokens = enc.encode(text)
    chunks = []
    start = 0

    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        # Si no es el primer chunk y estamos en medio de una palabra,
        # retroceder hasta encontrar un espacio (para no partir palabras)
        chunk_tokens = tokens[start:end]
        chunk_text = enc.decode(chunk_tokens)

        if len(chunk_text.strip()) >= MIN_CHUNK_CHARS:
            chunks.append(chunk_text)

        # Avanzar la ventana
        if end >= len(tokens):
            break
        start += chunk_size - overlap

    return chunks


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extrae texto de un PDF."""
    try:
        reader = PdfReader(pdf_path)
        text_parts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
        return "\n".join(text_parts)
    except Exception as e:
        log.warning(f"  ⚠ Error extrayendo texto de {pdf_path.name}: {e}")
        return ""


def pdf_fingerprint(pdf_path: Path) -> str:
    """Hash del PDF para identificar si cambió entre ejecuciones."""
    try:
        h = hashlib.sha256()
        with open(pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:
        return ""


def find_pdfs(docs_dir: Path, exclude_dirs: set) -> list[Path]:
    """Encuentra todos los PDFs recursivamente, excluyendo directorios."""
    pdfs = []
    for root, dirs, files in os.walk(docs_dir):
        # Excluir directorios
        rel = Path(root).relative_to(docs_dir)
        parts = set(rel.parts)
        if parts & exclude_dirs:
            continue
        for f in sorted(files):
            if f.lower().endswith(".pdf"):
                pdfs.append(Path(root) / f)
    return sorted(pdfs)


def source_name(pdf_path: Path) -> str:
    """Nombre legible de la fuente: 'nice/breast-cancer' o 'msd-manual/infections/fever'."""
    rel = pdf_path.relative_to(DOCS_DIR)
    return str(rel.with_suffix(""))


# ─── Estado de progreso (resume) ──────────────────────────────────────────────

def load_state() -> dict:
    """Carga el estado de progreso desde STATE_FILE."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"processed_files": {}, "generated_count": 0}


def save_state(state: dict):
    """Guarda el estado de progreso."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_existing_output() -> set:
    """Carga las fuentes ya procesadas desde el archivo de salida."""
    processed = set()
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        if "fuente" in entry:
                            processed.add(entry["fuente"])
                    except json.JSONDecodeError:
                        continue
    return processed


# ─── Interacción con DeepSeek ─────────────────────────────────────────────────

def call_deepseek(chunk_text: str, pdf_name: str, chunk_idx: int, total_chunks: int, few_shot: str = "") -> Optional[dict]:
    """
    Llama a DeepSeek para generar una pregunta a partir del chunk.
    Retorna el dict con la pregunta o None si hay que saltar.
    """
    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
    )

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(few_shot=few_shot)
    user_prompt = USER_PROMPT_TEMPLATE.format(chunk_text=chunk_text)

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=500,
                timeout=60,
            )

            content = resp.choices[0].message.content.strip()

            # Limpiar posibles marcadores markdown
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            content = content.strip()

            data = json.loads(content)

            if data.get("skip"):
                return None

            # Validar campos requeridos
            required = ["pregunta", "opcion_1", "opcion_2", "opcion_3", "opcion_4", "respuesta_correcta"]
            if not all(k in data for k in required):
                log.warning(f"  ⚠ Campos incompletos en respuesta, reintentando...")
                time.sleep(BASE_RETRY_DELAY)
                continue

            if not isinstance(data["respuesta_correcta"], int) or data["respuesta_correcta"] not in [1, 2, 3, 4]:
                log.warning(f"  ⚠ respuesta_correcta inválida, reintentando...")
                time.sleep(BASE_RETRY_DELAY)
                continue

            return {
                "pregunta": data["pregunta"],
                "opcion_1": data["opcion_1"],
                "opcion_2": data["opcion_2"],
                "opcion_3": data["opcion_3"],
                "opcion_4": data["opcion_4"],
                "respuesta_correcta": data["respuesta_correcta"],
            }

        except json.JSONDecodeError as e:
            log.warning(f"  ⚠ Error decodificando JSON (intento {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(BASE_RETRY_DELAY * (2 ** attempt))
        except Exception as e:
            log.warning(f"  ⚠ Error API (intento {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(BASE_RETRY_DELAY * (2 ** attempt))

    log.error(f"  ✗ Fallaron todos los intentos para chunk {chunk_idx + 1}/{total_chunks}")
    return None


# ─── Procesamiento principal ──────────────────────────────────────────────────

def process_pdf(pdf_path: Path, state: dict, dry_run: bool = False, few_shot: str = "") -> int:
    """
    Procesa un solo PDF: extrae texto, chunkea y genera preguntas.
    Retorna el número de preguntas generadas.
    """
    pdf_name = source_name(pdf_path)
    fp = pdf_fingerprint(pdf_path)

    log.info(f"\n{'─'*55}")
    log.info(f"  PDF: {pdf_name}")
    log.info(f"{'─'*55}")

    # Verificar si ya se procesó (resume)
    prev_state = state["processed_files"].get(pdf_name, {})
    if prev_state.get("fingerprint") == fp:
        prev_count = prev_state.get("questions", 0)
        log.info(f"  ✓ Ya procesado ({prev_count} preguntas). Saltando.")
        return 0

    # Extraer texto
    log.info(f"  Extrayendo texto...")
    text = extract_text_from_pdf(pdf_path)
    if not text:
        log.warning(f"  ⚠ No se pudo extraer texto.")
        return 0

    log.info(f"  Texto extraído: {len(text):,} caracteres")

    # Chunkear
    chunks = chunk_text(text)
    log.info(f"  Chunks generados: {len(chunks)}")

    if not chunks:
        log.warning(f"  ⚠ No hay chunks válidos.")
        return 0

    if dry_run:
        log.info(f"  [DRY-RUN] Se generarían ~{len(chunks)} preguntas")
        # Mostrar preview de los chunks
        for i, ch in enumerate(chunks[:3]):
            log.info(f"    Chunk {i + 1}: {ch[:100]}...")
        if len(chunks) > 3:
            log.info(f"    ... y {len(chunks) - 3} chunks más")
        return 0

    # Procesar cada chunk
    questions_generated = 0
    total_chunks = len(chunks)

    for idx, chunk in enumerate(chunks):
        log.info(f"  → Chunk {idx + 1}/{total_chunks} ({count_tokens(chunk)} tokens)")

        # Verificar si este chunk ya se procesó (por si el PDF estaba parcial)
        chunk_key = hashlib.md5(chunk.encode()).hexdigest()[:8]
        if prev_state.get("chunks_done") and chunk_key in prev_state["chunks_done"]:
            questions_generated += 1
            log.info(f"     ✓ Chunk ya procesado")
            continue

        result = call_deepseek(chunk, pdf_name, idx, total_chunks, few_shot=few_shot)

        if result is None:
            log.info(f"     - Sin pregunta (texto insuficiente o skip)")
        else:
            # Añadir metadatos al estilo del JSONL de preguntas_mir
            entry = {
                **result,
                "origen": "doc_medico",
                "fuente": pdf_name,
                "texto_referencia": chunk[:500],  # snippet del chunk como referencia
                "year": None,
                "num_pregunta": None,
                "imagen": None,
            }

            # Escribir al JSONL
            with open(OUTPUT_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            questions_generated += 1
            log.info(f"     ✓ Pregunta generada")

            # Pequeña pausa entre chunks para rate limiting
            if idx < total_chunks - 1:
                time.sleep(DELAY_BETWEEN_CALLS)

        # Actualizar estado cada chunk
        if "chunks_done" not in prev_state:
            prev_state["chunks_done"] = []
        prev_state["chunks_done"].append(chunk_key)
        state["generated_count"] = state.get("generated_count", 0) + 1

        # Guardar estado cada 5 chunks por si se interrumpe
        if (idx + 1) % 5 == 0:
            prev_state["questions"] = questions_generated
            state["processed_files"][pdf_name] = prev_state
            save_state(state)

    # Guardar estado final del PDF
    prev_state["fingerprint"] = fp
    prev_state["questions"] = questions_generated
    if "chunks_done" in prev_state:
        del prev_state["chunks_done"]  # ya no necesario
    state["processed_files"][pdf_name] = prev_state
    save_state(state)

    log.info(f"  ✓ Hecho: {questions_generated} preguntas generadas")
    return questions_generated


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Genera preguntas médicas desde PDFs usando DeepSeek"
    )
    parser.add_argument("--max-pdfs", type=int, default=0,
                        help="Máximo de PDFs a procesar (0 = todos)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo listar PDFs y mostrar chunks, sin llamar API")
    parser.add_argument("--reset", action="store_true",
                        help="Ignorar progreso anterior y empezar de nuevo")
    parser.add_argument("--chunk-size", type=int, default=None,
                        help="Tamaño de chunk en tokens")
    parser.add_argument("--overlap", type=int, default=None,
                        help="Solapamiento en tokens")
    args = parser.parse_args()

    print("=" * 60)
    print("  GENERADOR DE PREGUNTAS MÉDICAS (DeepSeek)")
    print("=" * 60)

    # Validar API key
    if not DEEPSEEK_API_KEY:
        log.error("✗ DEEPSEEK_API_KEY no encontrada. Configúrala en .env o variable de entorno.")
        return

    # Sobrescribir parámetros de chunking si se pasaron
    cfg_chunk_size = CHUNK_SIZE
    cfg_chunk_overlap = CHUNK_OVERLAP
    if args.chunk_size is not None:
        cfg_chunk_size = args.chunk_size
    if args.overlap is not None:
        cfg_chunk_overlap = args.overlap

    log.info(f"  API Key: {'✓' if DEEPSEEK_API_KEY else '✗'} {DEEPSEEK_API_KEY[:8]}...")
    log.info(f"  Base URL: {DEEPSEEK_BASE_URL}")
    log.info(f"  Modelo: {DEEPSEEK_MODEL}")
    log.info(f"  Chunk size: {cfg_chunk_size} tokens, Overlap: {cfg_chunk_overlap} tokens")

    # Encontrar PDFs
    pdfs = find_pdfs(DOCS_DIR, EXCLUDE_DIRS)
    log.info(f"  PDFs encontrados: {len(pdfs)}")

    if not pdfs:
        log.warning("  ⚠ No se encontraron PDFs para procesar.")
        return

    # Cargar estado
    state = {} if args.reset else load_state()
    if "processed_files" not in state:
        state["processed_files"] = {}
    if "generated_count" not in state:
        state["generated_count"] = 0

    if args.dry_run:
        log.info("\n  [DRY-RUN] PDFs a procesar:")
        for pdf in pdfs:
            s = source_name(pdf)
            fp = pdf_fingerprint(pdf)
            status = state["processed_files"].get(s, {})
            if status.get("fingerprint") == fp:
                log.info(f"    ✓ {s} ({status.get('questions', 0)} preguntas) — ya procesado")
            else:
                log.info(f"    · {s}")
        log.info(f"\n  Total: {len(pdfs)} PDFs")
        return

    # Crear directorio de salida
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Contadores
    total_questions = state.get("total_questions", 0)
    pdfs_processed = 0
    max_pdfs = args.max_pdfs if args.max_pdfs > 0 else len(pdfs)

    # Cargar ejemplos few-shot desde preguntas_mir.jsonl
    few_shot = load_mir_examples()
    if few_shot:
        log.info(f"  Few-shot examples cargados desde preguntas_mir.jsonl ✓")

    log.info(f"\n{'=' * 60}")
    log.info(f"  INICIANDO GENERACIÓN")
    log.info(f"  Ya generadas previamente: {state['generated_count']}")
    log.info(f"{'=' * 60}")

    for pdf_path in pdfs:
        if pdfs_processed >= max_pdfs:
            log.info(f"\n  Límite de {max_pdfs} PDFs alcanzado.")
            break

        q_count = process_pdf(pdf_path, state, dry_run=False, few_shot=few_shot)
        total_questions += q_count
        pdfs_processed += 1

        # Pausa entre PDFs
        if pdfs_processed < max_pdfs and q_count > 0:
            time.sleep(1)

    # Guardar total final
    state["total_questions"] = total_questions
    state["last_run"] = datetime.now().isoformat()
    save_state(state)

    print(f"\n{'=' * 60}")
    print(f"  RESUMEN")
    print(f"{'=' * 60}")
    print(f"  PDFs procesados: {pdfs_processed}")
    print(f"  Total preguntas generadas: {total_questions}")
    print(f"  Archivo: {OUTPUT_FILE}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
