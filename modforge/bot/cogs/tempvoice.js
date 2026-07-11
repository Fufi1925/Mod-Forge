const { SlashCommandBuilder, PermissionFlagsBits, ActionRowBuilder, ButtonBuilder, ButtonStyle, ChannelType } = require('discord.js');
const { createEmbed, reply } = require('../utils');
const { COLOR_SUCCESS, COLOR_PRIMARY } = require('../config');

const commands = [{
  data: new SlashCommandBuilder().setName('tempvoice_panel').setDescription('Sendet das TempVoice-Panel').setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild).addChannelOption(option => option.setName('channel').setDescription('Kanal').setRequired(false)),
  async execute(bot, interaction) {
    const channel = interaction.options.getChannel('channel') || interaction.channel;
    const row = new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('modforge:tempvoice_info').setLabel('TempVoice Info').setEmoji('🎤').setStyle(ButtonStyle.Secondary));
    await channel.send({ embeds: [createEmbed('🎤 TempVoice', 'Betritt den konfigurierten Hub-Kanal, um deinen temporären Voice-Kanal zu erstellen.', COLOR_PRIMARY)], components: [row] });
    return reply(interaction, { embeds: [createEmbed('✅ TempVoice-Panel', 'TempVoice-Panel wurde gesendet.', COLOR_SUCCESS)] }, true);
  },
}];

async function deleteEmptyTempChannel(bot, channel) {
  if (!channel || channel.type !== ChannelType.GuildVoice || channel.members.size > 0) return;
  const record = await bot.db.tempvoice_channels.findOne({ channel_id: String(channel.id) }).catch(() => null);
  if (!record) return;
  await bot.db.tempvoice_channels.deleteOne({ channel_id: String(channel.id) }).catch(() => null);
  await channel.delete('Leerer temporärer Voice-Kanal').catch(() => null);
}

const events = [
  {
    name: 'voiceStateUpdate',
    async execute(bot, oldState, newState) {
      const guild = newState.guild || oldState.guild;
      const fullConfig = await bot.db.fetchConfig(guild.id);
      const config = fullConfig.tempvoice || fullConfig.temp_voice || {};
      const hubId = String(config.join_channel_id || config.hub_channel_id || config.create_channel_id || config.join_channel || '');

      if (config.enabled && hubId && String(newState.channelId || '') === hubId && newState.member) {
        const existing = await bot.db.tempvoice_channels.findOne({ guild_id_str: String(guild.id), owner_id: String(newState.member.id) }).catch(() => null);
        let channel = existing ? guild.channels.cache.get(String(existing.channel_id)) : null;
        if (!channel) {
          const name = String(config.name_template || "🔊 {user}'s Kanal").replaceAll('{user}', newState.member.user.username).slice(0, 100);
          channel = await guild.channels.create({
            name,
            type: ChannelType.GuildVoice,
            parent: config.category_id ? String(config.category_id) : newState.channel?.parentId,
            reason: `TempVoice für ${newState.member.user.tag}`,
            permissionOverwrites: [{ id: newState.member.id, allow: [PermissionFlagsBits.ManageChannels, PermissionFlagsBits.MoveMembers, PermissionFlagsBits.Connect, PermissionFlagsBits.Speak] }],
          });
          await bot.db.tempvoice_channels.insertOne({ guild_id: Number(guild.id), guild_id_str: String(guild.id), channel_id: String(channel.id), owner_id: String(newState.member.id), created_at: new Date() });
        }
        await newState.member.voice.setChannel(channel, 'TempVoice erstellt').catch(() => null);
      }

      if (oldState.channelId && oldState.channelId !== newState.channelId) {
        setTimeout(() => void deleteEmptyTempChannel(bot, oldState.channel), 1000);
      }
    },
  },
  {
    name: 'interactionCreate',
    async execute(bot, interaction) {
      if (!interaction.isButton() || interaction.customId !== 'modforge:tempvoice_info') return;
      const config = await bot.db.fetchConfig(interaction.guild.id);
      const tv = config.tempvoice || config.temp_voice || {};
      const hubId = tv.join_channel_id || tv.hub_channel_id || tv.create_channel_id;
      await interaction.reply({ content: hubId ? `🎤 Betritt <#${hubId}>, um deinen eigenen Voice-Kanal zu erstellen.` : '❌ Es wurde noch kein TempVoice-Hub konfiguriert.', ephemeral: true });
    },
  },
];

module.exports = { commands, events, deleteEmptyTempChannel };
