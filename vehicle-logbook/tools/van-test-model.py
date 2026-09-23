# -*- coding: utf-8 -*-
"""Скільки насправді коштує виняток для van (ITA 248(1)(e)(ii)).

Питання, на яке відповідає модель: варто чи не варто тримати особистий
пробіг під 10% до 31.03.2027, щоб авто перестало бути `automobile`.

Відповідь залежить майже виключно від річного пробігу, а його ми поки не
знаємо: перший тиждень (113 км) був нетиповий — багато прорахунків, мало
роз'їздів. Тому модель рахує діапазон, а не одну цифру.

Ключова механіка, через яку інтуїція підводить: standby charge при
бізнес-використанні >50% і особистому пробігу <20 004 км/рік рахується
НЕ від вартості авто, а пропорційно особистому пробігу (ITA 6(2)).
Тобто умова, що дає право на виняток, сама ж зменшує те, від чого
виняток рятує.
"""

C          = 47147.70   # вартість з HST (fleet.vehicles.original_cost)
MONTHS     = 12
CAP_KM     = 20004      # стеля особистого пробігу для зменшеного standby
OP_RATE    = 0.34       # prescribed operating benefit rate, 2026
HST_SB     = 14 / 114   # частка HST зі standby charge, провінції з HST 15%
HST_OP     = 0.11       # частка HST з operating benefit
PERS_RATE  = 0.30       # гранична ставка податку Романа (уточнити)
CORP_RATE  = 0.115      # small business NB: 9% фед + 2.5% пров

full_standby = 0.02 * C * MONTHS


def automobile(total_km, pers_pct):
    """Benefit, якщо авто лишається `automobile` (поточний стан)."""
    pers = total_km * pers_pct
    biz_ok = (1 - pers_pct) > 0.50
    if biz_ok and pers < CAP_KM:
        standby = full_standby * pers / CAP_KM
        operating = min(OP_RATE * pers, 0.5 * standby)   # вибір методу 50%
    else:
        standby = full_standby                            # обрив: повна сума
        operating = OP_RATE * pers
    return standby, operating


def motor_vehicle(total_km, pers_pct, rate):
    """Benefit, якщо виняток спрацював: standby немає, лишається 6(1)(a) —
    «розумна вартість» особистого користування. Оцінка спірна, тому два
    краї: тільки експлуатація (34 c/км) і повна ставка відшкодування."""
    return rate * total_km * pers_pct


print(f'Повний standby (2% x {C:,.2f} x 12) = ${full_standby:,.0f}/рік\n')
print(f'{"км/рік":>8} {"особ.10%":>9} | {"automobile":>22} | {"motor vehicle":>15} | {"різниця":>9}')
print(f'{"":>8} {"":>9} | {"standby":>10}{"operat.":>7}{"HST":>5} | {"34c":>7}{"73/67c":>8} | {"податок":>9}')
print('-' * 78)

for total in (6000, 10000, 15000, 20000, 25000, 30000):
    sb, op = automobile(total, 0.10)
    auto_benefit = sb + op
    hst = sb * HST_SB + op * HST_OP
    mv_lo = motor_vehicle(total, 0.10, OP_RATE)
    mv_hi = motor_vehicle(total, 0.10, 0.70)
    # економія: різниця в benefit x ставка Романа + HST, яку не платить компанія
    save_hi = (auto_benefit - mv_lo) * PERS_RATE + hst
    save_lo = (auto_benefit - mv_hi) * PERS_RATE + hst
    print(f'{total:>8,} {total*0.10:>9,.0f} | {sb:>10,.0f}{op:>7,.0f}{hst:>5,.0f} |'
          f' {mv_lo:>7,.0f}{mv_hi:>8,.0f} | {save_lo:>4,.0f}-{save_hi:<4,.0f}')

print('\nОбрив: коли особистий пробіг >= 20 004 км або бізнес <= 50% —')
print('зменшений standby не діє, нараховується повна сума:')
for total, pp in ((30000, 0.50), (40000, 0.50), (45000, 0.45)):
    sb, op = automobile(total, pp)
    print(f'  {total:,} км, особисте {int(pp*100)}% = {total*pp:,.0f} км -> '
          f'standby ${sb:,.0f} + operating ${op:,.0f} = ${sb+op:,.0f}')

print('\nОдноразові й фіксовані переваги class 10 проти 10.1 (не залежать від пробігу):')
print(f'  HST ITC не обмежений стелею:       ${0.15*40998 - 0.15*39000:>8,.0f} разово')
print(f'  база CCA більша на $2 298:         ${2297.70*CORP_RATE:>8,.0f} за весь строк')
print(f'  відсотки понад $350/міс ({840:,}/рік): ${840*CORP_RATE:>8,.0f} на рік, поки є кредит')
print('  terminal loss при продажу дозволений (для 10.1 заборонений) — сума невідома')
