.PHONY: setup dev test eval lint build down
setup:
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -r services/api/requirements.txt
	cd services/web && npm install
dev:
	docker compose up --build
test:
	PYTHONPATH=services/api .venv/bin/pytest services/api/tests -q
	cd services/web && npm test
eval:
	PYTHONPATH=services/api .venv/bin/python services/api/evals/run.py
lint:
	.venv/bin/ruff check services/api/app services/api/tests services/api/evals
	cd services/web && npm run lint && npm run typecheck
build:
	cd services/web && npm run build
	docker compose build
down:
	docker compose down
