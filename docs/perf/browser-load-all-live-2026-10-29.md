# Browser load — All Live بلا بوابات مرحلة (2026-10-29، ADR-034)

الخام: `docs/perf/raw-browser-load-all-live.json` (يكتبه الاختبار نفسه — لا رقم مكتوبًا باليد).

## الإعداد

نفس عتاد الجولات السابقة: **2 vCPU / 4GB**، PostgreSQL 16.2 (pgserver)، uvicorn عاملان،
ومتصفح Chromium على نفس الجهاز. البيانات: seed + `seed_volume.py --leads 600 --clients 120
--requests 1500 --reps 10` + `erp_volume.py --rows 20000` ⇒ **20,004 قيد دفتر، 1,534 طلبًا،
663 ليدز، 200 عميل**.

السيناريو: `frontend/e2e/load-browser.spec.ts` — ‏**8 جلسات متصفح متوازية بحسابات مميزة**
(مدير، أدمن، مدير حسابات، خدمة عملاء، و4 مندوبين)، كل جلسة **6 دورات**: دخول عبر النموذج ←
Dashboard ← Inbox ← ‏/erp بتبديل فترتين (ربع سنوي ثم شهري) ← Policies ← Reports ← Issuing
(والمندوبون: لوحة الليدز — لا Dashboard/وثائق لهم بالصلاحية، وهذا مقصود).
حساب واحد لكل سياق عمدًا: سياقان بنفس الحساب يدوّران refresh token لبعضهما فيقرآن
كأعطال عشوائية (درس S3 موثقًا في المواصفة).

## الأوامر

```bash
cd backend && .venv/bin/python scripts/load/pg_start.py /tmp/s10pg   # + CREATE DATABASE brokerhub_load
export DATABASE_URL="postgresql+asyncpg://postgres@/brokerhub_load?host=/tmp/s10pg" INTEGRATIONS_DRIVER=sim ENV=dev PYTHONPATH=.
.venv/bin/python -m alembic -c alembic.ini upgrade head && .venv/bin/python -m app.seed
.venv/bin/python scripts/load/seed_volume.py --leads 600 --clients 120 --requests 1500 --reps 10
.venv/bin/python scripts/load/erp_volume.py --rows 20000 --clients 200
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8031 --workers 2
cd ../frontend && VITE_API_ORIGIN=http://127.0.0.1:8031 npm run build
VITE_API_ORIGIN=http://127.0.0.1:8031 VITE_PREVIEW_PORT=5176 npx vite preview --port 5176
E2E_SKIP_WEBSERVER=1 LOAD_WEB_URL=http://127.0.0.1:5176 LOAD_USERS=8 LOAD_CYCLES=6 \
  npx playwright test e2e/load-browser.spec.ts --project desktop
```

ملحوظة بيئة صادقة: تنزيل متصفح Playwright الرسمي محجوب في هذا الـsandbox
(`cdn.playwright.dev`)، فشُغّل Chromium مضغوطًا موزّعًا عبر npm
(`@sparticuz/chromium` — رندر برمجي بطيء أصلًا)؛ أزمنة الخطوات أدناه سقفٌ متشائم
لا قياس إنتاج. في CI يعمل الاختبار نفسه بمتصفح Playwright الرسمي.

## النتائج (معايير C3)

| المعيار | النتيجة |
|---|---|
| فشل سيناريو/خطوة | **0 من 138 خطوة** (8 مستخدمين × 6 دورات، 44 ثانية) |
| 5xx على XHR أساسية | **0** |
| أخطاء صفحة غير ملتقطة (pageerror) | **0** |
| ظهور نص بوابة المرحلة («غير مفعّلة بعد»/«تشغيل هذه المرحلة»/«المرحلة الثانية») | **0** |
| p95 خطوة: وثائق / تقارير / إصدار | 704ms / 854ms / 1302ms (رندر برمجي — انظر الملحوظة) |
| p95 خطوة: Dashboard / Inbox / ‏ERP بفترتين / ليدز | 2871ms / 2822ms / 5829ms / 2004ms |

## مكمّل API (C4)

بنفس الخادم والحساب (مدير): `GET /policies` ‏200 · `/policies/kpis` ‏200 ·
`/commissions` ‏200 · `/issuing-cases` ‏200 · `/reports/insurer-performance` ‏200 ·
`POST /exports/insurer-performance` ‏200 — لا `feature_disabled` في أي مسار كان محروسًا،
والصف `phase2.enabled=False` مزروع في قاعدة الاختبار الآلي (`tests/test_no_phase_gates.py`)
ليثبت أن لا قارئ له: 200 بالصلاحية و403 بدونها.
