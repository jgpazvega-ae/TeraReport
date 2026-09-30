# -*- coding: utf-8 -*-
"""Utilidades de bajo nivel sobre el XML de WordprocessingML.

python-docx no expone cuadros de texto, bookmarks ni saltos de página, y el
machote corporativo depende de los tres. Todo lo que toca el XML directamente
vive aquí para que el resto del código se mantenga legible.
"""

from xml.sax.saxutils import escape

from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

# Formato heredado del machote: Arial, con tres tamaños (16 pt para el nombre
# de la estación, 14 pt para la etiqueta de sección y 12 pt para las viñetas).
_FONT = ('<w:rFonts w:ascii="Arial" w:cs="Arial" w:eastAsia="Arial" '
         'w:hAnsi="Arial"/>')

# numId=3 es la lista con viñetas que ya trae el machote.
BULLET_NUM_ID = 3


# ---------------------------------------------------------------------------
# lectura
# ---------------------------------------------------------------------------

def element_text(el):
    """Texto plano de un elemento, uniendo todos sus <w:t> y normalizando."""
    parts = [t.text or '' for t in el.iter(qn('w:t'))]
    return ' '.join(''.join(parts).split())


def is_page_break_only(p):
    """True si el párrafo solo contiene un salto de página (o está vacío)."""
    if p.tag != qn('w:p'):
        return False
    if element_text(p):
        return False
    for node in p.iter():
        if node.tag in (qn('w:drawing'), qn('w:pict')):
            return False
    return True


def has_page_break(p):
    """True si el parrafo contiene un salto de pagina explicito."""
    if p.tag != qn('w:p'):
        return False
    for node in p.iter(qn('w:br')):
        if node.get(qn('w:type')) == 'page':
            return True
    return False


def is_droppable_tail(el):
    """True si el elemento puede quedar fuera de un bloque sin perder contenido."""
    if el.tag in (qn('w:bookmarkStart'), qn('w:bookmarkEnd')):
        return True
    return is_page_break_only(el)


# ---------------------------------------------------------------------------
# creación de elementos
# ---------------------------------------------------------------------------

def _run(text, bold=False, size=24):
    return (
        '<w:r %s><w:rPr>%s%s<w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr>'
        '<w:t xml:space="preserve">%s</w:t></w:r>'
        % (nsdecls('w'), _FONT, '<w:b/><w:bCs/>' if bold else '', size, size,
           escape(text))
    )


def plain_paragraph(text='', size=24):
    """Párrafo normal en Arial."""
    body = _run(text, size=size) if text else ''
    return parse_xml(
        '<w:p %s><w:pPr><w:rPr>%s<w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr>'
        '</w:pPr>%s</w:p>' % (nsdecls('w'), _FONT, size, size, body))


def page_break_paragraph():
    return parse_xml(
        '<w:p %s><w:pPr><w:rPr>%s<w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr>'
        '</w:pPr><w:r><w:rPr>%s<w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr>'
        '<w:br w:type="page"/></w:r></w:p>' % (nsdecls('w'), _FONT, _FONT))


def station_paragraph(prefix, name):
    """Nombre de la estación: Heading 2, Arial 16 pt."""
    rpr = ('<w:rPr>%s<w:bCs/><w:color w:val="000000"/><w:sz w:val="32"/>'
           '<w:szCs w:val="32"/></w:rPr>' % _FONT)
    runs = ''
    if prefix:
        runs += '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, escape(prefix))
    runs += '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, escape(name))
    return parse_xml(
        '<w:p %s><w:pPr><w:pStyle w:val="Heading2"/><w:ind w:left="10"/>%s</w:pPr>'
        '%s</w:p>' % (nsdecls('w'), rpr, runs))


