# Runbook — Broker Hub

موجه لمن يشغّل النظام: تشغيل، مراقبة، حوادث، وصلاحيات. كل أمر هنا نصفيًا قابل للنسخ.

## 1) التشغيل

### حاويات (المسار الأساسي)

```bash
cp infra/.env.example infra/.env            # JWT_SECRET إلزامي في أي بيئة مشتركة
docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml exec backend python -m app.seed   # بيانات تجريبية فقط للعرض
curl -fsS http://localhost:8000/healthz; echo
curl -fsS http://localhost:8000/readyz; echo
```

- `migrate` مهمة لمرة واحدة تخرج بنجاح؛ إذا فشلت فلن يبدأ `backend` (بوابة `service_completed_successfully`).
- الوسائط على وحدة `objectsdata` (`STORAGE_DIR=/srv/objects`). لاستخدام S3/MinIO خارجي: `STORAGE_BACKEND=s3`
  و`S3_ENDPOINT_URL`/`S3_BUCKET`/المفاتيح — الصور الرسمية لـMinIO لم تعد قابلة للسحب المجهول (ADR-020).
- الواجهة على `WEB_PORT` (5173) تمرّر `/api` للـAPI عبر nginx؛ لا يوجد أصل API مضمّن في الحزمة.

### بدون حاويات

```bash
cd backend && pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head && python -m app.seed && uvicorn app.main:app --port 8000
cd ../frontend && npm ci && npm run codegen:api && VITE_API_ORIGIN=http://127.0.0.1:8000 npm run dev
```

## 2) المراقبة

| إشارة | مكان | معنى |
| --- | --- | --- |
| `GET /healthz` | :8000 | العملية للحية (لا يلمس قاعدة بيانات) |
| `GET /readyz` | :8000 | `SELECT 1` — 503 مع `not_ready` عند فقدان القاعدة |
| `GET /metrics` | :8000 | Prometheus نصي: `broker_hub_http_requests_total{method,route,status}` + `..._duration_seconds` + `..._in_flight_requests`. التسمية `route` قالب مسار لا URL خام. في التطوير مفتوح؛ مع `METRICS_TOKEN` يحتاج `Authorization: Bearer`؛ بدونه في الإنتاج 403 `metrics_disabled`. مقاييس الـworker ليست هنا عمداً (انظر ADR-011) |
| بريد تجريبي | mailpit على :8025 | كل إشعار بريدّي في stack المحلي يظهر هناك؛ لا SMTP خارج الجهاز. `SMTP_URL=smtp://mailpit:1025` |
| logs | stdout JSON (structlog) | حقول ثابتة: `method path status ms cid driver env`؛ `ms` هو زمن المعالجة بالمللي ثانية |
| طابور Celery | `celery -A app.workers.celery_app:celery_app inspect active` | إن كان فارغًا والمهام تتراكم فالعامل ميت |
| مهمات مجدولة | `celery ... inspect scheduled` | المفروض 4 tasks — انظر §4 |

الجدول الزمني لـ beat (من `app/workers/celery_app.py`):

| المهمة | التكرار | الوظيفة |
| --- | --- | --- |
| `broker_hub.sla_sweep` | كل 60 ثانية | يعلّم `is_overdue` ويحسب «متأخر N س» ويبعث تنبيهات |
| `broker_hub.lead_followup_reminders` | 8:00 و14:00 | تذكيرات متابعة الـLeads |
| `broker_hub.purge_expired_recordings` | 3:15 | حذف تسجيلات تجاوزت `RECORDING_RETENTION_DAYS` |
| `broker_hub.cleanup_tmp_files` | 4:30 | تنظيف ملفات الاستيراد المؤقتة |

## 3) الترقية المخططة (Migrations)

- لا تُحرَّر migration مُدمجة أبدًا؛ أضف واحدة جديدة (`alembic revision -m "..."`). الاستثناء الوحيد
  المسجَّل هو 0001/0002: لم تكونا قادرتين على التشغيل على PostgreSQL إطلاقًا، فلم تُطبَّقا على أي قاعدة،
  والتصحيح كان مستحيلًا في migration لاحقة — التفاصيل والتبرير في `docs/decisions/014-*.md` (ADR-014).
