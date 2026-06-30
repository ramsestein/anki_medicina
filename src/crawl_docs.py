#!/usr/bin/env python3
"""
Crawler de documentos médicos - MIR Anki Project
================================================
Lee los links base de list_links.txt, navega recursivamente por cada sitio web,
descarga documentos (PDF) o convierte páginas HTML a PDF, y los guarda
organizadamente en docs/

Uso:
  python3 src/crawl_docs.py                     # Ejecución normal
  python3 src/crawl_docs.py --dry-run            # Solo muestra qué haría
  python3 src/crawl_docs.py --max-pages 50       # Límite de páginas por sitio
  python3 src/crawl_docs.py --max-depth 3        # Profundidad máxima
  python3 src/crawl_docs.py --delay 2.0          # Delay entre requests (seg)
  python3 src/crawl_docs.py --resume             # Reanudar desde cache
"""

import os
import re
import sys
import time
import json
import math
import signal
import hashlib
import argparse
import threading
import urllib.parse
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from weasyprint import HTML as WeasyHTML

# ─── Constants ───────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent  # /home/ramses/Proyectos/Anki
LINKS_FILE = BASE_DIR / "list_links.txt"
OUTPUT_DIR = BASE_DIR / "docs"
CACHE_DIR = BASE_DIR / "docs" / ".crawler_cache"

REQUEST_TIMEOUT = 30  # segundos
DEFAULT_DELAY = 1.5   # segundos entre requests
DEFAULT_MAX_PAGES = 500  # máximo de páginas a procesar por sitio
DEFAULT_MAX_DEPTH = 4    # profundidad máxima de crawl

# User-Agent respetable
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; MIR-Anki-Crawler/1.0; "
        "+https://github.com/ramses/anki-mir)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def slugify(text, max_len=80):
    """Convierte texto en un nombre de archivo seguro."""
    text = text.strip().lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text[:max_len].strip('-')


def url_to_filename(url, ext=".pdf"):
    """Convierte una URL en un nombre de archivo único."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip('/').replace('/', '_')
    if not path:
        path = 'index'
    # Limitar longitud
    if len(path) > 100:
        h = hashlib.md5(url.encode()).hexdigest()[:8]
        path = path[:90] + '_' + h
    return path + ext


def domain_from_url(url):
    """Extrae el dominio base de una URL."""
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.replace('www.', '')


def is_same_domain(url, base_domain):
    """Comprueba si una URL pertenece al mismo dominio base."""
    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.replace('www.', '')
        return domain == base_domain or domain.endswith('.' + base_domain)
    except Exception:
        return False


def is_valid_scheme(url):
    """Comprueba si la URL tiene un esquema válido."""
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in ('http', 'https')


def is_printable_url(url):
    """Filtra URLs que no son páginas de contenido."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    # Excluir rutas no deseadas
    excluded_patterns = [
        '/login', '/logout', '/register', '/signup',
        '/cart', '/checkout', '/payment',
        '/search', '/api/', '/widget',
        '/tag/', '/category/', '/archive',
        '.css', '.js', '.json', '.xml', '.rss',
        '.ico', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
        '.woff', '.woff2', '.ttf', '.eot',
        '.mp4', '.mp3', '.avi', '.mov',
        '.zip', '.tar', '.gz',
        '#', 'javascript:', 'mailto:', 'tel:',
    ]
    for pat in excluded_patterns:
        if pat in path:
            return False
    return True


def download_pdf(url, output_path):
    """Descarga un PDF directamente."""
    try:
        resp = SESSION.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        resp.raise_for_status()
        content_type = resp.headers.get('Content-Type', '')
        if 'pdf' not in content_type.lower():
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"    ⚠ Error descargando PDF {url}: {e}")
        return False


