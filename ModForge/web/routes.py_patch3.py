import re

with open('web/routes.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Route für tempvoice hinzufügen
tv_route = """@flask_app.route("/dashboard/<guild_id>/tempvoice")
@require_auth
def guild_tempvoice(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    categories = [{"id": str(c.id), "name": c.name} for c in g.categories] if g else []
    voice_channels = [{"id": str(c.id), "name": c.name} for c in g.voice_channels] if g else []

    return render_template(
        "dashboard/tempvoice.html",
        guild=g,
        cfg=cfg,
        user=us["user"],
        categories=categories,
        voice_channels=voice_channels,
        active="tempvoice"
    )
"""

if "def guild_tempvoice" not in text:
    text = text.replace("# =========================================================", tv_route + "\n# =========================================================", 1)

# API config save
if "_temp_voice" not in text:
    tv_api = """    if "_temp_voice" in data:
        tv = cfg.get("temp_voice", {})
        for k, v in data["_temp_voice"].items():
            tv[k] = v
        cfg["temp_voice"] = tv"""
    text = text.replace('    if "_webhook_logging" in data:', tv_api + '\n    if "_webhook_logging" in data:')

with open('web/routes.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Tempvoice route and API patched.")
