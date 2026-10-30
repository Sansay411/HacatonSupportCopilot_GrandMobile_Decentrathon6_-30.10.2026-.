PY ?= python3
IN ?= data/tickets_valid.jsonl
OUT ?= pred.jsonl
PORT ?= 8000

.PHONY: install train predict serve eval test gold check-data

install:
	$(PY) -m pip install -r requirements.txt

# обучение двух моделей на data/tickets_train.jsonl.gz (~3 минуты на 2 CPU)
train:
	$(PY) scripts/train.py
	$(PY) scripts/train_verdict.py

predict:
	$(PY) scripts/predict.py --in $(IN) --out $(OUT)

serve:
	$(PY) -m uvicorn copilot.api:app --host 0.0.0.0 --port $(PORT)

# dev-разметка valid (нужна только для метрик категории и приоритета)
gold:
	$(PY) scripts/make_gold.py

eval:
	$(PY) scripts/evaluate.py

test:
	$(PY) -m pytest -q tests

# проверка, что данные кейса не попали в git
check-data:
	@! git ls-files | grep -E '\.(jsonl|jsonl\.gz|pkl)$$|^data/' && echo "ok: данных в репозитории нет"