def convert_html_to_pdf(url, output_path, timeout=120):
    """
    Convierte una página HTML a PDF usando WeasyPrint.
    Con timeout para evitar que páginas muy pesadas bloqueen el crawler.
    """
    result = {'success': False, 'error': None}
    thread = threading.Thread(target=_weasy_print, args=(url, output_path, result))

    thread.daemon = True
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        print(f"    ⚠ Timeout ({timeout}s) convirtiendo: {url}")
        return False

    if not result['success']:
        print(f"    ⚠ Error: {result['error']}")
        return False

    return True


def _weasy_print(url, output_path, result):
    """Ejecuta WeasyPrint en un hilo separado."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        WeasyHTML(url=url).write_pdf(str(output_path))
        result['success'] = True
    except Exception as e:
        result['error'] = str(e)


def extract_links(soup, base_url):
    """Extrae todos los enlaces relevantes de una página HTML."""
    links = set()
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()
        # Resolver URL relativa
        absolute = urllib.parse.urljoin(base_url, href)
        # Eliminar fragmentos
        absolute = urllib.parse.urldefrag(absolute)[0]
        if is_valid_scheme(absolute) and is_printable_url(absolute):
            links.add(absolute)
    return links


def is_pdf_link(url, soup=None):
    """Detecta si una URL apunta a un PDF."""
    if url.lower().endswith('.pdf'):
        return True
    if soup:
        # Buscar indicadores de PDF en la página
        for link in soup.find_all('a', href=True):
            href = link['href'].lower()
            text = link.get_text(strip=True).lower()
            if href.endswith('.pdf'):
                return True
            if any(w in text for w in ['pdf', 'download', 'descargar', 'pdf version']):
                if any(w in href for w in ['.pdf', 'download', 'pdf']):
                    return True
    return False


# ─── Site-specific crawlers ──────────────────────────────────────────────────

def crawl_generic(base_url, output_dir, max_pages, max_depth, delay, dry_run, cache):
    """
    Crawl genérico para sitios web estándar.
    Sigue enlaces dentro del mismo dominio y convierte páginas HTML a PDF.
    """
    domain = domain_from_url(base_url)
    visited = cache.get('visited', set())
    queue = [(base_url, 0)]
    processed = 0
    skipped_extensions = {'.pdf', '.mp4', '.mp3', '.zip', '.png', '.jpg', '.jpeg', '.gif'}

    while queue and processed < max_pages:
        url, depth = queue.pop(0)
        if url in visited or depth > max_depth:
            continue

        visited.add(url)
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()

        # Si es PDF, descargarlo directamente
        if ext == '.pdf':
            rel_path = urllib.parse.urlparse(url).path.strip('/')
            if not rel_path:
                rel_path = f"doc_{hashlib.md5(url.encode()).hexdigest()[:8]}"
            out_file = output_dir / rel_path
            if not out_file.exists():
                if dry_run:
                    print(f"  [DRY-RUN] Descargaría PDF: {url}")
                else:
                    print(f"  ↓ Descargando PDF: {url}")
                    download_pdf(url, out_file)
                    time.sleep(delay)
                processed += 1
            continue
        elif ext in skipped_extensions:
            continue

        # HTML page - fetch and convert
        try:
            if dry_run:
                print(f"  [DRY-RUN] Visitaría: {url} (depth={depth})")
                resp_text = None
            else:
                print(f"  → Visitando: {url} (depth={depth})")
                resp = SESSION.get(url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                resp_text = resp.text

            # Verificar Content-Type
            if not dry_run:
                ct = resp.headers.get('Content-Type', '')
                if 'html' not in ct.lower():
                    continue

            soup = BeautifulSoup(resp_text, 'lxml') if resp_text else None

            # Generar nombre de archivo
            if soup and soup.title and soup.title.string:
                title = soup.title.string.strip()
            else:
                title = url_to_filename(url).replace('.pdf', '')
            safe_title = slugify(title) if title else url_to_filename(url).replace('.pdf', '')

            # Crear estructura de directorios basada en la ruta URL
            parsed = urllib.parse.urlparse(url)
            url_path = parsed.path.strip('/')
            if url_path:
                path_parts = url_path.split('/')
                # Los primeros 1-2 segmentos como directorios, el resto en nombre
                if len(path_parts) > 2:
                    subdir = '/'.join(path_parts[:-1])
                    filename = slugify(path_parts[-1]) + '.pdf'
                else:
                    subdir = ''
                    filename = safe_title + '.pdf'
            else:
                subdir = ''
                filename = safe_title + '.pdf'

            page_dir = output_dir / subdir
            out_file = page_dir / filename

            # Si el archivo ya existe, añadir sufijo
            counter = 1
            while out_file.exists():
                base = out_file.stem
                out_file = page_dir / f"{base}_{counter}.pdf"
                counter += 1

            if not dry_run:
                print(f"    ↪ Convirtiendo a PDF: {out_file.name}")
                success = convert_html_to_pdf(url, out_file)
                if success:
                    processed += 1
                time.sleep(delay)
            else:
                processed += 1

            # Extraer más enlaces para seguir crawleando (solo mismo dominio)
            if soup and depth < max_depth:
                new_links = extract_links(soup, url)
                for link in new_links:
                    if is_same_domain(link, domain) and link not in visited:
                        queue.append((link, depth + 1))

        except requests.exceptions.RequestException as e:
            print(f"    ⚠ Error de red: {e}")
            time.sleep(delay * 2)
        except Exception as e:
            print(f"    ⚠ Error inesperado: {e}")

    cache['visited'] = visited
    return processed


def crawl_nice(base_url, output_dir, max_pages, max_depth, delay, dry_run, cache):
    """
    Crawler específico para NICE Guidelines (nice.org.uk/guidance/published).
    Busca guías publicadas y descarga sus PDFs.
    """
    visited = cache.get('visited', set())
    processed = 0
    domain = 'nice.org.uk'

    try:
        if dry_run:
            print(f"  [DRY-RUN] Visitaría: {base_url}")
        else:
            print(f"  → Visitando página de guías NICE: {base_url}")
            resp = SESSION.get(base_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'lxml')

            # Buscar enlaces a guías individuales
            # Las guías NICE suelen estar en /guidance/XXXX
            guide_links = set()
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/guidance/' in href and not href.endswith('/published'):
                    full_url = urllib.parse.urljoin(base_url, href)
                    full_url = urllib.parse.urldefrag(full_url)[0]
                    if full_url not in visited:
                        guide_links.add(full_url)

            print(f"    Encontradas {len(guide_links)} guías potenciales")

            for glink in list(guide_links)[:max_pages]:
                if processed >= max_pages:
                    break
                if glink in visited:
                    continue
                visited.add(glink)

                try:
                    print(f"    → Procesando guía: {glink}")
                    gresp = SESSION.get(glink, timeout=REQUEST_TIMEOUT)
                    gresp.raise_for_status()
                    gsoup = BeautifulSoup(gresp.text, 'lxml')

                    # Buscar título
                    title_tag = gsoup.find('h1') or gsoup.find('title')
                    title = title_tag.get_text(strip=True) if title_tag else slugify(glink)

                    # Buscar enlace a PDF
                    pdf_url = None
                    for a in gsoup.find_all('a', href=True):
                        href = a['href']
                        text = a.get_text(strip=True).lower()
                        if href.endswith('.pdf') or 'pdf' in text or 'download' in text:
                            pdf_url = urllib.parse.urljoin(glink, href)
                            break

                    safe_title = slugify(title)
                    out_file = output_dir / f"{safe_title}.pdf"

                    if pdf_url and not out_file.exists():
                        print(f"      ↓ Descargando PDF: {safe_title}.pdf")
                        download_pdf(pdf_url, out_file)
                    elif not out_file.exists():
                        print(f"      ↪ Convirtiendo HTML a PDF: {safe_title}.pdf")
                        convert_html_to_pdf(glink, out_file)

                    processed += 1
                    time.sleep(delay)

                except Exception as e:
                    print(f"      ⚠ Error: {e}")
                    time.sleep(delay)

            # Paginación - siguiente página
            next_page = soup.find('a', string=re.compile(r'next|siguiente|›|»', re.I))
            if next_page and next_page.get('href') and processed < max_pages:
                next_url = urllib.parse.urljoin(base_url, next_page['href'])
                if next_url not in visited:
                    p = crawl_nice(next_url, output_dir, max_pages - processed,
                                   max_depth, delay, dry_run, cache)
                    processed += p

    except Exception as e:
        print(f"  ⚠ Error en NICE crawler: {e}")

    cache['visited'] = visited
    return processed


def is_msd_article_page(soup, url):
    """
    Determina si una URL de MSD Manuals es un artículo real o una página índice.
    Los artículos reales tienen: URL profunda (≥4 segmentos), título <h1>,
    contenido sustancial, y NO son páginas de listado.
    """
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip('/')
    segments = path.split('/')

    # Las URL de categoría superficial (≤3 segmentos) son índices
    # Ej: /home/symptoms, /home/first-aid, /home/digestive-disorders
    if len(segments) <= 3:
        return False

    # Un artículo tiene un <h1> y contenido de texto significativo
    h1 = soup.find('h1')
    if not h1:
        return False

    # Buscar contenido textual real (no menús/navegación)
    # Los artículos MSD tienen un <article> o <main> o div.contenido
    has_article_tag = bool(soup.find(['article', 'main']))
    # O buscar un div con mucho texto
    text_blocks = soup.find_all(['p', 'li', 'h2', 'h3', 'h4'])
    text_content = sum(len(b.get_text(strip=True)) for b in text_blocks if len(b.get_text(strip=True)) > 50)
    has_real_content = text_content > 300

    # Los índices tienen muchos enlaces densos y poco texto real
    links_count = len(soup.find_all('a'))
    links_density = links_count / max(len(soup.get_text(strip=True)), 1)

    is_index = links_density > 0.15 and not has_real_content

    return has_real_content and not is_index


def crawl_msd_manual(base_url, output_dir, max_pages, max_depth, delay, dry_run, cache):
    """
    Crawler específico para MSD Manuals (msdmanuals.com).
    Sigue la estructura jerárquica: categorías → subcategorías → artículos.
    Solo convierte a PDF las páginas que son artículos reales (no índices).
    Las páginas índice se usan solo para extraer enlaces.
    """
    visited = cache.get('visited', set())
    processed = 0
    domain = domain_from_url(base_url)
    queue = [(base_url, 0)]

    while queue and processed < max_pages:
        url, depth = queue.pop(0)
        if url in visited or depth > max_depth:
            continue
        visited.add(url)

        try:
            if dry_run:
                print(f"  [DRY-RUN] Visitaría: {url} (depth={depth})")
                continue

            resp = SESSION.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'lxml')

            title_tag = soup.find('h1') or soup.find('title')
            title = title_tag.get_text(strip=True) if title_tag else ""
            safe_title = slugify(title) if title else url_to_filename(url).replace('.pdf', '')

            # Determinar si es artículo real o página índice
            is_article = is_msd_article_page(soup, url)

            if is_article:
                # Artículo real → convertir a PDF
                parsed = urllib.parse.urlparse(url)
                path_parts = parsed.path.strip('/').split('/')
                # Usar estructura: docs/msd-manual/<categoria>/<articulo>.pdf
                if len(path_parts) > 3:
                    subdir = '/'.join(path_parts[1:-1])  # saltar 'home'
                else:
                    subdir = ''
                page_dir = output_dir / subdir
                page_dir.mkdir(parents=True, exist_ok=True)

                out_file = page_dir / f"{safe_title}.pdf"
                counter = 1
                while out_file.exists():
                    out_file = page_dir / f"{safe_title}_{counter}.pdf"
                    counter += 1

                print(f"  → Artículo: {title[:70]} ({url})")
                print(f"    ↪ PDF: {out_file.name}")
                convert_html_to_pdf(url, out_file)
                time.sleep(delay)
                processed += 1
            else:
                if depth <= 2:
                    print(f"  → Índice: {title or url} (extrayendo enlaces...)")
                # Página índice: solo extraer enlaces, no generar PDF

            # Extraer enlaces (tanto desde artículos como desde índices)
            if depth < max_depth:
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    full = urllib.parse.urljoin(url, href)
                    full = urllib.parse.urldefrag(full)[0]
                    if (is_same_domain(full, domain) and full not in visited
                            and is_printable_url(full)):
                        queue.append((full, depth + 1))

        except Exception as e:
            print(f"    ⚠ Error: {e}")
            time.sleep(delay)

    cache['visited'] = visited
    return processed


def crawl_ncbi_bookshelf(base_url, output_dir, max_pages, max_depth, delay, dry_run, cache):
    """
    Crawler para NCBI Bookshelf (ncbi.nlm.nih.gov/books/).
    Busca libros y descarga sus capítulos como PDF.
    """
    visited = cache.get('visited', set())
    processed = 0
    domain = 'ncbi.nlm.nih.gov'

    try:
        if dry_run:
            print(f"  [DRY-RUN] Visitaría: {base_url}")
        else:
            print(f"  → Visitando NCBI Bookshelf: {base_url}")
            resp = SESSION.get(base_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'lxml')

            # Buscar enlaces a libros
            book_links = set()
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/books/NBK' in href or '/bookshelf/br.fcgi' in href:
                    full_url = urllib.parse.urljoin(base_url, href)
                    full_url = urllib.parse.urldefrag(full_url)[0]
                    book_links.add(full_url)

            print(f"    Encontrados {len(book_links)} libros potenciales")

            for bl in list(book_links)[:max_pages]:
                if processed >= max_pages:
                    break
                if bl in visited:
                    continue
                visited.add(bl)

                try:
                    print(f"    → Procesando libro: {bl}")
                    bresp = SESSION.get(bl, timeout=REQUEST_TIMEOUT)
                    bresp.raise_for_status()
                    bsoup = BeautifulSoup(bresp.text, 'lxml')

                    # Buscar título
                    title_tag = bsoup.find('h1') or bsoup.find('title')
                    title = title_tag.get_text(strip=True) if title_tag else slugify(bl)
                    safe_title = slugify(title)

                    # Intentar descargar PDF del libro completo
                    pdf_found = False
                    for a in bsoup.find_all('a', href=True):
                        href = a['href']
                        text = a.get_text(strip=True).lower()
                        if href.endswith('.pdf') or 'download' in text or 'pdf' in text:
                            pdf_url = urllib.parse.urljoin(bl, href)
                            out_file = output_dir / f"{safe_title}.pdf"
                            if not out_file.exists():
                                print(f"      ↓ Descargando PDF: {safe_title}.pdf")
                                download_pdf(pdf_url, out_file)
                                processed += 1
                                pdf_found = True
                            time.sleep(delay)
                            break

                    if not pdf_found:
                        # Convertir página principal del libro a PDF
                        out_file = output_dir / f"{safe_title}.pdf"
                        if not out_file.exists():
                            print(f"      ↪ Convirtiendo a PDF: {safe_title}.pdf")
                            convert_html_to_pdf(bl, out_file)
                            processed += 1
                        time.sleep(delay)

                except Exception as e:
                    print(f"      ⚠ Error: {e}")
                    time.sleep(delay)

    except Exception as e:
        print(f"  ⚠ Error en NCBI crawler: {e}")

    cache['visited'] = visited
    return processed


def crawl_libretexts(base_url, output_dir, max_pages, max_depth, delay, dry_run, cache):
    """
    Crawler para LibreTexts (med.libretexts.org).
    """
    return crawl_generic(base_url, output_dir, max_pages, max_depth, delay, dry_run, cache)


def crawl_openwho(base_url, output_dir, max_pages, max_depth, delay, dry_run, cache):
    """
    Crawler para OpenWHO (openwho.org).
    OpenWHO usa Kaltura (JS-heavy), el contenido se carga dinámicamente.
    Intentamos: sitemap.xml, /courses, /about/courses, o patrones comunes.
    """
    visited = cache.get('visited', set())
    processed = 0

    # Posibles URLs donde podría haber listados de cursos
    course_listings = [
        base_url,
        urllib.parse.urljoin(base_url, '/courses'),
        urllib.parse.urljoin(base_url, '/courses/'),
        urllib.parse.urljoin(base_url, '/about'),
    ]

    try:
        for page_url in course_listings:
            if processed >= max_pages:
                break
            if page_url in visited:
                continue

            if dry_run:
                print(f"  [DRY-RUN] Visitaría: {page_url}")
                continue

            print(f"  → Visitando: {page_url}")
            try:
                resp = SESSION.get(page_url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
            except requests.RequestException:
                continue

            soup = BeautifulSoup(resp.text, 'lxml')

            # Buscar enlaces a cursos con varios patrones comunes
            course_links = set()
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text(strip=True).lower()
                # Patrones típicos de LMS/Cursos online
                if any(p in href for p in ['/course/', '/courses/', '/learn/',
                                            '/program/', '/training/', '/c/']):
                    full_url = urllib.parse.urljoin(page_url, href)
                    full_url = urllib.parse.urldefrag(full_url)[0]
                    if full_url not in visited:
                        course_links.add(full_url)
                # También detectar por texto
                elif any(w in text for w in ['course', 'curso', 'program', 'training']):
                    full_url = urllib.parse.urljoin(page_url, href)
                    full_url = urllib.parse.urldefrag(full_url)[0]
                    if full_url not in visited:
                        course_links.add(full_url)

            if course_links:
                print(f"    Encontrados {len(course_links)} enlaces a cursos")

            for cl in list(course_links)[:max_pages]:
                if processed >= max_pages:
                    break
                if cl in visited:
                    continue
                visited.add(cl)

                try:
                    print(f"    → Procesando: {cl}")
                    cresp = SESSION.get(cl, timeout=REQUEST_TIMEOUT)
                    if cresp.status_code == 200:
                        title = BeautifulSoup(cresp.text, 'lxml').title
                        title_str = title.get_text(strip=True) if title else slugify(cl)
                        safe_title = slugify(title_str)

                        out_file = output_dir / f"{safe_title}.pdf"
                        if not out_file.exists():
                            print(f"      ↪ Convirtiendo a PDF: {safe_title}.pdf")
                            convert_html_to_pdf(cl, out_file)
                            processed += 1
                        time.sleep(delay)
                except Exception as e:
                    print(f"      ⚠ Error: {e}")
                    time.sleep(delay)

            if not course_links:
                print(f"    ⚠ No se encontraron cursos. OpenWHO usa carga dinámica (JavaScript).")
                print(f"      Prueba a abrir https://openwho.org/courses en un navegador.")

    except Exception as e:
        print(f"  ⚠ Error en OpenWHO crawler: {e}")

    cache['visited'] = visited
    return processed


# ─── Site router ─────────────────────────────────────────────────────────────

SITE_HANDLERS = {
    'nice.org.uk': ('nice', crawl_nice),
    'msdmanuals.com': ('msd-manual', crawl_msd_manual),
    'ncbi.nlm.nih.gov': ('ncbi-bookshelf', crawl_ncbi_bookshelf),
    'med.libretexts.org': ('med-libretexts', crawl_libretexts),
    'openwho.org': ('openwho', crawl_openwho),
}


def get_handler(url):
    """Devuelve el manejador apropiado para una URL."""
    domain = domain_from_url(url)
    for key, (name, handler) in SITE_HANDLERS.items():
        if key in domain:
            return name, handler
    # Fallback al genérico
    domain_clean = domain.replace('.', '_')
    return domain_clean, crawl_generic


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Crawler de documentos médicos - MIR Anki Project"
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Solo muestra lo que haría sin ejecutar')
    parser.add_argument('--max-pages', type=int, default=DEFAULT_MAX_PAGES,
                        help=f'Máximo de páginas a procesar por sitio (default: {DEFAULT_MAX_PAGES})')
    parser.add_argument('--max-depth', type=int, default=DEFAULT_MAX_DEPTH,
                        help=f'Profundidad máxima de crawl (default: {DEFAULT_MAX_DEPTH})')
    parser.add_argument('--delay', type=float, default=DEFAULT_DELAY,
                        help=f'Segundos entre requests (default: {DEFAULT_DELAY})')
    parser.add_argument('--resume', action='store_true',
                        help='Reanudar desde cache (evita reprocesar URLs)')
    args = parser.parse_args()

    print("=" * 70)
    print("  CRAWLER DE DOCUMENTOS MÉDICOS - MIR Anki Project")
    print("=" * 70)
    print()

    # Leer links base
    if not LINKS_FILE.exists():
        print(f"ERROR: No se encuentra {LINKS_FILE}")
        sys.exit(1)

    with open(LINKS_FILE, 'r') as f:
        base_links = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]

    print(f"📋 {len(base_links)} URLs base encontradas en {LINKS_FILE}")
    print()

    # Cache de URLs visitadas (para reanudar)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    total_processed = 0
    total_errors = 0

    for i, url in enumerate(base_links, 1):
        site_name, handler = get_handler(url)
        site_output = OUTPUT_DIR / site_name
        site_output.mkdir(parents=True, exist_ok=True)

        cache_file = CACHE_DIR / f"{site_name}_cache.json"
        cache = {}
        if args.resume and cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    cache = json.load(f)
                # JSON guarda listas, convertir a set para usar .add()
                if 'visited' in cache and isinstance(cache['visited'], list):
                    cache['visited'] = set(cache['visited'])
                print(f"🔄 Reanudando {site_name} desde cache ({len(cache['visited'])} URLs ya visitadas)")
            except Exception:
                cache = {}

        print(f"\n{'─' * 50}")
        print(f"  [{i}/{len(base_links)}] {site_name}")
        print(f"  URL: {url}")
        print(f"  Destino: {site_output}")
        print(f"{'─' * 50}")

        try:
            n = handler(url, site_output, args.max_pages, args.max_depth,
                        args.delay, args.dry_run, cache)
            total_processed += n
            print(f"\n  ✅ {site_name}: {n} documentos procesados")
        except Exception as e:
            print(f"\n  ❌ {site_name}: ERROR - {e}")
            total_errors += 1

        # Guardar cache
        if not args.dry_run:
            try:
                # Limitar tamaño de cache serializable (convertir set a list)
                cache_serializable = {
                    'visited': list(cache.get('visited', set())),
                    'timestamp': datetime.now().isoformat()
                }
                with open(cache_file, 'w') as f:
                    json.dump(cache_serializable, f)
            except Exception as e:
                print(f"    ⚠ No se pudo guardar cache: {e}")

        print()

    # Resumen final
    print("=" * 70)
    print("  RESUMEN FINAL")
    print("=" * 70)
    print(f"  Total sitios procesados: {len(base_links)}")
    print(f"  Total documentos generados: {total_processed}")
    print(f"  Errores: {total_errors}")
    print()
    print(f"  📁 Los documentos están en: {OUTPUT_DIR}")
    print()

    # Mostrar estructura
    print("  Estructura generada:")
    for item in sorted(OUTPUT_DIR.iterdir()):
        if item.is_dir() and not item.name.startswith('.'):
            pdf_count = len(list(item.glob('**/*.pdf')))
            print(f"    📂 {item.name}/ ({pdf_count} PDFs)")
        elif item.is_file() and item.suffix == '.pdf':
            size = item.stat().st_size / (1024 * 1024)
            print(f"    📄 {item.name} ({size:.1f} MB)")

    print()


if __name__ == "__main__":
    main()
