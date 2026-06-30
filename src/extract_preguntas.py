#!/usr/bin/env python3
"""
Extrae preguntas de los PDFs de examen MIR y genera JSONL.
Lee los PDFs fusionados (Examen_MIR_202X.pdf) y extrae:
  - Número de pregunta
  - Texto de la pregunta
  - Opciones (1-4)
  - Respuesta correcta (desde tabla de respuestas al final)
  - Origen (examen_mir)

Uso:
  python3 src/extract_preguntas.py                              # Todos
  python3 src/extract_preguntas.py --years 2021                 # Solo 2021
  python3 src/extract_preguntas.py --years 2021,2022            # Varios
  python3 src/extract_preguntas.py --output data/preguntas.jsonl
"""

import os
import re
import json
import base64
import argparse
from pathlib import Path
from io import BytesIO

from pypdf import PdfReader


BASE_DIR = Path(__file__).resolve().parent.parent
EXAMEN_DIR = BASE_DIR / "docs" / "examen_mir"
DEFAULT_OUTPUT = BASE_DIR / "data" / "preguntas_mir.jsonl"
YEARS = [2021, 2022, 2023, 2024, 2025]

RE_QUESTION = re.compile(r'^(\d+)[.]\s+(.*)')
RE_OPTION = re.compile(r'^([1-4])[.]\s*(.*)')
RE_PAGE_HDR = re.compile(r'^-\s*\d+\s*-$')


# ─── Limpieza de texto extraído del PDF ─────────────────────────────────────

