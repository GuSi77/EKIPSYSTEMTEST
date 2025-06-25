import discord
from discord.ext import commands
import os

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
    print(f"Member joined event wurde ausgelöst!")

    # Konfiguration
    welcome_channel_id = 1250809478232932402  # Deine Kanal-ID
    role_name = "Mitglied"  # Deine Rolle

    # Debug: Kanal-Zugriff testen
    channel = bot.get_channel(welcome_channel_id)
    if channel:
        print(f"✅ DEBUG: Willkommenskanal gefunden: {channel.name} (ID: {channel.id})")

        # Debug: Bot-Berechtigungen im Kanal prüfen
        bot_member = channel.guild.get_member(bot.user.id)
        permissions = channel.permissions_for(bot_member)
        print(f"Bot-Berechtigungen im Kanal:")
        print(f"  - Nachrichten senden: {permissions.send_messages}")
        print(f"  - Embeds senden: {permissions.embed_links}")
        print(f"  - Kanal lesen: {permissions.read_messages}")

    else:
        print(f"❌ FEHLER: Willkommenskanal mit ID {welcome_channel_id} nicht gefunden!")
        print("Verfügbare Kanäle auf diesem Server:")
        for ch in member.guild.channels:
            if isinstance(ch, discord.TextChannel):
                print(f"  - {ch.name} (ID: {ch.id})")
        return

    # Debug: Rolle testen
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role:
        print(f"✅ DEBUG: Rolle gefunden: {role.name} (ID: {role.id})")

        # Debug: Bot-Berechtigungen für Rollenverwaltung prüfen
        bot_member = member.guild.get_member(bot.user.id)
        can_manage_roles = bot_member.guild_permissions.manage_roles
        print(f"Bot kann Rollen verwalten: {can_manage_roles}")

        # Debug: Rollenhierarchie prüfen
        bot_top_role = bot_member.top_role
        print(f"Bot's höchste Rolle: {bot_top_role.name} (Position: {bot_top_role.position})")
        print(f"Zuzuweisende Rolle: {role.name} (Position: {role.position})")
        print(f"Bot kann diese Rolle zuweisen: {bot_top_role.position > role.position}")

    else:
        print(f"❌ FEHLER: Rolle '{role_name}' nicht gefunden!")
        print("Verfügbare Rollen auf diesem Server:")
        for r in member.guild.roles:
            print(f"  - {r.name} (ID: {r.id})")

    # Willkommensnachricht senden
    try:
        embed = discord.Embed(
            title=f"Willkommen auf dem Server, {member.name}!",
            description=f"Schön, dass du da bist, {member.mention}!\n\n Wir hoffen, du hast eine tolle Zeit hier.",
            color=discord.Color.red()
        )

        # Optional: Füge das Profilbild des neuen Mitglieds hinzu
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        else:
            embed.set_thumbnail(url=member.default_avatar.url)

        # Optional: Füge ein Feld mit Server-Informationen hinzu
        embed.add_field(
            name="Server-Info",
            value=f"Du bist das {len(member.guild.members)}. Mitglied!",
            inline=False
        )

        await channel.send(embed=embed)
        print(f"✅ DEBUG: Willkommensnachricht für {member.name} erfolgreich gesendet!")

    except discord.Forbidden:
        print(f"❌ FEHLER: Bot hat keine Berechtigung, Nachrichten in {channel.name} zu senden!")
    except Exception as e:
        print(f"❌ FEHLER beim Senden der Willkommensnachricht: {e}")

    # Rolle zuweisen
    if role:
        try:
            await member.add_roles(role)
            print(f"✅ DEBUG: Rolle {role_name} wurde {member.name} erfolgreich zugewiesen!")

        except discord.Forbidden:
            print(f"❌ FEHLER: Bot hat keine Berechtigung, Rolle {role_name} zuzuweisen!")
            print("Mögliche Ursachen:")
            print("  - Bot-Rolle ist nicht hoch genug in der Hierarchie")
            print("  - Bot hat keine 'Rollen verwalten'-Berechtigung")

        except discord.HTTPException as e:
            print(f"❌ HTTP-FEHLER beim Zuweisen der Rolle: {e}")

        except Exception as e:
            print(f"❌ UNBEKANNTER FEHLER beim Zuweisen der Rolle: {e}")


@bot.command()
async def ping(ctx):
    await ctx.send('Pong!')


@bot.command()
async def test_welcome(ctx):
    """Test-Befehl um die Willkommensfunktion manuell zu testen"""
    print(f"Test-Willkommensnachricht angefordert von {ctx.author.name}")

    # Simuliere ein member_join Event für den Benutzer, der den Befehl ausgeführt hat
    await on_member_join(ctx.author)
    await ctx.send("Test-Willkommensnachricht wurde ausgelöst! Überprüfe die Logs.")


# Debug: Zeige beim Start alle wichtigen Informationen
@bot.event
async def on_guild_join(guild):
    print(f"Bot wurde zu Server hinzugefügt: {guild.name} (ID: {guild.id})")


# Starte den Bot
if TOKEN:
    print("Starte Bot...")
    print(f"Konfigurierte Intents: {intents}")
    bot.run(TOKEN)
else:
    print(
        "Fehler: Bot-Token nicht gefunden. Bitte setze die Umgebungsvariable 'DISCORD_BOT_TOKEN' oder füge das Token direkt in den Code ein.")



