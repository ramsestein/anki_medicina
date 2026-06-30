# 🏥 MIR-Anki

**Flashcards tipo test MIR para Anki** — listas para descargar e importar.

Este proyecto contiene **mazos de Anki con preguntas de examen MIR** ya preparadas, con imágenes incluidas y diseño bonito. Además, incluye un *pipeline* para generar nuevas preguntas desde documentación médica usando inteligencia artificial.

---

## 🎯 ¿Solo quieres estudiar? Descarga las flashcards ya listas

Si solo quieres usar las flashcards sin complicarte con informática:

1. **Descarga** este proyecto: ve a https://github.com/ramsestein/anki_medicina, haz clic en el botón verde **`<> Code`** → **`Download ZIP`**, y descomprime el archivo en tu ordenador.
2. **Abre Anki** (si no lo tienes, descárgalo gratis desde https://apps.ankiweb.net).
3. En Anki, ve a **Archivo → Importar** y selecciona el archivo que quieras de la carpeta `tarjetas_anki/`:
   - **`preguntas_mir.apkg`** → 927 preguntas de exámenes MIR reales (2021-2025), con imágenes
   - **`preguntas_medicas.apkg`** → Preguntas generadas desde documentación médica
4. ¡A estudiar! 🎉

> Los mazos ya están procesados y listos para usar. Conforme generemos más preguntas nuevas, se añadirán más archivos `.apkg` a la carpeta `tarjetas_anki/`.

---

## ✨ ¿Qué hace el proyecto completo?

Si además quieres **generar tus propias preguntas** usando inteligencia artificial, el pipeline completo hace esto:

1. **Descarga** documentación médica de fuentes como NICE, MSD Manuals, etc.
2. **Convierte** los exámenes MIR originales en PDFs fusionados
3. **Extrae** las preguntas MIR reales a un formato estructurado
4. **Genera** nuevas preguntas tipo test desde la documentación médica usando **DeepSeek** (una IA), imitando el estilo de las preguntas MIR
5. **Convierte** todo a mazos `.apkg` para Anki con diseño bonito e imágenes

---

## 📁 Estructura del proyecto

```
anki-medicina/
├── tarjetas_anki/           # 🃏 MAZOS LISTOS PARA IMPORTAR EN ANKI
│   ├── preguntas_mir.apkg       # 927 preguntas MIR con imágenes
│   └── preguntas_medicas.apkg   # Preguntas generadas por IA
│
├── src/                     # 🔧 Código (solo si quieres generar más)
├── data/                    # 📊 Datos intermedios
├── docs/                    # 📄 PDFs de documentación médica
├── orquestador.sh           # Script para Linux/Mac
├── orquestador.ps1          # Script para Windows
├── requirements.txt         # Dependencias
└── README.md                # Este archivo
```

> **👆 Si solo quieres estudiar**, solo necesitas la carpeta `tarjetas_anki/`. Ignora el resto.

---

## 🚀 Para quien quiera generar más preguntas (conocimientos básicos de informática)

Si ya tienes el proyecto descargado y quieres generar nuevas preguntas desde la documentación médica usando IA:

### 1. Requisitos

Necesitas tener instalado:
- **Python 3.10 o superior** (descárgalo de https://www.python.org/downloads/)
- **Git** (opcional, descárgalo de https://git-scm.com/downloads)

### 2. Descargar el proyecto

**Opción A — Con Git (recomendado):**
```bash
git clone https://github.com/ramsestein/anki_medicina.git
cd anki_medicina
```

**Opción B — Sin Git:**
1. Ve a https://github.com/ramsestein/anki_medicina
2. Haz clic en el botón verde **`<> Code`** → **`Download ZIP`**
3. Descomprime el archivo en una carpeta

### 3. Ejecutar el orquestador (menú interactivo)

**En Linux o Mac:**
```bash
./orquestador.sh
```

**En Windows:** haz doble clic en `orquestador.ps1` o ejecuta en PowerShell:
```powershell
.\orquestador.ps1
```

El menú te guiará paso a paso. La primera vez instalará todo automáticamente.

### 4. Pasos individuales (para quien quiera control fino)

```bash
# 1. Crawlear documentación médica
python3 src/crawl_docs.py

# 2. Convertir exámenes MIR originales a PDF
python3 src/convert_mir_to_pdf.py

# 3. Extraer preguntas MIR a JSONL
python3 src/extract_preguntas.py

# 4. Generar preguntas con IA (DeepSeek) — necesitas API key
python3 src/generate_preguntas_llm.py --reset

# 5. Convertir JSONL a mazo .apkg para Anki
python3 src/convert_to_anki.py
```

### 5. (Opcional) Configurar API key de DeepSeek

Para el paso 4 (generar preguntas con IA), necesitas una clave de API de DeepSeek:
1. Ve a https://platform.deepseek.com/ y crea una cuenta
2. Ve a la sección de API Keys y genera una nueva clave
3. Crea un archivo llamado `.env` en la carpeta del proyecto con este contenido:
   ```
   DEEPSEEK_API_KEY=sk-pon-aqui-tu-clave
   ```

> 📌 **¿Cuánto cuesta?** Generar preguntas con DeepSeek cuesta aproximadamente **20 céntimos de dólar** por cada 100 PDFs procesados. Es muy económico.
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

## 📊 Datos disponibles

| Archivo | Descripción | ¿Necesitas hacer algo? |
|---|---|---|
| `tarjetas_anki/preguntas_mir.apkg` | **927 preguntas** de exámenes MIR 2021-2025, con 75 imágenes | ✅ **Ya listo** — solo importar en Anki |
| `tarjetas_anki/preguntas_medicas.apkg` | Preguntas generadas por DeepSeek desde documentación médica | ⏳ **En crecimiento** — se añadirán más conforme las generemos |
| `data/preguntas_mir.jsonl` | Datos intermedios de las 927 preguntas MIR | 🔧 Solo si quieres regenerar |
| `data/preguntas_medicas.jsonl` | Datos intermedios de las preguntas generadas | 🔧 Solo si quieres regenerar |

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
