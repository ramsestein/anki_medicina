# 🏥 MIR-Anki

**Pipeline para generar flashcards tipo test MIR en formato Anki** a partir de exámenes oficiales del MIR y documentación médica.

El resultado final son archivos **`.apkg`** listos para importar directamente en Anki, con imágenes embebidas, diseño bonito y respuesta correcta resaltada.

---

## ✨ ¿Qué hace?

1. **Crawlea** documentación médica de fuentes como NICE, MSD Manuals, etc. y las guarda como PDFs
2. **Convierte** los exámenes MIR originales (cuadernos de preguntas + cuadernos de imágenes + respuestas) en PDFs fusionados con hoja de respuestas
3. **Extrae** las 927+ preguntas MIR reales desde los PDFs fusionados a un archivo JSONL estructurado
4. **Genera** nuevas preguntas tipo test desde la documentación médica usando **DeepSeek** (API), imitando el estilo de las preguntas MIR reales mediante *few-shot learning*
5. **Convierte** los JSONL a mazos **`.apkg`** de Anki con diseño bonito e imágenes incluidas

---

## 📁 Estructura del proyecto

```
anki-mir/
├── orquestador.sh          # Script orquestador (Linux/macOS)
├── orquestador.ps1         # Script orquestador (Windows PowerShell)
├── requirements.txt        # Dependencias Python
├── .env                    # API key de DeepSeek (no versionar)
├── .gitignore
├── README.md
│
├── src/
│   ├── crawl_docs.py              # Crawler de documentación médica
│   ├── convert_mir_to_pdf.py      # Fusión de PDFs MIR originales
│   ├── extract_preguntas.py       # Extracción de preguntas a JSONL
│   ├── generate_preguntas_llm.py  # Generación LLM con DeepSeek
│   └── convert_to_anki.py         # Conversor JSONL → .apkg para Anki
│
├── data/
│   ├── preguntas_mir.jsonl      # 927 preguntas extraídas del MIR
│   ├── preguntas_medicas.jsonl  # Preguntas generadas por DeepSeek
│
├── tarjetas_anki/
│   ├── preguntas_mir.apkg       # Mazo Anki (con imágenes)
│   ├── preguntas_medicas.apkg   # Mazo Anki
│   ├── .generation_state.json   # Estado de progreso (generación LLM)
│   └── exam_mir_original/       # PDFs originales del MIR
│       ├── Cuaderno_2025_M_0_C.pdf   # Cuaderno de preguntas
│       ├── Cuaderno_2025_M_I.pdf     # Cuaderno de imágenes
│       └── respuestas_2025.txt       # Hoja de respuestas
│
├── docs/
│   ├── examen_mir/          # PDFs fusionados (Examen_MIR_202X.pdf)
│   ├── nice/                # PDFs crawleados de NICE
│   ├── msd-manual/          # PDFs crawleados de MSD Manuals
│   └── .crawler_cache/      # Caché del crawler
│
└── list_links.txt           # URLs para el crawler
```

---

## 🚀 Uso rápido

### 1. Preparar el entorno

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt
```

### 2. Configurar API key (solo para generación LLM)

Crea un archivo `.env` en la raíz:

```
DEEPSEEK_API_KEY=sk-tu-api-key-de-deepseek
```

### 3. Ejecutar el pipeline

**Linux/macOS:**
```bash
# Menú interactivo
./orquestador.sh

