@echo off
cd /d "%~dp0"
echo Запуск бота...
venv\Scripts\python.exe main.py
if errorlevel 1 (
    echo.
    echo Если видишь «Бот уже запущен» — закрой другое окно с ботом или нажми Ctrl+C там.
    pause
)
Start polling