- 0001 = الأساس الكامل (33 جدولًا بترتيب تبعي لا أبجدي: `users` قبل `clients`، وقيد `clients.source_lead_id`
  يُضاف بعد وجود الجدولين لأن حلقة `leads ↔ clients` لا تُعبَّر داخل `CREATE TABLE` على PostgreSQL)؛
  0002 = RLS + فهارس جزئية (PostgreSQL فقط، تقفز على SQLite)؛ 0003 = سياسة `FOR ALL` واحدة لكل جدول
  (تغطي `INSERT` أيضًا) + بند البوابة `app.scope_client_id` + دور `brokerhub_app`.
- لا يتجاوز `revision` 32 حرفًا: `alembic_version.version_num` هو `VARCHAR(32)`، ومخالفته تُفشِل آخر خطوة
  من الترقية بعد تنفيذ الـDDL كله. البوابة: `tests/test_migrations.py::test_every_revision_id_fits_the_version_table`.
- قبل الدمج لا تُصدَّق السلسلة يدويًا فقط — `tests/test_migrations.py` يبني قاعدة PostgreSQL فارغة ويشغّل
  `upgrade head ← downgrade base ← upgrade head` ثم يقارن المخطط الناتج بنماذج `Base.metadata`. يدويًا على
  نسخة إنتاج: `alembic upgrade head` (أو `docker compose run --rm migrate`).
- للنزول الآمن: فضّل إضافة column nullable ثم backfill ثم NOT NULL، بدل downgrade كامل.

## 4) SLA: كيف تُحسب ومتى «تظلم»

1. الأولوية تأتي من `sla_policies` (جدول في القاعدة، لا ثابت في الكود): عاجل 30/120، عالية 60/240،
   عادية 240/1440، منخفضة 600/2880 دقيقة.
2. العدّاد يعمل داخل ساعات العمل من `business_hours` (الجمعة والسبت مغلقان في مصر):
   `app/domain/sla.py` + `WEEKEND_DAYS=[4,5]`.
3. `sla_due_at` تُحسب عند الإنشاء، وتُعاد حسابتها إذا تغيّرت الأولوية (خدمة `requests_svc.update`).
4. `is_overdue` لا يحدّثها الطلب نفسه بل `sla_sweep` — لذا إذا تأخّر worker فلن تظهر «متأخر» حتى لو
   انتهى الوقت. أول تشخيص عند شكوى «لا يوجد أحمر»: تحقق من `inspect scheduled` و`status=200` لمهة الـsweep.
5. أول رد (`first_response_at`) يُختم عند أول رد من موظف، ومنه يشتق «متوسط زمن أول رد» في اللوحة.

## 5) الصلاحيات والعزل (عند شكوى «فلان يرى أكثر/أقل»)

```sql
-- ما الأدوار الممنوحة لهذا المستخدم فعليًا؟
select u.email, r.code, string_agg(p.code, ', ' order by p.code)
from users u join roles r on r.id = u.role_id
left join role_permissions rp on rp.role_id = r.id
left join permissions p on p.id = rp.permission_id
where u.email = 'sara.elsayed@brokerhub.test' group by 1,2;

-- هل له user_scopes تضيّق النطاق (مدير حساب/خدمة عملاء)؟
select s.scope_type, s.scope_id, c.name from user_scopes s left join clients c on c.id = s.scope_id
where s.user_id = (select id from users where email = 'cs@brokerhub.test');
```

- المندوب: `owner` scope (leads به `assigned_to`، عملاء بـ `account_owner_id`)؛ id خارج النطاق ⇒ **404**.
- المدير/أدمن: `all`؛ المندوب `owner`.
- الشبكة الثانية موصولة الآن (ADR-014): `app/core/rls.py` يثبّت `app.bypass_rls` / `app.scope_user_id` /
  `app.scope_client_id` على كل معاملة تفتحها جلسة الطلب (خطّاف `after_begin`)، فيسري حتى على استعلام نسي
  فلتر المستودع. الاختيار ليس `SET LOCAL` عاريًا لأن نقاط النهاية تعمل `commit` في منتصف الطلب — بل إعادة
  تطبيق عند كل `begin`؛ والقيم المعامة لا تبقى على اتصال الـpool عند انتهائه (بوّابتان في
  `tests/test_rls_postgres.py` تُثبتان الأمرين على PostgreSQL حقيقي).
