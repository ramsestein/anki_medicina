#!/usr/bin/env python3
"""
Conversor de exámenes MIR (formato original) a PDF fusionado.
=============================================================
Lee los archivos fuente de data/exam_mir_original/ y genera
un PDF único por año en docs/examen_mir/ con:
  - Cuaderno de preguntas (M_0_C)
  - Cuadernillo de imágenes (M_I)
  - Página de respuestas correctas

Uso:
  python3 src/convert_mir_to_pdf.py                          # Todos los años
  python3 src/convert_mir_to_pdf.py --years 2025             # Solo 2025
  python3 src/convert_mir_to_pdf.py --years 2024,2025        # Varios
"""

import os
import re
import json
import argparse
import subprocess
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER


BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "data" / "exam_mir_original"
OUTPUT_DIR = BASE_DIR / "docs" / "examen_mir"
YEARS = [2021, 2022, 2023, 2024, 2025]


# ─── Parseo de respuestas ────────────────────────────────────────────────────

def parse_respuestas(filepath):
    """
    Lee el archivo TXT de respuestas y devuelve un dict {num_pregunta: respuesta}.
    El formato esperado es una tabla tabulada con pares V( número ) R(espuesta).
    """
    respuestas = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split('\t')
        # Cada fila tiene pares V R V R V R V R V R (5 pares)
        if len(parts) >= 2 and all(
            p.strip().isdigit() or p.strip() == '' for p in parts
        ):
            for i in range(0, len(parts), 2):
                if i + 1 < len(parts):
                    q_num = parts[i].strip()
                    q_ans = parts[i + 1].strip()
                    if q_num and q_ans:
                        respuestas[int(q_num)] = int(q_ans)

    return respuestas


# ─── Generación de página de respuestas ─────────────────────────────────────

def create_answer_page(output_path, year, respuestas):
    """
    Crea un PDF con una tabla de respuestas correctas para añadir al final.
    """
    doc = SimpleDocTemplate(
        str(output_path), pagesize=A4,
        topMargin=20*mm, bottomMargin=15*mm,
        leftMargin=15*mm, rightMargin=15*mm
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Heading1'],
        fontSize=16, alignment=TA_CENTER, spaceAfter=6*mm
    )
    subtitle_style = ParagraphStyle(
        'CustomSubtitle', parent=styles['Heading2'],
        fontSize=12, alignment=TA_CENTER, spaceAfter=4*mm
    )
    cell_style = ParagraphStyle(
        'CellStyle', parent=styles['Normal'],
        fontSize=8, alignment=TA_CENTER, leading=10
    )
    header_style = ParagraphStyle(
        'HeaderStyle', parent=styles['Normal'],
        fontSize=9, alignment=TA_CENTER, leading=12,
        fontName='Helvetica-Bold'
    )

    elements = []
    elements.append(Paragraph(f"Examen MIR {year}", title_style))
    elements.append(Paragraph(
        "Plantilla de Respuestas Correctas", subtitle_style
    ))
    elements.append(Spacer(1, 4*mm))

    headers = [
        Paragraph("Preg.", header_style),
        Paragraph("Resp.", header_style),
        Paragraph("Preg.", header_style),
        Paragraph("Resp.", header_style),
        Paragraph("Preg.", header_style),
        Paragraph("Resp.", header_style),
        Paragraph("Preg.", header_style),
        Paragraph("Resp.", header_style),
    ]
    table_data = [headers]

    ranges = [(1, 50), (51, 100), (101, 150), (151, 210)]
    for i in range(50):
        row = []
        for start, end in ranges:
            q_num = start + i
            if q_num <= end and q_num <= 210:
                ans = respuestas.get(q_num, '')
                row.append(Paragraph(str(q_num), cell_style))
                row.append(Paragraph(str(ans) if ans else '-', cell_style))
            else:
                row.append(Paragraph('', cell_style))
                row.append(Paragraph('', cell_style))
        table_data.append(row)

    col_widths = [22*mm, 18*mm, 22*mm, 18*mm, 22*mm, 18*mm, 22*mm, 18*mm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#005687')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
         [colors.white, colors.HexColor('#E6EEF7')]),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(table)

    empty_questions = [
        str(q) for q in sorted(respuestas.keys())
        if respuestas[q] == ''
    ]
    if empty_questions:
        note_style = ParagraphStyle(
            'NoteStyle', parent=styles['Normal'],
            fontSize=8, textColor=colors.red
        )
        elements.append(Spacer(1, 4*mm))
        elements.append(Paragraph(
            f"Nota: Preguntas {', '.join(empty_questions)} "
            f"sin respuesta (anuladas).",
            note_style
        ))

    doc.build(elements)


