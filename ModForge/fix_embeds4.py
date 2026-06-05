
with open('bot/bot.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)', 'await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Keine Berechtigung.", color=COLOR_DANGER), ephemeral=True)')
text = text.replace('await interaction.response.send_message("Das Ticket wird in 5 Sekunden geschlossen...")', 'await interaction.response.send_message(embed=discord.Embed(title="🔒 Ticket", description="Das Ticket wird in 5 Sekunden geschlossen...", color=COLOR_WARNING))')
text = text.replace('await interaction.response.send_message("Kein Report-Kanal.",ephemeral=True)', 'await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Kein Report-Kanal eingerichtet.", color=COLOR_DANGER), ephemeral=True)')
text = text.replace('await interaction.response.send_message("Nichts zu snipen.",ephemeral=True)', 'await interaction.response.send_message(embed=discord.Embed(title="ℹ️ Info", description="Nichts zu snipen (keine kürzlich gelöschte Nachricht).", color=COLOR_INFO), ephemeral=True)')

with open('bot/bot.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
