# -*- coding: utf-8 -*-
"""Друкований логбук на перехідний період.

Телефон як трекер виявився ненадійним (Samsung душить фоновий GPS), апаратний
трекер ще не куплений. Поки його немає, первинним записом стає папір — CRA
приймає саме таку форму, і зшита книга з послідовними сторінками виглядає
надійніше за експорт із бази.

Генерує один PDF: довідкова сторінка, перенос уже записаних поїздок і чисті
бланки. Letter landscape — у Канаді друкують на Letter, не на A4.
"""
import csv, sys
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdfmetrics.registerFont(TTFont('DJ',  '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DJB', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))

PAGE = landscape(letter)          # 792 x 612
W, H = PAGE
M    = 0.5 * inch                 # поля під дірокол і палітурку

# Колонки: чотири перші — те, що CRA вимагає буквально. Одометр не вимагається
# per-trip, але робить книгу самоперевірною: сусідні рядки мають зійтися.
COLS = [
    ('Дата\nDate',                    58),
    ('Водій\nDriver',                 52),
    ('Звідки\nFrom',                 108),
    ('Куди\nDestination',            128),
    ('Мета поїздки\nPurpose',        170),
    ('Одометр\nстарт',                58),
    ('Одометр\nфініш',                58),
    ('Км\nKm',                        44),
    ('Б/О\nB/P',                      36),
]
TABLE_W  = sum(w for _, w in COLS)
ROW_H    = 28
HEAD_H   = 24
TOTAL_H  = 22
TITLE_H  = 34


def header(c, title, sub=''):
    c.setFont('DJB', 13)
    c.drawString(M, H - M - 12, title)
    if sub:
        c.setFont('DJ', 8.5)
        c.setFillGray(0.35)
        c.drawRightString(W - M, H - M - 12, sub)
        c.setFillGray(0)


def table_head(c, y):
    c.setFont('DJB', 7.5)
    x = M
    c.setLineWidth(0.9)
    c.line(M, y, M + TABLE_W, y)
    c.line(M, y - HEAD_H, M + TABLE_W, y - HEAD_H)
    for name, w in COLS:
        ua, en = name.split('\n')
        c.drawString(x + 3, y - 10, ua)
        c.setFont('DJ', 6.5)
        c.setFillGray(0.45)
        c.drawString(x + 3, y - 19, en)
        c.setFillGray(0)
        c.setFont('DJB', 7.5)
        c.line(x, y, x, y - HEAD_H)
        x += w
    c.line(x, y, x, y - HEAD_H)
    return y - HEAD_H


def rows(c, y, n, data=None):
    """Малює n рядків; data — список кортежів для вже відомих поїздок."""
    c.setLineWidth(0.4)
    for i in range(n):
        y2 = y - ROW_H
        c.line(M, y2, M + TABLE_W, y2)
        x = M
        for j, (_, w) in enumerate(COLS):
            c.line(x, y, x, y2)
            if data and i < len(data):
                val = data[i][j]
                if val:
                    # спершу зменшуємо кегль, і лише потім ріжемо: обрізана на
                    # півслові адреса в журналі виглядає як недбалий запис
                    size = 7.0
                    while size > 5.5 and pdfmetrics.stringWidth(val, 'DJ', size) > w - 6:
                        size -= 0.25
                    while pdfmetrics.stringWidth(val, 'DJ', size) > w - 6 and len(val) > 1:
                        val = val[:-2] + '…'
                    c.setFont('DJ', size)
                    c.drawString(x + 3, y2 + 10, val)
            x += w
        c.line(x, y, x, y2)
        y = y2
    return y


def total_row(c, y):
    y2 = y - TOTAL_H
    c.setLineWidth(0.9)
    c.rect(M, y2, TABLE_W, TOTAL_H)
    x = M
    for _, w in COLS[:-2]:
        x += w
    c.line(x, y, x, y2)
    c.line(x + COLS[-2][1], y, x + COLS[-2][1], y2)
    c.setFont('DJB', 7.5)
    c.drawRightString(x - 6, y2 + 8, 'Разом за сторінку / Page total')
    return y2


def footer(c, page, note=''):
    c.setFont('DJ', 7)
    c.setFillGray(0.45)
    c.drawString(M, M - 6, note)
    c.drawRightString(W - M, M - 6, f'стор. {page}')
    c.setFillGray(0)


