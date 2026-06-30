# ============================================================================
# Orquestador del proyecto Anki-MIR (PowerShell)
# ============================================================================
# Script que coordina todos los pasos del pipeline:
#   1. Crawling de documentación médica
#   2. Conversión de exámenes MIR originales a PDFs fusionados
#   3. Extracción de preguntas MIR a JSONL
#   4. Generación de preguntas desde documentación médica vía DeepSeek
#   5. Conversión de JSONL a mazo .apkg para Anki
# ============================================================================

param(
    [ValidateSet('crawl', 'convert', 'extract', 'generate', 'anki', 'all')]
    [string]$Step = '',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$StepArgs
)

$ScriptDir = Split-Path -Parent $PSCommandPath
Set-Location $ScriptDir

$VenvDir = Join-Path $ScriptDir ".venv"
$Python = "python3"
$Activate = Join-Path $VenvDir "Scripts\Activate.ps1"

# ─── Colores ─────────────────────────────────────────────────────────────────
$Colors = @{
    Red    = @{ForegroundColor = 'Red'; BackgroundColor = 'Black'}
    Green  = @{ForegroundColor = 'Green'; BackgroundColor = 'Black'}
    Yellow = @{ForegroundColor = 'Yellow'; BackgroundColor = 'Black'}
    Blue   = @{ForegroundColor = 'Cyan'; BackgroundColor = 'Black'}
    Bold   = @{ForegroundColor = 'White'; BackgroundColor = 'Black'}
}

function Write-Color($Color, $Text) {
    $params = $Colors[$Color] + @{Object = $Text}
    Write-Host @params
}

# ─── Funciones auxiliares ────────────────────────────────────────────────────

function Check-Venv {
    if (-not (Test-Path $Activate)) {
        Write-Color 'Yellow' "⚠  Entorno virtual no encontrado. Creándolo..."
        & $Python -m venv $VenvDir
        Write-Color 'Green' "✓ Entorno virtual creado en $VenvDir"
    }
    & $Activate
}

function Check-Deps {
    Write-Color 'Blue' "📦 Instalando dependencias..."
    pip install -q -r requirements.txt
    pip install -q openai tiktoken python-dotenv 2>$null
    pip install -q genanki 2>$null
    Write-Color 'Green' "✓ Dependencias instaladas"
}

function Check-Env {
    $envFile = Join-Path $ScriptDir ".env"
    if (-not (Test-Path $envFile)) {
        Write-Color 'Red' "✗ No se encuentra el archivo .env con DEEPSEEK_API_KEY"
        Write-Host "   Crea un archivo .env con:"
        Write-Host "   DEEPSEEK_API_KEY=tu-api-key"
        exit 1
    }
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^DEEPSEEK_API_KEY=(.+)') {
            $env:DEEPSEEK_API_KEY = $Matches[1]
        }
    }
    if (-not $env:DEEPSEEK_API_KEY) {
        Write-Color 'Red' "✗ DEEPSEEK_API_KEY no está definida en .env"
        exit 1
    }
    Write-Color 'Green' "✓ API Key encontrada"
}

function Print-Banner {
    Write-Color 'Blue' @"
╔══════════════════════════════════════════════════╗
║         🏥  MIR-ANKI  ·  Pipeline completo      ║
║  Exámenes MIR → Flashcards → DeepSeek           ║
╚══════════════════════════════════════════════════╝
"@
}

function Show-Menu {
    Write-Host ""
    Write-Host "Selecciona una opción:" -ForegroundColor White
    Write-Host "  ┌─────────────────────────────────────────────────────┐"
    Write-Host "  │  1  Crawlear documentación médica (NICE, MSD, etc.) │"
    Write-Host "  │  2  Convertir exámenes MIR originales a PDF        │"
    Write-Host "  │  3  Extraer preguntas MIR de PDFs a JSONL          │"
    Write-Host "  │  4  Generar preguntas desde docs médicos (LLM)     │"
    Write-Host "  │  5  Convertir JSONL a mazo .apkg para Anki         │"
    Write-Host "  │  6  Ejecutar TODO el pipeline                      │"
    Write-Host "  │  0  Salir                                          │"
    Write-Host "  └─────────────────────────────────────────────────────┘"
    Write-Host ""
    $script:opt = Read-Host "Opción"
    Write-Host ""
}

# ─── Pasos del pipeline ──────────────────────────────────────────────────────

function Step-Crawl {
    Write-Color 'Blue' "╔══════════════════════════════════════════════╗"
    Write-Color 'Blue' "║  1. Crawleando documentación médica         ║"
    Write-Color 'Blue' "╚══════════════════════════════════════════════╝"
    python3 src/crawl_docs.py @StepArgs
}

function Step-Convert {
    Write-Color 'Blue' "╔══════════════════════════════════════════════╗"
    Write-Color 'Blue' "║  2. Convirtiendo exámenes MIR a PDF         ║"
    Write-Color 'Blue' "╚══════════════════════════════════════════════╝"
    python3 src/convert_mir_to_pdf.py @StepArgs
}

function Step-Extract {
    Write-Color 'Blue' "╔══════════════════════════════════════════════╗"
    Write-Color 'Blue' "║  3. Extrayendo preguntas MIR a JSONL        ║"
    Write-Color 'Blue' "╚══════════════════════════════════════════════╝"
    python3 src/extract_preguntas.py @StepArgs
}

function Step-Generate {
    Write-Color 'Blue' "╔══════════════════════════════════════════════╗"
    Write-Color 'Blue' "║  4. Generando preguntas con DeepSeek (LLM)  ║"
    Write-Color 'Blue' "╚══════════════════════════════════════════════╝"
    Check-Env
    python3 src/generate_preguntas_llm.py @StepArgs
}

function Step-Anki {
    Write-Color 'Blue' "╔══════════════════════════════════════════════╗"
    Write-Color 'Blue' "║  5. Convirtiendo JSONL a mazo .apkg         ║"
    Write-Color 'Blue' "╚══════════════════════════════════════════════╝"
    python3 src/convert_to_anki.py @StepArgs
}

# ─── Main ─────────────────────────────────────────────────────────────────────

Print-Banner
Check-Venv
Check-Deps

# Ejecución directa por parámetro
if ($Step) {
    switch ($Step) {
        'crawl'    { Step-Crawl }
        'convert'  { Step-Convert }
        'extract'  { Step-Extract }
        'generate' { Step-Generate }
        'anki'     { Step-Anki }
        'all'      {
            Step-Crawl
            Step-Convert
            Step-Extract
            Step-Generate
            Step-Anki
            Write-Color 'Green' "✅ Pipeline completo ejecutado."
        }
    }
    exit 0
}

# Menú interactivo
while ($true) {
    Show-Menu
    switch ($opt) {
        '1' { Step-Crawl }
        '2' { Step-Convert }
        '3' { Step-Extract }
        '4' { Step-Generate }
        '5' { Step-Anki }
        '6' {
            Step-Crawl
            Step-Convert
            Step-Extract
            Step-Generate
            Step-Anki
            Write-Color 'Green' "✅ Pipeline completo ejecutado."
        }
        '0' {
            Write-Color 'Green' "¡Hasta luego!"
            exit 0
        }
        default { Write-Color 'Red' "Opción no válida" }
    }
    Write-Host ""
    Read-Host "Presiona Enter para continuar..."
}
