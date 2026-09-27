// ─────────────────────────────────────────────────────────────────────────────
// immich-ingest.js — фото з робочого телефону → логбук, чеки, одометр
//
// Робочий телефон (Samsung SM-S908W, їздить у Pacifica) робить авто-бекап в
// Immich під окремим акаунтом fleet@rotes.ca. Цей скрипт раз на добу забирає
// ВЧОРАШНІ знімки і розкладає їх куди треба:
//
//   чек      → /mnt/fileshare/scan_inbox/Rotes_receipts  (далі вже існуючий
//              receipt-bot.js: ROG OCR → Drive → аркуш bils → Invoice Ninja)
//   одометр  → fleet.odometer_readings
//   решта    → fleet.photos, привʼязані до поїздки, яка привезла водія на місце
//
// Чому доба затримки, а не одразу: Роман просив саме так. Причина здорова —
// телефон вивантажує в Immich не миттєво (Wi-Fi вдома, черга бекапу), тож
// «сьогоднішній» день завжди неповний. Обробка вчорашнього дня бачить його
// цілим. Вікно береться ширше (8 діб) і все вже оброблене пропускається —
// так простій сервісу не з'їдає жодного чека.
//
// Навмисно НЕ дублює логіку чеків. Чек просто кладеться у ту саму теку, куди
// його поклав би сканер, і далі працює той самий перевірений конвеєр. Єдина
// нова відповідальність тут — вирішити, що це за фото.
// ─────────────────────────────────────────────────────────────────────────────

require('dotenv').config({ path: '/opt/agent/.env' });

const fs      = require('fs');
const path    = require('path');
const sharp   = require('sharp');
const { Pool } = require('pg');
const { NodeSSH } = require('node-ssh');

const IMMICH_URL   = process.env.IMMICH_URL       || 'http://192.168.2.9:2283';
const IMMICH_KEY   = process.env.IMMICH_FLEET_KEY;
const ROG_URL      = process.env.ROG_OLLAMA_URL   || 'http://10.10.99.50:11434';
const ROG_MODEL    = process.env.ROG_VISION_MODEL || 'qwen2.5vl:7b';

const SSH_HOST     = process.env.SSH_HOST     || '192.168.2.230';
const SSH_USER     = process.env.SSH_USER     || 'root';
const SSH_KEY_PATH = process.env.SSH_KEY_PATH || '/root/.ssh/id_ed25519';
const SCAN_INBOX   = '/mnt/fileshare/scan_inbox/Rotes_receipts';

const TG_TOKEN     = process.env.TELEGRAM_BOT_TOKEN;
const TG_CHAT      = process.env.TELEGRAM_CHAT_ID;

const STATE_FILE   = '/opt/agent/immich-processed.json';
const TMP_DIR      = '/tmp/immich-ingest';
const TZ           = 'America/Moncton';

// Скільки діб назад дивитися. 1 = тільки вчора; більше — щоб надолужити простій.
const LOOKBACK_DAYS  = Number(process.env.IMMICH_LOOKBACK_DAYS || 8);
// Наскільки пізніше старту поїздки фото ще вважається зробленим у тій поїздці.
const TRIP_TAIL_HOURS = 6;
// Те саме фото могло раніше прилетіти через Telegram. Секунди розбіжності:
// той самий тип знімка — широке вікно, різний тип — лише майже точний збіг.
const DEDUP_SAME_KIND_SEC = 600;
const DEDUP_ANY_KIND_SEC  = 180;

const DRY_RUN = process.argv.includes('--dry-run');

const pool = new Pool({
  host: process.env.FLEET_PGHOST || '192.168.2.25',
  port: Number(process.env.FLEET_PGPORT || 5432),
  database: process.env.FLEET_PGDATABASE || 'rotes_construction',
  user: process.env.FLEET_PGUSER || 'fleet_ingest',
  password: process.env.FLEET_PGPASSWORD,
  ssl: { rejectUnauthorized: false },
});