- **السياسات لا تسري على superuser**، ولو مع `FORCE ROW LEVEL SECURITY`. لذا لا معنى للشبكة ما لم يتصل
  التطبيق بدور `NOBYPASSRLS`: 0003 ينشئ `brokerhub_app` (بلا LOGIN وبمنح بيانات فقط). للتحويل: امنحه كلمة
  مرور ثم بدّل `DATABASE_URL` إليه — `ALTER ROLE brokerhub_app PASSWORD '…';` ثم
  `DATABASE_URL=postgresql+asyncpg://brokerhub_app:…@postgres:5432/brokerhub`. لا تُنشِئ الأدوار يدويًا في
  بيئة لا تملك فيها `CREATEROLE`: الترقية تُكمل وتُنبّه (المهاجرة تتخطّى إنشاء الدور بهدوء).
- فحص من `psql` (المتوقّع `0` لغير المالك، ثم `2` بعد مفتاح التجاوز):

```sql
BEGIN;
SET LOCAL ROLE brokerhub_app;
SELECT set_config('app.bypass_rls', 'off', true);
SELECT set_config('app.scope_user_id', '00000000-0000-0000-0000-000000000000', true);
SELECT count(*) FROM clients;  -- ⇒ 0
SELECT set_config('app.bypass_rls', 'on', true);
SELECT count(*) FROM clients;  -- ⇒ كل الصفوف (نطاق مدير)
ROLLBACK;
```
- تغيير صلاحيات دور يرفع `refresh_token_version` لكل مستخدميه ⇒ جلسات تُنهى. توقّع إعادة دخول.
- تغيير كلمة مرور من شاشة المستخدمين ينهي الجلسات القديمة أيضًا.

### مكتب المبيعات: الاستيراد، وإعادة التوزيع، والمقاعد

| سؤال عند التشغيل | أين الجواب | السلوك المتوقع |
|---|---|---|
| «البيّاع رفع ملف Excel؟» | `POST /leads/import` خلف `leads.view_all` (`backend/app/api/v1/endpoints/leads.py`) | 403 `details.missing = ["leads.view_all"]` — والزر في `KanbanPage` لا يُعرض أصلًا لنفس السبب (إخفاءٌ للواجهة، لا إذن لها) |
| «زر إعادة التوزيع حرّك 25 فقط من 63» | `repo.unassigned_ids` (سقف 2000 صفاً) + `POST /leads/assign-bulk` | لا صفحة ولا حلقة `PATCH`: طلب واحد، و`assigned` في الردّ = عدد الحوض في البطاقة، وسطر `lead.assigned_bulk` واحد للتدقيق وسطر `assignment` لكل ليد |
| «فلان موقوف ولا يُحمَّل شغلاً» | `RepWorkloadOut.is_active` ⇒ `rows.filter((row) => row.is_active)` في منتقي `SalesTeamPage` | الموقوف يبقى على لوحة الحِمل (أعماله الحقيقية لا تختفي) ولا يظهر في المنتقي؛ لو أُرسِل صراحةً في `assign-bulk` ⇒ 422 `Target rep does not exist or is inactive` (الفحص في الخادم، لا في الواجهة) |
| «الملف كبير / مرفوض» | `MAX_ROWS = 5000` · `MAX_FILE_BYTES = 5_000_000` · `.xlsx` أو `.csv` (`backend/app/services/lead_import.py`) | 422 قبل القراءة. داخل الملف: بلا موبايل = error؛ نوع تأمين أو بيّاع لا يطابق = warning ويبقى الصف غير مسند؛ موبايل موجود في lead نشط = skipped ولا يُنشَف |
| «مقعد جديد بلا كلمة مرور» / «أوقفوا حسابًا» | `POST/PATCH /api/v1/sales-team/members[/{user_id}]` | كلمة المرور يولّدها الخادم وتُعرض في الردّ مرة واحدة ولا تُكتب في `audit_logs` (ADR-017 §5)؛ `{"is_active": false}` تمنع تسجيل الدخول (403) وتُخرج المقعد من منتقي التوزيع |

### الرايات (Feature flags) — إطفاء ميزة بدون نشر

تُقرأ من جدول `feature_flags` في كل طلب (ADR-008)، وتُقلَّب `PATCH /api/v1/feature-flags/{key}`
(`{"enabled": true|false}`، للادمن، بسطر في `audit_logs`).

