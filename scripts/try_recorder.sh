#!/bin/zsh
# Проверка рекордера: 10 секунд записи микрофона и системного звука в /tmp/lt-rec-*.wav
cd "$(dirname "$0")/../recorder/macos" || exit 1
echo "Запись через 3 секунды: говорите в микрофон и включите английское видео"
sleep 3
./ltrecord /tmp/lt-rec-mic.wav /tmp/lt-rec-system.wav &
pid=$!
afplay /System/Library/Sounds/Ping.aiff
echo "ЗАПИСЬ ИДЁТ, говорите"
sleep 10
kill -INT $pid
wait $pid
ls -la /tmp/lt-rec-*.wav
