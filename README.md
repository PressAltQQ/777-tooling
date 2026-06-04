# 777 KB Enforcement Tooling

Этот репозиторий содержит слой энфорса для базы знаний на Obsidian: хук-валидатор фронтматтера, схему зон и конфигурацию Claude Code. Репозиторий является единственным источником правды для этого тулинга — vault-копии являются установленными артефактами, а не оригиналами.

**Почему отдельный репо?** Obsidian Sync передаёт только контент (markdown-файлы). Папка `.claude/` не синкается никогда — Obsidian игнорирует все dot-папки. Файлы `.py` и `.json` синкаются только опционально, и включать эту опцию нежелательно: тогда один и тот же файл управляется и git-репо, и Sync, что создаёт два источника правды и потенциальные конфликты. Поэтому слой энфорса доставляется этим репо отдельно от контента и устанавливается один раз на каждую машину члена команды.

---

## Что входит в репо

| Файл | Назначение |
|------|-----------|
| `.claude/settings.json` | Конфигурация хука `PreToolUse` для Claude Code — запускает валидатор перед каждым Write/Edit |
| `_meta/validate.py` | Валидатор фронтматтера: hook-режим (stdin JSON) и CLI-режим (`python3 validate.py file.md`) |
| `_meta/schema.json` | Схема зон: какие поля обязательны, допустимые значения `status`, enforced-зоны |
| `install.sh` | Установщик — копирует три файла выше в нужные места vault |

Контент базы знаний (заметки) сюда НЕ входит — он живёт в Obsidian Sync.

---

## Установка

```bash
git clone <repo-url> ~/777-tooling
cd ~/777-tooling
./install.sh "/path/to/your/local/vault"
```

> Куратор репо добавит реальный URL вместо `<repo-url>` и настроит remote.

После установки скрипт выведет список установленных файлов и два напоминания (плагин Dataview + опция «Detect all file extensions»).

**Важно:** хард-гейт (блокировка записи при невалидном фронтматтере) становится активным **только после запуска `install.sh`** на конкретной машине. До установки никакой проверки нет.

---

## Обновление

При выходе новой версии тулинга (изменения в схеме, валидаторе или хуке):

```bash
cd ~/777-tooling
git pull
./install.sh "/path/to/your/local/vault"
```

---

## Codex

The validator also supports **Codex CLI** via a `PostToolUse` hook on `apply_patch`.

### Как это работает

| | Claude Code | Codex |
|---|---|---|
| Hook type | `PreToolUse` | `PostToolUse` |
| Tool watched | `Write` / `Edit` / `MultiEdit` | `apply_patch` |
| Validation timing | **Before** the write (blocks the write) | **After** the write (file on disk; blocks and model fixes) |
| Config file | `.claude/settings.json` | `.codex/config.toml` |

Codex выполняет файловые правки через `apply_patch`. После записи хук вызывает `validate.py`, который читает изменённые `.md`-файлы с диска, проверяет фронтматтер и при ошибке выходит с кодом 2 — Codex показывает причину модели, и та исправляет файл.

### Настройка Codex

1. **Включить хуки** в `~/.codex/config.toml`:
   ```toml
   [features]
   hooks = true
   ```

2. **Запускать Codex из корня vault**:
   ```bash
   cd /path/to/your/vault
   codex
   ```

3. **Доверить хук** при первом запуске — выполнить команду `/hooks` в Codex и подтвердить хук по SHA (SHA-pinned approval).

После `./install.sh` файл `.codex/config.toml` будет установлен в vault автоматически.

---

## Важно: настройка Obsidian Sync

Держать в Obsidian Sync настройку **«Sync all other file types» ВЫКЛ**. Если включить синк `.py`/`.json`, тулинг окажется под управлением двух источников (git и Sync одновременно), что приведёт к конфликтам и непредсказуемому состоянию. Git — единственный источник правды для тулинга; Obsidian Sync — единственный источник правды для контента.
