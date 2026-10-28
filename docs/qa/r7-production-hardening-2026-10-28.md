# تقرير QA — جولة R7 «التحصين للإنتاج» (2026-10-28)

النطاق: المسار التشغيلي للفاز‑2 (مسودة → إصدار → PDF → أقساط → دفع)، صقل البوابة، قفل القنوات الحيّة،
والانحدار الإلزامي على طلبات المالك السابقة. كل رقم هنا **مخرَج أمر شُغِّل على هذه الشجرة**؛ وما لم يُشغَّل
مذكور بسببه في §7.

---

## 1) ما كان مكسورًا فعلًا قبل الجولة

| # | العَرَض | السبب الجذري | الإصلاح | اختبار الانحدار |
|---|---|---|---|---|
| 1 | لا طريق في الواجهة لإنشاء مسودة وثيقة | الشاشة كانت تقرأ فقط؛ الإنشاء يعيش في `POST /policies` وحده | `NewPolicyDialog` ببابين (رأس `/policies` + مستندات ملف العميل)، ولا يُفعَّل الحفظ قبل (عميل + بداية + قسط > 0) | `frontend/tests/phase2Ops.test.tsx` |
| 2 | صفّ السياسة يطبع `—` بدل اسم العميل | `Policy` لم يكن له علاقة `client` أصلًا، والـserializer لا يُرسل شيئًا | `Policy.client` (`lazy="joined"`) + `ClientRefOut` | `test_phase2_ops.py` (اسم العميل في `GET /policies`) |
| 3 | شارة الحالة تظهر **جملة توست كاملة** | المفتاح `phase2.issued` نصّه «تم إصدار الوثيقة…» وكان يُستخدم كورقة حالة | مساحة جديدة `phase2.policyStatus.{draft,pending_insurer,issued,expired,cancelled}` | `phase2Ops.test.tsx` (الشارة «مسودة») |
| 4 | «متأخر» يُحسب في المتصفح، و`installments.status` يبقى `upcoming` للأبد | لا كاتب للـstatus، ولا تعريف مخزَّن للتأخر | `refresh_late()` (idempotent، يحرّك `upcoming → late` فقط) ويُستدعى عند القراءة وعند الدفع | `test_phase2_ops.py` + تعديل اختبار قديم كان يثبّت السلوك الخاطئ |
| 5 | لا يمكن تسجيل دفع من الشاشة ولا من الـAPI | لا يوجد مسار | `POST /policies/{id}/installments/{iid}/pay` + `services.installments.pay`، وسجل تدقيق | `test_phase2_ops.py` (دفع مرة + 409 للثانية) · `SMOKE` |
| 6 | عمولة `0.00` عند غياب النسبة أو القسط | `commission_amount` كان يُكتب صفرًا ويُعرض كأنه حساب | `computed` / `not_computed`، والشاشة تكتب «غير محسوبة» | `phase2Ops.test.tsx` |
| 7 | **P1 أمني:** توقيع webhook صحيح على مفتاح **فارغ** | `hmac.new(b"", …)` قابل للحساب من أي أحد، فغياب App Secret كان يفتح مسار الاستقبال بدل أن يرفضه | `verify_webhook_signature` ترفض المفتاح الفارغ | `test_intake.py` (وحدة) + `test_live_channels.py` (طرف‑لطرف `403`) |
| 8 | لم يكن هناك دليل أن الفلتر الإداري يقرأ من الخادم | لا اختبار للـ`board` بفلتر أصلًا | `tests/test_manager_filters.py` | 3 اختبارات |
| 9 | موظف الاستقبال يسلّم كلمة المرور يدويًا فيُخطئ العنوان | البطاقة تعرض حقلين فقط | كتلة رسالة جاهزة + «نسخ الرسالة» + تحذير | `e2e/live-round.spec.ts` (وجود الكتلة وكلمة المرور داخلها) |

## 2) دليل PDF والبوابة (طلبات المالك: «بدليل حرفي»)

من `python scripts/smoke_api.py` (مخرَج حرفي):

```
ok   POST /api/v1/policies/{id}/issue -> BH-2026-0000xx (xxxxx bytes)
ok   GET /api/v1/policies/{id}/document -> a real PDF (… bytes)
ok   GET /api/v1/portal/policies/{id}/document -> the same file, one company only
ok   POST /api/v1/policies/{id}/issue twice -> 409, not a second document
ok   GET /api/v1/portal/policies -> the owner sees the issued contract
ok   GET /api/v1/policies/{id}/installments -> 12 rows, 12 unpaid
ok   POST /api/v1/policies/{id}/installments/{iid}/pay -> paid, once
ok   POST …/pay twice -> 409, not a second receipt
```

