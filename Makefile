.PHONY: install test build serve dev-ui smoke smoke-m2

install:
	uv sync --locked
	npm --prefix frontend ci

test:
	.venv/bin/python -m pytest -q
	npm --prefix frontend test

build:
	npm --prefix frontend run build
ifeq ($(shell uname -s),Darwin)
	$(MAKE) build/kakaoreply-scoped-send
endif

build/kakaoreply-scoped-send: backend/kakaoreply/kakao/scoped_send.swift
	mkdir -p build
	/usr/bin/swiftc -module-cache-path build/swift-cache $< -o $@

serve:
	.venv/bin/python -m uvicorn kakaoreply.api:app --app-dir backend --host 127.0.0.1 --port 8765 --no-access-log

dev-ui:
	npm --prefix frontend run dev

smoke:
	.venv/bin/python scripts/smoke.py

smoke-m2:
	.venv/bin/python scripts/m2_smoke.py
