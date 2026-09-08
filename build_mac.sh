#!/bin/bash
# Локальная сборка .app на настоящем Mac (альтернатива GitHub Actions).
# Запускать из корня проекта: bash build_mac.sh
set -e

echo "[1/4] Зависимости..."
python3 -m pip install --upgrade pyinstaller
python3 -m pip install -r requirements.txt

echo "[2/4] Chromium для Playwright..."
python3 -m playwright install chromium

BROWSERS_DIR="$HOME/Library/Caches/ms-playwright"
rm -rf pw-browsers
mkdir -p pw-browsers
cp -R "$BROWSERS_DIR"/chromium-* pw-browsers/ 2>/dev/null || true
cp -R "$BROWSERS_DIR"/ffmpeg-* pw-browsers/ 2>/dev/null || true

ICON_ARG=""
if [ -f "assets/acrelis_icon.icns" ]; then
  ICON_ARG="--icon assets/acrelis_icon.icns"
fi

echo "[3/4] Сборка .app (несколько минут)..."
# --onedir, а не --onefile: на macOS для --windowed это официально рекомендованный режим
# (onefile+windowed — deprecated). ms-playwright НЕ передаём через --add-data — PyInstaller
# пытается ad-hoc codesign'ить каждый найденный внутри Mach-O бинарник, а вложенный .app
# самого Chromium (со своими Frameworks) от переподписания ломается. Кладём браузер рядом
# с готовым .app ниже — main.py ищет его там на macOS.
python3 -m PyInstaller --noconfirm --clean \
    --onedir \
    --windowed \
    --name "ParserYandex" \
    $ICON_ARG \
    --collect-all customtkinter \
    --collect-all playwright \
    --collect-all docx \
    --collect-all openpyxl \
    --add-data "assets:assets" \
    main.py

echo "[4/4] Размещаю браузер рядом с .app..."
cp -R pw-browsers dist/ms-playwright

echo "Готово: dist/ParserYandex.app (запускать вместе с папкой dist/ms-playwright рядом)"
echo "Временное можно удалить: rm -rf pw-browsers build ParserYandex.spec"
