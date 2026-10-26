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

- `migrate` و `minio-init` مهمتان لمرة واحدة تخرجان بنجاح؛ إذا فشل أحدهما فلن يبدأ `backend` (بوابة
  `service_completed_successfully`).
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

- لا تُحرَّر migration مُدمجة أبدًا؛ أضف واحدة جديدة (`alembic revision -m "..."`).
- 0001 = الأساس الكامل؛ 0002 = RLS + فهارس جزئية (PostgreSQL فقط، تقفز على SQLite).
- قبل الدمج: `alembic upgrade head` على نسخة من قاعدة الإنتاج (أو `docker compose run --rm migrate`).
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
- المدير/أدمن: `all`؛ المندوب `owner`. `Scope.session_settings()` يهيّئ GUC المطلوب (`app.bypass_rls`,
  `app.scope_user_id`) لكن **تطبيقها على جلسة الطلب غير موصول بعد** (ADR-003): سياسة RLS تُختبر بالفحص
  اليدوي أعلاه، والحماية النافذة حالياً هي طبقة المستودعات.
- تغيير صلاحيات دور يرفع `refresh_token_version` لكل مستخدميه ⇒ جلسات تُنهى. توقّع إعادة دخول.
- تغيير كلمة مرور من شاشة المستخدمين ينهي الجلسات القديمة أيضًا.

## 6) الوسائط والتسجيلات

- كل مرفق وارد من مزوّد خارجي يُنسخ إلى دلائنا أولًا (`stage_inbound_media`)؛ لا نعرض روابط المزوّد.
- رابط التشغيل موقّع وقصير العمر: `RECORDING_SIGNED_URL_TTL_SECONDS` (120 ثانية افتراضيًا). «403/404 بعد
  قليل من الفتح» يعني أن الرابط انتهت صلاحيته — الواجهة تطلب رابطًا جديدًا عند كل ضغطة، لا تُخزّنه.
- كل استماع يسجّل `call.recording_listened` في `audit_logs` مع `ttl_seconds` و`recording_consent`.
- التعديل السريع عند ضياع كائن: `aws s3api head-object --bucket brokerhub --key <object_key>` أو من
  حاوية minio (`mc ls local/brokerhub/<prefix>`).

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
