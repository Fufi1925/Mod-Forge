import re

with open("bot/bot.py", "r", encoding="utf-8") as f:
    text = f.read()

# Modify on_voice_state_update
if "tv_cfg = cfg.get" not in text:
    tv_logic = """
    # ── Temp Voice Logic ──
    try:
        cfg = await bot.db.aget_config(guild.id)
        tv_cfg = cfg.get("temp_voice", {})
        if tv_cfg.get("enabled"):
            hub_id = tv_cfg.get("hub_channel_id")
            
            # User joined Hub Channel
            if after.channel and after.channel.id == hub_id:
                category_id = tv_cfg.get("category_id")
                category = guild.get_channel(category_id) if category_id else after.channel.category
                name_tpl = tv_cfg.get("name_template", "🔊 {user}'s Kanal")
                cname = name_tpl.replace("{user}", member.display_name)
                try:
                    new_vc = await guild.create_voice_channel(name=cname, category=category)
                    await member.move_to(new_vc)
                    await bot.db.aadd_temp_voice(guild.id, new_vc.id, member.id)
                    # Give owner permissions
                    await new_vc.set_permissions(member, connect=True, manage_channels=True)
                except discord.Forbidden:
                    pass
                except Exception as e:
                    pass

            # User left a Temp Channel
            if before.channel and before.channel.id != hub_id:
                if len(before.channel.members) == 0:
                    data = await bot.db.aget_temp_voice(before.channel.id)
                    if data:
                        try:
                            await before.channel.delete()
                        except discord.Forbidden:
                            pass
                        finally:
                            await bot.db.aremove_temp_voice(before.channel.id)
    except Exception as e:
        pass
"""
    parts = text.split("guild = member.guild\n")
    # Es gibt zwei occurrences von guild = member.guild, in on_member_update und on_voice_state_update
    # Wir machen es per regex replace
    text = re.sub(
        r'(guild = member\.guild\n)(\s*if member\.bot:)',
        r'\1' + tv_logic.replace('\n', '\n    ') + r'\n\2',
        text
    )
    with open("bot/bot.py", "w", encoding="utf-8") as f:
        f.write(text)

print("on_voice_state_update patched correctly.")
