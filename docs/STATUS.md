# STATUS — منصة إدارة الوساطة التأمينية (Broker Hub)

آخر تحديث: 2026-10-26 · فرع العمل: `arena/358fbc4e-insurance-platform-new`

مرجع التحقق: ملف تصميم الواجهات (16 شاشة) المرفق من صاحب المشروع + نصّ المواصفات §1–§13.
قاعدة العمل: لا يُكتب «مطابقة» إلا بموافقة المالك — انظر [`ui-parity/`](ui-parity/README.md).

## حالة المراحل

| مرحلة | الحالة | ما يثبت ذلك |
| --- | --- | --- |
| M0 توثيق القرار والهيكل | ✅ منتهية | [`decisions/001-architecture.md`](decisions/001-architecture.md) + هيكل المستودع (`backend/ frontend/ infra/ docs/ .github/`) |
| M1 التخطيط: الجلسات والصلاحيات والعزل | ✅ منتهية | `app/core/{security,scope,deps}.py` · 33 جدول · `tests/test_isolation_matrix.py` (404 لكل id خارج النطاق) · ADR-005 |
| M2 الهياكل المرجعية (شركات/أنواع/مستندات/أسباب فقد/ساعات عمل/SLA) | ✅ منتهية | `app/models/masters.py` · `app/data/insurers_eg.csv` (37 شركة مرخّصة من السجل الرسمي) · `tests/test_masters.py` |
| M3 قنوات الورود (واتساب/مكالمات) + محاكي + SLA | ✅ منتهية | `app/integrations/*` · `webhooks.py` (توقيع + idempotency) · `tests/test_intake.py` · `GET /api/v1/dev/sim` لوحة محاكاة حقيقية |
| M4 الطلبات: صندوق موحّد + ردود + ملاحظات داخلية + تسجيلات | ✅ منتهية | `services/requests_svc.py` · `tests/test_requests_flow.py` `test_requests_svc.py` · روابط موقّعة قصيرة العمر + تدقيق لكل استماع |
| M5 المبيعات: Leads/Kanban/تحويل ذرّي | ✅ منتهية | `services/leads.py` (`convert` في معاملة واحدة + idempotent) · `tests/test_leads_flow.py` |
| M6 العملاء وملف العميل والمؤمَّن عليهم + Excel | ✅ منتهية | `services/clients.py` · `tests/test_import_insured.py` `test_clients_crud.py` · معاينة→تأكيد→تقرير |
| M7 البورتال | ✅ منتهية | `services/portal.py` · `tests/test_portal.py` (اختبار يمنع تسرّب أي مفتاح حسّاس) |
| M8 المرحلة الثانية (وثائق/أقساط/عمولات/إصدار/تقارير) خلف flag | 🟡 واجهات كاملة + API مقروء؛ الأعمال اليدوية فقط | `api/v1/endpoints/phase2.py` · `tests/test_dashboard_phase2.py` · الشاشات 12–14 تعمل عند تفعيل `phase2.enabled` |
| M9 التوثيق والمحاكاة وتشغيل UI | 🟡 جزئي | هذا الملف + [`runbook.md`](runbook.md) + [`ui-parity/`](ui-parity/README.md) · لقطات الشاشة تُنتَج في CI فقط (انظر «ما لم يُشغَّل») |
| M10 الاختبارات النهائية + parity + تجهيز الدمج | 🟡 جارية | CI أخضر محليًا (backend+frontend)؛ e2e مكتوبة و typecheck ✓ لكن لم تُشغَّل (لا متصفح في البيئة) |

## ما شُغِّل فعليًا (هذه الجلسة، نفس نتائج CI)

backend (`/home/user/.venv2`، Python 3.11، SQLite):

```
ruff check .            → All checks passed!
mypy app                → Success: no issues found in 85 source files
pytest -q               → 103 passed
coverage report         → TOTAL 81.7%  · كل ملفات النواة ≥80% (بوابة `scripts/check_core_coverage.py`
                          تقرأ `coverage json`، لأن `skip_covered` كان يُخفي الملفات المغطاة 100% ويحوّلها إلى FAIL)
scripts/export_openapi.py → docs/api/openapi.json (75 path, 101 schema)
```

frontend (Node 22):