def section_paragraph(title):
    """Etiqueta de sección: Arial 14 pt en negrita, con nivel de esquema 3."""
    rpr = ('<w:rPr>%s<w:b/><w:bCs/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr>'
           % _FONT)
    return parse_xml(
        '<w:p %s><w:pPr><w:spacing w:after="40" w:before="100" w:line="360" '
        'w:lineRule="auto"/><w:outlineLvl w:val="2"/>%s</w:pPr>'
        '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p>'
        % (nsdecls('w'), rpr, rpr, escape(title)))


def bullet_paragraph(label, text):
    """Viñeta: etiqueta en negrita y el resto en redonda, Arial 12 pt."""
    runs = ''
    if label:
        runs += _run(label, bold=True)
        if text:
            runs += _run(' ' + text)
    else:
        runs += _run(text)
    return parse_xml(
        '<w:p %s><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="%d"/></w:numPr>'
        '<w:spacing w:after="36" w:before="36" w:line="240" w:lineRule="auto"/>'
        '<w:rPr>%s<w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:pPr>%s</w:p>'
        % (nsdecls('w'), BULLET_NUM_ID, _FONT, runs))


def bookmark_start(bm_id, name):
    return parse_xml('<w:bookmarkStart %s w:id="%d" w:name="%s"/>'
                     % (nsdecls('w'), bm_id, escape(name, {'"': '&quot;'})))


def bookmark_end(bm_id):
    return parse_xml('<w:bookmarkEnd %s w:id="%d"/>' % (nsdecls('w'), bm_id))


# ---------------------------------------------------------------------------
# sustitución de texto
# ---------------------------------------------------------------------------

def _set_paragraph_text(p, text):
    """Deja el párrafo con un solo run de texto, conservando su formato.

    Se reutiliza el primer run (y por tanto su <w:rPr>) y se vacían los demás,
    que es la forma segura de escribir en un párrafo cuyo texto Word partió en
    varios runs.
    """
    runs = p.findall(qn('w:r'))
    target = None
    for run in runs:
        for t in run.findall(qn('w:t')):
            if target is None:
                target = t
                t.text = text
                t.set(qn('xml:space'), 'preserve')
            else:
                t.text = ''
    return target is not None


def replace_paragraphs(root, rules, only_textboxes=False):
    """Sustituye párrafos completos cuyo texto contenga alguno de los `rules`.

    `rules` es una lista de pares (texto_a_buscar, texto_nuevo). Se sustituye el
    párrafo entero, no solo la coincidencia, porque en el machote cada campo
    ocupa su propio párrafo (un cuadro de texto en la portada, una celda en la
    tabla de firmas).
    """
    count = 0
    if only_textboxes:
        containers = [tb for tb in root.iter()
                      if tb.tag == qn('w:txbxContent')]
    else:
        containers = [root]

    for container in containers:
        for p in container.iter(qn('w:p')):
            text = element_text(p)
            if not text:
                continue
            for needle, replacement in rules:
                if needle in text:
                    if _set_paragraph_text(p, replacement):
                        count += 1
                    break
    return count


def substitute_placeholders(root, values):
    """Reemplaza {{CLAVE}} por su valor en todo el XML bajo `root`.

    A diferencia de `replace_paragraphs`, aquí sí se respeta el resto del texto
    del párrafo, para que sobreviva lo que el usuario haya escrito alrededor del
    marcador en la plantilla.
    """
    count = 0
    for p in root.iter(qn('w:p')):
        text = element_text(p)
        if '{{' not in text:
            continue
        new_text = text
        for key, value in values.items():
            new_text = new_text.replace('{{%s}}' % key, value)
        if new_text != text:
            if _set_paragraph_text(p, new_text):
                count += 1
    return count


# ---------------------------------------------------------------------------
# bookmarks
# ---------------------------------------------------------------------------

def find_bookmark_range(body, name):
    """Devuelve (índice_inicio, índice_fin) del bloque marcado, o None."""
    children = list(body)
    start = None
    bm_id = None
    for i, el in enumerate(children):
        if el.tag == qn('w:bookmarkStart') and el.get(qn('w:name')) == name:
            start = i
            bm_id = el.get(qn('w:id'))
            break
    if start is None:
        return None
    for j in range(start + 1, len(children)):
        el = children[j]
        if el.tag == qn('w:bookmarkEnd') and el.get(qn('w:id')) == bm_id:
            return start, j
    return None


