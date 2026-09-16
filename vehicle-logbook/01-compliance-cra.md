# 01 — Вимоги CRA і розрахунок benefit

## Обовʼязкові поля логбука

CRA вимагає по кожній поїздці рівно чотири речі:

| Поле | Приклад |
|---|---|
| **Дата** | 2026-09-16 |
| **Пункт призначення** | 47 Maple Dr, Dartmouth NS |
| **Мета** | Замір — заміна покрівлі |
| **Кілометри** | 34 |

Плюс **показник одометра на початок і кінець податкового року** по авто.

Чого CRA **не** вимагає: імені клієнта, номера телефону, назви компанії,
підтвердження, що поїздка призвела до доходу.

```
Business % = business km ÷ total km × 100
```

### Дім = офіс

Домашня адреса є principal place of business компанії. Отже поїздка
`Home office → обʼєкт/клієнт/постачальник` — **бізнес-кілометри**, а не
commuting. Кожен запис у логбуку починається з `Home office`.

Умова: дім має бути principal place of business фактично — там ведеться
основна діяльність, зберігається документація, зареєстрована адреса компанії.

### Поїздки на оцінку без даних клієнта

Виїзд на замір/оцінку — повноцінна бізнес-поїздка незалежно від результату.
Бізнес-мета визначається наміром на момент поїздки, а не тим, чи підписано
контракт. Програні тендери і «клієнт передумав» лишаються бізнес-км.

Адреса в полі «пункт призначення» достатня. Для міцності запису додаємо
корпоративні докази — див. `05-n8n-workflows.md`:

* конкретна мета (`Замір — підʼїзна доріжка`, не `робота`);
* гео-фото обʼєкта (Immich, LXC 400) — timestamp + GPS доводять присутність;
* lead-запис в Invoice Ninja з адресою замість імені + чернетка quote.

### Base year і спрощений метод

* Перші повні 12 місяців — **повний логбук**.
* Далі можна вести **3-місячну вибірку**, якщо business % не відхиляється
  більше ніж на 10 процентних пунктів від base year.
* Base-year логбук зберігати **6 років** після останнього року використання.

> Base year не можна відтворити заднім числом. Облік стартує з дня набуття
> авто, навіть якщо це ручна таблиця.

## Розрахунок taxable benefit

### Вхідні дані

```
Original cost (з HST)         C = $47 148
Періодів доступності на рік   P = 12   (30-денних)
Operating benefit rate 2026       34¢ / особистий км
Поріг зниження standby            20 004 км особистих на рік
```

### Standby charge

```
Повний:     Standby = 2% × C × P
                    = 0.02 × 47 148 × 12
                    = $11 315.52

Знижений:   доступний якщо  business km ≥ 50% від total
                       і    personal km ≤ 20 004

            Standby_reduced = Standby × (personal km / 20 004)
```

### Operating cost benefit

```
Operating = 0.34 × personal km
```

Альтернатива: 50% від standby charge до відшкодувань — лише якщо standby
включено, бізнес-використання >50%, і працівник письмово повідомив
роботодавця **до кінця року**.

### Таблиця результатів

| Особистих км/рік | Standby | Operating | **T4 benefit** |
|---:|---:|---:|---:|
| 1 000 | $566 | $340 | **$906** |
| 3 000 | $1 697 | $1 020 | **$2 717** |
| 5 000 | $2 828 | $1 700 | **$4 528** |
| 10 000 | $5 656 | $3 400 | **$9 056** |
| 15 000 | $8 485 | $5 100 | **$13 585** |
| *без логбука* | $11 316 | 0.34 × **всі** км | **$15 000+** |

### Зменшення benefit

* **Відшкодування компанії** протягом **45 днів** після кінця року за
  особисті операційні витрати → operating benefit = 0.
* **Пряма оплата третій стороні.** Якщо працівник платить АЗС напряму
  (особиста картка, готівка), частина, що припадає на особисте використання,
  віднімається від operating benefit. **Умова — записи, що доводять пряму
  оплату третій стороні.** Тому чек обовʼязковий незалежно від того, хто платив.

## Ліміти для passenger vehicle, 2026

| Позиція | Ліміт | Наслідок для цього авто |
|---|---|---|
| CCA, class 10.1 | $39 000 + податки = **$44 850** | фактична вартість $47 148 → **$2 298 не амортизуються ніколи** |
| Ставка CCA | 30% спадним залишком, half-year rule | застосування AII до class 10.1 у 2026 **уточнити в бухгалтера** |
| Відсотки по кредиту | **$350/міс** | фактичні ≈$420/міс у перший рік → ~$850/рік не вираховується |
| Лізинг | $1 100/міс | н/д (купівля) |
| HST ITC | 15% × $39 000 = **$5 850** | сплачено $6 150 → **$300 не повертається**; ITC вимагає бізнес-використання >50% |

## Що це означає для системи

Система мусить достовірно рахувати **три** величини:

1. `personal_km` за рік, по кожній особі — для standby і operating benefit;
2. `business_km` за рік — для перевірки порогу ≥50%;
3. `odometer` на 1 січня і 31 грудня — фото з панелі приладів.

І зберігати докази бізнес-мети по кожній поїздці (адреса + мета + фото/lead).

## Контрольний список на кінець року

- [ ] Фото одометра 31 грудня та 1 січня (Nextcloud, папка року)
- [ ] Логбук закритий, business % розрахований
- [ ] Перевірка: business ≥ 50%? personal ≤ 20 004?
- [ ] Річний PDF-експорт логбука → Nextcloud, розшарено бухгалтеру
- [ ] Відшкодування особистих operating costs **до 14 лютого**
- [ ] Письмове повідомлення роботодавцю про вибір 50%-методу (якщо застосовно) — **до 31 грудня**
- [ ] Розрахунок standby + operating передано на T4
- [ ] Архів року переведений у незмінний вигляд, retention 7 років

## Джерела

* [Automobile provided by the employer — Canada.ca](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/benefits-allowances/automobile/automobile-motor-vehicle-benefits/automobile.html)
* [2026 Automobile Deduction Limits — Department of Finance Canada](https://www.canada.ca/en/department-finance/news/2026/01/government-announces-the-2026-automobile-deduction-limits-and-expense-benefit-rates-for-businesses.html)
* [Automobile Standby Charge Benefit — TaxTips.ca](https://www.taxtips.ca/smallbusiness/automobile-standby-charge-benefit.htm)
* [Passenger Vehicle Expense Limitations — TaxTips.ca](https://www.taxtips.ca/smallbusiness/passenger-vehicle-limits.htm)
* [GST/HST Input Tax Credits for Vehicles — TaxTips.ca](https://www.taxtips.ca/gst/gst-input-tax-credits-vehicles-and-aircraft.htm)
* [Automobile expenses and recordkeeping — BDO Canada](https://www.bdo.ca/insights/tax-bulletin-automobile-expenses-and-recordkeeping)
* [Automobile Use by Employees — Baker Tilly Canada](https://www.bakertilly.ca/insights/automobile-use-by-employees)