def clean_pdf_text(text):
    """
    Limpia artefactos de la extracción de texto del PDF.
    """
    if not text:
        return text

    # 1. Detectar y corregir texto con espacios entre caracteres
    words = text.split()
    if len(words) > 5:
        single_items = sum(1 for w in words if len(w) == 1)
        # Detectar si hay una secuencia larga de caracteres sueltos (> 15 consecutivos
        # o proporción alta)
        max_run = 0
        current_run = 0
        for w in words:
            if len(w) == 1:
                current_run += 1
                max_run = max(max_run, current_run)
            else:
                current_run = 0

        needs_join = (single_items > len(words) * 0.25 or max_run >= 10)
        if needs_join:
            # Reconstruir agrupando caracteres consecutivos
            new_words = []
            buf = ''
            for w in words:
                if len(w) == 1:
                    buf += w
                else:
                    if buf:
                        new_words.append(buf)
                        buf = ''
                    new_words.append(w)
            if buf:
                new_words.append(buf)
            text = ' '.join(new_words)

    # 2. Reparar guiones de salto de línea: "faci- lidad" → "facilidad"
    text = re.sub(r'(\w{2,})-\s+(\w{2,})', lambda m: m.group(1) + m.group(2), text)

    # 3. Reparar espacios en medio de palabras (OCR): "sup erficial" → "superficial"
    text = re.sub(r'\b(de)\s+(l[oa]s?)\b', r'\1 \2', text)  # "de la" mantener
    text = re.sub(r'\b(sup)\s+(erficial)\b', r'superficial', text)
    text = re.sub(r'\b(intra)\s+(\w)', r'\1\2', text)
    text = re.sub(r'\b(extra)\s+(\w)', r'\1\2', text)

    # 4. Errores específicos comunes (ordenados de más específico a menos)
    replacements = {
        # Palabras completas que deben existir
        'ńo': 'ño',
        'Ńo': 'Ño',
        # OCR errors
        'ed ad': 'edad',
        'Ni ega': 'Niega',
        'b i o p s i a': 'biopsia',
        's i n t o m a t o l o g í a': 'sintomatología',
        'l e s i o n e s': 'lesiones',
        'c u t á n e a s': 'cutáneas',
        'e v o l u c i ó n': 'evolución',
        'a n t e c e d e n t e s': 'antecedentes',
        'e x p l o r a c i ó n': 'exploración',
        'p r e s e n t a': 'presenta',
        'e n f e r m e d a d': 'enfermedad',
        'd i a g n ó s t i c o': 'diagnóstico',
        't r a t a m i e n t o': 'tratamiento',
        'p a c i e n t e': 'paciente',
        # Reparar espacio unido (tras join)
        'Mujerde': 'Mujer de',
        'Varónde': 'Varón de',
        'Niñode': 'Niño de',
        'Hombrede': 'Hombre de',
        'Pacientede': 'Paciente de',
        'añosque': 'años que',
        'añosde': 'años de',
        'añode': 'año de',
        'añosy': 'años y',
        'añosen': 'años en',
        'añoscon': 'años con',
        'añosdetalle': 'años de',
        'mesesde': 'meses de',
        'mesescon': 'meses con',
        'mesesque': 'meses que',
        'semanasde': 'semanas de',
        'díasde': 'días de',
        'díascon': 'días con',
        'horasde': 'horas de',
        'minutosde': 'minutos de',
        'consultapor': 'consulta por',
        'queconsulta': 'que consulta',
        'queconsultó': 'que consultó',
        'queacude': 'que acude',
        'queingresa': 'que ingresa',
        'quepresenta': 'que presenta',
        'querefiere': 'que refiere',
        'quesigue': 'que sigue',
        'quetiene': 'que tiene',
        'ingresapor': 'ingresa por',
        'ingresópor': 'ingresó por',
        'acudepor': 'acude por',
        'acudiópor': 'acudió por',
        'presentauna': 'presenta una',
        'presentaun': 'presenta un',
        'presentade': 'presenta de',
        'presentaen': 'presenta en',
        'presentacon': 'presenta con',
        'presentaun': 'presenta un',
        'sinantecedentes': 'sin antecedentes',
        'conantecedentes': 'con antecedentes',
        'conhistoria': 'con historia',
        'delextremo': 'del extremo',
        '70años': '70 años',
        '1año': '1 año',
        'porlesiones': 'por lesiones',
        'porla': 'por la',
        'porel': 'por el',
        'seasocia': 'se asocia',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # 4b. Reparar dígitos unidos a palabras: "70años" → "70 años"
    text = re.sub(r'(\d+)([a-zA-ZáéíóúñÁÉÍÓÚÑ])', r'\1 \2', text)
    text = re.sub(r'([a-zA-ZáéíóúñÁÉÍÓÚÑ])(\d+)', r'\1 \2', text)

    # 5. Limpiar ":?" y "?:" al final (puntuación incorrecta)
    text = re.sub(r'[?:]+\s*[?:]+', '?', text)

    # 6. Espacios múltiples
    text = re.sub(r'\s+', ' ', text).strip()

    return text


# ─── Extracción de imágenes del PDF ─────────────────────────────────────────

def extract_images_from_pdf(pdf_path):
    """
    Extrae las imágenes del cuadernillo de imágenes (M_I) dentro del PDF fusionado.
    Devuelve un dict {num_imagen: base64_data}.
    Soporta formatos "IMAGEN X", "Imagen X" y "imagen X".
    """
    reader = PdfReader(pdf_path)
    images_map = {}

    # Buscar páginas que contengan imágenes
    for pg_idx, page in enumerate(reader.pages):
        text = page.extract_text()
        # Buscar etiquetas "IMAGEN/Imagen/imagen X"
        imagen_nums = []
        for m in re.finditer(r'(?i)imagen\s*(\d+)', text):
            imagen_nums.append(int(m.group(1)))

        if not imagen_nums:
            continue

        page_images = list(page.images)

        # Saltar páginas con muchas imágenes (portada del cuadernillo)
        if len(page_images) > 50:
            continue

        # Las imágenes están en orden de lectura (mismo orden que Imagen nums)
        # Algunas páginas tienen los números mezclados con otros dígitos,
        # así que filtramos solo números entre 1-25
        imagen_nums = [n for n in imagen_nums if 1 <= n <= 25]

        if not imagen_nums:
            continue

        # Algunas páginas pueden tener más imágenes que etiquetas o viceversa
        # Mapeamos 1:1 según orden de lectura
        for i, img_num in enumerate(imagen_nums):
            if i < len(page_images):
                img_data = page_images[i].data
                b64 = base64.b64encode(img_data).decode('utf-8')
                ext = Path(page_images[i].name).suffix or '.png'
                # Solo guardar si no tenemos ya esta imagen (primera ocurrencia)
                if img_num not in images_map:
                    images_map[img_num] = {
                        'data': b64,
                        'format': ext.lstrip('.')
                    }

    return images_map


# ─── Parser de preguntas ─────────────────────────────────────────────────────

def extract_questions_from_pdf(pdf_path):
    """
    Extrae preguntas y opciones.
    
    Estrategia de dos pasos:
    1. Identificar todas las líneas que son INICIOS DE PREGUNTA (numero_cuestión > 4
       o con palabras clave como "Pregunta asociada").
    2. Entre pregunta y pregunta, buscar el bloque de opciones 1-2-3-4.
    """
    full_text = ""
    for page in PdfReader(pdf_path).pages:
        full_text += "\n" + page.extract_text()
    lines = full_text.split('\n')

    # ── Paso 1: identificar todas las líneas de inicio de pregunta ──
    question_starts = {}  # {line_idx: q_num}
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or RE_PAGE_HDR.match(s):
            continue
        m = RE_QUESTION.match(s)
        if not m:
            continue
        qn = int(m.group(1))
        txt = m.group(2).strip().lower() if m.group(2) else ''

        # Criterios para ser INICIO DE PREGUNTA (no opción)
        is_question_start = False
        
        # 1) Números > 4 siempre son preguntas
        if qn > 4:
            is_question_start = True
        # 2) Números 1-4 pueden ser preguntas si tienen palabras clave
        elif any(w in txt for w in ['pregunta asociada', 'paciente', 'mujer', 'varón',
                                      'niño', 'hombre', 'consulta', 'ingresa', 'acude',
                                      'presenta', 'refiere']):
            # Verificar que no es una opción (opciones son cortas y no tienen historia clínica)
            if len(txt) > 20:
                is_question_start = True
        # 3) Números 1-4 también son preguntas si NO hay un bloque OP1-OP4 cerca
        # (se verifica en paso 2)

        if is_question_start:
            question_starts[i] = qn
            # Saltar instrucciones: primera Q#1 que es instrucción, no pregunta
            if qn == 1 and 'muy importante' in txt:
                del question_starts[i]

    # Si no se encontró Q#1 con palabras clave, usar la primera Q#1 tras línea 40
    has_q1 = any(qn == 1 for qn in question_starts.values())
    if not has_q1:
        for i, line in enumerate(lines):
            if i < 40:
                continue
            s = line.strip()
            m = RE_QUESTION.match(s)
            if m and int(m.group(1)) == 1:
                question_starts[i] = 1
                break

    # ── Paso 2: extraer preguntas con sus opciones ──
    sorted_starts = sorted(question_starts.items())  # [(line_idx, q_num), ...]
    questions = []

    for idx, (line_idx, q_num) in enumerate(sorted_starts):
        # Límite: hasta la siguiente pregunta o fin de texto
        end_idx = len(lines)
        if idx + 1 < len(sorted_starts):
            end_idx = sorted_starts[idx + 1][0]

        # Buscar bloque de opciones 1-2-3-4 dentro de este rango
        ob = _find_option_block(lines, line_idx + 1, end_idx)
        if not ob:
            continue

        opt1_line, opt4_line, options = ob

        # Texto de pregunta = desde el inicio hasta las opciones
        parts = [RE_QUESTION.match(lines[line_idx].strip()).group(2).strip()]
        for k in range(line_idx + 1, opt1_line):
            tk = lines[k].strip()
            if tk and not RE_PAGE_HDR.match(tk) and not RE_QUESTION.match(tk):
                parts.append(tk)

        q_text = re.sub(r'\s+', ' ', ' '.join(parts)).strip()
        questions.append({
            'num': q_num,
            'texto': q_text,
            'opciones': options
        })

    return questions


def _find_option_block(lines, start, end):
    """
    Busca un bloque de opciones 1-2-3-4 entre start y end.
    Soporta opciones multi-línea.
    Devuelve (line_1, line_4, {1: txt, 2: txt, 3: txt, 4: txt}) o None.
    """
    for idx in range(start, min(end, len(lines))):
        s = lines[idx].strip()
        o1 = RE_OPTION.match(s)
        if not o1 or o1.group(1) != '1':
            continue

        # Buscar 2, 3, 4 hacia adelante (saltando continuaciones)
        found = {1: idx}
        pos = idx + 1
        next_n = 2
        while pos < min(idx + 25, len(lines)) and next_n <= 4:
            ps = lines[pos].strip()
            if not ps or RE_PAGE_HDR.match(ps):
                pos += 1
                continue
            om = RE_OPTION.match(ps)
            if om and int(om.group(1)) == next_n:
                found[next_n] = pos
                next_n += 1
            pos += 1

        if len(found) == 4:
            # Extraer textos de opciones (multi-línea)
            options = {}
            p = found[1]
            for onum in range(1, 5):
                om = RE_OPTION.match(lines[p].strip())
                txt = om.group(2).strip()
                p += 1
                # Acumular líneas de continuación hasta la siguiente opción
                # Para op4, usar end (inicio de la siguiente pregunta) como límite
                next_p = found[onum + 1] if onum < 4 else min(end, len(lines))
                while p < next_p:
                    ns = lines[p].strip()
                    if ns and not RE_OPTION.match(ns) and not RE_PAGE_HDR.match(ns):
                        txt += ' ' + ns
                    p += 1
                options[onum] = re.sub(r'\s+', ' ', txt).strip()

            return (found[1], found[4], options)

    return None


# ─── Parser de respuestas ────────────────────────────────────────────────────

def extract_answers_from_pdf(pdf_path, total_pages):
    """
    Extrae la tabla de respuestas de las últimas 2 páginas.
    Formato: cada línea tiene un número de pregunta y la siguiente su respuesta.
    """
    answers = {}
    for pg in range(max(0, total_pages - 2), total_pages):
        text = PdfReader(pdf_path).pages[pg].extract_text()
        lines = text.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # Formato: pregunta y respuesta en la misma línea
            m = re.match(r'^(\d+)\s+(\d+|-)$', line)
            if m:
                if m.group(2) != '-':
                    answers[int(m.group(1))] = int(m.group(2))
                i += 1
                continue

            # Formato: pregunta en línea N, respuesta en línea N+1
            m_num = re.match(r'^(\d+)$', line)
            if m_num:
                qn = int(m_num.group(1))
                if 1 <= qn <= 210 and i + 1 < len(lines):
                    nl = lines[i + 1].strip()
                    m_ans = re.match(r'^(\d+|-)$', nl)
                    if m_ans and m_ans.group(1) != '-':
                        answers[qn] = int(m_ans.group(1))
                        i += 2
                        continue
            i += 1

    return answers


# ─── Procesamiento ───────────────────────────────────────────────────────────

def process_exam(year):
    pdf_path = EXAMEN_DIR / f"Examen_MIR_{year}.pdf"
    if not pdf_path.exists():
        print(f"  ⚠ {pdf_path.name} no encontrado")
        return []

    print(f"\n{'─'*50}")
    print(f"  Procesando: Examen MIR {year}")
    print(f"{'─'*50}")

    questions = extract_questions_from_pdf(pdf_path)
    print(f"  ✓ {len(questions)} preguntas encontradas")
    if not questions:
        return []

    # Deduplicar: si hay dos preguntas con el mismo número, conservar la de texto más largo
    questions.sort(key=lambda q: q['num'])
    deduped = {}
    for q in questions:
        n = q['num']
        if n not in deduped or len(q['texto']) > len(deduped[n]['texto']):
            deduped[n] = q
    questions = list(deduped.values())
    questions.sort(key=lambda q: q['num'])
    print(f"  ✓ {len(questions)} preguntas tras deduplicar")

    reader = PdfReader(pdf_path)
    answers = extract_answers_from_pdf(pdf_path, len(reader.pages))
    print(f"  ✓ {len(answers)} respuestas encontradas")

    # Extraer imágenes del cuadernillo M_I
    print(f"  Extrayendo imágenes...")
    images_map = extract_images_from_pdf(pdf_path)
    print(f"  ✓ {len(images_map)} imágenes encontradas")

    # Mapear imagen por pregunta
    q_image_map = {}
    for q in questions:
        m = re.search(r'imagen\s*(\d+)', q['texto'], re.IGNORECASE)
        if m:
            img_num = int(m.group(1))
            if img_num in images_map:
                q_image_map[q['num']] = images_map[img_num]

    result = []
    for q in questions:
        qn = q['num']
        entry = {
            'pregunta': clean_pdf_text(q['texto']),
            'opcion_1': clean_pdf_text(q['opciones'].get(1, '')),
            'opcion_2': clean_pdf_text(q['opciones'].get(2, '')),
            'opcion_3': clean_pdf_text(q['opciones'].get(3, '')),
            'opcion_4': clean_pdf_text(q['opciones'].get(4, '')),
            'respuesta_correcta': answers.get(qn),
            'origen': 'examen_mir',
            'year': year,
            'num_pregunta': qn,
        }
        if qn in q_image_map:
            entry['imagen'] = q_image_map[qn]
        result.append(entry)
    return result


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extrae preguntas MIR → JSONL")
    parser.add_argument('--years', type=str, default='')
    parser.add_argument('--output', type=str, default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    years = [int(y) for y in args.years.split(',') if y.strip()] if args.years else YEARS
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  EXTRACTOR DE PREGUNTAS MIR → JSONL")
    print("=" * 60)
    print(f"  Años: {', '.join(str(y) for y in years)}")
    print(f"  Salida: {output_path}")

    all_q = []
    for year in years:
        all_q.extend(process_exam(year))

    # Filtrar preguntas sin respuesta (anuladas en el examen oficial)
    total_before = len(all_q)
    all_q = [q for q in all_q if q['respuesta_correcta'] is not None]
    total_filtered = total_before - len(all_q)

    with open(output_path, 'w', encoding='utf-8') as f:
        for q in all_q:
            f.write(json.dumps(q, ensure_ascii=False) + '\n')

    with_ans = sum(1 for q in all_q if q['respuesta_correcta'] is not None)
    print(f"\n  TOTAL: {len(all_q)} preguntas | {total_filtered} filtradas sin respuesta")
    print(f"  Archivo: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
