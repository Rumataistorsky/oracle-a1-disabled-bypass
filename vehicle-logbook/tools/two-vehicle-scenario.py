# -*- coding: utf-8 -*-
"""Pacifica тільки робоча, Mitsubishi тільки особистий — що це міняє.

Рішення від 23.09.2026. Раптом виявляється, що воно перевертає пріоритети:
головна цінність не у винятку для van, а в самому журналі.
"""
C_INCL   = 47147.70    # з HST
ITC_10   = 0.15 * 40998        # повний ITC, якщо motor vehicle
ITC_101  = 0.15 * 39000        # ITC зі стелею, якщо passenger vehicle
BASE_10  = C_INCL - ITC_10
BASE_101 = 39000.0             # стеля класу 10.1, до податків
CORP     = 0.115               # small business NB
full_sb  = 0.02 * C_INCL * 12

print('=== 1. Standby charge при майже нульовому особистому пробігу ===')
print(f'Повний standby, якщо журналу немає:            ${full_sb:>9,.0f}/рік')
for pers in (0, 200, 500, 1000):
    print(f'  зменшений при {pers:>5,} особистих км:            ${full_sb*pers/20004:>9,.0f}/рік')
print()
print('Зменшений standby діє, якщо бізнес >50% пробігу І особисте <20 004 км.')
print('Довести це може ТІЛЬКИ журнал. Без нього - повна сума.')
print(f'Тобто журнал сам по собі коштує до ${full_sb:,.0f}/рік, а виняток для van')
print('на цьому полі не додає майже нічого: віднімати вже нема від чого.')

print('\n=== 2. CCA: class 10 проти 10.1 за 5 років ===')
def cca(base, rate=0.30, first=0.30, years=5):
    """first=0.30 - AII у фазі згортання: 2 x (30%/2). Уточнити коефіцієнт 2026."""
    ucc, total, rows = base, 0.0, []
    for y in range(1, years+1):
        d = ucc * (first if y == 1 else rate)
        ucc -= d; total += d
        rows.append((y, d, ucc))
    return rows, total, ucc

r10,  t10,  u10  = cca(BASE_10)
r101, t101, u101 = cca(BASE_101)
print(f'{"рік":>4} {"class 10 CCA":>13} {"UCC":>10} | {"class 10.1 CCA":>15} {"UCC":>10}')
for (y,d,u),(_,d2,u2) in zip(r10, r101):
    print(f'{y:>4} {d:>13,.0f} {u:>10,.0f} | {d2:>15,.0f} {u2:>10,.0f}')
print(f'{"разом":>4} {t10:>13,.0f} {"":>10} | {t101:>15,.0f}')
print(f'\nбаза: class 10 ${BASE_10:,.0f} (ITC ${ITC_10:,.0f}) проти 10.1 ${BASE_101:,.0f} (ITC ${ITC_101:,.0f})')
print(f'різниця в загальній амортизації за 5 років: ${t10-t101:,.0f} -> податок ${(t10-t101)*CORP:,.0f}')
print(f'різниця в ITC (разово):                     ${ITC_10-ITC_101:,.0f}')

print('\n=== 3. Продаж через 5 років — тут class 10 програє ===')
for price in (10000, 14000, 18000):
    rec10 = price - u10          # >0 = recapture (дохід), <0 = terminal loss
    print(f'  продаж за ${price:>6,}:  UCC class 10 ${u10:,.0f} -> ', end='')
    if rec10 > 0:
        print(f'RECAPTURE +${rec10:,.0f} у дохід (податок ${rec10*CORP:,.0f})')
    else:
        print(f'terminal loss ${-rec10:,.0f} у витрати (економія ${-rec10*CORP:,.0f})')
print('  class 10.1: ні recapture, ні terminal loss - нічого. Завжди $0.')
print('\nPacifica тримає ціну краще, ніж 30% спадним залишком, тож імовірніший')
print('recapture, а не terminal loss. Тоді відсутність recapture у 10.1 - це')
print('перевага 10.1, а не недолік. Я раніше писав навпаки.')
