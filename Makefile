PY ?= python3
IN ?= data/tickets_valid.jsonl
OUT ?= pred.jsonl
PORT ?= 8000

.PHONY: install train predict serve serve-fixture eval test e2e bench data-status gold check-data suggest-templates eval-drafts eval-drafts-real

install:
	$(PY) -m pip install -r requirements.txt

# обучение двух моделей на data/tickets_train.jsonl.gz (~3 минуты на 2 CPU)
train:
	$(PY) scripts/train.py
	$(PY) scripts/train_verdict.py

predict:
	$(PY) scripts/predict.py --in "$(IN)" --out "$(OUT)"

serve:
	$(PY) -m uvicorn copilot.api:app --host 0.0.0.0 --port $(PORT)

# явный режим на ТЕСТОВЫХ правилах (tests/fixtures), когда данных кейса нет; интерфейс постоянно об этом предупреждает
serve-fixture:
	$(PY) scripts/serve.py --fixture --port $(PORT)

# какие файлы кейса и модели на месте, пригоден ли rules.json (ничего не создаёт и не подменяет)
data-status:
	$(PY) scripts/check_data.py

# замер p50/p95 и стоимости на настоящих вызовах POST /triage (reports/bench_local.json)
bench:
	$(PY) scripts/bench.py --http --n 1000

# dev-разметка valid (нужна только для метрик категории и приоритета)
gold:
	$(PY) scripts/make_gold.py

eval:
	$(PY) scripts/evaluate.py

test:
	$(PY) -m pytest -q tests

# сквозные тесты в настоящем браузере (нужны playwright и Edge, Chrome или Chromium; без них пропускаются)
e2e:
	$(PY) -m pytest -q tests/e2e

# качество черновиков: инварианты (язык, пункты в тексте, обещания, эскалации) на синтетике, без data/ и models/
eval-drafts:
	$(PY) scripts/eval_drafts.py

# то же на реальных тикетах + выборка для ручной проверки в reports/private/ (нужны data/ и models/)
eval-drafts-real:
	$(PY) scripts/eval_drafts.py --in data/tickets_valid.jsonl

# бонус: кандидаты в шаблоны по кластерам обращений (reports/template_suggestions_summary.md)
suggest-templates:
	$(PY) scripts/suggest_templates.py

# проверка, что данные кейса не попали в git
check-data:
	@! git ls-files | grep -E '\.(jsonl|jsonl\.gz|pkl)$$|^data/' && echo "ok: данных в репозитории нет"
