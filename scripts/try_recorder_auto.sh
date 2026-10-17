#!/bin/zsh
# Автопроверка рекордера без участия человека: системный звук создаётся командой say.
cd "$(dirname "$0")/../recorder/macos" || exit 1
./ltrecord /tmp/lt-auto-mic.wav /tmp/lt-auto-system.wav &
pid=$!
sleep 3
say -v Samantha "Hello, this is a system audio test. I went to the mountains last weekend."
sleep 2
kill -INT $pid
wait $pid
ls -la /tmp/lt-auto-*.wav