الملف يبدأ بـ`%PDF-` في المسارين (الموظف والبوابة)، والعميل لا يرى إلا وثائق شركته: تحميل وثيقة شركة أخرى
يعطي `404` (اختبارات `test_portal.py`)، والمفاتيح الممنوعة (عمولة/ملاحظة داخلية/اسم موظف) لا تظهر في
`GET /portal/*` (اختبارات `test_phase2_ops.py` و`test_portal.py`).

## 3) القنوات الحيّة — ما أُثبت وما لم يُثبت

أُثبت (اختبارات + مصفوفة):

- توقيع HMAC على **البايتات الخام** (لا على JSON بعد التحليل) — تغيير مسافة واحدة يُبطل التوقيع.
- رفض التوقيع الخاطئ `403` مع سطر `rejected` في `webhook_events` (واتساب وسنترال).
- المفتاح الفارغ يرفض (عيب P1 أعلاه).
- منع التكرار: نفس `wamid` ⇒ `duplicate` ولا رسالة ثانية؛ نفس `CallSid` كذلك.
- رد الموظف يخرج عبر السائق الحيّ إلى `graph.facebook.com/v21.0/...` بالتوكن الصحيح، والتوكن **لا يظهر** في
  أي استجابة.
- حصر مضيف التسجيل: تسجيل من مضيف غير `provider_url` ⇒ رفض (SSRF).
- اختبار اتصال السنترال لا يعطي «سليم» بلا عنوان.

لم يُثبت، ولا يُدّعى: الاتصال الفعلي بحساب Meta أو سنترال حقيقي. لا يوجد في هذه البيئة رقم مرخّص ولا
اعتماد خارجي؛ ولذلك نُفِّذ الفحص بعقد (توقيع/تكرار/تسريب/SSRF) + إدخال HTTP حقيقي، والخطوات السبعة في
`docs/runbook.md` §6.1 هي ما ينفّذه المشغّل عند أول تشغيل حقيقي.

## 4) الفحص اليدوي على مكدّس محلي

| البند | الأمر | المخرَج |
|---|---|---|
| إعدادات preflight | `GET /settings/integrations/whatsapp/preflight` قبل الاختبار | `ready=false`, `blockers[0].code="test"` ورسالته عربية |
| المفتاح الحيّ | `POST …/whatsapp/live` بلا تأكيد | `409` ومعه `labels` عربية (لا خطأ صامت) |
| الأقساط | `GET /policies/{id}/installments` بعد إصدار | 12 صفًا، والتأخر محسوب من `due_date` |
| الدفع | `POST …/pay` مرتين | `200` ثم `409` |
| البوابة | `POST /auth/login` باسم مستخدم | `200` ثم `GET /portal/overview` `200` |

## 5) البوابات — مخرجات حرفية

```
Backend:
  ruff check .              All checks passed!
  ruff format --check .     165 files already formatted
  mypy app                  Success: no issues found in 113 source files
  pytest -q                 279 collected · 0 failed · exit 0
  smoke_api.py              SMOKE OK — 126/129 documented calls answered
  live_matrix.py            checks: 231 · passed: 231 · P0 failed: 0 · warnings: 0
  check_openapi_fresh.py    openapi.json is fresh (110 paths)

Frontend:
  npm run lint              eslint . --max-warnings 0 → no output
  npm run typecheck         tsc -p tsconfig.json && tsc -p tsconfig.e2e.json → clean
  npm run build             ✓ built in 7.76s
  npx vitest run            Test Files 17 passed (17) · Tests 121 passed (121)
  npm run codegen:api       openapi.json (110 paths, 146 schemas)
```

## 6) ما لم يُشغَّل ولماذا

- **e2e (Playwright):** لا متصفح في هذه البيئة، وتنزيله محجوب. `frontend/e2e/r7-round.spec.ts` (2) يُنفَّذ في
  CI، والملف يُصرَّف محليًا (`tsc -p tsconfig.e2e.json` نظيف) ليضمن أن الفشل المحتمل سلوكي لا نحوي.
- **PostgreSQL:** لا خدمة قاعدة بيانات هنا؛ اختبارات `postgres_only` (10) مُتخطَّاة، وتُشغَّل في مهمة CI.
- **Meta / PBX حقيقي:** لا حساب ولا رقم (انظر §3).

## 7) قرارات اتُّخذت نيابة عن المالك

1. **تعديل اختبار قديم بدل إبقاء سلوك خاطئ:** `test_underwriting_defaults_…` كان يثبّت
   `status == "upcoming"` لأقساط تواريخها ماضية — أي أنه كان يحمي العيب. صار يشتقّ المتوقّع من `due_date`
   مقابل اليوم، فيبقى الاختبار صحيحًا في أي سنة.
2. **الدفع يدوي:** تسجيل «تم الدفع» حقيقة تشغيلية (تحويل/شيك)، لا بوابة دفع. أي تحصيل آلي خارج النطاق.
3. **PDF عربي فقط:** لم تُضَف نسخة إنجليزية؛ المطلوب «PDF عربي سليم» وقد أُثبت.
