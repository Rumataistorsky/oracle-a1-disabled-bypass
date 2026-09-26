# cacomply - AI compliance pre-check сайтів під канадське законодавство (прототип)

Пайплайн: **скрапер → Markdown → база правил (по юрисдикціях) → механічні перевірки → LLM-аудит (Claude) → звіт зі штрафами → fix pack**.
Ідея взята з хакатону Hub71 (UAE + free zones), адаптована під матрицю "федеральний закон + провінція".

## Що перевіряє

| Файл правил | Закон | Юрисдикція |
|---|---|---|
| `rules/canada/casl.yaml` | CASL (anti-spam): opt-in, ідентифікація відправника, unsubscribe, трекери | federal |
| `rules/canada/pipeda.yaml` | PIPEDA: privacy policy, цілі збору, privacy officer, права доступу, трансфери | federal |
| `rules/canada/competition_act.yaml` | Competition Act: drip pricing, "was/now" ціни, greenwashing, відгуки, "free" | federal |
| `rules/canada/quebec_law25.yaml` | Law 25: трекери off by default, відповідальна особа, політика, згода, трансфери, права | QC |
| `rules/canada/bill96.yaml` | Charter of the French Language (Bill 96): французька версія, договори, маркування | QC |
| `rules/canada/aoda.yaml` | AODA / WCAG 2.0 AA: alt, lang, labels, accessibility statement, навігація | ON |
| `rules/canada/consumer_protection.yaml` | Ontario CPA, Quebec CPA: internet agreements, підписки, all-inclusive price | ON, QC |

33 правила. Кожне має `requirement`, `check` (що шукати), `penalty`, `penalty_max_cad`, `source`, `fix_hint`.
Частина правил має `auto_fail_when` — вираз над сигналами, який вирішує правило без LLM
(наприклад `email_signup_form and prechecked_checkboxes > 0` для CASL-01).

Нова юрисдикція (EU, UA для Космоса) = нова папка `rules/<name>/*.yaml` з тією ж схемою плюс, за потреби, нові сигнали в `signals.py`.

## Архітектура

```
cacomply/
  crawl.py     BFS по сайту (пріоритет: privacy, terms, contact, cookies, pricing, fr), HTML → Markdown; є офлайн-режим для папки
  signals.py   ~45 механічних сигналів: форми, pre-checked чекбокси, трекери (GA, Meta, Hotjar...), cookie banner,
               alt/lang/labels, drip pricing, sale claims, green claims, підписки, згадки QC/ON, французька версія
  rules.py     завантаження YAML, вибір правил за провінцією + applies_when
  audit.py     auto-findings із сигналів + ClaudeAuditor (structured output, PageAudit) + злиття по правилах
  report.py    Markdown-звіт: summary, таблиця статутних максимумів по законах, findings з evidence/fix, disclaimer
  fixes.py     fix pack: готові HTML-сніпети та тексти політик (EN + FR для Квебеку)
  cli.py       python -m cacomply audit ...
```

LLM: `claude-opus-5`, adaptive thinking, `output_config.effort`, structured output через `client.messages.parse(output_format=PageAudit)`,
system prompt кешується (`cache_control`). Модель отримує одну сторінку + сигнали + правила і повертає по одному finding на правило
(`pass | fail | unclear | not_applicable`, evidence — тільки дослівна цитата). Правила, які вже провалились механічно, моделі не передаються.

## Запуск

```bash
cd compliance-audit-ca
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...

# повний аудит сайту, бізнес працює в Онтаріо та Квебеку
python -m cacomply audit https://example.ca --provinces ON,QC --out report.md --json findings.json --fixes fixes.md

# тільки механічні перевірки, без ключа (правила без auto-вердикту позначаються REVIEW)
python -m cacomply audit https://example.ca --provinces ON --no-llm

# офлайн: папка з HTML (так працюють тести)
python -m cacomply audit tests/fixtures/site --local --provinces ON,QC --no-llm

# список правил
python -m cacomply rules --law casl
```

Код виходу: `1`, якщо є FAIL (зручно для CI), `0` — чисто, `2` — помилка.

## Тести

```bash
PYTHONPATH=. python -m pytest -q
```

Fixture-сайт `tests/fixtures/site` містить навмисні порушення: pre-checked чекбокс розсилки, немає privacy policy, GA + Meta Pixel без банера,
"plus fees at checkout", "Was $299 / Now $199", eco-friendly claims, підписка з автопродовженням, картинки без alt, сторінка без `lang`,
згадка Montréal без французької версії. Механічний режим ловить 13 правил, решта 20 йде на LLM-перевірку.

## Що далі

1. Реальний прогін на 5-10 канадських Shopify-магазинах, калібрування промпту (false positives по `unclear`).
2. Автофікс через PR: якщо репо публічне, взяти fix pack і відкрити PR (GitHub API); для Shopify — theme snippets.
3. Окремі бази правил `rules/eu/` (GDPR, ePrivacy, DSA, EAA, AI Act) і `rules/ua/` для Космоса.
4. Cookie-банер: перевірка через headless Chromium (які трекери реально вантажаться до згоди), а не тільки за HTML.
5. Оцінка ризику по обороту бізнесу (Law 25: 2–4% turnover, Competition Act: 3% revenue) замість статутних максимумів.

## Обмеження

- Не юридична порада. Це pre-check перед юристом; у звіті є disclaimer.
- Статутні максимуми у звіті — для пріоритизації, а не прогноз штрафу.
- Cookie-банер і трекери визначаються за статичним HTML: SPA та відкладене завантаження скриптів потребують headless-браузера.
- Законодавство рухоме: Ontario CPA 2023, Bill C-27/CPPA, поправки до Competition Act 2024–2025 — перевіряти `source` у правилах перед продакшеном.
