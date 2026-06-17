# ModForge Bug Fix Report

Datum: 2026-06-17  
Branch: ModForge

## Gefundene und gefixte Bugs

### Bug 1: Falscher Import in Cogs (CRITICAL)
**Datei:** `bot/cogs/events.py` + `bot/cogs/verification.py`

**Problem:** Die beiden Cogs importierten Funktionen vom falschen Modul:
- `events.py` importierte `check_phishing_url` aus `bot.embed_config`, aber diese Funktion liegt in `bot.utils`
- `verification.py` importierte `generate_captcha` aus `bot.embed_config`, aber diese Funktion liegt in `bot.utils`

**Effekt:** Beim Start crashte der Bot mit `ImportError: cannot import name 'check_phishing_url' from 'bot.embed_config'`

**Fix:**
```python
# bot/cogs/events.py
from bot.utils import create_embed, check_phishing_url
from bot.embed_config import get_embed

# bot/cogs/verification.py
from bot.utils import create_embed, generate_captcha
from bot.embed_config import get_embed
```

### Bug 2: RuntimeWarning "coroutine was never awaited" (HIGH)
**Datei:** `bot/utils.py` + `web/routes.py`

**Problem:** `_run_async` und `safe_async` gaben `None` zurück, wenn der Bot offline war, ohne die übergebene Coroutine zu schließen. Python warnte dann: `RuntimeWarning: coroutine 'Database.aset_config' was never awaited`.

**Effekt:** Spam im Log, unsauberer Code, mögliche Memory-Leaks.

**Fix in `bot/utils.py`:** Coroutine explizit mit `.close()` schließen wenn Bot offline ist.
**Fix in `web/routes.py`:** `safe_async` schließt die Coroutine im Except-Pfad.

### Bug 3: RecursionError bei Config-Save (HIGH)
**Datei:** `web/routes.py`

**Problem:** Wenn eine Config stark verschachtelt war oder Zyklen enthielt, schlugen `_copy.deepcopy` und `json.dumps` mit `RecursionError: maximum recursion depth exceeded` fehl. Der Fehler wiederholte sich alle 3 Sekunden über den SocketIO-Emitter.

**Fix in `_sanitize_cfg_for_mongo`:** Verwendet einen memo-basierten `_safe_json_default` der Zyklen erkennt und zu tiefe Strukturen abfängt.

**Fix in `_deep_merge`:** Neue MAX_DEPTH=50 Schutz gegen tiefe Verschachtelung; fängt RecursionError ab.

**Fix in `_direct_save_config`:** Fängt jetzt `RecursionError` explizit ab und gibt sauber `False` zurück.

**Fix in `_save_config_version`:** Fängt `RecursionError` bei `_copy.deepcopy` ab.

## Verifizierte Tests

- ✅ Alle 13 Cogs laden fehlerfrei
- ✅ Bot-Modul lädt sauber, `BOT_REF` ist definiert
- ✅ `_run_async` schließt Coroutinen (kein RuntimeWarning)
- ✅ `_sanitize_cfg_for_mongo` handhabt zirkuläre Referenzen + tiefe Strukturen (3000+ Ebenen)
- ✅ `_deep_merge` handhabt Edge-Cases ohne Recursion
- ✅ `_direct_save_config` funktioniert mit allen Edge-Cases
- ✅ `safe_async` handhabt Coroutinen korrekt

## Status

✅ Alle bekannten Bugs aus dem Log und der Code-Analyse sind gefixt.
✅ Keine Syntax-Fehler in allen Python-Dateien.
✅ Keine HTML-Fehler in allen Templates.
