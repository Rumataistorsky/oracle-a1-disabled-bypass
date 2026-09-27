// ─────────────────────────────────────────────────────────────────────────────
// fix-immich-dates-20260927.js — разова правка, вже застосована 27.09.2026.
// Лишається в репо як запис того, що саме змінено в книгах.
//
// receipt-bot розібрав 6 чеків із конвеєра Immich, не маючи в імені файлу
// шаблону дати від Canon. Без цієї підстраховки ROG нагалюцинував рік:
// п'ять чеків стали 2023-м, один 2020-м. Гірше за саму дату те, що перевірка
// дублікатів шукає рядок у місячному аркуші — а в «09 23» і «09 20» скану з
// Canon не було, тож п'ять витрат завелися вдруге.
//
// Що з чим збігається, встановлено арифметикою, не на око:
//   Fredericton HHBC — у рядку з Immich підсумок 36.77, податок 4.80,
//   «разом» 31.97. Але 31.97 + 4.80 = 36.77 рівно, а скан 0355 записав
//   разом 36.77. Той самий чек, у якого переплутано підсумок і разом.
//   Shaw Group Limited — 1017.78 + 151.77 = 1169.55, а не 1163.55. Зате
//   1163.55 − 151.77 = 1011.78, і 1011.78 × 0.15 = 151.77 рівно. Отже
//   разом прочитано правильно, а в підсумку сплутано цифру.
//
// Скрипт за замовчуванням лише показує, що зробив би. Пише тільки з --apply.
// ─────────────────────────────────────────────────────────────────────────────
require('dotenv').config({ path: '/opt/agent/.env' });
const { google } = require('googleapis');

const APPLY = process.argv.includes('--apply');
const GOOGLE_CREDENTIALS  = '/opt/agent/google-credentials.json';
const BILS_SHEET_ID       = '19kvzur1Eim1TPVnarp3GYkan1yOYbBkBkQlAJsLT0t8';
const GDRIVE_SHARED_DRIVE = 'ROTES Corporation';
const GDRIVE_BASE_FOLDER  = 'Orders and Invoice ROTes SMART';
const IN_BASE             = process.env.INVOICE_NINJA_BASE || 'https://invoices.rotes.ca/api/v1';
const IN_TOKEN            = process.env.INVOICE_NINJA_TOKEN;

// twin — скан того самого чека з Canon, заведений раніше і правильно.
const ENTRIES = [
  { file: '2023-09-15-8811Supplies-0000-ShawBrickPre-36.80.JPG',        sheet: '09 23',
    expense: 'MYerk04aOB', act: 'delete', twin: '0378 → 2026-09-23 ShawGroup 36.80' },
  { file: '2023-09-23-8811Supplies-0000-ShawBrick-345.00.JPG',          sheet: '09 23',
    expense: 'l9av2g0aG1', act: 'delete', twin: '0374 → 2026-09-23 ShawGroup 345.00' },
  { file: '2023-09-24-8811Supplies-0000-ShawGroupLimited-1163.55.JPG',  sheet: '09 23',
    expense: 'LDdwpj1e1Y', act: 'redate', newDate: '2026-09-24', fixSubtotal: '1011.78' },
  { file: '2023-09-25-8811Supplies-0000-FrederictonHHBC-31.97.JPG',     sheet: '09 23',
    expense: 'X7axkG3eyv', act: 'delete', twin: '0355 → 2026-09-25 FrederictonHHBC 36.77' },
  { file: '2023-09-26-8811Supplies-7620-Scholtens-156.17.JPG',          sheet: '09 23',
    expense: 'zPdyP8EbQr', act: 'delete', twin: '0377 → 2026-09-26 Scholtens 156.17' },
  { file: '2020-09-26-8811Supplies-0000-EvergreenTraders-206.88.JPG',   sheet: '09 20',
    expense: 'xkazpmZdJ0', act: 'delete', twin: '0379 → 2026-09-26 EvergreenTraders 206.88' },
];

