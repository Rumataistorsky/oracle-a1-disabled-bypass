#!/usr/bin/env python3
# Навчити receipt-bot читати дату з імені файлу конвеєра Immich.
import io, shutil, sys

p = '/opt/agent/receipt-bot.js'
s = io.open(p, encoding='utf-8').read()

old = "  const scanTs = /_(\\d{2})(\\d{2})(\\d{2})\\d{6}_/.exec(filename);\n"
new = (
    "  // Конвеєр Immich кладе сюди файли з іменем immich-YYYYMMDDHHMMSS-<asset>.\n"
    "  // Дата знімка — така сама надійна верхня межа, як дата сканування: чек\n"
    "  // фотографують у момент покупки або пізніше, ніколи раніше. Штамп у UTC,\n"
    "  // тож межа може зсунутись на добу вперед — це послаблює її, не звужує.\n"
    "  const immichTs = /^immich-(\\d{4})(\\d{2})(\\d{2})\\d{6}-/.exec(filename);\n"
    "  const scanTs = immichTs\n"
    "    ? [immichTs[0], immichTs[1].slice(2), immichTs[2], immichTs[3]]\n"
    "    : /_(\\d{2})(\\d{2})(\\d{2})\\d{6}_/.exec(filename);\n"
)

if new in s:
    print('already patched'); sys.exit(0)
if s.count(old) != 1:
    print('ANCHOR NOT FOUND, count=%d' % s.count(old)); sys.exit(1)

shutil.copy2(p, p + '.bak-20260927-immichdate')
io.open(p, 'w', encoding='utf-8').write(s.replace(old, new, 1))
print('patched')
