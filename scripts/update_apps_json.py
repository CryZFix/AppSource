#!/usr/bin/env python3
"""
Сканирует папку с .ipa файлами, извлекает метаданные (bundleIdentifier,
версия, имя) из Info.plist внутри каждого .ipa и добавляет/обновляет
соответствующую запись в apps.json (формат источника LiveContainer/AltStore).

Уже существующие записи с тем же bundleIdentifier + version не трогаются.
Если для bundleIdentifier найдена НОВАЯ версия — старая запись заменяется.
"""
import datetime
import json
import os
import plistlib
import sys
import zipfile
from pathlib import Path

IPA_DIR = Path("ipas")
APPS_JSON = Path("apps.json")

# Заполняются автоматически GitHub Actions (можно переопределить локально)
REPO = os.environ.get("GITHUB_REPOSITORY", "CryZFix/AppSource")
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")


def raw_url(path: Path) -> str:
    """Прямая ссылка на файл в репозитории через raw.githubusercontent.com"""
    rel = path.as_posix()
    return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{rel}"


def read_info_plist(ipa_path: Path) -> dict:
    """Достаёт и парсит Info.plist из корня .app внутри .ipa"""
    with zipfile.ZipFile(ipa_path) as zf:
        info_plist_name = None
        for name in zf.namelist():
            parts = name.split("/")
            # Ищем именно Payload/<Имя>.app/Info.plist (верхний уровень .app)
            if len(parts) == 3 and parts[0] == "Payload" and parts[1].endswith(".app") and parts[2] == "Info.plist":
                info_plist_name = name
                break
        if info_plist_name is None:
            raise ValueError("Info.plist не найден внутри Payload/*.app/")
        with zf.open(info_plist_name) as f:
            return plistlib.loads(f.read())


def load_apps_json() -> dict:
    if APPS_JSON.exists():
        with open(APPS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    # Заготовка, если apps.json ещё не создан
    return {
        "name": "LiveContainer Store",
        "identifier": "com.github.cryzfix",
        "subtitle": "List of applications for personal use",
        "description": "Collection of applications for LiveContainer",
        "apps": [],
        "news": [],
    }


def save_apps_json(data: dict) -> None:
    with open(APPS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main() -> int:
    data = load_apps_json()
    apps = data.setdefault("apps", [])

    existing_keys = {(a.get("bundleIdentifier"), a.get("version")) for a in apps}

    if not IPA_DIR.exists():
        print(f"Папка {IPA_DIR} не найдена — нечего обрабатывать.")
        return 0

    changed = False
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    for ipa_path in sorted(IPA_DIR.rglob("*.ipa")):
        try:
            plist = read_info_plist(ipa_path)
        except Exception as e:
            print(f"⚠️  Пропуск {ipa_path}: {e}")
            continue

        bundle_id = plist.get("CFBundleIdentifier")
        version = plist.get("CFBundleShortVersionString") or plist.get("CFBundleVersion")
        name = plist.get("CFBundleDisplayName") or plist.get("CFBundleName") or ipa_path.stem

        if not bundle_id or not version:
            print(f"⚠️  Пропуск {ipa_path}: не удалось прочитать bundleIdentifier/версию")
            continue

        key = (bundle_id, version)
        if key in existing_keys:
            print(f"— {name} {version} ({bundle_id}) уже в apps.json, пропуск")
            continue

        entry = {
            "name": name,
            "bundleIdentifier": bundle_id,
            "version": version,
            "versionDate": today,
            "downloadURL": raw_url(ipa_path),
            "size": ipa_path.stat().st_size,
        }

        # Если для этого bundleIdentifier уже была запись — заменяем её
        # (это будет обновление версии), иначе добавляем новую
        replaced = False
        for i, a in enumerate(apps):
            if a.get("bundleIdentifier") == bundle_id:
                apps[i] = {**a, **entry}
                replaced = True
                break
        if not replaced:
            apps.append(entry)

        existing_keys.add(key)
        changed = True
        action = "Обновлено" if replaced else "Добавлено"
        print(f"✅ {action}: {name} {version} ({bundle_id})")

    if changed:
        save_apps_json(data)
        print("apps.json обновлён.")
    else:
        print("Новых .ipa не найдено, изменений нет.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
