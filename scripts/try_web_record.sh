#!/bin/zsh
# Автопроверка записи через веб-API (сервер должен работать на :8000). Создаёт тестовый разговор.
curl -s -o /dev/null -w "start: %{http_code} -> %{redirect_url}\n" -X POST http://127.0.0.1:8000/record/start
sleep 2
say -v Samantha "Yesterday I go to the store and I buy two apple."
sleep 1
curl -s -o /dev/null -w "stop: %{http_code} -> %{redirect_url}\n" -X POST http://127.0.0.1:8000/record/stop
