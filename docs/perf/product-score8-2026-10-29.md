# Load test — Product Score-8 (2026-10-29): قبل/بعد

خام: `docs/qa/load/raw/s8-*.csv`. نفس عتاد الجولات السابقة: **2 vCPU / 4GB**، PostgreSQL 16.2 (pgserver)،
uvicorn عاملان، وLocust على نفس الجهاز (يشارك الـCPU مع الخادم — جزء من سبب الأرقام، ويُذكر لا يُخفى).

## ما تغيّر في الكود (C1)
- فهارس مركّبة (migration `0011`): `ledger_entries(posted_at, entry_no)` لقائمة الدفتر، و`requests(status, last_activity_at)` لقوائم الطلبات.
- الصندوق: من ~10 استعلامات SUM منفصلة إلى تجميع واحد مجمّع (method × direction + نوافذ اليوم/الشهر بشرط CASE).

## الأوامر
```bash
cd backend && .venv/bin/python scripts/load/pg_start.py /tmp/s8pg   # + CREATE DATABASE brokerhub_load
export DATABASE_URL="postgresql+asyncpg://postgres@/brokerhub_load?host=/tmp/s8pg" INTEGRATIONS_DRIVER=sim ENV=dev STORAGE_DIR=/tmp/s8-objects
.venv/bin/python -m alembic -c alembic.ini upgrade head   # يشمل 0011
.venv/bin/python -m app.seed
PYTHONPATH=. .venv/bin/python scripts/load/erp_volume.py --rows 50000 --clients 200   # ledger_after=50004
PYTHONPATH=. .venv/bin/python scripts/load/r12_volume.py --requests 20000              # requests_total=20024
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8023 --workers 2
.venv/bin/locust -f scripts/load/erp_locustfile.py  --headless -u 20 -r 5  -t 3m --host http://127.0.0.1:8023 --csv docs/qa/load/raw/s8-erp   --only-summary
LOAD_MODE=inbox .venv/bin/locust -f scripts/load/r12_locustfile.py --headless -u 50 -r 10 -t 3m --host http://127.0.0.1:8023 --csv docs/qa/load/raw/s8-inbox --only-summary
```

## النتائج (p95)

| المسار | قبل | بعد | الحكم |
|---|---|---|---|
| `GET /finance/ledger` | 750ms (R11: ‏50k قيد، عامل واحد) · 1900ms (R12: ‏100k قيد) | **1000ms** عند 50k قيد/عاملين | ❌ فوق بوابة 600ms على هذا العتاد |
| `GET /finance/spend-by-period` | 530ms (R11) · 1400ms (R12@100k) | **730ms** عند 50k | ❌ فوق 600ms هنا |
| `GET /finance/cashbox` | 3400ms (R12@100k) | **1200ms** عند 50k (تجميع واحد) | تحسّن واضح، ما زال بطيئًا في المزيج |
| `GET /executive/dashboard` | 7100ms (R12@100k) | **2400ms** عند 50k | تحسّن، ثقيل بنيويًا (تجميعات كثيرة) |
| `GET /requests` (قائمة) | 800ms (R12، ‏20k طلب) | **1100ms** عند 20k طلب/50 مستخدم | ❌ فوق بوابة 400ms هنا |
| أخطاء/5xx | 0 | **0** (3660 طلب ERP + 7980 قراءة) | ✅ |

## القرار الصادق
الفهارس وتجميع الصندوق حسّنا مسارات المال مقارنة بقياس R12 عند ضعف الحجم تقريبًا، لكن **بوابات الزمن
(600ms للدفتر، 400ms لقائمة الطلبات) ما زالت FAIL on this hardware**: عاملان وLocust نفسه يتقاسمون
2 vCPU، والمزيج يشمل `executive/dashboard` الثقيل. لم تُخفَّض أي بوابة. إعادة القياس على staging
بـ4+ أنوية وLocust من جهاز منفصل هي خطوة الـ Pilot الأولى قبل أي ادعاء نجاح أدائي — الأوامر أعلاه
حرفية لهذا الغرض. ما ثبت وظيفيًا: الحجم (50k قيد + 20k طلب)، صفر 5xx، والعزل والـvoid↔قسط لم يتغيرا
(اختبارات pytest + تشغيلات R12 السابقة).
