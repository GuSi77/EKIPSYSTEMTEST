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