const ssh = new NodeSSH();

// ── стан ─────────────────────────────────────────────────────────────────────

function loadState() {
  try { return new Set(JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'))); }
  catch { return new Set(); }
}
function saveState(set) {
  fs.writeFileSync(STATE_FILE, JSON.stringify([...set], null, 0));
}

// ── Immich ───────────────────────────────────────────────────────────────────

async function immich(pathAndQuery, options = {}) {
  const resp = await fetch(IMMICH_URL + pathAndQuery, {
    ...options,
    headers: {
      'x-api-key': IMMICH_KEY,
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  if (!resp.ok) {
    throw new Error(`Immich ${options.method || 'GET'} ${pathAndQuery} -> ${resp.status} ${await resp.text()}`);
  }
  return resp.status === 204 ? null : resp.json();
}

// Вікно днів рахуємо в місцевій зоні, а не в UTC: інакше вечірні знімки
// потрапляють у наступну добу і день обробляється двічі наполовину.
function localDayBounds(daysAgo) {
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit',
  });
  const d = new Date(Date.now() - daysAgo * 86400000);
  const day = fmt.format(d);                       // YYYY-MM-DD
  return { day, from: `${day}T00:00:00.000Z`, to: `${day}T23:59:59.999Z` };
}

async function fetchAssetsForDay(day) {
  const out = [];
  let page = 1;
  for (;;) {
    const body = {
      takenAfter:  `${day}T00:00:00.000Z`,
      takenBefore: `${day}T23:59:59.999Z`,
      withExif: true,
      size: 250,
      page,
    };
    const r = await immich('/api/search/metadata', { method: 'POST', body: JSON.stringify(body) });
    const items = (r && r.assets && r.assets.items) || [];
    out.push(...items.filter(a => a.type === 'IMAGE'));
    const next = r && r.assets && r.assets.nextPage;
    if (!next) break;
    page = Number(next);
  }
  return out;
}

async function downloadAsset(id, dest) {
  const resp = await fetch(`${IMMICH_URL}/api/assets/${id}/original`, {
    headers: { 'x-api-key': IMMICH_KEY },
  });
  if (!resp.ok) throw new Error(`download ${id} -> ${resp.status}`);
  fs.writeFileSync(dest, Buffer.from(await resp.arrayBuffer()));
}

// Теги — зручність для Романа, щоб в Immich було видно, що вже розібране.
// Ніколи не валимо через них увесь прохід.
const tagCache = new Map();
async function tagAsset(assetId, tagName) {
  try {
    if (!tagCache.has(tagName)) {
      // POST /api/tags віддає 400, якщо тег уже є, і id не повертає.
      // Тому спершу шукаємо серед наявних, створюємо лише коли справді нема.
      let id = null;
      try {
        const all = await immich('/api/tags');
        const hit = (all || []).find(t => t.value === tagName || t.name === tagName);
        if (hit) id = hit.id;
      } catch { /* список не критичний */ }
      if (!id) {
        const t = await immich('/api/tags', {
          method: 'POST', body: JSON.stringify({ name: tagName }),
        });
        id = t.id;
      }
      tagCache.set(tagName, id);
    }
    await immich(`/api/tags/${tagCache.get(tagName)}/assets`, {
      method: 'PUT', body: JSON.stringify({ ids: [assetId] }),
    });
  } catch (e) {
    console.warn(`[immich-ingest] tag ${tagName} failed (не критично):`, e.message);
  }
}

// ── класифікатор ─────────────────────────────────────────────────────────────

const CLASSIFY_PROMPT = `You are sorting photos taken by a construction contractor on a work phone.
Return ONLY valid JSON, no markdown, no backticks:
{"type":"receipt","odometer_km":null,"note":""}

"type" must be exactly one of:
  receipt  - a store receipt, invoice, bill, order slip or any printed proof of payment
  odometer - a car dashboard or instrument cluster showing a kilometre reading
  site     - a building, room, roof, deck, wall, tools, materials, work in progress
  address  - a house number, street sign, business sign or nameplate
  other    - anything else

If and only if type is "odometer", set odometer_km to the total-distance number you
read on the dashboard, as an integer with no separators. Otherwise leave it null.
Do not confuse trip meters (usually under 1000, often with one decimal) with the
odometer; the odometer is the larger number.
"note": at most 8 words describing what is in the photo, in Ukrainian.`;

async function classify(imagePath) {
  const compressed = await sharp(imagePath)
    .resize({ width: 1400, withoutEnlargement: true })
    .jpeg({ quality: 85 })
    .toBuffer();

  const resp = await fetch(`${ROG_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: ROG_MODEL,
      stream: false,
      options: { temperature: 0.1 },
      messages: [{ role: 'user', content: CLASSIFY_PROMPT, images: [compressed.toString('base64')] }],
    }),
  });
  if (!resp.ok) throw new Error(`ROG HTTP ${resp.status}: ${await resp.text()}`);

  const data = await resp.json();
  const raw = ((data.message && data.message.content) || '')
    .trim().replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
  const parsed = JSON.parse(raw);

  const allowed = ['receipt', 'odometer', 'site', 'address', 'other'];
  if (!allowed.includes(parsed.type)) parsed.type = 'other';
  return parsed;
}

// ── призначення ──────────────────────────────────────────────────────────────

async function pushReceiptToInbox(localPath, assetId, takenAt) {
  const stamp = takenAt.replace(/[-:T]/g, '').slice(0, 14);
  // Дефіси, не підкреслення: receipt-bot виправляє рік за шаблоном
  // Canon-сканера _YYMMDDHHMMSS_ , і підкреслення могли б туди влучити.
  const name  = `immich-${stamp}-${assetId.slice(0, 8)}${path.extname(localPath) || '.jpg'}`;
  if (DRY_RUN) { console.log(`[dry-run] чек → ${SCAN_INBOX}/${name}`); return name; }
  if (!ssh.isConnected()) {
    await ssh.connect({ host: SSH_HOST, username: SSH_USER, privateKeyPath: SSH_KEY_PATH });
  }
  await ssh.putFile(localPath, `${SCAN_INBOX}/${name}`);
  return name;
}

// Фото робиться після того, як водій кудись приїхав, тож поїздка-власник — це
// остання, що стартувала до знімка. Прив'язка до найближчої за часом дала б
// наступну поїздку (від'їзд), а це вже інше місце.
async function findTripFor(takenAtIso) {
  const { rows } = await pool.query(
    `SELECT id, destination_address,
            started_at AT TIME ZONE 'America/Moncton' AS started_local
       FROM fleet.trips
      WHERE started_at <= $1::timestamptz
        AND started_at >  $1::timestamptz - ($2 || ' hours')::interval
      ORDER BY started_at DESC
      LIMIT 1`,
    [takenAtIso, String(TRIP_TAIL_HOURS)]
  );
  return rows[0] || null;
}

// Знімок міг уже пройти шлях Telegram → fleet.photos → scan_inbox → Ninja.
// Другий раз його заводити не можна: у ніндзі з'явиться дубль витрати, а в
// книзі — дубль фото. Шукаємо рядок без immich_asset_id поруч за часом.
async function findExistingPhoto(kind, takenAtIso) {
  const { rows } = await pool.query(
    `SELECT id, kind
       FROM fleet.photos
      WHERE immich_asset_id IS NULL
        AND abs(extract(epoch FROM taken_at - $1::timestamptz))
            <= CASE WHEN kind = $2 THEN $3::numeric ELSE $4::numeric END
      ORDER BY (kind = $2) DESC,
               abs(extract(epoch FROM taken_at - $1::timestamptz))
      LIMIT 1`,
    [takenAtIso, kind, DEDUP_SAME_KIND_SEC, DEDUP_ANY_KIND_SEC]
  );
  return rows[0] || null;
}

async function linkExistingPhoto(photoId, assetId) {
  await pool.query(
    'UPDATE fleet.photos SET immich_asset_id = $1 WHERE id = $2 AND immich_asset_id IS NULL',
    [assetId, photoId]
  );
}

async function savePhoto({ assetId, kind, takenAt, lat, lon, note, tripId }) {
  if (DRY_RUN) { console.log(`[dry-run] ${kind} → fleet.photos (поїздка ${tripId || '—'})`); return; }
  await pool.query(
    `INSERT INTO fleet.photos
       (kind, taken_at, immich_asset_id, source, latitude, longitude, note, trip_id, storage_url)
     VALUES ($1, $2::timestamptz, $3, 'immich', $4, $5, $6, $7, $8)
     ON CONFLICT (immich_asset_id) WHERE immich_asset_id IS NOT NULL DO NOTHING`,
    [kind, takenAt, assetId, lat, lon, note || null, tripId,
     `immich://${assetId}`]
  );
}

async function saveOdometer({ assetId, km, takenAt }) {
  if (!Number.isFinite(km) || km < 10000 || km > 999999) return false;
  if (DRY_RUN) { console.log(`[dry-run] одометр ${km} км`); return true; }
  const { rowCount } = await pool.query(
    `INSERT INTO fleet.odometer_readings (vehicle_id, read_on, odometer_km, reason, photo_url, read_at)
     SELECT 1, ($1::timestamptz AT TIME ZONE 'America/Moncton')::date, $2, 'photo', $3, $1::timestamptz
      WHERE NOT EXISTS (
        SELECT 1 FROM fleet.odometer_readings
         WHERE read_at = $1::timestamptz OR odometer_km = $2
      )`,
    [takenAt, km, `immich://${assetId}`]
  );
  return rowCount > 0;
}

// ── Telegram ─────────────────────────────────────────────────────────────────

async function tg(text) {
  if (!TG_TOKEN || !TG_CHAT) return;
  try {
    await fetch(`https://api.telegram.org/bot${TG_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: TG_CHAT, text, parse_mode: 'HTML' }),
    });
  } catch (e) {
    console.error('[immich-ingest] telegram:', e.message);
  }
}

// ── головний прохід ──────────────────────────────────────────────────────────

async function main() {
  if (!IMMICH_KEY) throw new Error('IMMICH_FLEET_KEY не заданий у /opt/agent/.env');
  fs.mkdirSync(TMP_DIR, { recursive: true });

  const done = loadState();
  const tally = { receipt: 0, odometer: 0, site: 0, address: 0, other: 0, duplicate: 0, failed: 0, skipped: 0 };
  const lines = [];

  // Від найдавнішого дня до вчорашнього. Сьогодні НЕ чіпаємо: бекап ще йде.
  for (let d = LOOKBACK_DAYS; d >= 1; d--) {
    const { day } = localDayBounds(d);
    let assets;
    try {
      assets = await fetchAssetsForDay(day);
    } catch (e) {
      console.error(`[immich-ingest] ${day}: ${e.message}`);
      continue;
    }
    if (!assets.length) continue;
    console.log(`[immich-ingest] ${day}: ${assets.length} знімків`);

    for (const a of assets) {
      if (done.has(a.id)) { tally.skipped++; continue; }

      const takenAt = a.fileCreatedAt || a.localDateTime || a.updatedAt;
      const local   = path.join(TMP_DIR, `${a.id}.jpg`);
      try {
        await downloadAsset(a.id, local);
        const c = await classify(local);
        const lat = (a.exifInfo && a.exifInfo.latitude) ?? null;
        const lon = (a.exifInfo && a.exifInfo.longitude) ?? null;

        const kindOf = c.type === 'receipt'  ? 'receipt'
                     : c.type === 'odometer' ? 'odometer'
                     : c.type === 'site'     ? 'site' : 'other';
        const dup = await findExistingPhoto(kindOf, takenAt);
        if (dup) {
          console.log(`[immich-ingest] дубль Telegram → fleet.photos #${dup.id} (${dup.kind}), пропускаю`);
          if (!DRY_RUN) {
            await linkExistingPhoto(dup.id, a.id);
            await tagAsset(a.id, 'logbook/дубль');
            done.add(a.id); saveState(done);
          }
          tally.duplicate++;
          continue;
        }

        if (c.type === 'receipt') {
          const name = await pushReceiptToInbox(local, a.id, takenAt);
          await savePhoto({ assetId: a.id, kind: 'receipt', takenAt, lat, lon,
                            note: c.note, tripId: (await findTripFor(takenAt))?.id || null });
          await tagAsset(a.id, 'logbook/чек');
          lines.push(`🧾 ${name}`);
          tally.receipt++;
        } else if (c.type === 'odometer') {
          const ok = await saveOdometer({ assetId: a.id, km: Number(c.odometer_km), takenAt });
          await savePhoto({ assetId: a.id, kind: 'odometer', takenAt, lat, lon,
                            note: c.note, tripId: null });
          await tagAsset(a.id, 'logbook/одометр');
          lines.push(ok ? `🔢 одометр ${c.odometer_km} км` : `🔢 одометр (вже був, пропущено)`);
          tally.odometer++;
        } else {
          const trip = await findTripFor(takenAt);
          const kind = c.type === 'site' ? 'site' : 'other';
          await savePhoto({ assetId: a.id, kind, takenAt, lat, lon, note: c.note,
                            tripId: trip ? trip.id : null });
          await tagAsset(a.id, 'logbook/обʼєкт');
          tally[c.type]++;
        }

        // Сухий прогін не має права позначати фото обробленим: інакше він
        // отруює стан і наступний бойовий запуск мовчки все пропускає.
        if (!DRY_RUN) { done.add(a.id); saveState(done); }
      } catch (e) {
        console.error(`[immich-ingest] ${a.id}: ${e.message}`);
        tally.failed++;   // не додаємо в done — спробуємо завтра
      } finally {
        try { fs.unlinkSync(local); } catch {}
      }
    }
  }

  const total = tally.receipt + tally.odometer + tally.site + tally.address + tally.other;
  if (total || tally.failed) {
    const head = `📥 <b>Фото з робочого телефону</b>\nРозібрано ${total}` +
                 (tally.failed ? `, помилок ${tally.failed}` : '');
    const body = [
      tally.receipt  ? `🧾 чеків: ${tally.receipt} → пішли в обробку` : '',
      tally.odometer ? `🔢 одометр: ${tally.odometer}` : '',
      tally.site     ? `🏗 обʼєкти: ${tally.site}` : '',
      tally.address  ? `🏠 адреси: ${tally.address}` : '',
      tally.other    ? `📷 інше: ${tally.other}` : '',
      tally.duplicate ? `♻️ дублів із Telegram: ${tally.duplicate}` : '',
    ].filter(Boolean).join('\n');
    await tg([head, body, lines.slice(0, 15).join('\n')].filter(Boolean).join('\n'));
  }
  console.log('[immich-ingest]', JSON.stringify(tally));
}

main()
  .then(async () => { try { ssh.dispose(); } catch {} await pool.end(); process.exit(0); })
  .catch(async (e) => {
    console.error('[immich-ingest] FATAL:', e);
    await tg(`⚠️ <b>immich-ingest впав</b>\n<code>${String(e.message).slice(0, 300)}</code>`);
    try { ssh.dispose(); } catch {}
    try { await pool.end(); } catch {}
    process.exit(1);
  });
