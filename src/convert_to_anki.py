#!/usr/bin/env python3
"""
Convierte archivos JSONL de preguntas médicas a mazos importables en Anki (.apkg).

Uso:
  python3 src/convert_to_anki.py                              # Todos los JSONL
  python3 src/convert_to_anki.py data/preguntas_mir.jsonl     # Solo MIR
  python3 src/convert_to_anki.py data/preguntas_medicas.jsonl # Solo generadas
  python3 src/convert_to_anki.py --deck "MIR 2021-2025"       # Nombre personalizado

Genera archivos .apkg listos para importar en Anki con:
  - Imágenes embebidas (desde base64)
  - Diseño bonito con estilo clínico
  - Respuesta correcta resaltada en verde
"""

import argparse
import json
import logging
import os
import re
from pathlib import Path
from datetime import datetime

import genanki

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Configuración ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── Estilo CSS de las cartas (mono, bonito, agradable) ──────────────────

CARD_CSS = """
.card {
  font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
  font-size: 16px;
  line-height: 1.6;
  color: #2c3e50;
  padding: 20px;
  max-width: 720px;
  margin: 0 auto;
}

/* ── Night mode (Anki oscuro) ── */
.nightMode .card {
  color: #e0e0e0;
}
.nightMode .question {
  background: #2d2d2d !important;
  border-left-color: #5dade2 !important;
  color: #e0e0e0 !important;
}
.nightMode .option-item {
  background: #333 !important;
  border-color: #555 !important;
  color: #e0e0e0 !important;
}
.nightMode .option-item:hover {
  background: #3a3a3a !important;
  border-color: #5dade2 !important;
}
.nightMode .option-label {
  background: #555 !important;
  color: #ccc !important;
}
.nightMode .correct-answer {
  background: #1a3a2a !important;
  border-color: #27ae60 !important;
}
.nightMode .correct-answer .label {
  color: #2ecc71 !important;
}
.nightMode .correct-answer .answer-text {
  color: #58d68d !important;
}
.nightMode .reference {
  background: #2d2d2d !important;
  border-color: #555 !important;
  color: #999 !important;
}
.nightMode .reference strong {
  color: #bbb !important;
}
.nightMode .header {
  color: #999 !important;
  border-bottom-color: #5dade2 !important;
}
.nightMode .badge-year {
  background: #444 !important;
  color: #ccc !important;
}
.nightMode .image-container {
  background: #2d2d2d !important;
  border-color: #555 !important;
}

/* ── Encabezado ── */
.header {
  font-size: 13px;
  color: #7f8c8d;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 2px solid #3498db;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header .badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.badge-mir {
  background: #3498db;
  color: #ffffff;
}
.badge-llm {
  background: #9b59b6;
  color: #ffffff;
}
.badge-year {
  background: #ecf0f1;
  color: #7f8c8d;
}

/* ── Pregunta ── */
.question {
  font-size: 17px;
  font-weight: 500;
  color: #2c3e50;
  margin-bottom: 18px;
  padding: 12px 16px;
  background: #f8f9fa;
  border-radius: 10px;
  border-left: 4px solid #3498db;
}

/* ── Imagen ── */
.image-container {
  text-align: center;
  margin: 16px 0;
  padding: 12px;
  background: #fafafa;
  border-radius: 10px;
  border: 1px solid #e8e8e8;
}
.image-container img {
  max-width: 100%;
  max-height: 400px;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.15);
}

/* ── Opciones ── */
.options {
  list-style: none;
  padding: 0;
  margin: 12px 0;
}
.option-item {
  padding: 10px 16px;
  margin-bottom: 8px;
  background: #ffffff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  transition: all 0.2s;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.option-item:hover {
  background: #f0f7ff;
  border-color: #3498db;
}
.option-label {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #ecf0f1;
  color: #7f8c8d;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}
.option-text {
  flex: 1;
}

/* ── Respuesta correcta (cara trasera) ── */
.correct-answer {
  margin-top: 24px;
  padding: 16px 20px;
  background: linear-gradient(135deg, #e8f8f5, #d5f5e3);
  border: 2px solid #27ae60;
  border-radius: 12px;
  text-align: center;
}
.correct-answer .label {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: #27ae60;
  font-weight: 700;
}
.correct-answer .answer-text {
  font-size: 18px;
  font-weight: 700;
  color: #1a7a42;
  margin-top: 6px;
}

/* ── Referencia / fuente ── */
.reference {
  margin-top: 16px;
  padding: 10px 14px;
  background: #f8f9fa;
  border-radius: 8px;
  font-size: 12px;
  color: #7f8c8d;
  border: 1px solid #e8e8e8;
}
.reference strong {
  color: #5a6a7a;
}

/* ── Separador en cara trasera ── */
.back-divider {
  margin: 24px 0 12px;
  border: 0;
  border-top: 1px dashed #bdc3c7;
}
"""

# ─── Plantillas HTML de la carta ─────────────────────────────────────────────

