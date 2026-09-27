#!/usr/bin/env python3
# Звірка арифметики чека перед записом.
import io, shutil, sys

p = '/opt/agent/receipt-bot.js'
s = io.open(p, encoding='utf-8').read()

old = """  const receipt = {
    ...extracted,
    card:          classifyCard(extracted.card_last4),
    originalFile:  filename,
    localPath,
    remotePath,
  };
"""

new = """  // Арифметика чека — єдина перевірка, яку можна зробити без людини.
  // Спостережено 27.09.2026 на чеку Fredericton HHBC: ROG записав підсумок
  // 36.77, податок 4.80, разом 31.97 — тобто переставив підсумок і разом
  // місцями. Наслідок гірший за саму цифру: перевірка дублікатів шукає
  // рядок за сумою «разом», не знаходить скан того самого чека і заводить
  // другу витрату. Якщо перестановка повертає рівність — міняємо назад;
  // якщо ні, лишаємо як є і кажемо про це вголос.
  {
    const sub = Number(extracted.subtotal);
    const tax = Number(extracted.tax);
    const tot = Number(extracted.total);
    const ok  = (a, b) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) < 0.01;
    if (Number.isFinite(sub) && Number.isFinite(tax) && Number.isFinite(tot) && !ok(sub + tax, tot)) {
      if (ok(tot + tax, sub)) {
        console.log(`[receipt] Subtotal/total look swapped for ${filename} (${sub}/${tax}/${tot}) — swapping`);
        extracted.subtotal = tot;
        extracted.total    = sub;
      } else {
        console.log(`[receipt] Totals do not add up for ${filename}: ${sub} + ${tax} != ${tot}`);
        await tgSendText(`\\u26a0\\ufe0f \\u0421\\u0443\\u043c\\u0438 \\u043d\\u0435 \\u0441\\u0445\\u043e\\u0434\\u044f\\u0442\\u044c\\u0441\\u044f: <code>${filename}</code>\\n` +
                         `${sub} + ${tax} \\u2260 ${tot} \\u2014 \\u043f\\u0435\\u0440\\u0435\\u0432\\u0456\\u0440 \\u0440\\u0443\\u043a\\u0430\\u043c\\u0438`);
      }
    }
  }

  const receipt = {
    ...extracted,
    card:          classifyCard(extracted.card_last4),
    originalFile:  filename,
    localPath,
    remotePath,
  };
"""

if 'Subtotal/total look swapped' in s:
    print('already patched'); sys.exit(0)
if s.count(old) != 1:
    print('ANCHOR NOT FOUND, count=%d' % s.count(old)); sys.exit(1)

shutil.copy2(p, p + '.bak-20260927-totals')
io.open(p, 'w', encoding='utf-8').write(s.replace(old, new, 1))
print('patched')
