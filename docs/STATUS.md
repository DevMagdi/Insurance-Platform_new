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
| M10 الاختبارات النهائية + parity + تجهيز الدمج | 🟡 جارية | backend أخضر على **PostgreSQL 16** (154) وعلى SQLite (145 + 9 مُتخطَّاة بعلامة `postgres_only`) · frontend أخضر (68 اختبار وحدة + build) · e2e: typecheck ✓ و8 ملفات ✓ لكنها **لم تُشغَّل** محلياً (لا متصفح — «ما لم يُشغَّل» 1) · ruff/mypy/تغطية النواة/استقرار الـOpenAPI/**تمرير كل النقاط** نظيفة |
| R1 مركز الإعدادات: تكاملات حقيقية + إنشاء وثيقة | ✅ منتهية (محلياً) | `/settings` بثلاث بطاقات + حيّ/محاكاة بتأكيد + سجلّ `webhook_events` + `POST /policies` بجدول أقساط وعمولة · `tests/test_integrations_settings.py` (16) · `frontend/tests/settingsView.test.tsx` (14) · ADR-016 |
| مزوّد AI (§11 M10): واجهة واحدة خلف `ai.enabled` + مراجعة بشرية | ✅ السطح كامل بسائق محاكاة · ⬜ بلا مزوّد حقيقي | `integrations/ai_sim.py` (حتمي، استخلاصي) · `endpoints/ai.py`: `GET /ai/status` · `POST /ai/calls/{id}/transcribe` · `POST /ai/requests/{id}/summarize` · `POST /ai/classify` · `tests/test_ai.py` (7) · زر «تلخيص آلي» في `InboxPage` يظهر فقط عند تشغيل الراية · ADR-013 |

## ما شُغِّل فعليًا (جولة R1 — مركز الإعدادات؛ الأرقام من نفس الجلسة)

backend — **على محرّكَي القاعدة**، لأن `DATABASE_URL_TEST` صار يحدّد المحرّك (ADR-014):

```
ruff check .            → All checks passed!           (139 ملفاً)
ruff format --check .   → 139 files already formatted
mypy app                → Success: no issues found in 104 source files
python -m pytest        → rc 0 · 154 مُجمَّعة، منها 9 بعلامة `postgres_only` ⇒ 145 ناجحاً + 9 مُتخطَّاة (~228s SQLite)
DATABASE_URL_TEST=postgresql+asyncpg://… python -m pytest
                        → rc 0 · 154 ناجحاً بلا تخطٍّ (PostgreSQL 16.2 حقيقي، ~4 دقائق)
coverage run -m pytest  → rc 0 · بوابة النواة `scripts/check_core_coverage.py` → 12/12 فوق 80% (أدنى 80.4%)
scripts/check_openapi_fresh.py → openapi.json is fresh (92 paths)
scripts/check_migrations.py    → migration immutability ok (3 merged, 0 new)
scripts/smoke_api.py           → SMOKE OK — 107 نداءً من 109 في الوثيقة، واثنان مستثنيان بسببهما مكتوب
```

ملخّص `pytest -q` لا يُطبع هنا لأن `addopts` يضيف `-q` ثانية؛ الأرقام مأخوذة من `--collect-only -q` (154) ومن
حروف التقدّم (`9×s` على SQLite، وصفر `s` وصفر `F` على PostgreSQL) مع `rc=0` — لا «تمّ» بلا مخرجات.
سلسلة الترقية 0001→0004 على قاعدة PostgreSQL فارغة يثبتها `tests/test_migrations.py` (جزء من الـ154، يعمل
هناك وحده)، و`tests/test_rls_postgres.py` (8) يثبّت أن الجدول الجديد لم يفتح ثغرة عزل.

أسطر جديدة قِيست بالتغطية ولا تدخل بوابة النواة (لا إخفاء لرقم منخفض):
`endpoints/settings.py` 98.2% · `core/secrets.py` 90.6% · `integrations/registry.py` 87.3% ·
`services/policies.py` 85.7% · `services/policy_settings.py` 83.9% · `core/rate_limit.py` 80.0% ·
`services/integrations_settings.py` **71.2%** · `workers/tasks/media.py` **62.8%** — السبب والقرار مسجَّلان
في «اختصارات» سطر 17.

frontend (Node 22):

```
eslint . --max-warnings 0 → 0 مشكلة
tsc -p tsconfig.json --noEmit && tsc -p tsconfig.e2e.json --noEmit → نظيف
npx vitest run            → 68 passed / 8 files (منها 14 في `settingsView.test.tsx` و5 في `i18n-parity.test.ts`)
npm run build             → ✓ في 7.3s (chunk لكل شاشة)
e2e (Playwright)          → typecheck ✓ · **لم تُشغَّل محلياً**: لا متصفح بلا root (`libnss3` غائب) ⇒ الدليل من CI
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
| 12 | كاش السائق لكل عملية: الحفظ يسري في العملية التي خدمت الطلب، وبقية العمال تحتاج إعادة تشغيل | `registry.prime()` بعد كل حفظ؛ لا invalidation بين العمليات (قاع القاعدة في كل نداء صادر أثقل). الأمر في `docs/runbook.md` §5 «إعدادات التكاملات». لا يُدّعى أن الحفظ فوري في كل عملية |
| 13 | `frontend/e2e/settings.spec.ts` **لم يُشغَّل محلياً** (لا متصفح: `libnss3/libnspr4` غائبان بلا root) | ما مُتحَّق منه محلياً: `tsc -p tsconfig.e2e.json` ✓ ونجاح اكتشاف الاختبارات. الدليل على المرور من CI وحده — لا «تم» قبله |
| 14 | الـe2e لا يضغط «اختبار الاتصال» بعد التحوّل إلى الحيّ | CI لا يصرف حِصّة Meta الحقيقية ولا يتعلّق بشبكة الخارج؛ المسار الحيّ مُغطّى بوهميّة نقل في `backend/tests/test_integrations_settings.py` |
| 15 | لقطة باسم `15b-settings-hub.png` خارج تسلسل `01…16` | شاشة 15 صارت تبويباً داخل الـhub (`/settings?tab=users`)؛ اسم الملف يبقى حتى لا تنكسر مراجع `ui-parity/screens.md`، و`Shot.who` وسّع `admin` لأن `users.manage` ليست في دور المدير |
| 16 | تمرير `scripts/smoke_api.py` يستثني نقطتين (بسبب مكتوب أمام كل واحدة) | `/media/{key}` رابط موقّع لمرّة واحدة ويُستهلك في نفس السكربت؛ ومرفق البوابة برقمه من قائمة البوابة (`tests/test_portal.py`). الباقي: 107 نداءً من 109 مُجاب عليه، والتمرير صار خطوة CI |
| 17 | بوابة تغطية النواة بقيت على قائمتها (12 ملفاً)؛ ملفات الجولة الجديدة خارجها | الرقم **مقيس لا مدّعى**: `services/integrations_settings.py` 71.2% و`workers/tasks/media.py` 62.8%. السبب: فحوص الوضع الحيّ (debug_token، `EHLO`+`AUTH`) تحتاج وهايماً للمزوّد، وغلاف Celery لا يُستدعى داخل حلقة اختبار (`run_async` يحلّق على حلقة pytest) — ولا اختبار مهمة عامل في المستودع أصلاً. القرار: لا تُخفض البوابة ولا تُزيَّن؛ تُضاف عند كتابة الـstubs |

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
| 016 إعدادات التكاملات في القاعدة: تخزين، أسرار مشفّرة، شارة حيّ/محاكاة، وسجلّ webhook | [`decisions/016-integrations-settings.md`](decisions/016-integrations-settings.md) |

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
- [x] runbook + STATUS + ui-parity (README + screens.md بكل فوارق §9) + سجل القرارات 001–016 بلا فجوة
- [x] **كل نقطة موثّقة تجيب**: `python scripts/smoke_api.py` يعبر على كل `(path, method)` في الوثيقة
  (107/109، واستثناءَان بسببهما مكتوب) — خطوة CI قائمة بذاتها بعد بوابات التغطية
- [x] CI: ruff+mypy+pytest (على PostgreSQL أيضًا)+بوابة تغطية النواة+تدقيق الاعتماديات+فحص staleness
  للـOpenAPI+**منع تحرير الترقيات**+**سلسلة الترقية على قاعدة PostgreSQL فارغة**؛ lint/typecheck/vitest/build
  للواجهة؛ e2e مع اللقطات؛ ووظيفة `docker` صارت **تُقلع الـstack بالكامل** (health + nginx + seed + login)