FRONT_HTML = """
<div class="header">
  <span>{{Origen}}</span>
  <span>
    {{#Year}}<span class="badge badge-year">{{Year}}</span>{{/Year}}
    {{#Fuente}}<span class="badge badge-year">{{Fuente}}</span>{{/Fuente}}
  </span>
</div>

<div class="question">{{Pregunta}}</div>

{{#Imagen}}
<div class="image-container">
  <img src="{{Imagen}}" />
</div>
{{/Imagen}}

<ul class="options">
  <li class="option-item">
    <span class="option-label">1</span>
    <span class="option-text">{{Opcion1}}</span>
  </li>
  <li class="option-item">
    <span class="option-label">2</span>
    <span class="option-text">{{Opcion2}}</span>
  </li>
  <li class="option-item">
    <span class="option-label">3</span>
    <span class="option-text">{{Opcion3}}</span>
  </li>
  <li class="option-item">
    <span class="option-label">4</span>
    <span class="option-text">{{Opcion4}}</span>
  </li>
</ul>
"""

BACK_HTML = FRONT_HTML + """
<hr class="back-divider">

<div class="correct-answer">
  <div class="label">✓ Respuesta correcta</div>
  <div class="answer-text">{{RespuestaCorrectaTexto}}</div>
</div>

{{#Referencia}}
<div class="reference">
  <strong>📖 Fuente:</strong> {{Referencia}}
</div>
{{/Referencia}}
"""


# ─── Modelo de nota Anki ─────────────────────────────────────────────────────

def create_model() -> genanki.Model:
    """Crea el modelo de nota con el diseño personalizado."""
    model_id = 1742593601  # fijo para que sea el mismo modelo siempre
    return genanki.Model(
        model_id,
        "MIR Pregunta Médica",
        fields=[
            {"name": "Pregunta"},
            {"name": "Opcion1"},
            {"name": "Opcion2"},
            {"name": "Opcion3"},
            {"name": "Opcion4"},
            {"name": "RespuestaCorrecta"},
            {"name": "RespuestaCorrectaTexto"},
            {"name": "Imagen"},
            {"name": "Origen"},
            {"name": "Year"},
            {"name": "Fuente"},
            {"name": "Referencia"},
        ],
        templates=[
            {
                "name": "MIR Pregunta",
                "qfmt": FRONT_HTML,
                "afmt": BACK_HTML,
            }
        ],
        css=CARD_CSS,
    )


# ─── Utilidades ───────────────────────────────────────────────────────────────

def opcion_letter(n: int) -> str:
    """Convierte número de opción a letra (1→A, 2→B, etc.)."""
    return chr(64 + n)  # 1→A, 2→B, 3→C, 4→D


def find_jsonl_files() -> list[Path]:
    """Encuentra todos los archivos JSONL en data/."""
    data_dir = BASE_DIR / "data"
    return sorted(data_dir.glob("*.jsonl"))


def load_questions(jsonl_path: Path) -> list[dict]:
    """Carga todas las preguntas de un archivo JSONL."""
    questions = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    questions.append(json.loads(line))
                except json.JSONDecodeError as e:
                    log.warning(f"  ⚠ Error decodificando línea: {e}")
    return questions


# ─── Conversión ───────────────────────────────────────────────────────────────

