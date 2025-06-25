import discord
from discord.ext import commands
import os

# Lade das Bot-Token aus der Umgebungsvariable namens 'DISCORD_BOT_TOKEN'
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    await bot.change_presence(status=discord.Status.dnd) # <-- Diese Zeile hinzufügen
    print(f'{bot.user} hat sich erfolgreich angemeldet!')

@bot.command()
async def ping(ctx):
    await ctx.send('Pong!')

# Starte den Bot
if TOKEN:
    bot.run(TOKEN)
else:
    print("Fehler: Bot-Token nicht gefunden. Bitte setze die Umgebungsvariable 'DISCORD_BOT_TOKEN' oder füge das Token direkt in den Code ein.")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True # <-- Diese Zeile hinzufügen

@bot.event
async def on_member_join(member):
    # Hier kommt der Code für die Willkommensnachricht und Rollenzuweisung hin
    print(f'{member.name} ist dem Server beigetreten!')

    # Konfiguriere hier die ID des Willkommenskanals und den Namen der Rolle
    welcome_channel_id = 1250809478232932402 # ERSETZE DIES DURCH DIE ECHTE KANAL-ID
    role_name = "Mitglied" # ERSETZE DIES DURCH DEN ECHTEN ROLLENNAMEN

    # Willkommensnachricht als Embed senden
    channel = bot.get_channel(welcome_channel_id)
    if channel:
        embed = discord.Embed(
            title=f"Willkommen auf dem Server, {member.name}!",
            description=f"Schön, dass du da bist, {member.mention}! Wir hoffen, du hast eine tolle Zeit hier.",
            color=discord.Color.red() # Du kannst hier eine andere Farbe wählen
        )
        # Optional: Füge ein Bild hinzu, wie auf deinem Beispielbild
        # embed.set_image(url="URL_ZU_DEINEM_WILLKOMMENSBILD")
        # Optional: Füge ein Thumbnail hinzu (z.B. das Profilbild des neuen Mitglieds)
        # embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)

        await channel.send(embed=embed)

    # Rolle zuweisen
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role:
        try:
            await member.add_roles(role)
            print(f'Rolle {role_name} wurde {member.name} zugewiesen.')
        except discord.Forbidden:
            print(f'Fehler: Bot hat keine Berechtigung, Rolle {role_name} zuzuweisen.')
    else:
        print(f'Fehler: Rolle {role_name} nicht gefunden.')