```
eslint . --max-warnings 0 → 0 مشكلة
tsc -p tsconfig.json      → نظيف      · tsc -p tsconfig.e2e.json → نظيف
vitest run                → 42 passed / 5 files
npm run build             → ✓ (chunks لكل شاشة)
playwright test --list    → 112 tests / 8 files (desktop + mobile)
```

تحقق حيّ من التشغيل (بدون متصفح): رفع الـAPI بقاعدةSeed جديدة ثم
`GET /healthz` · `POST /auth/login` · `POST /dev/sim/whatsapp` (رسالة صوتية → طلب #1025 + مرفق صوتي عبر رابط موقّع يُرجع 200) ·
`POST /dev/sim/call` (مكالمة + recording) · `GET /dev/sim` (HTML 200) · `GET /leads` (16 لـ rep مقابل 63 لمدير) + 404 لـ lead خارج النطاق ·
`GET /portal/overview` (بلا عمولات/ملاحظات) + 403 على `/requests` · `PATCH /feature-flags/phase2.enabled` ثم `/policies` + `/reports` ✓.
و`vite dev` مع الوصلة الأمامية `/api` (تسجيل دخول عبر المنفذ 5173 → 200).

## ما لم يُشغَّل ولماذا

1. **Playwright e2e واللقطات**: لا يوجد متصفح في هذه البيئة (لا شبكة لتنزيل `playwright install`)، لذلك
   `npm run e2e` لم يُنفَّذ. الاختبارات مكتوبة ومُفحوصة الأنواع وقائمة الاكتشاف سليم (112 اختبارًا)،
   ووظيفة الخادمين (API + Vite) متحققة يدويًا أعلاه. أول تشغيل لها في CI هو الحكم.
2. **docker compose**: لا Docker في البيئة. الملفات مُتحقق منها هيكليًا (YAML مُحلَّل، كل `depends_on`
   يشير لخدمة موجودة، كل `${VAR}` له قيمة في `infra/.env.example`، موازِنات `{}` في nginx.conf) —
   لكن البناء الفعلي والتشغيل يحدثان في وظيفة `docker` في CI.
3. **اختبارات PostgreSQL الحقيقية** (`postgres_only`): لم تُشغَّل لغياب PG محليًا؛ تُشغَّل في CI عبر
   خدمة postgres مع `DATABASE_URL_TEST`.
4. **رقم «47 شركة تأمين»**: السجل المُبذَّر في `insurers_eg.csv` فيه 37 شركة مُتحقق من أسمائها من
   الكتاب الإحصائي للهيئة العامة للرقابة المالية. الباقي يُحمَّل بنفس المسار المستخدم للإنتاج
   (`POST /api/v1/insurers/import-csv`). لم نخترع أسماء لسدّ العدد.

## اختصارات وانحرافات مسجّلة (لا شيء مخفيًا في الكود)

| # | الانحراف | السبب / التصرف |
| --- | --- | --- |
| 1 | المرفقات الصوتية الواردة تُربط بالرسالة في طبقة العرض (`serializers.request_detail`) لا عبر `owner_type="message"` | لا توجد قيمة `message` في `AttachmentOwner` وإضافتها تحتاج migration؛ الربط الحالي مرتب-بالأقدم ويغطي الواقع (مقطع واحد لكل رسالة). موثّق في ADR-007 |
| 2 | أرقام «+12% عن أمس» و«أسرع بـ4 دقائق» محسوبة من `requests_yesterday` / `avg_first_response_delta_minutes`، لكن «الهدف 90%» و«تحتاج تدخلاً» نص ثابت | لا يوجد نموذج لهدف SLA يومي في §5؛ انظر `ui-parity/screens.md` |
| 3 | «قسم المالية» في صف العميل بموك-أب الشاشة 1 غير موجود في النموذج | لا عمود لقسم الموظف في `service_requests`؛ يُعرض اسم الموظف فقط |
| 4 | رضا العميل في شاشة المدير يعرض `—` مع إيضاح `phase2.notTracked` | لا يوجد قياس NPS/رضا في §5 |
| 5 | زر تصدير التقارير معطّل مع سبب `phase2.exportPending` | §10 يطلب تصديرًا عبر Celery؛ التنفيذ مؤجَّل للمرحلة 2 ولم نُدّعِ أنه جاهز |
| 6 | شاشات المرحلة الثانية خلف `phase2.enabled` تعرض «غير مفعّلة بعد» | تعليمية المالك الصريحة |
| 7 | لا يوجد `/import-jobs/{id}/template` | لم يُكتب في §7؛ الواجهة لا تطلبه |
| 8 | اللقطات تُكتب باسم `desktop-NN-*` / `mobile-NN-*` داخل `docs/screenshots/` ويرفعها CI كـ artifact؛ لا يُلتزَم بها في المستودع تلقائيًا | قرار المالك بعد المراجعة البصرية |
| 9 | مسارات الحظر في المرحلة الثانية ترجع **503** `feature_disabled` لا 403 | «الميزة مطفأة» حالة خدمة وليست عجز صلاحيات؛ موثّق في `decisions/008` |
| 10 | **فجوة معروفة:** سياسات RLS في migration 0002 تقرأ `app.scope_user_id`/`app.bypass_rls`، و`Scope.session_settings()` يولّدهما، لكن لا مستدعٍ يطبّقهما على جلسة الطلب ⇒ RLS حالياً شبكة للوصول المباشر للقاعدة فقط | لا Postgres هنا لاختبار المسار؛ ربط الـGUC يجب أن يُعمل مع اختبار `postgres_only` قبل الاعتماد عليه في الإنتاج (`decisions/003`) |

## قرارات اتُّخذت نيابة عن المالك (لأن الأسئلة غير مسموحة)

| قرار | ملف |
|---|---|
| 001 الهيكل والمكدّس والـstack الثابت | [`decisions/001-architecture.md`](decisions/001-architecture.md) |
| 002 أرضيات الاعتماديات و`pip-audit` | [`decisions/002-dependency-floors.md`](decisions/002-dependency-floors.md) |
| 003 SQLite للوحدة وPostgres للتكامل (+وضع RLS الحالي) | [`decisions/003-sqlite-tests-postgres-integration.md`](decisions/003-sqlite-tests-postgres-integration.md) |
| 004 interpol واحد في react-i18next | [`decisions/004-i18n-interpolation.md`](decisions/004-i18n-interpolation.md) |
| 005 خصوصية البوابة بالحذف من النموذج | [`decisions/005-portal-privacy-by-absence.md`](decisions/005-portal-privacy-by-absence.md) |
| 006 Playwright واللقطات في CI | [`decisions/006-e2e-screenshots-in-ci.md`](decisions/006-e2e-screenshots-in-ci.md) |
| 007 تخزين الوسائط الواردة | [`decisions/007-inbound-media-staging.md`](decisions/007-inbound-media-staging.md) |
| 008 المرحلة الثانية خلف `feature_flag` | [`decisions/008-phase2-feature-flags.md`](decisions/008-phase2-feature-flags.md) |
| 009 سجل شركات التأمين (37 لا 47) | [`decisions/009-insurer-register.md`](decisions/009-insurer-register.md) |
| 012 جدول تدقيق الاعتماديات | [`decisions/012-dependency-audit.md`](decisions/012-dependency-audit.md) |

## قائمة ما قبل «جاهز للمراجعة»

- [x] parity للتوكنات مقصوصة من §4 ومحمية باختبار (`frontend/tests/tokens.test.ts`: 20 تأكيدًا على القيم نفسها)
- [x] عزل المندوب مُختبَر بالـ404 (backend matrix + `e2e/isolation.spec.ts`)
- [x] لم تُعدَّل أي migration مُدمجة؛ 0001/0002 فقط، وأي تغيير جديد يُضاف كـ0003
- [x] لا أسرار في المستودع: `.env` مُستثنى، والموجود أمثلة فقط (`backend/.env.example`, `frontend/.env.example`, `infra/.env.example`)
- [x] لا بيانات شخصية حقيقية في الـseed (أسماء/أرقام وهمية، نطاق `@brokerhub.test`، `+201…` غير مخصّصة)
- [~] لقطات الـ16 شاشة + contact sheet: مكتوبة وتعمل في CI، لم تُلخَّص محليًا (بلا متصفح)
- [x] README فيه تشغيل بأوامر ثلاثة + تشغيل بلا Docker
- [x] runbook + STATUS + ui-parity (README + screens.md بكل فوارق §9) + سجل القرارات 001–009 و012
- [x] CI: ruff+mypy+pytest+بوابة تغطية النواة+تدقيق الاعتماديات+فحص staleness للـOpenAPI، lint/typecheck/vitest/build للواجهة، e2e، وبنائي Docker