def convert_jsonl_to_anki(
    jsonl_path: Path,
    deck_name: str | None = None,
    output_dir: Path | None = None,
) -> Path | None:
    """
    Convierte un archivo JSONL a un mazo .apkg de Anki.
    Retorna la ruta del archivo .apkg generado o None si no hay preguntas.
    """
    log.info(f"\n{'='*55}")
    log.info(f"  Procesando: {jsonl_path.name}")
    log.info(f"{'='*55}")

    questions = load_questions(jsonl_path)
    if not questions:
        log.warning("  ⚠ No hay preguntas en el archivo.")
        return None

    log.info(f"  Preguntas cargadas: {len(questions)}")

    # Nombre del mazo
    if deck_name is None:
        stem = jsonl_path.stem.replace("_", " ").title()
        deck_name = f"MIR - {stem}"

    # Crear mazo
    deck_id = abs(hash(jsonl_path.name)) % (2 ** 31)
    deck = genanki.Deck(deck_id, deck_name)
    model = create_model()

    total = len(questions)
    for idx, q in enumerate(questions, 1):
        if idx % 50 == 0 or idx == 1 or idx == total:
            log.info(f"  [{idx}/{total}] Procesando pregunta...")

        pregunta = q.get("pregunta", "")
        opciones = [
            q.get("opcion_1", ""),
            q.get("opcion_2", ""),
            q.get("opcion_3", ""),
            q.get("opcion_4", ""),
        ]
        resp_correcta = q.get("respuesta_correcta", 1)

        # Validar respuesta
        if not isinstance(resp_correcta, int) or resp_correcta < 1 or resp_correcta > 4:
            resp_correcta = 1

        resp_texto = opciones[resp_correcta - 1]
        resp_label = f"{opcion_letter(resp_correcta)}) {resp_texto}"

        # Origen
        origen = q.get("origen", "")
        if origen == "examen_mir":
            origen_badge = f'<span class="badge badge-mir">📋 MIR</span>'
        else:
            origen_badge = f'<span class="badge badge-llm">🤖 Generada</span>'

        year = q.get("year")
        year_str = str(year) if year else ""

        fuente = q.get("fuente", "")
        # Limitar longitud
        if len(fuente) > 60:
            fuente = "..." + fuente[-57:]

        # Referencia (texto_referencia para generadas, year para MIR)
        referencia = q.get("texto_referencia", "")
        if not referencia and year:
            referencia = f"Examen MIR {year}, pregunta {q.get('num_pregunta', '')}"
        if not referencia and fuente:
            referencia = f"Fuente: {fuente}"
        # Limitar longitud de referencia
        if len(referencia) > 300:
            referencia = referencia[:297] + "..."

        # Imagen — embebida como data URI directamente en el HTML
        imagen_field = ""
        img_obj = q.get("imagen")
        if img_obj and isinstance(img_obj, dict) and "data" in img_obj:
            b64 = img_obj["data"]
            # Asegurar prefijo data URI
            if b64.startswith("data:"):
                imagen_field = b64
            elif b64.startswith("/9j/"):
                imagen_field = "data:image/jpeg;base64," + b64
            elif b64.startswith("iVBOR"):
                imagen_field = "data:image/png;base64," + b64
            elif b64.startswith("R0lG"):
                imagen_field = "data:image/gif;base64," + b64
            else:
                imagen_field = "data:image/png;base64," + b64

        # Crear nota
        note = genanki.Note(
            model=model,
            fields=[
                pregunta,
                opciones[0],
                opciones[1],
                opciones[2],
                opciones[3],
                str(resp_correcta),
                resp_label,
                imagen_field,
                origen_badge,
                year_str,
                fuente,
                referencia,
            ],
        )
        deck.add_note(note)

    if len(deck.notes) == 0:
        log.warning("  ⚠ No se generaron notas.")
        return None

    # Guardar paquete
    if output_dir is None:
        output_dir = BASE_DIR / "tarjetas_anki"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Nombre del archivo
    apkg_name = jsonl_path.stem + ".apkg"
    apkg_path = output_dir / apkg_name

    package = genanki.Package(deck)

    package.write_to_file(str(apkg_path))

    log.info(f"  ✅ Mazo creado: {apkg_path}")
    log.info(f"     Notas: {len(deck.notes)}")
    img_count = sum(1 for q in questions if q.get("imagen"))
    log.info(f"     Con imágenes: {img_count}")

    return apkg_path


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convierte JSONL de preguntas médicas a mazos .apkg para Anki"
    )
    parser.add_argument(
        "input", nargs="*",
        help="Archivo(s) JSONL a convertir (por defecto: todos en data/)"
    )
    parser.add_argument(
        "--deck", type=str, default=None,
        help="Nombre del mazo Anki (por defecto: nombre del archivo)"
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Directorio de salida (por defecto: data/)"
    )
    args = parser.parse_args()

    print("=" * 55)
    print("  🃏  CONVERTIDOR JSONL → ANKI")
    print("  Flashcards bonitas para estudiar MIR")
    print("=" * 55)

    # Determinar archivos de entrada
    if args.input:
        input_files = [Path(p) for p in args.input]
        # Verificar que existen
        for f in input_files:
            if not f.exists():
                log.error(f"✗ Archivo no encontrado: {f}")
                return
    else:
        input_files = find_jsonl_files()
        if not input_files:
            log.error("✗ No se encontraron archivos JSONL en data/")
            return

    log.info(f"  Archivos a convertir: {len(input_files)}")
    for f in input_files:
        size = f.stat().st_size
        log.info(f"    · {f.name} ({size:,} bytes)")

    output_dir = Path(args.output_dir) if args.output_dir else None

    generated = []
    for f in input_files:
        # Deck name específico por archivo
        deck_name = None
        if args.deck:
            if len(input_files) == 1:
                deck_name = args.deck
            else:
                deck_name = f"{args.deck} - {f.stem.replace('_', ' ').title()}"

        apkg = convert_jsonl_to_anki(f, deck_name=deck_name, output_dir=output_dir)
        if apkg:
            generated.append(apkg)

    print(f"\n{'='*55}")
    print(f"  📊  RESUMEN")
    print(f"{'='*55}")
    if generated:
        for g in generated:
            size = g.stat().st_size
            print(f"  ✅ {g.name}  ({size // 1024:,} KB)")
        print(f"\n  Importa los archivos .apkg en Anki:")
        print(f"     Archivo → Importar → Selecciona el .apkg")
    else:
        print(f"  ❌ No se generó ningún mazo.")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