# O por comando directo
./orquestador.sh all              # Todo el pipeline
./orquestador.sh crawl            # Solo crawlear docs
./orquestador.sh convert          # Solo convertir PDFs
./orquestador.sh extract          # Solo extraer preguntas
./orquestador.sh generate --reset # Solo generar con LLM
./orquestador.sh anki             # Solo convertir JSONL a .apkg
```

**Windows PowerShell:**
```powershell
.\orquestador.ps1
# o
.\orquestador.ps1 -Step all
```

---

## 📋 Pasos del pipeline

### 1. Crawlear documentación médica

```bash
python3 src/crawl_docs.py
```

Descarga páginas médicas desde las URLs en `list_links.txt` y las convierte a PDFs en `docs/`. Soporta caché y reanudación.

Opciones: `--dry-run`, `--max-pages N`, `--max-depth N`, `--delay N`, `--resume`

### 2. Convertir exámenes MIR originales

```bash
python3 src/convert_mir_to_pdf.py
```

Toma los PDFs originales de `data/exam_mir_original/` (cuaderno de preguntas + cuaderno de imágenes + respuestas) y los fusiona en un solo PDF por año con hoja de respuestas en `docs/examen_mir/`.

Opciones: `--years 2021,2022,2023`

### 3. Extraer preguntas MIR a JSONL

```bash
python3 src/extract_preguntas.py
```

Procesa los PDFs fusionados de `docs/examen_mir/` y extrae cada pregunta con sus opciones, respuesta correcta e imágenes (base64) a `data/preguntas_mir.jsonl`.

Opciones: `--years 2021,2022,2023`, `--output salida.jsonl`

### 4. Generar preguntas con DeepSeek

```bash
python3 src/generate_preguntas_llm.py
```

Procesa los PDFs de documentación médica en `docs/` (excluyendo `examen_mir/`), divide el texto en chunks y usa DeepSeek para generar preguntas tipo test al estilo MIR. Usa ejemplos reales del MIR como *few-shot learning*.

Opciones: `--max-pdfs N`, `--dry-run`, `--reset`, `--chunk-size N`, `--overlap N`

### 5. Convertir a mazo Anki (.apkg)

```bash
# Todos los JSONL
python3 src/convert_to_anki.py

# Solo un archivo
python3 src/convert_to_anki.py data/preguntas_mir.jsonl --deck "MIR 2021-2025"

# Solo las generadas por DeepSeek
python3 src/convert_to_anki.py data/preguntas_medicas.jsonl --deck "MIR - Generadas"
```

Genera archivos `.apkg` en `tarjetas_anki/` listos para importar en Anki (**Archivo → Importar**). Las cartas incluyen:
- Diseño bonito con estilo clínico (azul/bLANco)
- Imágenes embebidas (desde los exámenes MIR)
- Opciones numeradas con estilo visual
- Respuesta correcta resaltada en verde (cara trasera)
- Fuente o referencia del documento

---

## 📊 Datos generados

| Archivo | Descripción |
|---|---|
| `data/preguntas_mir.jsonl` | 927 preguntas extraídas de exámenes MIR 2021-2025 |
| `data/preguntas_medicas.jsonl` | Preguntas generadas por DeepSeek desde documentación médica |
| `tarjetas_anki/preguntas_mir.apkg` | Mazo Anki con imágenes (39 MB) — importar directamente |
| `tarjetas_anki/preguntas_medicas.apkg` | Mazo Anki de preguntas generadas |

### Formato JSONL

Cada línea es un objeto JSON:

```json
{
  "pregunta": "Varón de 65 años... ¿Cuál es el diagnóstico?",
  "opcion_1": "Primera opción",
  "opcion_2": "Segunda opción",
  "opcion_3": "Tercera opción",
  "opcion_4": "Cuarta opción",
  "respuesta_correcta": 3,
  "origen": "examen_mir",
  "year": 2021,
  "num_pregunta": 1,
  "imagen": { "data": "base64..." }
}
```

---

## 💰 Costes de la generación LLM

DeepSeek API es muy económica:
- **~$0.20** para procesar los 107 PDFs (~262 chunks, ~320K tokens de entrada)
- ~$0.09 por cada 1M tokens de entrada
- ~$0.35 por cada 1M tokens de salida

---

## 📥 Importar a Anki

Abre Anki, ve a **Archivo → Importar** y selecciona el archivo `.apkg`. Las cartas incluyen:

- **Cara frontal**: pregunta + opciones + imagen (si tiene)
- **Cara trasera**: todo lo anterior + respuesta correcta resaltada en verde + fuente

No necesitas ningún plugin adicional. El mazo se importa con el diseño personalizado incluido.

---

## 🛠️ Requisitos

- Python 3.10+
- pip
- Entorno virtual (recomendado)

Dependencias Python: `pypdf`, `reportlab`, `beautifulsoup4`, `lxml`, `requests`, `weasyprint`, `openai`, `tiktoken`, `genanki`