def cover(c):
    y = H - M
    c.setFont('DJB', 17)
    c.drawString(M, y - 16, 'ROTES SMART Construction Inc.')
    c.setFont('DJ', 11)
    c.drawString(M, y - 34, 'Журнал поїздок службового авто · Vehicle Logbook')
    c.setLineWidth(1)
    c.line(M, y - 44, W - M, y - 44)

    left_x, right_x = M, M + 380
    ty = y - 70

    def block(x, yy, title, lines, wide=330):
        c.setFont('DJB', 9.5)
        c.drawString(x, yy, title)
        yy -= 15
        c.setFont('DJ', 8.5)
        for a, b in lines:
            c.drawString(x, yy, a)
            if b is None:                       # місце під ручку
                c.setLineWidth(0.4)
                c.line(x + 155, yy - 2, x + wide, yy - 2)
            else:
                c.setFont('DJB', 8.5)
                c.drawString(x + 155, yy, b)
                c.setFont('DJ', 8.5)
            yy -= 14
        return yy - 8

    ny = block(left_x, ty, 'АВТО / VEHICLE', [
        ('Марка, модель, рік',  '2025 Chrysler Pacifica Limited'),
        ('VIN',                 '2C4RC1GGXSR535286'),
        ('Номерний знак',       None),
        ('Власник',             'ROTES SMART Construction Inc.'),
        ('Придбано',            '16.09.2026'),
        ('Податковий рік',      '1 квітня — 31 березня'),
        ('BN',                  '744375015RC0001'),
    ])

    ny = block(left_x, ny, 'ОДОМЕТР / ODOMETER', [
        ('На день придбання',   '47 321 км  (розрахунок)'),
        ('Звірено по фото',     '47 333 км  ·  17.09.2026 14:07'),
        ('На 01.04.2026',       '— (авто ще не куплене)'),
        ('На 31.03.2027',       None),
    ])

    c.setFont('DJ', 7.5)
    c.setFillGray(0.35)
    c.drawString(left_x, ny + 2, '47 321 — похідне число. Замінити цифрою з bill of sale, коли буде на руках.')
    c.setFillGray(0)

    # Праворуч — те, заради чого книга взагалі ведеться.
    ry = ty
    c.setFont('DJB', 9.5)
    c.drawString(right_x, ry, 'ЩО CRA ВИМАГАЄ ПО КОЖНІЙ ПОЇЗДЦІ')
    ry -= 16
    c.setFont('DJ', 8.5)
    for i, t in enumerate(['дата', 'пункт призначення', 'мета поїздки', 'кілометраж'], 1):
        c.drawString(right_x + 8, ry, f'{i}.  {t}')
        ry -= 13
    ry -= 4
    c.setFont('DJ', 7.5)
    c.setFillGray(0.35)
    c.drawString(right_x, ry, 'Плюс одометр на початок і кінець податкового року.')
    c.setFillGray(0)
    ry -= 22

    c.setFont('DJB', 9.5)
    c.drawString(right_x, ry, 'ЯК ЗАПОВНЮВАТИ')
    ry -= 16
    c.setFont('DJ', 8.5)
    for t in [
        'Записувати одразу після поїздки, а не в кінці тижня.',
        'Журнал, відновлений по памʼяті, втрачає доказову силу.',
        '',
        'Мета — це імʼя або обʼєкт, не «робота»:',
        '«Duncan Crowther — замір вікон», «Home Hardware — кріплення».',
        '',
        'Особисті поїздки теж записувати. Журнал зі 100% бізнесу —',
        'червоний прапор для аудитора, а не перемога.',
        '',
        'Не стирати і не замальовувати. Помилка — закреслити одним',
        'рядком і написати поруч.',
        '',
        'Б/О: Б — бізнес, О — особисте.',
    ]:
        c.drawString(right_x, ry, t)
        ry -= 12

    ry -= 10
    c.setFont('DJB', 9.5)
    c.drawString(right_x, ry, 'НЕ ЗАБУТИ')
    ry -= 16
    c.setFont('DJ', 8.5)
    for t in [
        'Зберігати чеки: журнал доводить кілометри, чеки — вартість.',
        'Зняти одометр 31.03.2027 — кінець податкового року компанії.',
        'Тест 90% для van: вікно 16.09.2026 — 31.03.2027.',
    ]:
        c.drawString(right_x, ry, t)
        ry -= 12

    c.setFont('DJB', 9.5)
    c.drawString(left_x, 150, 'ЦЯ КНИГА')
    c.setFont('DJ', 8.5)
    c.setLineWidth(0.4)
    for i, t in enumerate(['Книга №', 'Період з', 'по']):
        yy = 132 - i * 16
        c.drawString(left_x, yy, t)
        c.line(left_x + 60, yy - 2, left_x + 230, yy - 2)

    footer(c, 1, 'Довідкова сторінка · не для записів')
    c.showPage()


def main(csv_path, out_path, blank_pages=20):
    data = []
    with open(csv_path, encoding='utf-8') as f:
        for r in csv.DictReader(f, delimiter='|'):
            if r['d'] == 'd':
                continue
            dest = r['destination_address']
            data.append((
                '.'.join(reversed(r['d'].split('-')[1:])),   # 22.09
                'Roman',
                r['origin_address'],
                dest,
                r['p'] or '—',
                '', '',                                       # одометр вписати вручну
                f"{float(r['distance_km']):.1f}",
                'Б' if r['classification'] == 'business' else '?',
            ))

    c = canvas.Canvas(out_path, pagesize=PAGE)
    c.setTitle('ROTES SMART Construction Inc. — Vehicle Logbook')
    cover(c)

    page = 2
    per = 16
    for i in range(0, len(data), per):
        header(c, 'Перенесено з GPS-журналу · 16–22.09.2026',
               'записано автоматично до переходу на папір')
        y = table_head(c, H - M - TITLE_H)
        y = rows(c, y, per, data[i:i + per])
        total_row(c, y)
        footer(c, page, 'Одометр по цих поїздках не фіксувався — колонки лишаються порожніми.')
        c.showPage()
        page += 1

    for _ in range(blank_pages):
        header(c, 'Журнал поїздок · Vehicle Logbook',
               'ROTES SMART Construction Inc. · 2025 Chrysler Pacifica · 2C4RC1GGXSR535286')
        y = table_head(c, H - M - TITLE_H)
        y = rows(c, y, per)
        total_row(c, y)
        footer(c, page)
        c.showPage()
        page += 1

    c.save()
    print(f'{out_path}: {page - 1} стор., перенесено {len(data)} поїздок')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
