.PHONY: run cli test docker

run:
	python app.py

cli:
	python process.py --help

test:
	python -m pytest -q

docker:
	docker compose up --build