| الراية | ما تفتحه | سلوكها عند الإطفاء |
|---|---|---|
| `phase2.enabled` | شاشات الوثائق/الأقساط/العمولات/الإصدار/التقارير + `POST /exports/insurer-performance` + `GET /reports/*` | 503 `feature_disabled` مع `details.flag` (وليس 403: «الميزة مطفأة» حالة خدمة) |
| `ai.enabled` | `POST /api/v1/ai/calls/{id}/transcribe` · `POST /api/v1/ai/requests/{id}/summarize` · `POST /api/v1/ai/classify` | نفس الـ503. `GET /api/v1/ai/status` يبقى مقروءًا بدون الراية حتى تُخفي الواجهة زر «تلخيص آلي» (ADR-013) |
| `whatsapp.enabled` · `telephony.enabled` | — | **غير مطبقتين في الكود بعد**: الرايتان مزروعتان في الجدول فقط، ومسارا الـwebhook لا يقرأهما. موثّق كفجوة في `STATUS.md` (سطر 11) |


### إعدادات التكاملات (الشاشة، الكاش، الأسرار)

الشاشة `/settings` → تبويب «التكاملات» تكتب في `integration_configs`، والسائقون يقرأون عبر
`registry.prime()` — كاش داخل العملية لا مصدر ثانٍ للحقيقة (ADR-016 §1). عملياً:

| الحالة | ما يحدث | ما يُطلب منك |
|---|---|---|
| حفظت من الشاشة | السطر يُكتب ثم تُحمَّل القيم في ذاكرة **العملية التي خدمت الطلب** | لا شيء؛ الاختبار التالي يخرج بالقيمة الجديدة |
| نشر متعدد العمال (`uvicorn --workers N`) | بقية العمليات تبقى على نسختها حتى تُعاد | بعد تغيير يمسّ الأمان (`verify_token`, `webhook_secret`, `app_secret`) أو قبل التحوّل إلى الحيّ: `docker compose restart api` |
| `verify_token` مضبوط من الشاشة | مصافحة Meta (`GET /webhooks/whatsapp?hub.verify_token=…`) تقارنه بخريطة **الأسرار** | لا تضبطه في `config`؛ لا يوجد مثل هذا الحقل. بلا قيمة محفوظة الرفض 403 برسالة «اضبط Verify Token في /settings أولًا» |
| تدوير `SECRETS_ENCRYPTION_KEY` | اضبط `SECRETS_ENCRYPTION_KEY_OLD` بالمفتاح القديم مدة التدوير: قراءة با القديمة وكتابة بالجديد | بعد إعادة حفظ الأسرار من الشاشة **احذف المتغير القديم**؛ النافذة ليست دائمة |
| مفتاح بلا قيمة في `ENV=prod` | الإقلاع تفشل عمداً | `SECRETS_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")` |
| «اختبار الاتصال» يرفض | 429 مع `details.retry_after_seconds` (6/دقيقة/مستخدم) | انتظر الثواني؛ لا تحتاج إعادة تشغيل |

لا يوجد مسار يقرأ سرّاً إلى المتصفح: `GET /settings/integrations/{provider}` يعطي
`{"set": true, "display": "••••••••"}` فقط، والحقل الفارغ في الحفظ = «لا تغيير»، و`null` = حذف (ADR-016 §2).
كل حفظ وكل اختبار وكل تبديل حيّ/محاكاة يكتب صفاً في `audit_logs` بأسماء الحقول لا بقيمها.

بوابة «كل النقاط شغّالة»: `python scripts/smoke_api.py` — قاعدة مؤقتة مُزروعة ثم كل `(path, method)` في
وثيقة OpenAPI (107 نداءً؛ 2 مستثنيان بسبب مكتوب). تُشغَّل في CI بعد بوابات التغطية.


## 6) الوسائط والتسجيلات

- كل مرفق وارد من مزوّد خارجي يُنسخ إلى دلائنا أولًا (`stage_inbound_media`)؛ لا نعرض روابط المزوّد.
- رابط التشغيل موقّع وقصير العمر: `RECORDING_SIGNED_URL_TTL_SECONDS` (120 ثانية افتراضيًا). «403/404 بعد
  قليل من الفتح» يعني أن الرابط انتهت صلاحيته — الواجهة تطلب رابطًا جديدًا عند كل ضغطة، لا تُخزّنه.