async function auth(scopes) {
  return new google.auth.GoogleAuth({ keyFile: GOOGLE_CREDENTIALS, scopes }).getClient();
}
async function inRequest(p, options = {}) {
  const r = await fetch(`${IN_BASE}${p}`, {
    ...options,
    headers: { 'X-API-TOKEN': IN_TOKEN, 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  if (!r.ok) throw new Error(`Ninja HTTP ${r.status} ${p}: ${(await r.text()).slice(0, 300)}`);
  return r.json();
}

// Рядок шукаємо за id файлу в посиланні на Drive (колонка J), а не за сумою:
// у «09 23» лежать справжні записи вересня 2023-го, зачепити їх не можна.
async function findRow(sheets, sheetName, fileId) {
  let res;
  try {
    res = await sheets.spreadsheets.values.get({
      spreadsheetId: BILS_SHEET_ID, range: `'${sheetName}'!A4:K`,
    });
  } catch { return null; }
  const rows = res.data.values || [];
  for (let i = 0; i < rows.length; i++) {
    if ((rows[i][9] || '').includes(fileId)) return { rowNumber: i + 4, values: rows[i] };
  }
  return null;
}

// Перший порожній рядок у колонці A. Саме сюди пишемо через values.update.
// values.append із діапазоном A4:K тут не годиться: Sheets сам вирішує, де
// починається «таблиця», і під час правки поклав значення з колонки J —
// перші два потрапили в J і K, решта зникла. Помічено й виправлено вручну.
async function firstFreeRow(sheets, sheetName) {
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId: BILS_SHEET_ID, range: `'${sheetName}'!A4:A`,
  });
  const col = res.data.values || [];
  for (let i = 0; i < col.length; i++) {
    if (!(col[i] && String(col[i][0] || '').trim())) return i + 4;
  }
  return col.length + 4;
}

async function folderFor(drive, driveId, year, month) {
  let parent = driveId;
  for (const name of ['ROTes Incorporation', GDRIVE_BASE_FOLDER, year, `${year}-${month}`]) {
    const res = await drive.files.list({
      q: `name='${name}' and mimeType='application/vnd.google-apps.folder' and '${parent}' in parents and trashed=false`,
      driveId, corpora: 'drive', includeItemsFromAllDrives: true, supportsAllDrives: true,
      fields: 'files(id,name)',
    });
    if (!res.data.files.length) {
      if (!APPLY) return null;
      const made = await drive.files.create({
        requestBody: { name, mimeType: 'application/vnd.google-apps.folder', parents: [parent] },
        supportsAllDrives: true, fields: 'id',
      });
      parent = made.data.id;
    } else parent = res.data.files[0].id;
  }
  return parent;
}

(async () => {
  const drive  = google.drive({ version: 'v3', auth: await auth(['https://www.googleapis.com/auth/drive']) });
  const sheets = google.sheets({ version: 'v4', auth: await auth(['https://www.googleapis.com/auth/spreadsheets']) });

  const drives = await drive.drives.list({ fields: 'drives(id,name)' });
  const shared = drives.data.drives.find(d => d.name === GDRIVE_SHARED_DRIVE);
  if (!shared) throw new Error(`Shared Drive "${GDRIVE_SHARED_DRIVE}" не знайдено`);

  console.log(APPLY ? '=== ПРАВКА ===' : '=== СУХИЙ ПРОГІН (нічого не змінюється) ===');

  for (const e of ENTRIES) {
    console.log(`\n--- ${e.file}`);
    const found = await drive.files.list({
      q: `name='${e.file}' and trashed=false`,
      driveId: shared.id, corpora: 'drive', includeItemsFromAllDrives: true,
      supportsAllDrives: true, fields: 'files(id,name,parents)',
    });
    const df = found.data.files[0];
    console.log(`  Drive: ${df ? df.id : 'НЕ ЗНАЙДЕНО'}`);

    const row = df ? await findRow(sheets, e.sheet, df.id) : null;
    console.log(`  Аркуш «${e.sheet}»: ${row ? `рядок ${row.rowNumber} → ${JSON.stringify(row.values.slice(0, 6))}` : 'рядок не знайдено'}`);

    if (e.act === 'delete') {
      console.log(`  Дія: ВИДАЛИТИ (дубль скану ${e.twin})`);
      if (APPLY) {
        if (row) {
          await sheets.spreadsheets.values.clear({
            spreadsheetId: BILS_SHEET_ID, range: `'${e.sheet}'!A${row.rowNumber}:K${row.rowNumber}`,
          });
          console.log('    ✓ рядок очищено');
        }
        if (df) {
          await drive.files.update({ fileId: df.id, requestBody: { trashed: true }, supportsAllDrives: true });
          console.log('    ✓ файл у кошику Drive');
        }
        await inRequest(`/expenses/${e.expense}`, { method: 'DELETE' });
        console.log(`    ✓ витрату ${e.expense} видалено з Invoice Ninja`);
      }
    } else {
      const [y, m, d] = e.newDate.split('-');
      const newName = `${e.newDate}${e.file.slice(10)}`;
      const newSheet = `${m} ${y.slice(2)}`;
      console.log(`  Дія: ПЕРЕДАТУВАТИ на ${e.newDate}`);
      console.log(`    файл  → ${newName}, тека ${y}/${y}-${m}`);
      console.log(`    рядок → аркуш «${newSheet}», день ${Number(d)}` +
                  (e.fixSubtotal ? `, підсумок → ${e.fixSubtotal}` : ''));
      if (APPLY) {
        if (row) {
          const target = await firstFreeRow(sheets, newSheet);
          const moved = [...row.values];
          while (moved.length < 11) moved.push('');
          moved[0] = String(Number(d));
          if (e.fixSubtotal) moved[3] = e.fixSubtotal;
          await sheets.spreadsheets.values.update({
            spreadsheetId: BILS_SHEET_ID, range: `'${newSheet}'!A${target}:K${target}`,
            valueInputOption: 'USER_ENTERED', requestBody: { values: [moved] },
          });
          await sheets.spreadsheets.values.clear({
            spreadsheetId: BILS_SHEET_ID, range: `'${e.sheet}'!A${row.rowNumber}:K${row.rowNumber}`,
          });
          console.log(`    ✓ рядок перенесено в «${newSheet}», рядок ${target}`);
        }
        if (df) {
          const dest = await folderFor(drive, shared.id, y, m);
          await drive.files.update({
            fileId: df.id, requestBody: { name: newName },
            addParents: dest, removeParents: (df.parents || []).join(','),
            supportsAllDrives: true,
          });
          console.log('    ✓ файл перейменовано й перенесено');
        }
        await inRequest(`/expenses/${e.expense}`, {
          method: 'PUT', body: JSON.stringify({ date: e.newDate }),
        });
        console.log(`    ✓ дату витрати ${e.expense} виправлено`);
      }
    }
  }

  console.log(APPLY ? '\nГотово.' : '\nЗапустити з --apply, щоб застосувати.');
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
