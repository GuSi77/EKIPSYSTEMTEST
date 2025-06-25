import discord
from discord.ext import commands
import os
from datetime import datetime

# Lade das Bot-Token aus der Umgebungsvariable namens 'DISCORD_BOT_TOKEN'
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

# Korrekte Intent-Konfiguration mit allen notwendigen Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # KRITISCH für on_member_join
intents.presences = True  # Für Präsenz-Updates

bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    print(f'{bot.user} hat sich erfolgreich angemeldet!')
    print(f'Bot ist auf {len(bot.guilds)} Servern aktiv')

    # Debug: Zeige alle verfügbaren Intents an
    print(f'Aktive Intents: {bot.intents}')
    print(f'Members Intent aktiv: {bot.intents.members}')
    print(f'Message Content Intent aktiv: {bot.intents.message_content}')

    # Setze Bot-Status auf "Bitte nicht stören"
    await bot.change_presence(status=discord.Status.dnd)
    print('Bot-Status auf "Bitte nicht stören" gesetzt')


@bot.event
async def on_member_join(member):
    print(f"🎉 DEBUG: {member.name} ({member.id}) ist dem Server {member.guild.name} beigetreten!")

    # Konfiguration
    welcome_channel_id = 1250809478232932402  # Willkommenskanal
    join_log_channel_id = 1387484930438598859  # Join-Log-Kanal
    role_name = "Mitglied"  # Rolle für neue Mitglieder

    # === WILLKOMMENSNACHRICHT (wie bisher) ===
    welcome_channel = bot.get_channel(welcome_channel_id)
    if welcome_channel:
        try:
            embed = discord.Embed(
                title=f"Willkommen auf dem Server, {member.name}!",
                description=f"Schön, dass du da bist, {member.mention}!\n\nWir hoffen, du hast eine tolle Zeit hier.",
                color=discord.Color.red()
            )

            if member.avatar:
                embed.set_thumbnail(url=member.avatar.url)
            else:
                embed.set_thumbnail(url=member.default_avatar.url)

            embed.add_field(
                name="Server-Info",
                value=f"Du bist das {len(member.guild.members)}. Mitglied!",
                inline=False
            )

            await welcome_channel.send(embed=embed)
            print(f"✅ Willkommensnachricht für {member.name} gesendet!")

        except Exception as e:
            print(f"❌ Fehler bei Willkommensnachricht: {e}")

    # === JOIN-LOG (mit Benutzer-Profilbild und dunkelroter Farbe) ===
    log_channel = bot.get_channel(join_log_channel_id)
    if log_channel:
        try:
            # Berechne Kontoalter
            account_created = member.created_at
            now = datetime.now(account_created.tzinfo)
            account_age = now - account_created

            # Formatiere das Kontoalter
            if account_age.days >= 365:
                years = account_age.days // 365
                months = (account_age.days % 365) // 30
                if years == 1:
                    age_text = f"{years} year"
                else:
                    age_text = f"{years} years"
                if months > 0:
                    age_text += f", {months} months"
            elif account_age.days >= 30:
                months = account_age.days // 30
                if months == 1:
                    age_text = f"{months} month"
                else:
                    age_text = f"{months} months"
            elif account_age.days > 0:
                if account_age.days == 1:
                    age_text = f"{account_age.days} day"
                else:
                    age_text = f"{account_age.days} days"
            else:
                hours = account_age.seconds // 3600
                if hours == 1:
                    age_text = f"{hours} hour"
                else:
                    age_text = f"{hours} hours"

            # Erstelle Join-Log Embed mit dunkelroter Farbe
            log_embed = discord.Embed(
                color=discord.Color.dark_red()  # Dunkelrote Farbe statt Discord-Blau
            )

            # Setze das Profilbild des Benutzers als Author-Bild
            if member.avatar:
                log_embed.set_author(name=member.name, icon_url=member.avatar.url)
                log_embed.set_thumbnail(url=member.avatar.url)
            else:
                log_embed.set_author(name=member.name, icon_url=member.default_avatar.url)
                log_embed.set_thumbnail(url=member.default_avatar.url)

            # Haupttext mit Benutzername und ID
            log_embed.add_field(
                name="",
                value=f"**{member.name}** `{member.id}`\n@{member.mention} trat dem Server bei.",
                inline=False
            )

            # Kontoalter
            log_embed.add_field(
                name="⏰ Alter des Kontos:",
                value=f"{account_created.strftime('%d/%m/%Y %H:%M')}\n**{age_text} ago**",
                inline=False
            )

            # Server-Name und aktuelle Zeit
            current_time = datetime.now().strftime('%H:%M')
            log_embed.add_field(
                name="",
                value=f"**{member.guild.name}** • heute um {current_time} Uhr",
                inline=False
            )

            await log_channel.send(embed=log_embed)
            print(f"✅ Join-Log für {member.name} gesendet!")

        except Exception as e:
            print(f"❌ Fehler bei Join-Log: {e}")

    # === ROLLE ZUWEISEN (wie bisher) ===
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role:
        try:
            await member.add_roles(role)
            print(f"✅ Rolle {role_name} wurde {member.name} zugewiesen!")
        except Exception as e:
            print(f"❌ Fehler beim Zuweisen der Rolle: {e}")