def delete_bookmark_block(body, name):
    """Elimina el bloque marcado (incluidos sus propios bookmarks)."""
    found = find_bookmark_range(body, name)
    if not found:
        return False
    start, end = found
    for el in list(body)[start:end + 1]:
        body.remove(el)
    return True


def prune_orphan_bookmarks(root):
    """Quita bookmarkStart/End sin pareja, que hacen que Word marque el archivo."""
    starts, ends = {}, {}
    for el in root.iter(qn('w:bookmarkStart')):
        starts[el.get(qn('w:id'))] = el
    for el in root.iter(qn('w:bookmarkEnd')):
        ends[el.get(qn('w:id'))] = el
    removed = 0
    for bm_id, el in list(starts.items()):
        if bm_id not in ends:
            el.getparent().remove(el)
            removed += 1
    for bm_id, el in list(ends.items()):
        if bm_id not in starts:
            el.getparent().remove(el)
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# capacidades nuevas de v2 (confirmadas contra el stack real: ver
# tools/probe_capacidades.py antes de tocar esta sección)
# ---------------------------------------------------------------------------

def toc_field_paragraphs(levels='1-2'):
    """Párrafos de un campo TOC { \\o "1-2" \\h \\z \\u } que Word actualiza
    con F9 o al abrir con "actualizar campos" activado.

    python-docx no tiene API para campos; se escribe el run-de-campo completo
    (begin/instrText/separate/texto-de-marcador-de-posición/end) a mano. El
    texto de marcador de posición es el que se ve hasta el primer F9.
    """
    rpr = '<w:rPr>%s</w:rPr>' % _FONT
    heading = ('<w:p %s><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
              '<w:r>%s<w:t>Índice</w:t></w:r></w:p>') % (nsdecls('w'), rpr)
    field = (
        '<w:p %s>%s'
        '<w:r>%s<w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r>%s<w:instrText xml:space="preserve"> TOC \\o "%s" \\h \\z \\u </w:instrText></w:r>'
        '<w:r>%s<w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r>%s<w:t>Clic derecho → Actualizar campos para generar el índice.</w:t></w:r>'
        '<w:r>%s<w:fldChar w:fldCharType="end"/></w:r>'
        '</w:p>'
    ) % (nsdecls('w'), rpr, rpr, rpr, levels, rpr, rpr, rpr)
    return [parse_xml(heading), parse_xml(field)]


def shade_cell(cell, hex_color):
    """Aplica un color de fondo sólido a una celda de tabla (RRGGBB sin '#')."""
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_pr.append(parse_xml(
        '<w:shd %s w:val="clear" w:color="auto" w:fill="%s"/>'
        % (nsdecls('w'), hex_color)))


def difficulty_bar_cell(cell, level, max_level=5):
    """Pinta la celda con una escala de color según la dificultad (1..5):
    verde (fácil) -> ámbar -> rojo (difícil). Sin dependencias de gráficos:
    solo sombreado de celda, igual que un semáforo en una hoja de cálculo.
    """
    palette = ['C6E0B4', 'E2EFDA', 'FFF2CC', 'FCE4D6', 'F8CBAD']
    try:
        level = max(1, min(max_level, int(level)))
    except (TypeError, ValueError):
        level = 3
    shade_cell(cell, palette[level - 1])


def caption_paragraph(text, label='Foto'):
    """Pie de foto: Arial 10 pt, cursiva, gris, centrado."""
    rpr = ('<w:rPr>%s<w:i/><w:iCs/><w:color w:val="595959"/>'
          '<w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>' % _FONT)
    return parse_xml(
        '<w:p %s><w:pPr><w:jc w:val="center"/>%s</w:pPr>'
        '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p>'
        % (nsdecls('w'), rpr, rpr, escape('%s: %s' % (label, text) if label else text)))