# ─── Conversión principal ───────────────────────────────────────────────────

def convert_exam(year):
    """
    Convierte un examen MIR del formato original al PDF fusionado.
    """
    # Archivos fuente
    m0c_pdf = INPUT_DIR / f"Cuaderno_{year}_M_0_C.pdf"
    mi_pdf = INPUT_DIR / f"Cuaderno_{year}_M_I.pdf"
    respuestas_txt = INPUT_DIR / f"respuestas_{year}.txt"
    output_pdf = OUTPUT_DIR / f"Examen_MIR_{year}.pdf"

    # Validar existencia
    missing = []
    if not m0c_pdf.exists():
        missing.append(f"Cuaderno_{year}_M_0_C.pdf")
    if not mi_pdf.exists():
        missing.append(f"Cuaderno_{year}_M_I.pdf")
    if not respuestas_txt.exists():
        missing.append(f"respuestas_{year}.txt")

    if missing:
        print(f"  ⚠ Faltan archivos para {year}: {', '.join(missing)}")
        return False

    print(f"\n{'─'*50}")
    print(f"  Convirtiendo: Examen MIR {year}")
    print(f"{'─'*50}")

    # 1. Fusionar M_0_C + M_I
    temp_combined = OUTPUT_DIR / f".temp_combined_{year}.pdf"
    print(f"  Fusionando cuaderno de preguntas + imágenes...")
    subprocess.run(
        ['pdfunite', str(m0c_pdf), str(mi_pdf), str(temp_combined)],
        capture_output=True, check=True
    )

    # 2. Leer el PDF combinado
    reader = PdfReader(temp_combined)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    # 3. Generar página de respuestas
    print(f"  Generando página de respuestas...")
    temp_answers = OUTPUT_DIR / f".temp_answers_{year}.pdf"
    respuestas = parse_respuestas(respuestas_txt)
    create_answer_page(temp_answers, year, respuestas)
    print(f"    ({len(respuestas)} respuestas)")

    # 4. Añadir página de respuestas
    answer_reader = PdfReader(temp_answers)
    for page in answer_reader.pages:
        writer.add_page(page)

    # 5. Guardar PDF final
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_pdf, 'wb') as f:
        writer.write(f)

    # 6. Limpiar temporales
    temp_combined.unlink(missing_ok=True)
    temp_answers.unlink(missing_ok=True)

    file_size = output_pdf.stat().st_size / (1024 * 1024)
    pages = len(PdfReader(output_pdf).pages)
    print(f"  ✓ {output_pdf.name} ({pages} páginas, {file_size:.1f} MB)")
    return True


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convierte exámenes MIR a PDF fusionado"
    )
    parser.add_argument('--years', type=str, default='',
                        help='Años a convertir (separados por coma)')
    args = parser.parse_args()

    years = (
        [int(y.strip()) for y in args.years.split(',') if y.strip()]
        if args.years else YEARS
    )

    print("=" * 60)
    print("  CONVERSOR MIR → PDF FUSIONADO")
    print("=" * 60)
    print(f"  Origen:  {INPUT_DIR}")
    print(f"  Destino: {OUTPUT_DIR}")
    print(f"  Años:    {', '.join(str(y) for y in years)}")
    print()

    ok = 0
    for year in years:
        if convert_exam(year):
            ok += 1

    print(f"\n{'='*60}")
    print(f"  {ok}/{len(years)} exámenes convertidos correctamente")
    print(f"  Destino: {OUTPUT_DIR}")
    print(f"{'='*60}")

    # Listar resultados
    print("\n  Archivos generados:")
    for f in sorted(OUTPUT_DIR.glob("Examen_MIR_*.pdf")):
        size = f.stat().st_size / (1024 * 1024)
        print(f"    {f.name} ({size:.1f} MB)")


if __name__ == "__main__":
    main()