@bot.event
async def on_member_remove(member):
    print(f"👋 DEBUG: {member.name} ({member.id}) hat den Server {member.guild.name} verlassen!")

    # Konfiguration
    join_log_channel_id = 1387484932862906450

    # === LEAVE-LOG ===
    log_channel = bot.get_channel(join_log_channel_id)
    if log_channel:
        try:
            # Erstelle Leave-Log Embed mit dunkelroter Farbe
            log_embed = discord.Embed(
                color=discord.Color.dark_red()
            )

            # Setze das Profilbild des Benutzers als Author-Bild
            if member.avatar:
                log_embed.set_author(name=member.name, icon_url=member.avatar.url)
                log_embed.set_thumbnail(url=member.avatar.url)
            else:
                log_embed.set_author(name=member.name, icon_url=member.default_avatar.url)
                log_embed.set_thumbnail(url=member.default_avatar.url)

            # Haupttext mit Benutzername und ID
            log_embed.add_field(
                name="",
                value=f"**{member.name}**\n<@{member.id}> hat uns verlassen.",
                inline=False
            )

            # Server-Name und aktuelle Zeit
            current_time = datetime.now().strftime('%d.%m.%Y %H:%M')
            log_embed.add_field(
                name="",
                value=f"**{member.guild.name}** • {current_time}",
                inline=False
            )

            await log_channel.send(embed=log_embed)
            print(f"✅ Leave-Log für {member.name} gesendet!")

        except Exception as e:
            print(f"❌ Fehler bei Leave-Log: {e}")


@bot.command()
async def ping(ctx):
    await ctx.send('Pong!')


@bot.command()
async def test_join(ctx):
    """Test-Befehl um die Willkommensfunktion manuell zu testen"""
    print(f"Test-Join angefordert von {ctx.author.name}")
    await on_member_join(ctx.author)
    await ctx.send("Test-Willkommensnachricht und Join-Log wurden ausgelöst! Überprüfe die Kanäle.")


@bot.command()
async def test_leave(ctx):
    """Test-Befehl um die Leave-Log-Funktion manuell zu testen"""
    print(f"Test-Leave angefordert von {ctx.author.name}")
    await on_member_remove(ctx.author)
    await ctx.send("Test-Leave-Log wurde ausgelöst! Überprüfe den Log-Kanal.")


# Starte den Bot
if TOKEN:
    print("Starte Bot...")
    print(f"Konfigurierte Intents: {intents}")
    bot.run(TOKEN)
else:
    print(
        "Fehler: Bot-Token nicht gefunden. Bitte setze die Umgebungsvariable 'DISCORD_BOT_TOKEN' oder füge das Token direkt in den Code ein.")