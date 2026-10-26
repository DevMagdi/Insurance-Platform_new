# STATUS — منصة إدارة الوساطة التأمينية (Broker Hub)

آخر تحديث: 2026-10-26 · فرع العمل: `arena/16c2338f-insurance-platform-new` (`main` عند `4a785c5`، PR #1
و#2 مدموجان). هذه الجولة = **R0** من خطة إعادة التحقق: لا يُكتب «تم» إلا مع الأمر ومخرجاته، وما لا يُشغَّل
يُكتب «لم يُشغَّل» مع سببه الحرفي.

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
| M10 الاختبارات النهائية + parity + تجهيز الدمج | 🟡 جارية | backend أخضر على **PostgreSQL 16** (138) وعلى SQLite (129 + 9 مُتخطَّاة بعلامة `postgres_only`) · frontend أخضر (51 اختبار وحدة + build) · e2e: typecheck ✓ واكتشاف 114 اختبارًا ✓ لكنها **لم تُشغَّل** (لا متصفح — «ما لم يُشغَّل» 1) · ruff/mypy/تغطية النواة/استقرار الـOpenAPI كلها نظيفة |
| مزوّد AI (§11 M10): واجهة واحدة خلف `ai.enabled` + مراجعة بشرية | ✅ السطح كامل بسائق محاكاة · ⬜ بلا مزوّد حقيقي | `integrations/ai_sim.py` (حتمي، استخلاصي) · `endpoints/ai.py`: `GET /ai/status` · `POST /ai/calls/{id}/transcribe` · `POST /ai/requests/{id}/summarize` · `POST /ai/classify` · `tests/test_ai.py` (7) · زر «تلخيص آلي» في `InboxPage` يظهر فقط عند تشغيل الراية · ADR-013 |

## ما شُغِّل فعليًا (هذه الجلسة، نفس نتائج CI)

backend — **على محرّكَي القاعدة**، لأن `DATABASE_URL_TEST` صار يحدّد المحرّك (ADR-014):

```
ruff check .            → All checks passed!           (129 ملفاً)
ruff format --check .   → 129 files already formatted
mypy app                → Success: no issues found in 96 source files
python -m pytest        → 129 passed, 9 skipped in 97.91s      (SQLite؛ التسعة هي `postgres_only`)
DATABASE_URL_TEST=postgresql+asyncpg://… python -m pytest
                        → 138 passed in 113.92s                (PostgreSQL 16.2 حقيقي، بلا تخطٍّ)
coverage report         → TOTAL 5601/979 → 82.5% · بوابة النواة `scripts/check_core_coverage.py` ✓
scripts/check_openapi_fresh.py → openapi.json is fresh (84 paths, 110 schemas)
scripts/check_migrations.py    → migration immutability ok (2 merged, 0 new)
alembic upgrade head    (PostgreSQL 16، قاعدة فارغة)      → rc 0
alembic downgrade base  →  upgrade head (نفس القاعدة)     → rc 0
   33 جدولاً · 55 مفتاحاً أجنبياً · سِياسَتا `leads_scope`/`clients_scope` · `relforcerowsecurity = t` عليهما
   · دور `brokerhub_app` بـ`bypass=false login=false`
alembic upgrade head    (ملف SQLite فارغ)                 → rc 0 (41 فهرساً، وقيد `clients→leads` موجود)
```

PostgreSQL شُغِّل هنا بـحزمة `pgserver` (محرّك مضمّن، بلا Docker) — لا ادّعاء تغطية على PG بغير تشغيله.
13 اختباراً جديداً في هذه الجولة: `tests/test_rls_postgres.py` (8، كلها `postgres_only`) و
`tests/test_migrations.py` (5، واحد منها `postgres_only`). لذلك الفرق بين رقمَي المحرّكين = 9: ثمانية
مُتخطَّاة + اختبار السلسلة على PG الذي يعمل هناك وحده.

frontend (Node 22):

```
eslint . --max-warnings 0 → 0 مشكلة
npm run typecheck         → نظيف (tsconfig.json + tsconfig.e2e.json؛ الأول يغطي `tests/` أيضاً)
vitest run                → 51 passed / 7 files  (منها 8 لـ`navModel` و3 لبوابة مسارات المستندات)
npm run build             → ✓ (chunks لكل شاشة)
playwright test --list    → 114 tests in 8 files (desktop + mobile)
```

تحقق حيّ من التشغيل (بدون متصفح): رفع الـAPI بقاعدةSeed جديدة ثم
`GET /healthz` · `POST /auth/login` · `POST /dev/sim/whatsapp` (رسالة صوتية → طلب #1025 + مرفق صوتي عبر رابط موقّع يُرجع 200) ·
`POST /dev/sim/call` (مكالمة + recording) · `GET /dev/sim` (HTML 200) · `GET /leads` (16 لـ rep مقابل 63 لمدير) + 404 لـ lead خارج النطاق ·
`GET /portal/overview` (بلا عمولات/ملاحظات) + 403 على `/requests` · `PATCH /feature-flags/phase2.enabled` ثم `/policies` + `/reports` ✓.
و`vite dev` مع الوصلة الأمامية `/api` (تسجيل دخول عبر المنفذ 5173 → 200).
كما تحقّق حيّ من `vite preview` على الحزمة المبنية: `/login` → 200 و`/api/v1/auth/login` عبر الـproxy → 200
و`GET /api/v1/requests` بجلسة حقيقية → بيانات مزروعة (طلبات برقم 1003+).

## ما أصلحه أول تشغيل لـ CI على هذا الطلب

| الفشل | السبب | الإصلاح |
|---|---|---|
| `backend · OpenAPI export must be committed` | مقارنة نصية: إصدار FastAPI يغيّر حقولاً تجميلية في الملف المولّد | `backend/scripts/check_openapi_fresh.py` يقارن JSON محلولاً ويطبع أول 12 تبايناً |
| `e2e · config.webServer was not able to start` | `webServer.env` يستبدل البيئة ⇒ ضاع `PATH` فاشتُغل بـ python بلا alembic؛ و`bash -lc` كان يخفي المشكلة | البيئة تُدمج مع `process.env`، والقيادة `sh -c` بلا login shell، و`reuseExistingServer` مطفأ في CI |
| بوابة تغطية النواة FAIL على ملف مغطى 100% | `skip_covered` في `pyproject.toml` يُخفي الملف من `coverage report` | البوابة تقرأ `coverage json` |
| `ruff format --check` على 5 ملفات | تنسيق لم يُجرَ محلياً | `ruff format .` ثم أُعيد التصدير والتوليد |
| `e2e`: أول 9 اختبارات في مشروع desktop تسقط بعناوين مفقودة | تبريد Vite (أول transform للمسار) يلتهم مهلة 8–20 ثانية؛ نفس الـ specs تنجح بعد ثوانٍ | `e2e/global-setup.ts` يفتح `/login` وينتظر النموذج قبل المجموعة، وCI يشغّل `vite preview` على الحزمة المبنية (`E2E_USE_PREVIEW=1`) |
| `e2e/insured.spec.ts`: `after.total === undefined` | الاختبار قرأ غلافاً مسطحاً، و`GET /clients/{id}/insured` يرجع `{kpis, page:{items,total}}` | يُقرأ `page.total` من دالة `rosterTotal()` — الخادم كان صحيحاً والاختبار هو الغلط |

بعد الإصلاحات في PR #2: `backend` ✅ · `frontend` ✅ · `docker` ✅ · `e2e` أحمر بعشرة تشخيصات — صُححت
مقدّماتها (ADR-015) ولم يُخفَّف أي تأكيد. تشخيصات CI لا تُقرأ من ذاكرة: تُسحب بـ
`gh api repos/DevMagdi/Insurance-Platform_new/check-runs/<id>/annotations`. نتائج أول تشغيل بعد هذه
الجولة تُذكر في نص الطلب، ولا يُنقل هنا رقم لم يُنفَّذ.

## ما كشفه أول تشغيل حقيقي (وهو مضمون ADR-014)

| كان مُسلَّماً به | ما حدث عند التشغيل | التصرف |
|---|---|---|
| «0001 هو الأساس الكامل» | `alembic upgrade head` يسقط على PostgreSQL بـ`relation "users" does not exist`: الجداول الـ33 بترتيب أبجدي، فـ`clients` تُبنى قبل `users`. أي أن `compose up` — المسار الموثّق — لم يُقلع من قاعدة فارغة قطّ | ترتيب طوبولوجي، وكسر حلقة `leads ↔ clients` بإضافة `clients.source_lead_id` بعد وجود الجدولين في وضع batch. لا عمود أُضيف ولا حُذف ولا أُعيدت تسميته |
| «0002 يفعّل RLS» | `CREATE POLICY … FOR UPDATE, DELETE` ليست SQL صحيحة (سياسة = أمر واحد) ⇒ `syntax error at or near ","` | سياسة لكل أمر في 0002، ثم سياسة واحدة `FOR ALL` في 0003 |
| «CI تشغّل المجموعة على Postgres» | `tests/conftest.py` كان يبني SQLite دائماً رغم خدمة `postgres` و`DATABASE_URL_TEST` ⇒ لم يرَ أي اختبار PostgreSQL قطّ. أول رؤية وجدت خطأً حقيقياً: `function round(double precision, integer) does not exist` في `app/services/exports.py` | المحرّك يحدّده `DATABASE_URL_TEST`؛ التصدير يعمل `cast(… → NUMERIC(12,4))` قبل `round` (نفس النتيجة على المحرّكين) |
| «تفعيل السياسات كافٍ» | سياسة قراءة بلا سياسة كتابة على جدول `FORCE` ⇒ PostgreSQL يرفض كل `INSERT` للدور غير المميّز؛ و`FORCE ROW LEVEL SECURITY` نفسه لا يسري على superuser، وكل البيئات كانت تتصل كمالك القاعدة | `FOR ALL` مع `WITH CHECK` في 0003 + دور `brokerhub_app` + خطوتا `DATABASE_URL` في runbook §5 |
| «هوية الترقية نصّ حرّ» | `0003_rls_portal_clause_and_app_role` = 34 حرفاً > `VARCHAR(32)` لعمود `alembic_version.version_num` ⇒ يفشل **بعد** تنفيذ الـDDL كله | هوية أقصر + بوابة `test_every_revision_id_fits_the_version_table` |
| «بوابة منع تحرير الترقيات موصولة» | `scripts/check_migrations.py` كان موثّقاً في ADR-001 «في CI» لكنه لم يكن في أي وظيفة؛ وكان يعمل من جذر المستودع فقط (ومن `backend/` لا يجد شيئاً فيمرّ) | وُصل في وظيفة `backend` مع `fetch-depth: 0`، وصار يستدعي git بـ`-C <root>` |

## ما لم يُشغَّل ولماذا

1. **Playwright e2e واللقطات (16 شاشة)**: `npm run e2e` لم يُنفَّذ — لا متصفح في البيئة. جُرِّب فعلاً هذه
   المرة: `npm i -D @sparticuz/chromium` نزّل chromium حقيقيًا (68 م.ب) و`chromium.launch()` عثر عليه، ثم
   مات عند `error while loading shared libraries: libnspr4.so` — تنقص `libnspr4/libnss3/libnssutil3`، ولا
   صلاحية root لتثبيتها (`apt-get update` مرفوض)، ولا مصدر شبكة مصرّح به لها. أُزيلت الاعتمادية من
   `package.json` بدل ترك اعتماد ميت. المتوقَّع: لا دليل على خضرة e2e غير وظيفة `e2e` في CI. المتحقق هنا:
   أنواع نظيفة (app + e2e + tests)، واكتشاف 114 اختبارًا، ووظيفة الخادمين يدويًا، وأن كل تأكيد في الـspecs
   قورن بسطر في الكود (ADR-015).
2. **docker compose**: لم يُشغَّل `up` محليًا (لا Docker). الملفات متحققة هيكليًا، ووظيفة `docker` في CI صارت
   تتجاوز `config --quiet` إلى الإقلاع الكامل للـstack: `up -d --wait` ثم `GET /healthz`، و`/` من nginx،
   و`/api/v1/openapi.json` عبر الـproxy، ثم `python -m app.seed` وتسجيل دخول و`GET /clients`. هذا دليل G2
   المطلوب — ولا يُكتب «يعمل» قبل أن تُخضر تلك الخطوات في CI.
3. **ما يبقى على بيئة نشر**: تشغيل التطبيق بدور `brokerhub_app` بدل مالك القاعدة (السياسات لا تسري على
   superuser). الترقية تنشئ الدور؛ سلسلة الاتصال قرار نشر، لا كود.
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
| 5 | تصدير **Excel يعمل** (`POST /api/v1/exports/insurer-performance` ← نفس استعلام الشاشة، سقف 5000 صّف، مدقَّق). زر **PDF** باقٍ معطّلاً بالسبب `phase2.exportPdfPending` | §7 يطلب `/exports/*`؛ PDF يحتاج تشكيلاً عربياً وخطاً مضمّناً — قرار موثّق في `decisions/010-exports.md` |
| 6 | شاشات المرحلة الثانية خلف `phase2.enabled` تعرض «غير مفعّلة بعد» | تعليمية المالك الصريحة |
| 7 | لا يوجد `/import-jobs/{id}/template` | لم يُكتب في §7؛ الواجهة لا تطلبه |
| 8 | اللقطات تُكتب باسم `desktop-NN-*` / `mobile-NN-*` داخل `docs/screenshots/` ويرفعها CI كـ artifact؛ لا يُلتزَم بها في المستودع تلقائيًا | قرار المالك بعد المراجعة البصرية |
| 9 | مسارات الحظر في المرحلة الثانية ترجع **503** `feature_disabled` لا 403 | «الميزة مطفأة» حالة خدمة وليست عجز صلاحيات؛ موثّق في `decisions/008` |
| 10 | ~~فجوة RLS~~ **أُغلقت في هذه الجولة**: الـGUC تُطبَّق على جلسة كل طلب (`app/core/rls.py`)، و0003 يضيف سياسة `FOR ALL` + بند البوابة + دور `brokerhub_app` | الدليل: `tests/test_rls_postgres.py` (8 اختبارات، PostgreSQL 16) و`tests/test_migrations.py` (5). ما لم يُغلق: تشغيل النشر الفعلي بالدور بدلاً من المالك — يحتاج DSN في بيئة نشر (runbook §5) |
| 10ب | استثناء مُوقَّع على قاعدة «لا تُحرَّر migration»: 0001 و0002 عُدِّلا | لم تكونا قابلتَي التشغيل على PostgreSQL إطلاقاً، فلم تُطبَّقا على أي قاعدة؛ والبديل (ترقية تالية تصلّح ما قبلها) مستحيل لأن 0001 يفشل قبلها. الوسم `# ALEMBIC-REWRITE-APPROVED:` داخل الملف + بوابة `scripts/check_migrations.py` ترفض أي تعديل بلا وسم. ADR-014 |
| 10ج | قاعدة الاختبار يحددها `DATABASE_URL_TEST` (فارغ ⇒ SQLite ملف مؤقت؛ postgres ⇒ نفس المجموعة على PG) | جعل CI «تعمل على Postgres» عبارة صحيحة بدلاً من خدمة مزخرفة؛ محلياً `pgserver`. لا تُترك الاختبارات «مريحة لمحرّك واحد» |
| 10د | لا فرع `fix/rN-*` لكل مرحلة رغم التعليمات | المنصّة تجمس الجلسة على فرع واحد (`arena/16c2338f-…`) ولا تسمح بتغييره؛ البديل المطبَّق: commit مستقل لكل نقطة عمل + هذا السطر يسجّله. لا شيء يُدمج في `main` من هنا |
| 10هـ | `docs/ui-parity/screens.md` صار يُطابق الكود لا النوايا، وبوابة `frontend/tests/docPaths.test.ts` تفشل إن سمّى مستندٌ ملفاً غير موجود | المستند كان يصف ملفات وشاشات لا توجد (`KanbanPage` بمسار خاطئ، `RenewalsKpi`، KPIs باسم «تجديدات»)؛ أسماء ورقة التصميم نفسها غير قابلة للتحقق هنا لأن الورقة ليست في المستودع — لذا لا تُكتب «مطابقة» (ADR-015) |
| 11 | رايتا `whatsapp.enabled` و`telephony.enabled` مزروعتان في `feature_flags` لكن **لا مسار يقرأهما**: إيقافهما لا يوقف الـwebhooks | إضافتهما في §8 تخصّ المزوّدات، وتطبيقهما على `POST /webhooks/*` يحتاج قرارًا: الرفض 503 أم الإهمال الصامت للقناة. مُدرج كفجوة لا كحاجة؛ لا قناة إنتاجية موصولة أصلاً (`INTEGRATIONS_DRIVER=sim`) |

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
| 010 التصدير: XLSX الآن وPDF مؤجَّل | [`decisions/010-exports.md`](decisions/010-exports.md) |
| 011 `/metrics` وmailpit والمحاكيات داخل العملية | [`decisions/011-monitoring-and-mailpit.md`](decisions/011-monitoring-and-mailpit.md) |
| 013 سطح الـAI: محاكاة حتمية ومراجعة قبل أي كتابة | [`decisions/013-ai-surface-sim-only-and-review-before-write.md`](decisions/013-ai-surface-sim-only-and-review-before-write.md) |
| 014 سلسلة الترقية على PostgreSQL: ما انكشف، استثناء تحرير 0001/0002، وتوصيل RLS | [`decisions/014-migration-chain-run-for-real-on-postgres.md`](decisions/014-migration-chain-run-for-real-on-postgres.md) |
| 015 تصحيح مقدّمات e2e، والهبوط بالصلاحية، والشارة بالعدد الحقيقي | [`decisions/015-e2e-premises-corrected-and-permission-landing.md`](decisions/015-e2e-premises-corrected-and-permission-landing.md) |

## قائمة ما قبل «جاهز للمراجعة»

- [x] parity للتوكنات مقصوصة من §4 ومحمية باختبار (`frontend/tests/tokens.test.ts`: 20 تأكيدًا على القيم نفسها)
- [x] عزل المندوب مُختبَر بالـ404 (backend matrix + `e2e/isolation.spec.ts`)
- [~] لم تُعدَّل migration مُدمجة **إلا باستثناء موسَّم ومُبرَّر** (0001/0002، ADR-014): كل منهما كان
  مستحيل التشغيل على PostgreSQL فلم تُطبَّق على أي قاعدة. أي تغيير آخر يُضاف كترقية جديدة (0003 فما فوق)
- [x] لا أسرار في المستودع: `.env` مُستثنى، والموجود أمثلة فقط (`backend/.env.example`, `frontend/.env.example`, `infra/.env.example`)
- [x] لا بيانات شخصية حقيقية في الـseed (أسماء/أرقام وهمية، نطاق `@brokerhub.test`، `+201…` غير مخصّصة)
- [~] لقطات الـ16 شاشة + contact sheet: مكتوبة وتُنتَج في CI؛ لم تُشغَّل محليًا — جُرِّب `@sparticuz/chromium`
  وتعذّر التشغيل لغياب `libnss3/libnspr4` بلا root (تفصيل «ما لم يُشغَّل» 1)
- [x] README فيه تشغيل بأوامر ثلاثة + تشغيل بلا Docker
- [x] runbook + STATUS + ui-parity (README + screens.md بكل فوارق §9) + سجل القرارات 001–015 بلا فجوة
- [x] CI: ruff+mypy+pytest (على PostgreSQL أيضًا)+بوابة تغطية النواة+تدقيق الاعتماديات+فحص staleness
  للـOpenAPI+**منع تحرير الترقيات**+**سلسلة الترقية على قاعدة PostgreSQL فارغة**؛ lint/typecheck/vitest/build
  للواجهة؛ e2e مع اللقطات؛ ووظيفة `docker` صارت **تُقلع الـstack بالكامل** (health + nginx + seed + login)
