PY ?= python3
IN ?= data/tickets_valid.jsonl
OUT ?= pred.jsonl
PORT ?= 8000

.PHONY: install train predict serve eval test gold check-data suggest-templates eval-drafts eval-drafts-real

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

# dev-разметка valid (нужна только для метрик категории и приоритета)
gold:
	$(PY) scripts/make_gold.py

eval:
	$(PY) scripts/evaluate.py

test:
	$(PY) -m pytest -q tests

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