- كل استماع يسجّل `call.recording_listened` في `audit_logs` مع `ttl_seconds` و`recording_consent`.
- التعديل السريع عند ضياع كائن: مع `STORAGE_BACKEND=s3` استخدم
  `aws s3api head-object --bucket brokerhub --key <object_key>`؛ ومع المخزن المحلي ابحث في وحدة
  `objectsdata` (`docker compose exec backend ls -l /srv/objects/<prefix>`).

## 7) حوادث متكررة — تشخيص من نقطتين

| العَرَض | أول فحص | ثاني فحص |
| --- | --- | --- |
| رسالة واتساب واردة لم تفتح طلبًا | `docker compose logs backend \| grep webhooks/whatsapp` (401 توقيع؟) | `INTEGRATIONS_DRIVER` (إن كان `live` فلن يعمل `/dev/sim`)، و`WHATSAPP_APP_SECRET` |
| نفس الرسالة فتحت طلبين | `select external_id, count(*) from request_messages group by 1 having count(*)>1` | الفهرس الفريد على `external_id` موجود؟ (0002) |
| التسجيل لا يعمل | الشبكة: هل `src` يبدأ بـ `/api/v1/media/`؟ | صلاحية `calls.listen` للدور، وتاريخ `expires=` |
| المندوب يرى بيانات زميل | `Scope.mode` (يجب `owner`) | هل `account_owner_id/assigned_to` مضبوطة؟ وسياسات RLS مفعّلة (`ALTER TABLE … ENABLE ROW LEVEL SECURITY`) |
| بورتال أظهر بيانات داخلية | `grep -n "commission\|note" app/services/portal.py` (يجب ألا يوجد) | شغّل `pytest tests/test_portal.py -q` — فيه اختبار يمنع المفاتيح الحساسة |
| استيراد Excel معلّق | `select id,status,total_rows,stats from import_jobs order by created_at desc limit 5` | `status='dry_run'` يعني لم يُضغط تأكيد؛ `failed` اقرأ `error_report` |
| اللوحة أرقامها قديمة | TanStack Query cache: `staleTime` في `src/lib/api/client.ts` | شغّل `sla_sweep` يدويًا: `celery call broker_hub.sla_sweep` |
| 429 عند الدخول | `LOGIN_MAX_ATTEMPTS` (5) و`LOGIN_LOCKOUT_SECONDS` (300) | الجدول في `app/services/auth.py`؛ إعادة التشغيل تصفّر العدّادات في الوضع غير الدائم |

## 8) النسخ الاحتياطي والاستعادة

```bash
docker compose -f infra/docker-compose.yml exec -T postgres \
  pg_dump -U broker -d brokerhub -Fc -f /tmp/brokerhub.dump
docker compose -f infra/docker-compose.yml cp postgres:/tmp/brokerhub.dump ./backups/
# الاستعادة (توقف الخدمات أولًا)
docker compose -f infra/docker-compose.yml exec -T postgres pg_restore -U broker -d brokerhub --clean --if-exists < ./backups/brokerhub.dump
```

- الوسائط: دلو MinIO (أو الـS3 المضبوط) — خُذ نسخة منه أيضًا؛ الطلبات بلا وسائط تكون ناقصة.
- لا تُخزَّن نسخ في المستودع؛ مجلد `backups/` خارج git.

## 9) الطوارئ الأمنية

| حالة | تصرف |
| --- | --- |
| تسرّب `JWT_SECRET` | غيّره وأعد تشغيل الـAPI: كل access token يسقط فورًا. لا يمكن إبطال refresh دفعة واحدة بدون تدوير `refresh_token_version` — نفّذه لكل المستخدمين من SQL عند الحاجة |
| حساب مندوب مُسرَّب | عطّله من شاشة المستخدمين (`is_active=false`)؛ الدخول يُرفض والجلسة الحالية تسقط عند أول refresh |
| اشتباه قراءة تسجيلات بلا إذن | `select * from audit_logs where action='call.recording_listened' and occurred_at > now() - interval '1 day'` |
| تعديل صلاحيات خاطئ جماعي | `PUT /api/v1/roles/{id}/permissions` بالدور الصحيح؛ التدقيق في `audit_logs` يحمل `before/after` |
