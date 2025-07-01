import discord
from discord.ext import commands, tasks
import os
from datetime import datetime, timezone
import asyncio
import io
import json
import re
from collections import defaultdict, deque
import time
from datetime import timedelta
import openai
import requests

def check_bot_permissions(guild, required_permissions):
    """Überprüft Bot-Berechtigungen"""
    if not guild or not guild.me:
        return False
    
    bot_permissions = guild.me.guild_permissions
    
    for permission in required_permissions:
        if not getattr(bot_permissions, permission, False):
            print(f"❌ Fehlende Berechtigung: {permission}")
            return False
    
    return True

# Erforderliche Berechtigungen definieren
REQUIRED_PERMISSIONS = [
    'read_messages',
    'send_messages',
    'embed_links',
    'attach_files',
    'read_message_history',
    'manage_messages',
    'manage_channels',
    'kick_members',
    'ban_members',
    'moderate_members',
    'view_audit_log'
]

# Sicherheitsfunktionen
async def safe_send_embed(channel, embed, fallback_message="Fehler beim Senden der Nachricht"):
    """Sicheres Senden von Embeds mit Fallback"""
    try:
        if channel and hasattr(channel, 'send'):
            return await channel.send(embed=embed)
    except discord.Forbidden:
        print(f"❌ Keine Berechtigung zum Senden in Kanal {channel.id if channel else 'None'}")
    except discord.HTTPException as e:
        print(f"❌ HTTP-Fehler beim Senden: {e}")
    except Exception as e:
        print(f"❌ Unerwarteter Fehler beim Senden: {e}")
    
    # Fallback: Versuche einfache Textnachricht
    try:
        if channel and hasattr(channel, 'send'):
            return await channel.send(fallback_message)
    except:
        pass
    
    return None

async def safe_delete_message(message, reason="Automatische Moderation"):
    """Sicheres Löschen von Nachrichten"""
    try:
        if message and hasattr(message, 'delete'):
            await message.delete()
            return True
    except discord.NotFound:
        print(f"⚠️ Nachricht bereits gelöscht: {message.id if message else 'None'}")
    except discord.Forbidden:
        print(f"❌ Keine Berechtigung zum Löschen der Nachricht: {message.id if message else 'None'}")
    except Exception as e:
        print(f"❌ Fehler beim Löschen der Nachricht: {e}")
    
    return False

def sanitize_input(text, max_length=2000):
    """Bereinigt und validiert Benutzereingaben"""
    if not isinstance(text, str):
        return ""
    
    # Entferne potentiell gefährliche Zeichen
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    
    # Begrenze Länge
    if len(text) > max_length:
        text = text[:max_length] + "..."
    
    return text.strip()

def validate_channel_id(channel_id):
    """Validiert Channel-IDs"""
    try:
        channel_id = int(channel_id)
        return 100000000000000000 <= channel_id <= 999999999999999999
    except (ValueError, TypeError):
        return False

def validate_user_id(user_id):
    """Validiert User-IDs"""
    try:
        user_id = int(user_id)
        return 100000000000000000 <= user_id <= 999999999999999999
    except (ValueError, TypeError):
        return False

# Fügen Sie diese Funktion nach den Imports hinzu
async def create_ticket_transcript(channel, closed_by):
    """Erstellt ein Transkript aller Nachrichten im Ticket-Channel"""
    messages = []
    
    # Sammle alle Nachrichten aus dem Channel
    async for message in channel.history(limit=None, oldest_first=True):
        # Überspringe System-Nachrichten und Pins
        if message.type in [discord.MessageType.pins_add, discord.MessageType.channel_name_change]:
            continue
            
        timestamp = message.created_at.strftime("%d.%m.%Y - %H:%M:%S")
        author = message.author.display_name
        content = message.content if message.content else "[Keine Textnachricht]"
        
        # Behandle Embeds
        if message.embeds:
            for embed in message.embeds:
                if embed.title:
                    content += f"\n[Embed: {embed.title}]"
                if embed.description:
                    content += f"\n{embed.description}"
        
        # Behandle Anhänge
        if message.attachments:
            for attachment in message.attachments:
                content += f"\n[Anhang: {attachment.filename}]"
        
        messages.append(f"[{timestamp}] {author}: {content}")
    
    # Erstelle Transkript-Text
    transcript_header = f"""Transkript für Kanal #{channel.name} (ID: {channel.id})
Erstellt am: {datetime.now(timezone.utc).strftime("%d.%m.%Y - %H:%M:%S")}
{'-' * 50}
"""
    
    transcript_content = "\n".join(messages)
    full_transcript = transcript_header + transcript_content
    
    # Speichere als Datei
    filename = f"transcript-{channel.name}-{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    # Erstelle Discord-Datei
    transcript_file = discord.File(
        io.StringIO(full_transcript), 
        filename=filename
    )
    
    return transcript_file, len(messages)

# Ticket-System Klassen mit Dropdown
class TicketDropdown(discord.ui.Select):
    def __init__(self):
        # Erstelle Optionen für das Dropdown-Menü
        options = []
        for category_key, category_data in TICKET_CATEGORIES.items():
            options.append(discord.SelectOption(
                label=category_data['label'],
                description=category_data['description'],
                emoji=category_data['emoji'],
                value=category_key
            ))
        
        super().__init__(
            placeholder="Wie können wir dir helfen?",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_dropdown"
        )
    
    async def callback(self, interaction):
        category_key = self.values[0]
        await self.create_ticket(interaction, category_key)
    
    async def create_ticket(self, interaction, category_key):
        guild = interaction.guild
        user = interaction.user
        category_data = TICKET_CATEGORIES[category_key]
        
        # Prüfe, ob der Benutzer bereits ein offenes Ticket hat
        existing_channel = discord.utils.get(
            guild.channels,
            name=f'ticket-{user.name.lower()}',
            type=discord.ChannelType.text
        )
        
        if existing_channel:
            await interaction.response.send_message(
                "❌ Du hast bereits ein offenes Ticket!", 
                ephemeral=True
            )
            return
        
        try:
            # Hole die aktuelle Ticket-Kategorie (dynamisch)
            current_category_id = get_current_ticket_category()
            category = discord.utils.get(guild.categories, id=current_category_id)
            
            if not category:
                await interaction.response.send_message(
                    f"❌ Ticket-Kategorie (ID: {current_category_id}) nicht gefunden!\n💡 Verwende `!set_ticket_category <kategorie_id>` um eine gültige Kategorie zu setzen.", 
                    ephemeral=True
                )
                return
            
            # Erstelle den Ticket-Channel
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True
                )
            }
            
            # Füge Support-Rolle und EKIP Devs Team hinzu
            support_role = guild.get_role(TICKET_SUPPORT_ROLE_ID)
            ekip_role = guild.get_role(EKIP_DEVS_ROLE_ID)
            
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_messages=True
                )
            
            if ekip_role:
                overwrites[ekip_role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_messages=True
                )
            
            channel = await guild.create_text_channel(
                name=f'ticket-{user.name.lower()}',
                category=category,
                overwrites=overwrites
            )
            
            # Erstelle das erweiterte Ticket-Embed wie im Bild
            embed = discord.Embed(
                title="🎫 Herzlich Willkommen",
                color=0x6e0000,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(
                name="• Vielen Dank für dein Interesse!",
                value="Wir werden dein Anliegen so schnell wie möglich bearbeiten.",
                inline=False
            )
            
            embed.add_field(
                name="• Bitte warte auf eine Rückmeldung",
                value="Ein Mitglied unseres Teams wird sich bald bei dir melden.",
                inline=False
            )
            
            embed.set_footer(
                text=f"Ticket erstellt von {user.display_name} • {category_data['label']}",
                icon_url=user.display_avatar.url
            )
            
            # Füge das Ticket-Banner hinzu (falls vorhanden)
            # embed.set_image(url="URL_ZU_IHREM_TICKET_BANNER")
            
            # Erstelle die erweiterte View mit allen Buttons
            ticket_view = AdvancedTicketView(user.id, category_key)
            
            # Ping den Benutzer und das EKIP Devs Team ÜBER dem Embed
            ping_message = f"{user.mention} {ekip_role.mention if ekip_role else ''}"
            await channel.send(ping_message)  # Ping bleibt sichtbar
            
            # Sende das Embed mit Buttons
            ticket_message = await channel.send(embed=embed, view=ticket_view)
            
            # Pinne die Ticket-Nachricht
            await ticket_message.pin()
            
            # Log das Ticket (dunkelrot)
            log_channel = guild.get_channel(TICKET_LOG_CHANNEL_ID)
            if log_channel:
                log_embed = discord.Embed(
                    title="🎫 Neues Ticket erstellt",
                    description=f"**Benutzer:** {user.mention}\n**Kategorie:** {category_data['label']}\n**Channel:** {channel.mention}\n**Discord-Kategorie:** {category.name}",
                    color=0x6e0000,  # Dunkelrot
                    timestamp=datetime.now(timezone.utc)
                )
                await log_channel.send(embed=log_embed)
            
            await interaction.response.send_message(
                f"✅ Dein {category_data['label']} wurde erstellt: {channel.mention}\n📁 Kategorie: {category.name}",
                ephemeral=True
            )
            
        except Exception as e:
            print(f"Fehler beim Erstellen des Tickets: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Erstellen des Tickets!",
                ephemeral=True
            )

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketDropdown())

class AdvancedTicketView(discord.ui.View):
    def __init__(self, ticket_creator_id, ticket_type):
        super().__init__(timeout=None)
        self.ticket_creator_id = ticket_creator_id
        self.ticket_type = ticket_type
    
    @discord.ui.button(label='Claim', emoji='🔧', style=discord.ButtonStyle.primary, custom_id='claim_ticket')
    async def claim_ticket(self, interaction, button):
        # Nur Team-Mitglieder können Tickets claimen
        support_role = interaction.guild.get_role(TICKET_SUPPORT_ROLE_ID)
        ekip_role = interaction.guild.get_role(EKIP_DEVS_ROLE_ID)
        
        if not (support_role in interaction.user.roles or ekip_role in interaction.user.roles):
            await interaction.response.send_message(
                "❌ Nur Team-Mitglieder können Tickets claimen!",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="✅ Ticket geclaimed",
            description=f"Dieses Ticket wurde von {interaction.user.mention} übernommen.",
            color=0x6e0000,
            timestamp=datetime.now(timezone.utc)
        )
        
        await interaction.response.send_message(embed=embed)
        
        # Log das Claim
        log_channel = interaction.guild.get_channel(TICKET_LOG_CHANNEL_ID)
        if log_channel:
            log_embed = discord.Embed(
                title="🔧 Ticket geclaimed",
                description=f"**Ticket:** {interaction.channel.mention}\n**Geclaimed von:** {interaction.user.mention}",
                color=0x6e0000,
                timestamp=datetime.now(timezone.utc)
            )
            await log_channel.send(embed=log_embed)
    
    @discord.ui.button(label='Close', emoji='🔒', style=discord.ButtonStyle.secondary, custom_id='close_ticket_advanced')
    async def close_ticket(self, interaction, button):
        # Prüfe Berechtigung
        support_role = interaction.guild.get_role(TICKET_SUPPORT_ROLE_ID)
        ekip_role = interaction.guild.get_role(EKIP_DEVS_ROLE_ID)
        
        if not (support_role in interaction.user.roles or ekip_role in interaction.user.roles or interaction.user.id == self.ticket_creator_id):
            await interaction.response.send_message(
                "❌ Du hast keine Berechtigung, dieses Ticket zu schließen!",
                ephemeral=True
            )
            return
        
        # Erstelle Transkript vor dem Schließen
        try:
            transcript_file, message_count = await create_ticket_transcript(interaction.channel, interaction.user)
            
            # Log das geschlossene Ticket mit Transkript
            log_channel = interaction.guild.get_channel(TICKET_LOG_CHANNEL_ID)
            if log_channel:
                log_embed = discord.Embed(
                    title="🔒 Ticket geschlossen",
                    description=f"**Ticket:** {interaction.channel.mention}\n**Geschlossen von:** {interaction.user.mention}\n**Ersteller:** <@{self.ticket_creator_id}>\n**Nachrichten:** {message_count}",
                    color=0x6e0000,
                    timestamp=datetime.now(timezone.utc)
                )
                
                # Sende Embed mit Transkript-Datei
                await log_channel.send(embed=log_embed, file=transcript_file)
                
        except Exception as e:
            print(f"Fehler beim Erstellen des Transkripts: {e}")
        
        # Verschiebe zu geschlossene Tickets Kategorie
        closed_category = interaction.guild.get_channel(TICKET_CLOSED_CATEGORY_ID)
        if closed_category:
            await interaction.channel.edit(category=closed_category)
        
        embed = discord.Embed(
            title="🔒 Ticket geschlossen",
            description=f"Dieses Ticket wurde von {interaction.user.mention} geschlossen.\n\nDu kannst es mit dem **Reopen** Button wieder öffnen.",
            color=0x6e0000,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Erstelle neue View mit Reopen-Button
        reopen_view = ReopenTicketView(self.ticket_creator_id, self.ticket_type)
        await interaction.response.send_message(embed=embed, view=reopen_view)
    
    @discord.ui.button(label='Reopen', emoji='🔓', style=discord.ButtonStyle.success, custom_id='reopen_ticket')
    async def reopen_ticket(self, interaction, button):
        # Nur Team-Mitglieder können Tickets wiedereröffnen
        support_role = interaction.guild.get_role(TICKET_SUPPORT_ROLE_ID)
        ekip_role = interaction.guild.get_role(EKIP_DEVS_ROLE_ID)
        
        if not (support_role in interaction.user.roles or ekip_role in interaction.user.roles):
            await interaction.response.send_message(
                "❌ Nur Team-Mitglieder können Tickets wiedereröffnen!",
                ephemeral=True
            )
            return
        
        # Verschiebe zu wiedereröffnete Tickets Kategorie oder zurück zur Haupt-Kategorie
        reopen_category_id = TICKET_REOPENED_CATEGORY_ID if TICKET_REOPENED_CATEGORY_ID else get_current_ticket_category()
        reopen_category = interaction.guild.get_channel(reopen_category_id)
        
        if reopen_category:
            await interaction.channel.edit(category=reopen_category)
        
        embed = discord.Embed(
            title="🔓 Ticket wiedereröffnet",
            description=f"Dieses Ticket wurde von {interaction.user.mention} wiedereröffnet.",
            color=0x6e0000,
            timestamp=datetime.now(timezone.utc)
        )
        
        await interaction.response.send_message(embed=embed)
        
        # Log das Wiedereröffnen
        log_channel = interaction.guild.get_channel(TICKET_LOG_CHANNEL_ID)
        if log_channel:
            log_embed = discord.Embed(
                title="🔓 Ticket wiedereröffnet",
                description=f"**Ticket:** {interaction.channel.mention}\n**Wiedereröffnet von:** {interaction.user.mention}",
                color=0x6e0000,
                timestamp=datetime.now(timezone.utc)
            )
            await log_channel.send(embed=log_embed)
    
    @discord.ui.button(label='Delete', emoji='🗑️', style=discord.ButtonStyle.danger, custom_id='delete_ticket')
    async def delete_ticket(self, interaction, button):
        # Nur EKIP Devs Team kann Tickets löschen
        ekip_role = interaction.guild.get_role(EKIP_DEVS_ROLE_ID)
        
        if not (ekip_role in interaction.user.roles):
            await interaction.response.send_message(
                "❌ Nur das EKIP Devs Team kann Tickets löschen!",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="⚠️ Ticket löschen",
            description="Bist du sicher, dass du dieses Ticket **permanent** löschen möchtest?\n\n**Diese Aktion kann nicht rückgängig gemacht werden!**",
            color=0x6e0000
        )
        
        view = ConfirmDeleteView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ReopenTicketView(discord.ui.View):
    def __init__(self, ticket_creator_id, ticket_type):
        super().__init__(timeout=None)
        self.ticket_creator_id = ticket_creator_id
        self.ticket_type = ticket_type
    
    @discord.ui.button(label='Reopen', emoji='🔓', style=discord.ButtonStyle.success, custom_id='reopen_closed_ticket')
    async def reopen_ticket(self, interaction, button):
        # Nur Team-Mitglieder können geschlossene Tickets wiedereröffnen
        support_role = interaction.guild.get_role(TICKET_SUPPORT_ROLE_ID)
        ekip_role = interaction.guild.get_role(EKIP_DEVS_ROLE_ID)
        
        if not (support_role in interaction.user.roles or ekip_role in interaction.user.roles):
            await interaction.response.send_message(
                "❌ Nur Team-Mitglieder können Tickets wiedereröffnen!",
                ephemeral=True
            )
            return
        
        # Verschiebe zurück zur aktiven Kategorie
        reopen_category_id = TICKET_REOPENED_CATEGORY_ID if TICKET_REOPENED_CATEGORY_ID else get_current_ticket_category()
        reopen_category = interaction.guild.get_channel(reopen_category_id)
        
        if reopen_category:
            await interaction.channel.edit(category=reopen_category)
        
        embed = discord.Embed(
            title="🔓 Ticket wiedereröffnet",
            description=f"Dieses Ticket wurde von {interaction.user.mention} wiedereröffnet.",
            color=0x6e0000,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Erstelle neue View mit allen Buttons
        new_view = AdvancedTicketView(self.ticket_creator_id, self.ticket_type)
        await interaction.response.edit_message(embed=embed, view=new_view)
        
        # Ping den Ticket-Ersteller und EKIP Devs Team
        creator = interaction.guild.get_member(self.ticket_creator_id)
        ekip_role = interaction.guild.get_role(EKIP_DEVS_ROLE_ID)
        
        ping_message = f"{creator.mention if creator else ''} {ekip_role.mention if ekip_role else ''} - Ticket wurde wiedereröffnet!"
        await interaction.followup.send(ping_message)

class ConfirmDeleteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
    
    @discord.ui.button(label='Ja, löschen', emoji='✅', style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction, button):
        channel = interaction.channel
        guild = interaction.guild
        
        # Erstelle Transkript vor dem Löschen
        try:
            transcript_file, message_count = await create_ticket_transcript(channel, interaction.user)
            
            # Log das gelöschte Ticket mit Transkript
            log_channel = guild.get_channel(TICKET_LOG_CHANNEL_ID)
            if log_channel:
                log_embed = discord.Embed(
                    title="🗑️ Ticket gelöscht",
                    description=f"**Channel:** {channel.name}\n**Gelöscht von:** {interaction.user.mention}\n**Nachrichten:** {message_count}",
                    color=0x6e0000,
                    timestamp=datetime.now(timezone.utc)
                )
                
                # Sende Embed mit Transkript-Datei
                await log_channel.send(embed=log_embed, file=transcript_file)
                
        except Exception as e:
            print(f"Fehler beim Erstellen des Transkripts: {e}")
            # Fallback: Log ohne Transkript
            log_channel = guild.get_channel(TICKET_LOG_CHANNEL_ID)
            if log_channel:
                log_embed = discord.Embed(
                    title="🗑️ Ticket gelöscht",
                    description=f"**Channel:** {channel.name}\n**Gelöscht von:** {interaction.user.mention}\n**Transkript:** Fehler beim Erstellen",
                    color=0x6e0000,
                    timestamp=datetime.now(timezone.utc)
                )
                await log_channel.send(embed=log_embed)
        
        await interaction.response.send_message("🗑️ Ticket wird in 5 Sekunden gelöscht...", ephemeral=True)
        await asyncio.sleep(5)
        await channel.delete(reason=f"Ticket gelöscht von {interaction.user}")
    
    @discord.ui.button(label='Abbrechen', emoji='❌', style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, interaction, button):
        await interaction.response.send_message("❌ Ticket-Löschung abgebrochen.", ephemeral=True)

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='Ticket schließen', emoji='🔒', style=discord.ButtonStyle.danger, custom_id='close_ticket')
    async def close_ticket(self, interaction, button):
        embed = discord.Embed(
            title="🔒 Ticket schließen",
            description="Bist du sicher, dass du dieses Ticket schließen möchtest?\n\n⚠️ **Diese Aktion kann nicht rückgängig gemacht werden!**",
            color=0x6e0000  # Dunkelrot
        )
        
        view = TicketConfirmCloseView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class TicketConfirmCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Kein Timeout für Persistenz
    
    @discord.ui.button(label='Ja, schließen', emoji='✅', style=discord.ButtonStyle.danger, custom_id='confirm_close_ticket')
    async def confirm_close(self, interaction, button):
        channel = interaction.channel
        guild = interaction.guild
        
        # Log das geschlossene Ticket (dunkelrot)
        log_channel = guild.get_channel(TICKET_LOG_CHANNEL_ID)
        if log_channel:
            log_embed = discord.Embed(
                title="🔒 Ticket geschlossen",
                description=f"**Channel:** {channel.name}\n**Geschlossen von:** {interaction.user.mention}",
                color=0x6e0000,  # Dunkelrot
                timestamp=datetime.now(timezone.utc)
            )
            await log_channel.send(embed=log_embed)
        
        await interaction.response.send_message("🔒 Ticket wird in 5 Sekunden geschlossen...", ephemeral=True)
        await asyncio.sleep(5)
        await channel.delete(reason=f"Ticket geschlossen von {interaction.user}")
    
    @discord.ui.button(label='Abbrechen', emoji='❌', style=discord.ButtonStyle.secondary, custom_id='cancel_close_ticket')
    async def cancel_close(self, interaction, button):
        await interaction.response.send_message("❌ Ticket-Schließung abgebrochen.", ephemeral=True)

# Lade Umgebungsvariablen aus .env-Datei
from dotenv import load_dotenv
load_dotenv()

# Sicher Token aus Umgebungsvariable laden
TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    print("❌ FEHLER: DISCORD_TOKEN nicht in .env gefunden!")
    exit(1)


# Sichere API-Key-Validierung
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
    print("✅ OpenAI API konfiguriert")
else:
    print("⚠️ OpenAI API nicht konfiguriert - Basis-Features aktiv")

# Konfiguration - Channel IDs direkt im Code
WELCOME_CHANNEL_ID = 1387484818052481164
INVITE_LOG_CHANNEL_ID = 1387484937648865453
JOIN_LOG_CHANNEL_ID = 1387484930438598859
LEAVE_LOG_CHANNEL_ID = 1387484932862906450
VOICE_LOG_CHANNEL_ID = 1387484934423449631
MESSAGE_LOG_CHANNEL_ID = 1387484936222544022
ROLE_LOG_CHANNEL_ID = 1387484939972382795
CHANNEL_LOG_CHANNEL_ID = 1387484941914210306
MUTE_LOG_CHANNEL_ID = 1387484943684210828
KICK_LOG_CHANNEL_ID = 1387484945324441793
BAN_LOG_CHANNEL_ID = 1387484946691788890

# Konfigurationsdatei laden/speichern
CONFIG_FILE = 'config.json'

def load_config():
    """Lädt die Konfiguration aus der JSON-Datei"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        # Standard-Konfiguration erstellen, falls Datei nicht existiert
        default_config = {
            "TICKET_CATEGORY_ID": 1234567890123456789,
            "TICKET_LOG_CHANNEL_ID": 1236074037768093817,
            "TICKET_SUPPORT_ROLE_ID": 1234567890123456789,
            "TICKET_CLOSED_CATEGORY_ID": 1234567890123456789,
            "TICKET_REOPENED_CATEGORY_ID": 1234567890123456789,
            "EKIP_DEVS_ROLE_ID": 1234567890123456789
        }
        save_config(default_config)
        return default_config
    except json.JSONDecodeError:
        print("Fehler beim Laden der Konfiguration. Verwende Standard-Werte.")
        return load_config()  # Rekursiver Aufruf mit Standard-Werten

def save_config(config):
    """Speichert die Konfiguration in der JSON-Datei"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

# Konfiguration laden
config = load_config()

# Ticket-System Konfiguration
TICKET_CATEGORY_ID = config['TICKET_CATEGORY_ID']
TICKET_LOG_CHANNEL_ID = config['TICKET_LOG_CHANNEL_ID']
TICKET_SUPPORT_ROLE_ID = config['TICKET_SUPPORT_ROLE_ID']
TICKET_CLOSED_CATEGORY_ID = config['TICKET_CLOSED_CATEGORY_ID']
TICKET_REOPENED_CATEGORY_ID = config['TICKET_REOPENED_CATEGORY_ID']

# EKIP Devs Team Rolle
EKIP_DEVS_ROLE_ID = config['EKIP_DEVS_ROLE_ID']

# Globale Variable für dynamische Kategorie-Konfiguration
CURRENT_TICKET_CATEGORY_ID = TICKET_CATEGORY_ID  # Standard-Kategorie

# Funktion zum Aktualisieren der Ticket-Kategorie
def update_ticket_category(new_category_id):
    global CURRENT_TICKET_CATEGORY_ID, config
    CURRENT_TICKET_CATEGORY_ID = new_category_id
    config['TICKET_CATEGORY_ID'] = new_category_id
    save_config(config)
    print(f"Ticket-Kategorie aktualisiert und gespeichert: {new_category_id}")

# Funktion zum Abrufen der aktuellen Kategorie
def get_current_ticket_category():
    return CURRENT_TICKET_CATEGORY_ID

# Ticket-Kategorien mit einheitlicher Farbe #6e0000
TICKET_CATEGORIES = {
    'kauf': {
        'emoji': '💰',
        'label': 'Kauf-Ticket',
        'description': 'Interesse an einer Dienstleistung von uns?',
        'color': 0x6e0000  # Neue Farbe
    },
    'support': {
        'emoji': '🛠️',
        'label': 'Support-Ticket',
        'description': 'Benötigst du Hilfe oder hast Fragen?',
        'color': 0x6e0000  # Neue Farbe
    },
    'bug': {
        'emoji': '🐛',
        'label': 'Bug-Report',
        'description': 'Hast du einen Fehler gefunden?',
        'color': 0x6e0000  # Neue Farbe
    }
}

MEMBER_ROLE_NAME = 'Mitglied'

# Invite-Cache für Tracking
# Nach MEMBER_ROLE_NAME = 'Mitglied'
invite_cache = {}

# Intents konfigurieren
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # KRITISCH für on_member_join
intents.presences = True  # Für Präsenz-Updates
intents.invites = True  # Für Invite-Events

bot = commands.Bot(command_prefix='!', intents=intents)

# Ticket-System Befehle
@bot.command(name='ticket_panel')
@commands.has_permissions(administrator=True)
async def ticket_panel(ctx):
    """Sendet das Ticket-Panel mit Dropdown-Menü (nur für Administratoren)"""
    embed = discord.Embed(
        title="🎫 Ticketsystem",
        description="**• Informationen**\n\nDu hast hier die Möglichkeit, ein Ticket zu erstellen, um Support zu erhalten oder eine Bestellung aufzugeben. Darüber hinaus kannst du auch deinen Gewinn von einem gewonnenen Gewinnspiel hier abholen.\n\n**• Anliegen direkt angeben**\n\nUm dir unnötige Wartezeiten zu ersparen, bitten wir dich, dein Anliegen direkt in das Ticket einzutragen. So können wir dir noch schneller und effizienter weiterhelfen.",
        color=0x6e0000  # Dunkelrot
    )
    
    # Füge das große Ticket-Banner hinzu (falls Sie ein Bild haben)
    # embed.set_image(url="URL_ZU_IHREM_TICKET_BANNER")
    
    view = TicketView()
    await ctx.send(embed=embed, view=view)
    await ctx.message.delete()  # Lösche den Befehl

@bot.command(name='close_ticket')
async def close_ticket_command(ctx):
    """Schließt das aktuelle Ticket"""
    if not ctx.channel.name.startswith('ticket-'):
        await ctx.send("❌ Dieser Befehl kann nur in Ticket-Channels verwendet werden!")
        return
    
    view = TicketCloseView()
    embed = discord.Embed(
        title="🔒 Ticket schließen",
        description="Klicke auf den Button unten, um dieses Ticket zu schließen.",
        color=0x6e0000
    )
    await ctx.send(embed=embed, view=view)

@bot.event
async def on_ready():
    print(f'{bot.user} hat sich erfolgreich angemeldet!')
    print(f'Bot ist auf {len(bot.guilds)} Servern aktiv')
    
    # Debug: Zeige alle verfügbaren Intents an
    print(f'Aktive Intents: {bot.intents}')
    print(f'Members Intent aktiv: {bot.intents.members}')
    print(f'Message Content Intent aktiv: {bot.intents.message_content}')
    
    # Füge persistente Views hinzu
    bot.add_view(TicketView())
    bot.add_view(AdvancedTicketView(0, ""))  # Dummy-Werte für Persistenz
    bot.add_view(ReopenTicketView(0, ""))  # Dummy-Werte für Persistenz
    
    print("Erweiterte Ticket-System geladen!")
    
    # Setze Bot-Status auf "Bitte nicht stören"
    await bot.change_presence(status=discord.Status.dnd)
    print('Bot-Status auf "Bitte nicht stören" gesetzt')
    
    # Starte tägliche Bereinigung (nach dem Event Loop)
    if not daily_cleanup.is_running():
        daily_cleanup.start()
        print("✅ Tägliche Datenbereinigung gestartet")
    
    # Lade alle vorhandenen Invites in den Cache
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}
            print(f'✅ {len(invites)} Invites für {guild.name} geladen')
        except Exception as e:
            print(f'❌ Fehler beim Laden der Invites für {guild.name}: {e}')

@bot.event
async def on_member_join(member):
    print(f"🎉 DEBUG: {member.name} ({member.id}) ist dem Server {member.guild.name} beigetreten!")
    
    # Konfiguration aus Umgebungsvariablen
    welcome_channel_id = WELCOME_CHANNEL_ID
    join_log_channel_id = JOIN_LOG_CHANNEL_ID
    role_name = MEMBER_ROLE_NAME
    
    # === WILLKOMMENSNACHRICHT ===
    welcome_channel = bot.get_channel(welcome_channel_id)
    if welcome_channel:
        try:
            embed = discord.Embed(
                title=f"Willkommen auf dem Server, {member.name}!",
                description=f"Schön, dass du da bist, {member.mention}!\n\nWir hoffen, du hast eine tolle Zeit hier.",
                color=discord.Color.dark_red()
            )
            
            # Setze das Server-Icon als Autor-Bild und Thumbnail
            if member.guild.icon:
                embed.set_author(name=member.name, icon_url=member.guild.icon.url)
                embed.set_thumbnail(url=member.guild.icon.url)
            else:
                embed.set_author(name=member.name)
                
            embed.add_field(
                name="Server-Info", 
                value=f"Du bist das {len(member.guild.members)}. Mitglied!", 
                inline=False
            )
            
            # Footer mit Server-Name, Datum und Uhrzeit
            current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
            embed.set_footer(text=f"{member.guild.name} • {current_datetime}")
                
            await welcome_channel.send(embed=embed)
            print(f"✅ Willkommensnachricht für {member.name} gesendet!")
            
        except Exception as e:
            print(f"❌ Fehler bei Willkommensnachricht: {e}")
    
    # === JOIN-LOG ===
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
            log_embed = discord.Embed(color=discord.Color.dark_red())
            
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
                value=f"**{member.name}** `{member.id}`\n{member.mention} trat dem Server bei.",
                inline=False
            )
            
            # Kontoalter
            log_embed.add_field(
                name="⏰ Alter des Kontos:",
                value=f"{account_created.strftime('%d/%m/%Y %H:%M')}\n**{age_text} ago**",
                inline=False
            )
            
            # Footer mit Server-Name, Datum und Uhrzeit
            current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
            log_embed.set_footer(text=f"{member.guild.name} • {current_datetime}")
            
            await log_channel.send(embed=log_embed)
            print(f"✅ Join-Log für {member.name} gesendet!")
            
        except Exception as e:
            print(f"❌ Fehler bei Join-Log: {e}")
    
    # === ROLLE ZUWEISEN ===
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
    
    # Überprüfe Audit-Logs für Kick-Events
    try:
        print(f"🔍 Überprüfe Audit-Logs für Kick-Events...")
        
        # Überprüfe Bot-Berechtigungen
        if not member.guild.me.guild_permissions.view_audit_log:
            print(f"❌ Bot hat keine 'View Audit Log' Berechtigung!")
            # Fahre mit normalem Leave-Log fort
        else:
            print(f"✅ Bot hat Audit-Log Berechtigung")
            
            async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                print(f"📋 Audit-Log Entry gefunden: {entry.target.name if entry.target else 'Unknown'} von {entry.user.name if entry.user else 'Unknown'}")
                print(f"⏰ Entry Zeit: {entry.created_at}, Jetzt: {datetime.now(timezone.utc)}")
                print(f"⏱️ Zeitdifferenz: {(datetime.now(timezone.utc) - entry.created_at).total_seconds()} Sekunden")
                
                # Überprüfe ob der Kick in den letzten 10 Sekunden stattgefunden hat (erweitert von 5 auf 10)
                if (datetime.now(timezone.utc) - entry.created_at).total_seconds() < 10:
                    if entry.target and entry.target.id == member.id:
                        print(f"✅ Kick-Event erkannt für {member.name}!")
                        # Es war ein Kick - sende Kick-Log
                        await handle_kick_log(member, entry.user, entry.reason)
                        return  # Beende hier, damit kein Leave-Log gesendet wird
                    else:
                        print(f"❌ Target ID stimmt nicht überein: {entry.target.id if entry.target else 'None'} != {member.id}")
                else:
                    print(f"❌ Kick-Event zu alt: {(datetime.now(timezone.utc) - entry.created_at).total_seconds()} Sekunden")
                    
        print(f"ℹ️ Kein Kick-Event gefunden, sende Leave-Log...")
                    
    except Exception as e:
        print(f"❌ Fehler beim Überprüfen der Audit-Logs: {e}")
        import traceback
        traceback.print_exc()
    
    # Konfiguration aus Umgebungsvariablen
    leave_log_channel_id = LEAVE_LOG_CHANNEL_ID
    
    # === LEAVE-LOG ===
    log_channel = bot.get_channel(leave_log_channel_id)
    if log_channel:
        try:
            # Erstelle Leave-Log Embed mit dunkelroter Farbe
            log_embed = discord.Embed(color=discord.Color.dark_red())
            
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
            
            # Footer mit Server-Name, Datum und Uhrzeit
            current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
            log_embed.set_footer(text=f"{member.guild.name} • {current_datetime}")
            
            await log_channel.send(embed=log_embed)
            print(f"✅ Leave-Log für {member.name} gesendet!")
            
        except Exception as e:
            print(f"❌ Fehler bei Leave-Log: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    """Event für Voice-Channel Beitritt und Verlassen"""
    
    # Konfiguration aus Umgebungsvariablen
    voice_log_channel_id = VOICE_LOG_CHANNEL_ID
    
    log_channel = bot.get_channel(voice_log_channel_id)
    if not log_channel:
        return
    
    current_time = datetime.now().strftime('%H:%M')
    
    # Voice-Channel beigetreten
    if before.channel is None and after.channel is not None:
        print(f"🔊 DEBUG: {member.name} ist dem Voice-Channel {after.channel.name} beigetreten!")
        
        try:
            log_embed = discord.Embed(color=discord.Color.dark_red())
            
            # Setze das Benutzer-Profilbild als Autor-Bild
            if member.avatar:
                log_embed.set_author(name=member.name, icon_url=member.avatar.url)
            else:
                log_embed.set_author(name=member.name, icon_url=member.default_avatar.url)
            
            # Haupttext für Beitritt
            log_embed.add_field(
                name="",
                value=f"{member.mention} ist dem Sprachkanal `{after.channel.name}` beigetreten.",
                inline=False
            )
  
            # Footer mit Server-Name, Datum und Uhrzeit
            current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
            log_embed.set_footer(text=f"{member.guild.name} • {current_datetime}")
            
            await log_channel.send(embed=log_embed)
            print(f"✅ Voice-Join-Log für {member.name} gesendet!")
            
        except Exception as e:
            print(f"❌ Fehler bei Voice-Join-Log: {e}")
    
    # Voice-Channel verlassen
    elif before.channel is not None and after.channel is None:
        print(f"🔇 DEBUG: {member.name} hat den Voice-Channel {before.channel.name} verlassen!")
        
        try:
            log_embed = discord.Embed(color=discord.Color.dark_red())
            
            # Setze das Benutzer-Profilbild als Autor-Bild
            if member.avatar:
                log_embed.set_author(name=member.name, icon_url=member.avatar.url)
            else:
                log_embed.set_author(name=member.name, icon_url=member.default_avatar.url)
            
            # Haupttext für Verlassen
            log_embed.add_field(
                name="",
                value=f"{member.mention} hat den Sprachkanal `{before.channel.name}` verlassen.",
                inline=False
            )
            
            
            # Footer mit Server-Name, Datum und Uhrzeit
            current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
            log_embed.set_footer(text=f"{member.guild.name} • {current_datetime}")
            
            await log_channel.send(embed=log_embed)
            print(f"✅ Voice-Leave-Log für {member.name} gesendet!")
            
        except Exception as e:
            print(f"❌ Fehler bei Voice-Leave-Log: {e}")
    
    # Voice-Channel gewechselt
    elif before.channel is not None and after.channel is not None and before.channel != after.channel:
        print(f"🔄 DEBUG: {member.name} ist von {before.channel.name} zu {after.channel.name} gewechselt!")
        
        try:
            log_embed = discord.Embed(color=discord.Color.dark_red())
            
            # Setze das Benutzer-Profilbild als Autor-Bild
            if member.avatar:
                log_embed.set_author(name=member.name, icon_url=member.avatar.url)
            else:
                log_embed.set_author(name=member.name, icon_url=member.default_avatar.url)
            
            # Haupttext für Wechsel
            log_embed.add_field(
                name="",
                value=f"{member.mention} ist von `{before.channel.name}` zu `{after.channel.name}` gewechselt.",
                inline=False
            )
            

            
            # Footer mit Server-Name, Datum und Uhrzeit
            current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
            log_embed.set_footer(text=f"{member.guild.name} • {current_datetime}")
            
            await log_channel.send(embed=log_embed)
            print(f"✅ Voice-Switch-Log für {member.name} gesendet!")
            
        except Exception as e:
            print(f"❌ Fehler bei Voice-Switch-Log: {e}")

@bot.event
async def on_message_delete(message):
    """Event für gelöschte Nachrichten"""
    
    # Ignoriere Bot-Nachrichten
    if message.author.bot:
        return
    
    # Konfiguration
    message_log_channel_id = MESSAGE_LOG_CHANNEL_ID
    
    log_channel = bot.get_channel(message_log_channel_id)
    if not log_channel:
        return
    
    try:
        log_embed = discord.Embed(color=discord.Color.dark_red())
        
        # Setze das Benutzer-Profilbild als Autor-Bild
        if message.author.avatar:
            log_embed.set_author(name=message.author.name, icon_url=message.author.avatar.url)
        else:
            log_embed.set_author(name=message.author.name, icon_url=message.author.default_avatar.url)
        
        # Nachrichteninhalt (begrenzt auf 1024 Zeichen)
        content = message.content if message.content else "*Keine Textinhalte*"
        if len(content) > 1000:
            content = content[:1000] + "..."
        
        # Haupttext für Löschung
        log_embed.add_field(
            name="🗑️ Nachricht gelöscht",
            value=f"**Autor:** {message.author.mention}\n**Kanal:** {message.channel.mention}\n**Inhalt:** {content}",
            inline=False
        )
        
        # Footer mit Server-Name, Datum und Uhrzeit
        current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
        log_embed.set_footer(text=f"{message.guild.name} • {current_datetime}")
        
        await log_channel.send(embed=log_embed)
        print(f"✅ Message-Delete-Log für {message.author.name} gesendet!")
        
    except Exception as e:
        print(f"❌ Fehler bei Message-Delete-Log: {e}")

@bot.event
async def on_message_edit(before, after):
    """Event für bearbeitete Nachrichten"""
    
    # Ignoriere Bot-Nachrichten
    if before.author.bot:
        return
    
    # Ignoriere wenn Inhalt gleich ist (z.B. nur Embeds geändert)
    if before.content == after.content:
        return
    
    # Konfiguration
    message_log_channel_id = MESSAGE_LOG_CHANNEL_ID
    
    log_channel = bot.get_channel(message_log_channel_id)
    if not log_channel:
        return
    
    try:
        log_embed = discord.Embed(color=discord.Color.dark_red())
        
        # Setze das Benutzer-Profilbild als Autor-Bild
        if before.author.avatar:
            log_embed.set_author(name=before.author.name, icon_url=before.author.avatar.url)
        else:
            log_embed.set_author(name=before.author.name, icon_url=before.author.default_avatar.url)
        
        # Nachrichteninhalte (begrenzt auf 512 Zeichen pro Feld)
        old_content = before.content if before.content else "*Keine Textinhalte*"
        new_content = after.content if after.content else "*Keine Textinhalte*"
        
        if len(old_content) > 500:
            old_content = old_content[:500] + "..."
        if len(new_content) > 500:
            new_content = new_content[:500] + "..."
        
        # Haupttext für Bearbeitung
        log_embed.add_field(
            name="✏️ Nachricht bearbeitet",
            value=f"**Autor:** {before.author.mention}\n**Kanal:** {before.channel.mention}",
            inline=False
        )
        
        # Vorher - MIT Code-Block-Formatierung
        log_embed.add_field(
            name="Vorher:",
            value=f"```\n{old_content}\n```",
            inline=False
        )
        
        # Nachher - MIT Code-Block-Formatierung
        log_embed.add_field(
            name="Nachher:",
            value=f"```\n{new_content}\n```",
            inline=False
        )
        
        # Footer mit Server-Name, Datum und Uhrzeit
        current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
        log_embed.set_footer(text=f"{before.guild.name} • {current_datetime}")
        
        await log_channel.send(embed=log_embed)
        print(f"✅ Message-Edit-Log für {before.author.name} gesendet!")
        
    except Exception as e:
        print(f"❌ Fehler bei Message-Edit-Log: {e}")

@bot.event
async def on_member_update(before, after):
    """Event für Rollen-Änderungen und Mute-Status"""
    
    # Überprüfe Timeout-Änderungen (Mute-Status)
    if before.timed_out_until != after.timed_out_until:
        await handle_mute_log(before, after)
    
    # Überprüfe ob sich die Rollen geändert haben
    if before.roles == after.roles:
        return
    
    # Konfiguration
    role_log_channel_id = ROLE_LOG_CHANNEL_ID
    
    log_channel = bot.get_channel(role_log_channel_id)
    if not log_channel:
        return
    
    try:
        # Finde hinzugefügte und entfernte Rollen
        added_roles = [role for role in after.roles if role not in before.roles]
        removed_roles = [role for role in before.roles if role not in after.roles]
        
        # Ignoriere @everyone Rolle
        added_roles = [role for role in added_roles if role.name != "@everyone"]
        removed_roles = [role for role in removed_roles if role.name != "@everyone"]
        
        # Wenn keine relevanten Änderungen, beende
        if not added_roles and not removed_roles:
            return
        
        # Erstelle Embed mit der gleichen Farbe wie andere Logs
        log_embed = discord.Embed(color=discord.Color.dark_red())
        
        # Setze das Benutzer-Profilbild als Autor-Bild
        if after.avatar:
            log_embed.set_author(name=after.name, icon_url=after.avatar.url)
        else:
            log_embed.set_author(name=after.name, icon_url=after.default_avatar.url)
        
        # Hinzugefügte Rollen
        if added_roles:
            role_list = "\n".join([f"• {role.mention} • {role.name}" for role in added_roles])
            log_embed.add_field(
                name="🟢 Rolle(n) hinzugefügt",
                value=f"**{after.name}** `{after.id}`\n{after.mention}\n\n**Neue Rolle(n):**\n{role_list}",
                inline=False
            )
        
        # Entfernte Rollen
        if removed_roles:
            role_list = "\n".join([f"• {role.mention} • {role.name}" for role in removed_roles])
            log_embed.add_field(
                name="🔴 Rolle(n) entfernt",
                value=f"**{after.name}** `{after.id}`\n{after.mention}\n\n**Entfernte Rolle(n):**\n{role_list}",
                inline=False
            )
        
        # Footer mit Server-Name, Datum und Uhrzeit
        current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
        log_embed.set_footer(text=f"{after.guild.name} • {current_datetime}")
        
        await log_channel.send(embed=log_embed)
        
        # Debug-Ausgabe
        if added_roles:
            role_names = ", ".join([role.name for role in added_roles])
            print(f"✅ Role-Add-Log für {after.name}: {role_names}")
        if removed_roles:
            role_names = ", ".join([role.name for role in removed_roles])
            print(f"✅ Role-Remove-Log für {after.name}: {role_names}")
        
    except Exception as e:
        print(f"❌ Fehler bei Role-Log: {e}")

@bot.event
async def on_guild_channel_create(channel):
    """Event für erstellte Kanäle"""
    
    # Konfiguration
    channel_log_channel_id = CHANNEL_LOG_CHANNEL_ID
    
    log_channel = bot.get_channel(channel_log_channel_id)
    if not log_channel:
        return
    
    try:
        # Erstelle Embed mit der gleichen Farbe wie andere Logs
        log_embed = discord.Embed(color=discord.Color.dark_red())
        
        # Setze Server-Icon als Autor-Bild
        if channel.guild.icon:
            log_embed.set_author(name="System", icon_url=channel.guild.icon.url)
        else:
            log_embed.set_author(name="System")
        
        # Kanal-Typ bestimmen
        channel_type = "Unbekannt"
        if hasattr(channel, 'type'):
            if channel.type == discord.ChannelType.text:
                channel_type = "Text-Kanal"
            elif channel.type == discord.ChannelType.voice:
                channel_type = "Voice-Kanal"
            elif channel.type == discord.ChannelType.category:
                channel_type = "Kategorie"
            elif channel.type == discord.ChannelType.forum:
                channel_type = "Forum"
            elif channel.type == discord.ChannelType.stage_voice:
                channel_type = "Stage-Kanal"
        
        # Haupttext für Kanal-Erstellung
        log_embed.add_field(
            name="🏠 Kanal erstellt",
            value=(
                f"**Name:** {channel.name}\n"
                f"**Typ:** {channel_type}\n"
                f"**ID:** `{channel.id}`\n"
                f"**Mention:** {channel.mention if hasattr(channel, 'mention') else 'N/A'}"
            ),
            inline=False
        )
        
        # Footer mit Server-Name, Datum und Uhrzeit
        current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
        log_embed.set_footer(text=f"{channel.guild.name} • {current_datetime}")
        
        await log_channel.send(embed=log_embed)
        print(f"✅ Channel-Create-Log für {channel.name} gesendet!")
        
    except Exception as e:
        print(f"❌ Fehler bei Channel-Create-Log: {e}")

@bot.event
async def on_guild_channel_delete(channel):
    """Event für gelöschte Kanäle"""
    
    # Konfiguration
    channel_log_channel_id = CHANNEL_LOG_CHANNEL_ID
    
    log_channel = bot.get_channel(channel_log_channel_id)
    if not log_channel:
        return
    
    try:
        # Erstelle Embed mit der gleichen Farbe wie andere Logs
        log_embed = discord.Embed(color=discord.Color.dark_red())
        
        # Setze Server-Icon als Autor-Bild
        if channel.guild.icon:
            log_embed.set_author(name="System", icon_url=channel.guild.icon.url)
        else:
            log_embed.set_author(name="System")
        
        # Kanal-Typ bestimmen
        channel_type = "Unbekannt"
        if hasattr(channel, 'type'):
            if channel.type == discord.ChannelType.text:
                channel_type = "Text-Kanal"
            elif channel.type == discord.ChannelType.voice:
                channel_type = "Voice-Kanal"
            elif channel.type == discord.ChannelType.category:
                channel_type = "Kategorie"
            elif channel.type == discord.ChannelType.forum:
                channel_type = "Forum"
            elif channel.type == discord.ChannelType.stage_voice:
                channel_type = "Stage-Kanal"
        
        # Haupttext für Kanal-Löschung
        log_embed.add_field(
            name="🗑️ Kanal gelöscht",
            value=(
                f"**Name:** {channel.name}\n"
                f"**Typ:** {channel_type}\n"
                f"**ID:** `{channel.id}`"
            ),
            inline=False
        )
        
        # Footer mit Server-Name, Datum und Uhrzeit
        current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
        log_embed.set_footer(text=f"{channel.guild.name} • {current_datetime}")
        
        await log_channel.send(embed=log_embed)
        print(f"✅ Channel-Delete-Log für {channel.name} gesendet!")
        
    except Exception as e:
        print(f"❌ Fehler bei Channel-Delete-Log: {e}")

@bot.event
async def on_guild_channel_update(before, after):
    """Event für aktualisierte Kanäle"""
    
    # Konfiguration
    channel_log_channel_id = CHANNEL_LOG_CHANNEL_ID
    
    log_channel = bot.get_channel(channel_log_channel_id)
    if not log_channel:
        return
    
    try:
        # Überprüfe verschiedene Änderungen
        changes = []
        
        # Name geändert
        if before.name != after.name:
            changes.append(f"**Name:** `{before.name}` → `{after.name}`")
        
        # Topic geändert (nur für Text-Kanäle)
        if hasattr(before, 'topic') and hasattr(after, 'topic'):
            if before.topic != after.topic:
                old_topic = before.topic if before.topic else "*Kein Topic*"
                new_topic = after.topic if after.topic else "*Kein Topic*"
                changes.append(f"**Topic:** `{old_topic}` → `{new_topic}`")
        
        # Position geändert
        if before.position != after.position:
            changes.append(f"**Position:** `{before.position}` → `{after.position}`")
        
        # Kategorie geändert
        if before.category != after.category:
            old_cat = before.category.name if before.category else "*Keine Kategorie*"
            new_cat = after.category.name if after.category else "*Keine Kategorie*"
            changes.append(f"**Kategorie:** `{old_cat}` → `{new_cat}`")
        
        # Wenn keine relevanten Änderungen, beende
        if not changes:
            return
        
        # Erstelle Embed mit der gleichen Farbe wie andere Logs
        log_embed = discord.Embed(color=discord.Color.dark_red())
        
        # Setze Server-Icon als Autor-Bild
        if after.guild.icon:
            log_embed.set_author(name="System", icon_url=after.guild.icon.url)
        else:
            log_embed.set_author(name="System")
        
        # Kanal-Typ bestimmen
        channel_type = "Unbekannt"
        if hasattr(after, 'type'):
            if after.type == discord.ChannelType.text:
                channel_type = "Text-Kanal"
            elif after.type == discord.ChannelType.voice:
                channel_type = "Voice-Kanal"
            elif after.type == discord.ChannelType.category:
                channel_type = "Kategorie"
            elif after.type == discord.ChannelType.forum:
                channel_type = "Forum"
            elif after.type == discord.ChannelType.stage_voice:
                channel_type = "Stage-Kanal"
        
        # Haupttext für Kanal-Update
        changes_text = "\n".join(changes)
        log_embed.add_field(
            name="📝 Kanal aktualisiert",
            value=(
                f"**Kanal:** {after.mention} • {after.name}\n"
                f"**Typ:** {channel_type}\n"
                f"**ID:** `{after.id}`\n\n"
                f"**Änderungen:**\n{changes_text}"
            ),
            inline=False
        )
        
        # Footer mit Server-Name, Datum und Uhrzeit
        current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
        log_embed.set_footer(text=f"{after.guild.name} • {current_datetime}")
        
        await log_channel.send(embed=log_embed)
        print(f"✅ Channel-Update-Log für {after.name} gesendet!")
        
    except Exception as e:
        print(f"❌ Fehler bei Channel-Update-Log: {e}")

async def handle_mute_log(before, after):
    """Behandelt Mute-Log Events"""
    
    # Konfiguration
    mute_log_channel_id = MUTE_LOG_CHANNEL_ID
    
    log_channel = bot.get_channel(mute_log_channel_id)
    if not log_channel:
        return
    
    try:
        # Erstelle Embed mit der gleichen Farbe wie andere Logs
        log_embed = discord.Embed(color=discord.Color.dark_red())
        
        # Setze das Benutzer-Profilbild als Autor-Bild
        if after.avatar:
            log_embed.set_author(name=after.name, icon_url=after.avatar.url)
            # Setze das Profilbild auch als Thumbnail rechts
            log_embed.set_thumbnail(url=after.avatar.url)
        else:
            log_embed.set_author(name=after.name, icon_url=after.default_avatar.url)
            # Setze das Standard-Profilbild auch als Thumbnail rechts
            log_embed.set_thumbnail(url=after.default_avatar.url)
        
        # Überprüfe ob User gemuted oder entmuted wurde
        if after.timed_out_until and not before.timed_out_until:
            # User wurde gemuted
            timeout_until = after.timed_out_until.strftime('%d.%m.%Y • %H:%M')
            log_embed.add_field(
                name="🔇 Mitglied getimeoutet",
                value=f"**{after.name}** `{after.id}`\n{after.mention}\n\n**Timeout bis:**\n{timeout_until}",
                inline=False
            )
            print(f"✅ Mute-Log für {after.name}: Getimeoutet bis {timeout_until}")
            
        elif before.timed_out_until and not after.timed_out_until:
            # User wurde entmuted
            log_embed.add_field(
                name="🔊 Mitglied-Timeout entfernt",
                value=f"**{after.name}** `{after.id}`\n{after.mention}\n\n**Status:**\nTimeout wurde entfernt",
                inline=False
            )
            print(f"✅ Mute-Log für {after.name}: Timeout entfernt")
            
        elif before.timed_out_until and after.timed_out_until:
            # Timeout-Zeit wurde geändert
            old_timeout = before.timed_out_until.strftime('%d.%m.%Y • %H:%M')
            new_timeout = after.timed_out_until.strftime('%d.%m.%Y • %H:%M')
            log_embed.add_field(
                name="⏰ Timeout-Zeit geändert",
                value=f"**{after.name}** `{after.id}`\n{after.mention}\n\n**Vorher:**\n{old_timeout}\n\n**Jetzt:**\n{new_timeout}",
                inline=False
            )
            print(f"✅ Mute-Log für {after.name}: Timeout geändert von {old_timeout} zu {new_timeout}")
        
        # Footer mit Server-Name, Datum und Uhrzeit
        current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
        log_embed.set_footer(text=f"{after.guild.name} • {current_datetime}")
        
        await log_channel.send(embed=log_embed)
        
    except Exception as e:
        print(f"❌ Fehler bei Mute-Log: {e}")

async def handle_kick_log(kicked_member, moderator, reason):
    """Behandelt Kick-Log Events"""
    
    print(f"🚀 handle_kick_log aufgerufen für {kicked_member.name}")
    
    # Konfiguration
    kick_log_channel_id = KICK_LOG_CHANNEL_ID
    print(f"📋 Kick Log Channel ID: {kick_log_channel_id}")
    
    log_channel = bot.get_channel(kick_log_channel_id)
    if not log_channel:
        print(f"❌ Kick-Log-Channel nicht gefunden! ID: {kick_log_channel_id}")
        return
    else:
        print(f"✅ Kick-Log-Channel gefunden: {log_channel.name}")
    
    try:
        # Erstelle Embed mit der gleichen Farbe wie andere Logs
        log_embed = discord.Embed(color=discord.Color.dark_red())
        
        # Setze das Profilbild des gekickten Benutzers als Autor-Bild
        if kicked_member.avatar:
            log_embed.set_author(name=kicked_member.name, icon_url=kicked_member.avatar.url)
            log_embed.set_thumbnail(url=kicked_member.avatar.url)
        else:
            log_embed.set_author(name=kicked_member.name, icon_url=kicked_member.default_avatar.url)
            log_embed.set_thumbnail(url=kicked_member.default_avatar.url)
        
        # Kick-Information
        kick_reason = reason if reason else "Kein Grund angegeben"
        log_embed.add_field(
            name="👋 Mitglied gekickt",
            value=f"**{kicked_member.name}** `{kicked_member.id}`\n{kicked_member.mention}\n\n**Verantwortlicher Moderator:**\n{moderator.mention}\n\n**Grund:**\n{kick_reason}",
            inline=False
        )
        
        # Footer mit Server-Name, Datum und Uhrzeit
        current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
        log_embed.set_footer(text=f"{kicked_member.guild.name} • {current_datetime}")
        
        await log_channel.send(embed=log_embed)
        print(f"✅ Kick-Log für {kicked_member.name} gesendet! Gekickt von {moderator.name}")
        
    except Exception as e:
        print(f"❌ Fehler bei Kick-Log: {e}")
        import traceback
        traceback.print_exc()

@bot.event
async def on_member_ban(guild, user):
    """Event für Ban-Logs"""
    print(f"🔨 DEBUG: {user.name} ({user.id}) wurde vom Server {guild.name} gebannt!")
    
    # Warte kurz, damit Audit-Log-Entry erstellt wird
    await asyncio.sleep(1)
    
    # Überprüfe Audit-Logs für Ban-Events
    try:
        print(f"🔍 Überprüfe Audit-Logs für Ban-Events...")
        
        # Überprüfe Bot-Berechtigungen
        if not guild.me.guild_permissions.view_audit_log:
            print(f"❌ Bot hat keine 'View Audit Log' Berechtigung!")
            return
        else:
            print(f"✅ Bot hat Audit-Log Berechtigung")
            
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            print(f"📋 Ban Audit-Log Entry gefunden: {entry.target.name if entry.target else 'Unknown'} von {entry.user.name if entry.user else 'Unknown'}")
            
            # Überprüfe ob der Ban in den letzten 10 Sekunden stattgefunden hat
            if (datetime.now(timezone.utc) - entry.created_at).total_seconds() < 10:
                if entry.target and entry.target.id == user.id:
                    print(f"✅ Ban-Event erkannt für {user.name}!")
                    # Es war ein Ban - sende Ban-Log
                    await handle_ban_log(user, entry.user, entry.reason, guild)
                    return
                    
        print(f"ℹ️ Kein Ban-Event gefunden")
                    
    except Exception as e:
        print(f"❌ Fehler beim Überprüfen der Ban Audit-Logs: {e}")
        import traceback
        traceback.print_exc()

@bot.event
async def on_member_unban(guild, user):
    """Event für Unban-Logs"""
    print(f"🔓 DEBUG: {user.name} ({user.id}) wurde vom Server {guild.name} entbannt!")
    
    # Warte kurz, damit Audit-Log-Entry erstellt wird
    await asyncio.sleep(1)
    
    # Überprüfe Audit-Logs für Unban-Events
    try:
        print(f"🔍 Überprüfe Audit-Logs für Unban-Events...")
        
        # Überprüfe Bot-Berechtigungen
        if not guild.me.guild_permissions.view_audit_log:
            print(f"❌ Bot hat keine 'View Audit Log' Berechtigung!")
            return
        else:
            print(f"✅ Bot hat Audit-Log Berechtigung")
            
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
            print(f"📋 Unban Audit-Log Entry gefunden: {entry.target.name if entry.target else 'Unknown'} von {entry.user.name if entry.user else 'Unknown'}")
            
            # Überprüfe ob der Unban in den letzten 10 Sekunden stattgefunden hat
            if (datetime.now(timezone.utc) - entry.created_at).total_seconds() < 10:
                if entry.target and entry.target.id == user.id:
                    print(f"✅ Unban-Event erkannt für {user.name}!")
                    # Es war ein Unban - sende Unban-Log
                    await handle_unban_log(user, entry.user, entry.reason, guild)
                    return
                    
        print(f"ℹ️ Kein Unban-Event gefunden")
                    
    except Exception as e:
        print(f"❌ Fehler beim Überprüfen der Unban Audit-Logs: {e}")
        import traceback
        traceback.print_exc()

@bot.event
async def handle_ban_log(banned_user, moderator, reason, guild):
    """Behandelt Ban-Log Events"""
    
    print(f"🔨 handle_ban_log aufgerufen für {banned_user.name}")
    
    # Konfiguration
    ban_log_channel_id = BAN_LOG_CHANNEL_ID
    print(f"📋 Ban Log Channel ID: {ban_log_channel_id}")
    
    log_channel = bot.get_channel(ban_log_channel_id)
    if not log_channel:
        print(f"❌ Ban-Log-Channel nicht gefunden! ID: {ban_log_channel_id}")
        return
    else:
        print(f"✅ Ban-Log-Channel gefunden: {log_channel.name}")
    
    try:
        # Erstelle Embed mit der gleichen Farbe wie andere Logs
        log_embed = discord.Embed(color=discord.Color.dark_red())
        
        # Setze das Profilbild des gebannten Benutzers als Autor-Bild
        if banned_user.avatar:
            log_embed.set_author(name=banned_user.name, icon_url=banned_user.avatar.url)
            log_embed.set_thumbnail(url=banned_user.avatar.url)
        else:
            log_embed.set_author(name=banned_user.name, icon_url=banned_user.default_avatar.url)
            log_embed.set_thumbnail(url=banned_user.default_avatar.url)
        
        # Ban-Information
        ban_reason = reason if reason else "Kein Grund angegeben"
        log_embed.add_field(
            name="🔨 Mitglied gebannt",
            value=f"**{banned_user.name}** `{banned_user.id}`\n{banned_user.mention}\n\n**Verantwortlicher Moderator:**\n{moderator.mention}\n\n**Grund:**\n{ban_reason}",
            inline=False
        )
        
        # Footer mit Server-Name, Datum und Uhrzeit
        current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
        log_embed.set_footer(text=f"{guild.name} • {current_datetime}")
        
        await log_channel.send(embed=log_embed)
        print(f"✅ Ban-Log für {banned_user.name} gesendet! Gebannt von {moderator.name}")
        
    except Exception as e:
        print(f"❌ Fehler bei Ban-Log: {e}")
        import traceback
        traceback.print_exc()

@bot.event
async def handle_unban_log(unbanned_user, moderator, reason, guild):
    """Behandelt Unban-Log Events"""
    
    print(f"🔓 handle_unban_log aufgerufen für {unbanned_user.name}")
    
    # Konfiguration
    ban_log_channel_id = BAN_LOG_CHANNEL_ID
    
    log_channel = bot.get_channel(ban_log_channel_id)
    if not log_channel:
        print(f"❌ Ban-Log-Channel nicht gefunden! ID: {ban_log_channel_id}")
        return
    
    try:
        # Erstelle Embed mit der gleichen Farbe wie andere Logs
        log_embed = discord.Embed(color=discord.Color.dark_red())
        
        # Setze das Profilbild des entbannten Benutzers als Autor-Bild
        if unbanned_user.avatar:
            log_embed.set_author(name=unbanned_user.name, icon_url=unbanned_user.avatar.url)
            log_embed.set_thumbnail(url=unbanned_user.avatar.url)
        else:
            log_embed.set_author(name=unbanned_user.name, icon_url=unbanned_user.default_avatar.url)
            log_embed.set_thumbnail(url=unbanned_user.default_avatar.url)
        
        # Unban-Information
        unban_reason = reason if reason else "Kein Grund angegeben"
        log_embed.add_field(
            name="🔓 Mitglied entbannt",
            value=f"**{unbanned_user.name}** `{unbanned_user.id}`\n{unbanned_user.mention}\n\n**Verantwortlicher Moderator:**\n{moderator.mention}\n\n**Grund:**\n{unban_reason}",
            inline=False
        )
        
        # Footer mit Server-Name, Datum und Uhrzeit
        current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
        log_embed.set_footer(text=f"{guild.name} • {current_datetime}")
        
        await log_channel.send(embed=log_embed)
        print(f"✅ Unban-Log für {unbanned_user.name} gesendet! Entbannt von {moderator.name}")
        
    except Exception as e:
        print(f"❌ Fehler bei Unban-Log: {e}")
        import traceback
        traceback.print_exc()

@bot.event
async def on_invite_create(invite):
    """Event für Invite-Erstellung-Logs"""
    
    print(f"📨 Invite erstellt: {invite.code}")
    
    # Konfiguration
    invite_log_channel_id = INVITE_LOG_CHANNEL_ID
    
    log_channel = bot.get_channel(invite_log_channel_id)
    if not log_channel:
        print(f"❌ Invite-Log-Channel nicht gefunden! ID: {invite_log_channel_id}")
        return
    
    try:
        # Erstelle Embed
        log_embed = discord.Embed(color=0x6e0000)
        
        # Setze das Profilbild des Erstellers als Autor-Bild
        if invite.inviter:
            if invite.inviter.avatar:
                log_embed.set_author(name=invite.inviter.name, icon_url=invite.inviter.avatar.url)
                log_embed.set_thumbnail(url=invite.inviter.avatar.url)
            else:
                log_embed.set_author(name=invite.inviter.name, icon_url=invite.inviter.default_avatar.url)
                log_embed.set_thumbnail(url=invite.inviter.default_avatar.url)
        
        # Invite-Information
        invite_info = f"**Code:** `{invite.code}`\n"
        invite_info += f"**URL:** {invite.url}\n"
        invite_info += f"**Channel:** {invite.channel.mention}\n"
        
        if invite.inviter:
            invite_info += f"**Erstellt von:** {invite.inviter.mention}\n"
        
        if invite.max_uses:
            invite_info += f"**Max. Verwendungen:** {invite.max_uses}\n"
        else:
            invite_info += f"**Max. Verwendungen:** Unbegrenzt\n"
        
        if invite.max_age:
            invite_info += f"**Gültigkeitsdauer:** {invite.max_age} Sekunden\n"
        else:
            invite_info += f"**Gültigkeitsdauer:** Permanent\n"
        
        invite_info += f"**Temporäre Mitgliedschaft:** {'Ja' if invite.temporary else 'Nein'}"
        
        log_embed.add_field(
            name="📨 Invite erstellt",
            value=invite_info,
            inline=False
        )
        
        # Footer mit Server-Name, Datum und Uhrzeit
        current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
        log_embed.set_footer(text=f"{invite.guild.name} • {current_datetime}")
        
        await log_channel.send(embed=log_embed)
        print(f"✅ Invite-Erstellung-Log für {invite.code} gesendet!")
        
    except Exception as e:
        print(f"❌ Fehler bei Invite-Erstellung-Log: {e}")
        import traceback
        traceback.print_exc()

@bot.event
async def on_invite_delete(invite):
    """Event für Invite-Löschung-Logs"""
    
    print(f"🗑️ Invite gelöscht: {invite.code}")
    
    # Konfiguration
    invite_log_channel_id = INVITE_LOG_CHANNEL_ID
    
    log_channel = bot.get_channel(invite_log_channel_id)
    if not log_channel:
        print(f"❌ Invite-Log-Channel nicht gefunden! ID: {invite_log_channel_id}")
        return
    
    try:
        # Erstelle Embed
        log_embed = discord.Embed(color=0x6e0000)
        
        # Setze das Profilbild des ursprünglichen Erstellers als Autor-Bild (falls verfügbar)
        if invite.inviter:
            if invite.inviter.avatar:
                log_embed.set_author(name=invite.inviter.name, icon_url=invite.inviter.avatar.url)
                log_embed.set_thumbnail(url=invite.inviter.avatar.url)
            else:
                log_embed.set_author(name=invite.inviter.name, icon_url=invite.inviter.default_avatar.url)
                log_embed.set_thumbnail(url=invite.inviter.default_avatar.url)
        
        # Invite-Information
        invite_info = f"**Code:** `{invite.code}`\n"
        invite_info += f"**URL:** {invite.url}\n"
        invite_info += f"**Channel:** {invite.channel.mention}\n"
        
        if invite.inviter:
            invite_info += f"**Ursprünglich erstellt von:** {invite.inviter.mention}\n"
        
        if hasattr(invite, 'uses') and invite.uses is not None:
            invite_info += f"**Verwendungen:** {invite.uses}"
            if invite.max_uses:
                invite_info += f"/{invite.max_uses}"
            invite_info += "\n"
        
        log_embed.add_field(
            name="🗑️ Invite gelöscht",
            value=invite_info,
            inline=False
        )
        
        # Footer mit Server-Name, Datum und Uhrzeit
        current_datetime = datetime.now().strftime('%d.%m.%Y • %H:%M')
        log_embed.set_footer(text=f"{invite.guild.name} • {current_datetime}")
        
        await log_channel.send(embed=log_embed)
        print(f"✅ Invite-Löschung-Log für {invite.code} gesendet!")
        
    except Exception as e:
        print(f"❌ Fehler bei Invite-Löschung-Log: {e}")
        import traceback
        traceback.print_exc()

# Admin-Befehle für Ticket-Kategorie-Verwaltung
@bot.command(name='set_ticket_category')
@commands.has_permissions(administrator=True)
async def set_ticket_category(ctx, category_id: int):
    """Setzt die Kategorie für neue Tickets (nur für Administratoren)"""
    guild = ctx.guild
    
    # Prüfe, ob die Kategorie existiert
    category = discord.utils.get(guild.categories, id=category_id)
    if not category:
        embed = discord.Embed(
            title="❌ Kategorie nicht gefunden",
            description=f"Eine Kategorie mit der ID `{category_id}` existiert nicht auf diesem Server.",
            color=0x6e0000  # Dunkelrot
        )
        await ctx.send(embed=embed)
        return
    
    # Aktualisiere die Kategorie
    update_ticket_category(category_id)
    
    embed = discord.Embed(
        title="✅ Ticket-Kategorie aktualisiert",
        description=f"Neue Tickets werden jetzt in der Kategorie **{category.name}** erstellt.\n\n**Kategorie-ID:** `{category_id}`",
        color=0x6e0000  # Dunkelrot
    )
    await ctx.send(embed=embed)

@bot.command(name='get_ticket_category')
@commands.has_permissions(administrator=True)
async def get_ticket_category(ctx):
    """Zeigt die aktuelle Ticket-Kategorie an (nur für Administratoren)"""
    guild = ctx.guild
    current_id = get_current_ticket_category()
    category = discord.utils.get(guild.categories, id=current_id)
    
    if category:
        embed = discord.Embed(
            title="📁 Aktuelle Ticket-Kategorie",
            description=f"**Name:** {category.name}\n**ID:** `{current_id}`\n**Position:** {category.position + 1}",
            color=0x6e0000  # Dunkelrot
        )
    else:
        embed = discord.Embed(
            title="⚠️ Kategorie-Problem",
            description=f"Die konfigurierte Kategorie-ID `{current_id}` existiert nicht mehr.\n\n💡 Verwende `!set_ticket_category <neue_id>` um eine gültige Kategorie zu setzen.",
            color=0x6e0000  # Dunkelrot
        )
    
    await ctx.send(embed=embed)

@bot.command(name='list_categories')
@commands.has_permissions(administrator=True)
async def list_categories(ctx):
    """Listet alle verfügbaren Kategorien auf (nur für Administratoren)"""
    guild = ctx.guild
    categories = guild.categories
    
    if not categories:
        embed = discord.Embed(
            title="📁 Keine Kategorien gefunden",
            description="Auf diesem Server gibt es keine Kategorien.",
            color=0x6e0000  # Dunkelrot
        )
        await ctx.send(embed=embed)
        return
    
    embed = discord.Embed(
        title="📁 Verfügbare Kategorien",
        description="Hier sind alle Kategorien auf diesem Server:",
        color=0x6e0000  # Dunkelrot
    )
    
    current_id = get_current_ticket_category()
    
    for i, category in enumerate(categories, 1):
        status = "🎫 **AKTUELLE TICKET-KATEGORIE**" if category.id == current_id else ""
        embed.add_field(
            name=f"{i}. {category.name} {status}",
            value=f"**ID:** `{category.id}`\n**Channels:** {len(category.channels)}",
            inline=True
        )
    
    embed.set_footer(text="Verwende !set_ticket_category <kategorie_id> um die Ticket-Kategorie zu ändern.")
    await ctx.send(embed=embed)

@bot.command(name='set_closed_category')
@commands.has_permissions(administrator=True)
async def set_closed_category(ctx, category_id: int):
    """Setzt die Kategorie für geschlossene Tickets"""
    guild = ctx.guild
    category = discord.utils.get(guild.categories, id=category_id)
    
    if not category:
        embed = discord.Embed(
            title="❌ Kategorie nicht gefunden",
            description=f"Eine Kategorie mit der ID `{category_id}` existiert nicht.",
            color=0x6e0000
        )
        await ctx.send(embed=embed)
        return
    
    global TICKET_CLOSED_CATEGORY_ID, config
    TICKET_CLOSED_CATEGORY_ID = category_id
    config['TICKET_CLOSED_CATEGORY_ID'] = category_id
    save_config(config)
    
    embed = discord.Embed(
        title="✅ Geschlossene-Tickets-Kategorie gesetzt",
        description=f"Geschlossene Tickets werden jetzt in **{category.name}** verschoben.\n\n**Kategorie-ID:** `{category_id}`\n**✅ Konfiguration gespeichert!**",
        color=0x6e0000
    )
    await ctx.send(embed=embed)

@bot.command(name='set_reopened_category')
@commands.has_permissions(administrator=True)
async def set_reopened_category(ctx, category_id: int):
    """Setzt die Kategorie für wiedereröffnete Tickets"""
    guild = ctx.guild
    category = discord.utils.get(guild.categories, id=category_id)
    
    if not category:
        embed = discord.Embed(
            title="❌ Kategorie nicht gefunden",
            description=f"Eine Kategorie mit der ID `{category_id}` existiert nicht.",
            color=0x6e0000
        )
        await ctx.send(embed=embed)
        return
    
    global TICKET_REOPENED_CATEGORY_ID, config
    TICKET_REOPENED_CATEGORY_ID = category_id
    config['TICKET_REOPENED_CATEGORY_ID'] = category_id
    save_config(config)
    
    embed = discord.Embed(
        title="✅ Wiedereröffnete-Tickets-Kategorie gesetzt",
        description=f"Wiedereröffnete Tickets werden jetzt in **{category.name}** verschoben.\n\n**Kategorie-ID:** `{category_id}`\n**✅ Konfiguration gespeichert!**",
        color=0x6e0000
    )
    await ctx.send(embed=embed)

@bot.command(name='set_ekip_role')
@commands.has_permissions(administrator=True)
async def set_ekip_role(ctx, role_id: int):
    """Setzt die EKIP Devs Team Rolle"""
    guild = ctx.guild
    role = guild.get_role(role_id)
    
    if not role:
        embed = discord.Embed(
            title="❌ Rolle nicht gefunden",
            description=f"Eine Rolle mit der ID `{role_id}` existiert nicht.",
            color=0x6e0000
        )
        await ctx.send(embed=embed)
        return
    
    global EKIP_DEVS_ROLE_ID, config
    EKIP_DEVS_ROLE_ID = role_id
    config['EKIP_DEVS_ROLE_ID'] = role_id
    save_config(config)
    
    embed = discord.Embed(
        title="✅ EKIP Devs Team Rolle gesetzt",
        description=f"Die EKIP Devs Team Rolle wurde auf **{role.name}** gesetzt.\n\n**Rollen-ID:** `{role_id}`\n**✅ Konfiguration gespeichert!**",
        color=0x6e0000
    )
    await ctx.send(embed=embed)

@bot.command(name='ticket_help')
@commands.has_permissions(administrator=True)
async def ticket_help(ctx):
    """Zeigt alle Ticket-System Befehle an (nur für Administratoren)"""
    embed = discord.Embed(
        title="🎫 Ticket-System Befehle",
        description="Hier sind alle verfügbaren Admin-Befehle für das Ticket-System:",
        color=0x6e0000  # Dunkelrot
    )
    
    embed.add_field(
        name="📋 Panel & Verwaltung",
        value="`!ticket_panel` - Sendet das Ticket-Panel\n`!close_ticket` - Schließt ein Ticket (in Ticket-Channels)",
        inline=False
    )
    
    embed.add_field(
        name="📁 Kategorie-Verwaltung",
        value="`!set_ticket_category <id>` - Setzt die Ticket-Kategorie\n`!get_ticket_category` - Zeigt aktuelle Kategorie\n`!list_categories` - Listet alle Kategorien auf\n`!set_closed_category <id>` - Setzt Kategorie für geschlossene Tickets\n`!set_reopened_category <id>` - Setzt Kategorie für wiedereröffnete Tickets",
        inline=False
    )
    
    embed.add_field(
        name="👥 Rollen-Verwaltung",
        value="`!set_ekip_role <id>` - Setzt die EKIP Devs Team Rolle",
        inline=False
    )
    
    embed.add_field(
        name="💡 Beispiele",
        value="`!set_ticket_category 1234567890123456789`\n`!list_categories`\n`!get_ticket_category`\n`!set_ekip_role 1234567890123456789`",
        inline=False
    )
    
    embed.set_footer(text="Alle Befehle erfordern Administrator-Rechte.")
    await ctx.send(embed=embed)

# Fehlerbehandlung für Admin-Befehle
@set_ticket_category.error
@get_ticket_category.error
@list_categories.error
@set_closed_category.error
@set_reopened_category.error
@set_ekip_role.error
@ticket_help.error
async def admin_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Keine Berechtigung",
            description="Du benötigst Administrator-Rechte, um diesen Befehl zu verwenden.",
            color=0x6e0000
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Fehler",
            description=f"Ein unerwarteter Fehler ist aufgetreten: {error}",
            color=0x6e0000
        )
        await ctx.send(embed=embed)

# === KI-SYSTEM KONFIGURATION ===

# Benutzeraktivitäts-Tracking
user_activity = defaultdict(lambda: deque(maxlen=20))  # Letzte 20 Nachrichten pro User
user_warnings = defaultdict(int)  # Warnungen pro User
user_spam_score = defaultdict(float)  # Spam-Score pro User

# Spam-Erkennungsmuster
spam_patterns = [
    r'(.)\1{4,}',  # Wiederholte Zeichen (aaaaa)
    r'[A-Z]{5,}',  # Viele Großbuchstaben
    r'discord\.gg/\w+',  # Discord-Invites
    r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',  # URLs
    r'@everyone|@here',  # Massenerwähnungen
    r'(.)\1{2,}',  # Wiederholte Zeichen (aaa)
]

# Häufige Hilfeanfragen-Keywords
help_keywords = {
    'ticket': ['ticket', 'support', 'hilfe', 'help', 'problem'],
    'ban': ['ban', 'banned', 'gesperrt', 'sperrung'],
    'role': ['rolle', 'role', 'berechtigung', 'permission'],
    'channel': ['channel', 'kanal', 'zugang', 'access'],
    'bot': ['bot', 'befehl', 'command', 'funktioniert nicht']
}

# Automatische Antworten
auto_responses = {
    'ticket': {
        'title': '🎫 Ticket-Hilfe',
        'description': 'Um ein Ticket zu erstellen, verwende das Ticket-Panel oder den Befehl `!ticket_panel`.\n\n**Verfügbare Ticket-Typen:**\n• 💰 Kauf-Ticket\n• 🛠️ Support-Ticket\n• 🐛 Bug-Report',
        'color': 0x6e0000
    },
    'ban': {
        'title': '🔨 Ban-Informationen',
        'description': 'Falls du Fragen zu einem Ban hast, erstelle bitte ein Support-Ticket. Unsere Moderatoren werden dir helfen.',
        'color': 0x6e0000
    },
    'role': {
        'title': '👥 Rollen-Hilfe',
        'description': 'Rollen werden automatisch vergeben oder können von Moderatoren zugewiesen werden. Bei Fragen erstelle ein Support-Ticket.',
        'color': 0x6e0000
    }
}

# KI-Konfiguration
AI_CONFIG = {
    'spam_threshold': 0.7,  # Spam-Schwellenwert
    'message_rate_limit': 10,  # Max. Nachrichten pro Minute
    'warning_threshold': 3,  # Warnungen vor automatischer Aktion
    'auto_help_enabled': True,  # Automatische Hilfe aktiviert
    'learning_enabled': True,  # Lernfunktion aktiviert
    'openai_enabled': bool(OPENAI_API_KEY),  # OpenAI aktiviert
    'smart_responses_enabled': True,  # Intelligente Antworten
    'context_analysis_enabled': True,  # Kontext-Analyse
    'auto_moderation_enabled': True  # Automatische Moderation
}

# === KI-FUNKTIONEN ===

def cleanup_old_data():
    """Bereinigt alte Benutzerdaten (DSGVO-Konformität)"""
    current_time = time.time()
    retention_period = 30 * 24 * 60 * 60  # 30 Tage
    
    for user_id in list(user_activity.keys()):
        user_messages = user_activity[user_id]
        # Entferne Nachrichten älter als 30 Tage
        user_activity[user_id] = [
            msg for msg in user_messages 
            if current_time - msg['timestamp'] < retention_period
        ]
        
        # Entferne Benutzer ohne aktuelle Daten
        if not user_activity[user_id]:
            del user_activity[user_id]
            if user_id in user_warnings:
                del user_warnings[user_id]
            if user_id in user_spam_score:
                del user_spam_score[user_id]

# Führe Bereinigung alle 24 Stunden aus
@tasks.loop(hours=24)
async def daily_cleanup():
    """Tägliche Datenbereinigung"""
    cleanup_old_data()
    print("✅ Tägliche Datenbereinigung abgeschlossen")

async def analyze_message_with_ai(message_content, context="general"):
    """Analysiert eine Nachricht mit OpenAI GPT für erweiterte Insights"""
    if not AI_CONFIG['openai_enabled']:
        return None
    
    try:
        response = await asyncio.to_thread(
            openai.ChatCompletion.create,
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": f"Du bist ein Discord-Server-Moderations-Assistent. Analysiere die folgende Nachricht im Kontext '{context}' und bewerte sie auf: 1) Toxizität (0-1), 2) Spam-Wahrscheinlichkeit (0-1), 3) Hilfsbedürftigkeit (0-1), 4) Sentiment (positiv/neutral/negativ). Antworte nur mit einem JSON-Objekt."
                },
                {
                    "role": "user",
                    "content": message_content
                }
            ],
            max_tokens=150,
            temperature=0.3
        )
        
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"OpenAI-Analyse Fehler: {e}")
        return None

async def generate_smart_response(message_content, context="help"):
    """Generiert eine intelligente Antwort mit OpenAI"""
    if not AI_CONFIG['openai_enabled'] or not AI_CONFIG['smart_responses_enabled']:
        return None
    
    try:
        response = await asyncio.to_thread(
            openai.ChatCompletion.create,
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "Du bist ein hilfsreicher Discord-Bot-Assistent. Antworte kurz, freundlich und hilfreich auf Deutsch. Halte Antworten unter 200 Zeichen."
                },
                {
                    "role": "user",
                    "content": message_content
                }
            ],
            max_tokens=100,
            temperature=0.7
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Smart Response Fehler: {e}")
        return None

async def analyze_server_context(channel, limit=50):
    """Analysiert den Kontext der letzten Nachrichten im Kanal"""
    if not AI_CONFIG['context_analysis_enabled']:
        return "general"
    
    try:
        messages = []
        async for msg in channel.history(limit=limit):
            if msg.content and not msg.author.bot:
                messages.append(msg.content)
        
        if not messages:
            return "general"
        
        combined_text = " ".join(messages[-10:])  # Letzte 10 Nachrichten
        
        response = await asyncio.to_thread(
            openai.ChatCompletion.create,
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "Analysiere den Kontext dieser Discord-Kanal-Nachrichten und kategorisiere ihn in einem Wort: 'support', 'gaming', 'general', 'technical', 'social', oder 'moderation'."
                },
                {
                    "role": "user",
                    "content": combined_text[:500]  # Begrenzen auf 500 Zeichen
                }
            ],
            max_tokens=10,
            temperature=0.1
        )
        
        return response.choices[0].message.content.strip().lower()
    except Exception as e:
        print(f"Kontext-Analyse Fehler: {e}")
        return "general"

def calculate_spam_score(message):
    """Berechnet den Spam-Score einer Nachricht"""
    score = 0.0
    content = message.content.lower()
    
    # Pattern-basierte Erkennung
    for pattern in spam_patterns:
        matches = len(re.findall(pattern, content, re.IGNORECASE))
        if matches > 0:
            score += min(matches * 0.2, 0.5)  # Max 0.5 pro Pattern
    
    # Nachrichtenlänge bewerten
    if len(content) > 500:
        score += 0.2
    elif len(content) < 3:
        score += 0.1
    
    # Wiederholte Nachrichten
    user_messages = user_activity[message.author.id]
    if len(user_messages) >= 2:
        recent_content = [msg['content'] for msg in list(user_messages)[-3:]]
        if content in recent_content:
            score += 0.3
    
    # Caps-Lock Anteil
    if len(content) > 10:
        caps_ratio = sum(1 for c in content if c.isupper()) / len(content)
        if caps_ratio > 0.7:
            score += 0.3
    
    return min(score, 1.0)

def calculate_message_rate(user_id):
    """Berechnet die Nachrichtenrate eines Benutzers mit verbesserter Logik"""
    if user_id not in user_activity:
        return 0
    
    user_messages = user_activity[user_id]
    if len(user_messages) < 2:
        return 0
    
    now = time.time()
    # Berücksichtige verschiedene Zeitfenster
    recent_messages_1min = [msg for msg in user_messages if now - msg['timestamp'] < 60]
    recent_messages_5min = [msg for msg in user_messages if now - msg['timestamp'] < 300]
    
    # Gewichtete Rate-Berechnung
    rate_1min = len(recent_messages_1min)
    rate_5min = len(recent_messages_5min) / 5
    
    return max(rate_1min, rate_5min)

def track_user_activity(user, message):
    """Verfolgt Benutzeraktivität für KI-Analyse"""
    user_activity[user.id].append({
        'timestamp': time.time(),
        'content': message.content.lower(),
        'channel': message.channel.id,
        'length': len(message.content),
        'mentions': len(message.mentions),
        'attachments': len(message.attachments)
    })

async def detect_help_request(message):
    """Erkennt Hilfeanfragen basierend auf Keywords"""
    content = message.content.lower()
    
    for category, keywords in help_keywords.items():
        if any(keyword in content for keyword in keywords):
            return category
    
    # Fragezeichen-basierte Erkennung
    if '?' in content and any(word in content for word in ['wie', 'was', 'wo', 'wann', 'warum', 'how', 'what', 'where', 'when', 'why']):
        return 'general'
    
    return None

async def provide_automated_help(message, help_type):
    """Bietet automatische Hilfe basierend auf erkanntem Typ"""
    if help_type in auto_responses:
        response = auto_responses[help_type]
        embed = discord.Embed(
            title=response['title'],
            description=response['description'],
            color=response['color']
        )
        embed.set_footer(text="🤖 Automatische Hilfe • Für weitere Unterstützung erstelle ein Ticket")
        await message.channel.send(embed=embed)
        return True
    return False

async def handle_potential_spam(message, spam_score):
    """Behandelt potentielle Spam-Nachrichten"""
    user_id = message.author.id
    user_warnings[user_id] += 1
    user_spam_score[user_id] = max(user_spam_score[user_id], spam_score)
    
    # Lösche die Nachricht
    try:
        await message.delete()
    except:
        pass
    
    # Warnung an den Benutzer
    if user_warnings[user_id] <= AI_CONFIG['warning_threshold']:
        warning_embed = discord.Embed(
            title="⚠️ Automatische Moderation",
            description=f"Deine Nachricht wurde als potentieller Spam erkannt und entfernt.\n\n**Warnung {user_warnings[user_id]}/{AI_CONFIG['warning_threshold']}**\n\nBitte achte auf die Serverregeln.",
            color=0x6e0000
        )
        try:
            await message.author.send(embed=warning_embed)
        except:
            pass
    
    # Log für Moderatoren
    mod_channel = bot.get_channel(MESSAGE_LOG_CHANNEL_ID)
    if mod_channel:
        log_embed = discord.Embed(
            title="🤖 KI-Spam-Erkennung",
            description=f"**Benutzer:** {message.author.mention} ({message.author.id})\n**Kanal:** {message.channel.mention}\n**Spam-Score:** {spam_score:.2f}\n**Warnungen:** {user_warnings[user_id]}",
            color=0x6e0000
        )
        log_embed.add_field(name="Nachricht", value=message.content[:500] if message.content else "[Keine Textnachricht]", inline=False)
        log_embed.set_footer(text=f"User-ID: {user_id}")
        await mod_channel.send(embed=log_embed)

async def handle_rate_limit(message, rate):
    """Behandelt Nachrichten-Rate-Limiting"""
    user_id = message.author.id
    
    # Temporäre Stummschaltung (falls Bot entsprechende Berechtigung hat)
    try:
        timeout_duration = timedelta(minutes=5)
        await message.author.timeout(timeout_duration, reason="Automatische Moderation: Zu viele Nachrichten")
        
        # Benachrichtigung
        timeout_embed = discord.Embed(
            title="⏰ Automatische Moderation",
            description=f"Du wurdest für 5 Minuten stummgeschaltet, da du zu viele Nachrichten gesendet hast.\n\n**Nachrichten pro Minute:** {rate}",
            color=0x6e0000
        )
        await message.author.send(embed=timeout_embed)
        
    except:
        # Falls Timeout nicht möglich, nur warnen
        rate_embed = discord.Embed(
            title="⚠️ Automatische Moderation",
            description=f"Du sendest zu viele Nachrichten. Bitte verlangsame dich.\n\n**Nachrichten pro Minute:** {rate}",
            color=0x6e0000
        )
        await message.channel.send(embed=rate_embed, delete_after=10)
    
    # Log für Moderatoren
    mod_channel = bot.get_channel(MESSAGE_LOG_CHANNEL_ID)
    if mod_channel:
        log_embed = discord.Embed(
            title="🤖 KI-Rate-Limiting",
            description=f"**Benutzer:** {message.author.mention}\n**Nachrichten/Min:** {rate}\n**Aktion:** Timeout (5 Min)",
            color=0x6e0000
        )
        await mod_channel.send(embed=log_embed)





# Erweiterte KI-Event-Handler
@bot.event
async def on_message(message):
    """Erweiterte Nachrichtenbehandlung mit KI-Features"""
    # Ignoriere Bot-Nachrichten
    if message.author.bot:
        await bot.process_commands(message)
        return
    
    # Ignoriere DMs
    if isinstance(message.channel, discord.DMChannel):
        await bot.process_commands(message)
        return
    
    try:
        # === KI-VERARBEITUNG ===
        if AI_CONFIG['learning_enabled']:
            # Verfolge Benutzeraktivität
            track_user_activity(message.author, message)
            
            # Erweiterte KI-Analyse mit OpenAI
            if AI_CONFIG['openai_enabled']:
                context = await analyze_server_context(message.channel)
                ai_analysis = await analyze_message_with_ai(message.content, context)
                
                if ai_analysis:
                    # Erweiterte Spam-Erkennung
                    if ai_analysis.get('spam_probability', 0) > AI_CONFIG['spam_threshold']:
                        await handle_potential_spam(message, ai_analysis['spam_probability'])
                        return
                    
                    # Toxizitäts-Erkennung
                    if ai_analysis.get('toxicity', 0) > 0.8 and AI_CONFIG['auto_moderation_enabled']:
                        await message.delete()
                        embed = discord.Embed(
                            title="🚫 Nachricht entfernt",
                            description="Deine Nachricht wurde aufgrund toxischen Inhalts entfernt.",
                            color=0xff0000
                        )
                        try:
                            await message.author.send(embed=embed)
                        except:
                            pass
                        return
                    
                    # Intelligente Hilfe
                    if ai_analysis.get('help_needed', 0) > 0.7 and AI_CONFIG['smart_responses_enabled']:
                        smart_response = await generate_smart_response(message.content, context)
                        if smart_response:
                            embed = discord.Embed(
                                title="🤖 KI-Assistent",
                                description=smart_response,
                                color=0x00ff00
                            )
                            embed.set_footer(text="Generiert von KI • Für weitere Hilfe wende dich an das Team")
                            await message.channel.send(embed=embed)
            
            # Bestehende Spam-Erkennung als Fallback
            spam_score = calculate_spam_score(message)
            if spam_score >= AI_CONFIG['spam_threshold']:
                await handle_potential_spam(message, spam_score)
                return  # Stoppe weitere Verarbeitung
            
            # Rate-Limiting
            message_rate = calculate_message_rate(message.author.id)
            if message_rate > AI_CONFIG['message_rate_limit']:
                await handle_rate_limit(message, message_rate)
                return
            
            # Automatische Hilfe
            if AI_CONFIG['auto_help_enabled']:
                help_type = await detect_help_request(message)
                if help_type:
                    await provide_automated_help(message, help_type)
        
    except Exception as e:
        print(f"❌ Fehler in KI-Nachrichtenverarbeitung: {e}")
    
    # Verarbeite normale Bot-Befehle
    await bot.process_commands(message)

# KI-Admin-Befehle
@bot.command(name='ai_stats')
@commands.has_permissions(administrator=True)
async def ai_stats(ctx):
    """Zeigt KI-Statistiken an"""
    total_users = len(user_activity)
    total_messages = sum(len(messages) for messages in user_activity.values())
    total_warnings = sum(user_warnings.values())
    
    embed = discord.Embed(
        title="🤖 KI-System Statistiken",
        color=0x6e0000
    )
    embed.add_field(name="Überwachte Benutzer", value=total_users, inline=True)
    embed.add_field(name="Analysierte Nachrichten", value=total_messages, inline=True)
    embed.add_field(name="Spam-Pattern", value=len(spam_patterns), inline=True)
    embed.add_field(name="Ausgegebene Warnungen", value=total_warnings, inline=True)
    embed.add_field(name="Hilfe-Kategorien", value=len(help_keywords), inline=True)
    embed.add_field(name="Auto-Antworten", value=len(auto_responses), inline=True)
    
    # Konfiguration anzeigen
    config_text = "\n".join([f"**{k}:** {v}" for k, v in AI_CONFIG.items()])
    embed.add_field(name="Konfiguration", value=config_text, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='ai_user_analysis')
@commands.has_permissions(administrator=True)
async def ai_user_analysis(ctx, user: discord.Member):
    """Analysiert einen spezifischen Benutzer"""
    messages = user_activity[user.id]
    if not messages:
        await ctx.send(f"❌ Keine Daten für {user.mention} verfügbar.")
        return
    
    warnings = user_warnings[user.id]
    spam_score = user_spam_score[user.id]
    message_rate = calculate_message_rate(user.id)
    
    embed = discord.Embed(
        title=f"🤖 KI-Analyse für {user.name}",
        color=0x6e0000
    )
    embed.add_field(name="Nachrichten", value=len(messages), inline=True)
    embed.add_field(name="Warnungen", value=warnings, inline=True)
    embed.add_field(name="Höchster Spam-Score", value=f"{spam_score:.2f}", inline=True)
    embed.add_field(name="Aktuelle Rate/Min", value=message_rate, inline=True)
    
    if messages:
        avg_length = sum(msg['length'] for msg in messages) / len(messages)
        total_mentions = sum(msg['mentions'] for msg in messages)
        embed.add_field(name="Ø Nachrichtenlänge", value=f"{avg_length:.1f}", inline=True)
        embed.add_field(name="Erwähnungen gesamt", value=total_mentions, inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='ai_reset_user')
@commands.has_permissions(administrator=True)
async def ai_reset_user(ctx, user: discord.Member):
    """Setzt KI-Daten für einen Benutzer zurück"""
    user_id = user.id
    
    # Lösche alle Daten
    if user_id in user_activity:
        del user_activity[user_id]
    if user_id in user_warnings:
        del user_warnings[user_id]
    if user_id in user_spam_score:
        del user_spam_score[user_id]
    
    embed = discord.Embed(
        title="✅ Benutzer-Daten zurückgesetzt",
        description=f"Alle KI-Daten für {user.mention} wurden gelöscht.",
        color=0x6e0000
    )
    await ctx.send(embed=embed)

@bot.command(name='ai_status')
@commands.has_permissions(administrator=True)
async def ai_status(ctx):
    """Zeigt den Status des KI-Systems an"""
    total_users = len(user_activity)
    total_warnings = sum(user_warnings.values())
    avg_spam_score = sum(user_spam_score.values()) / len(user_spam_score) if user_spam_score else 0
    
    embed = discord.Embed(
        title="🤖 KI-System Status",
        color=0x6e0000
    )
    embed.add_field(name="📊 Statistiken", value=f"**Überwachte Benutzer:** {total_users}\n**Gesamte Warnungen:** {total_warnings}\n**Durchschn. Spam-Score:** {avg_spam_score:.2f}", inline=False)
    embed.add_field(name="⚙️ Konfiguration", value=f"**Spam-Schwellenwert:** {AI_CONFIG['spam_threshold']}\n**Rate-Limit:** {AI_CONFIG['message_rate_limit']}/min\n**Auto-Hilfe:** {'✅' if AI_CONFIG['auto_help_enabled'] else '❌'}\n**Lernen:** {'✅' if AI_CONFIG['learning_enabled'] else '❌'}", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='ai_config')
@commands.has_permissions(administrator=True)
async def ai_config(ctx, setting: str = None, value: str = None):
    """Konfiguriert das KI-System"""
    if not setting:
        embed = discord.Embed(
            title="🤖 KI-Konfiguration",
            description="**Verfügbare Einstellungen:**\n• `spam_threshold` (0.0-1.0)\n• `message_rate_limit` (Nachrichten/Min)\n• `auto_help_enabled` (true/false)\n• `learning_enabled` (true/false)",
            color=0x6e0000
        )
        embed.add_field(name="Beispiel", value="`!ai_config spam_threshold 0.8`", inline=False)
        await ctx.send(embed=embed)
        return
    
    if setting not in AI_CONFIG:
        await ctx.send("❌ Unbekannte Einstellung!")
        return
    
    if not value:
        current_value = AI_CONFIG[setting]
        await ctx.send(f"**{setting}:** `{current_value}`")
        return
    
    # Wert setzen
    try:
        if setting in ['auto_help_enabled', 'learning_enabled']:
            AI_CONFIG[setting] = value.lower() in ['true', '1', 'yes', 'ja']
        elif setting in ['spam_threshold']:
            AI_CONFIG[setting] = max(0.0, min(1.0, float(value)))
        elif setting in ['message_rate_limit', 'warning_threshold']:
            AI_CONFIG[setting] = max(1, int(value))
        
        embed = discord.Embed(
            title="✅ KI-Konfiguration aktualisiert",
            description=f"**{setting}** wurde auf `{AI_CONFIG[setting]}` gesetzt.",
            color=0x6e0000
        )
        await ctx.send(embed=embed)
        
    except ValueError:
        await ctx.send("❌ Ungültiger Wert!")

@bot.command(name='ai_chat')
@commands.has_permissions(administrator=True)
async def ai_chat(ctx, *, prompt):
    """Chatte direkt mit der KI"""
    if not AI_CONFIG['openai_enabled']:
        await ctx.send("❌ OpenAI ist nicht konfiguriert. Bitte setze OPENAI_API_KEY in der .env Datei.")
        return
    
    response = await generate_smart_response(prompt, "admin_chat")
    if response:
        embed = discord.Embed(
            title="🤖 KI-Chat",
            description=response,
            color=0x0099ff
        )
        embed.set_footer(text=f"Angefragt von {ctx.author.display_name}")
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Fehler beim Generieren der Antwort.")

@bot.command(name='ai_analyze')
@commands.has_permissions(administrator=True)
async def ai_analyze(ctx, *, text):
    """Analysiert einen Text mit KI"""
    if not AI_CONFIG['openai_enabled']:
        await ctx.send("❌ OpenAI ist nicht konfiguriert.")
        return
    
    analysis = await analyze_message_with_ai(text)
    if analysis:
        embed = discord.Embed(
            title="🔍 KI-Analyse",
            color=0xff9900
        )
        embed.add_field(name="Toxizität", value=f"{analysis.get('toxicity', 0):.2f}", inline=True)
        embed.add_field(name="Spam-Wahrscheinlichkeit", value=f"{analysis.get('spam_probability', 0):.2f}", inline=True)
        embed.add_field(name="Hilfsbedürftigkeit", value=f"{analysis.get('help_needed', 0):.2f}", inline=True)
        embed.add_field(name="Sentiment", value=analysis.get('sentiment', 'unbekannt'), inline=True)
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Fehler bei der Analyse.")

@bot.command(name='ai_config_advanced')
@commands.has_permissions(administrator=True)
async def ai_config_advanced(ctx, setting: str = None, value: str = None):
    """Erweiterte KI-Konfiguration für OpenAI-Features"""
    advanced_settings = {
        'openai_enabled': bool,
        'smart_responses_enabled': bool,
        'context_analysis_enabled': bool,
        'auto_moderation_enabled': bool
    }
    
    if not setting:
        embed = discord.Embed(title="🤖 Erweiterte KI-Konfiguration", color=0x0099ff)
        config_text = "\n".join([f"**{k}:** {v}" for k, v in AI_CONFIG.items() if k in advanced_settings])
        embed.add_field(name="Aktuelle Einstellungen", value=config_text, inline=False)
        embed.add_field(name="Verfügbare Einstellungen", value="\n".join(advanced_settings.keys()), inline=False)
        await ctx.send(embed=embed)
        return
    
    if setting not in advanced_settings:
        await ctx.send(f"❌ Unbekannte Einstellung. Verfügbar: {', '.join(advanced_settings.keys())}")
        return
    
    if value is None:
        current_value = AI_CONFIG[setting]
        await ctx.send(f"**{setting}:** `{current_value}`")
        return
    
    # Boolean-Werte
    AI_CONFIG[setting] = value.lower() in ['true', '1', 'yes', 'ja', 'an', 'on']
    
    embed = discord.Embed(
        title="✅ Konfiguration aktualisiert",
        description=f"**{setting}** wurde auf `{AI_CONFIG[setting]}` gesetzt.",
        color=0x00ff00
    )
    await ctx.send(embed=embed)

# Starte den Bot
if TOKEN:
    print("Starte Bot mit erweiterten KI-Features...")
    print(f"Konfigurierte Intents: {intents}")
    print(f"KI-Spam-Pattern geladen: {len(spam_patterns)}")
    print(f"Hilfe-Kategorien geladen: {len(help_keywords)}")
    print(f"Auto-Antworten geladen: {len(auto_responses)}")
    print(f"KI-Konfiguration: {AI_CONFIG}")
    print(f"OpenAI aktiviert: {AI_CONFIG['openai_enabled']}")
    if AI_CONFIG['openai_enabled']:
        print("✅ Erweiterte KI-Features verfügbar")
    else:
        print("⚠️ OpenAI nicht konfiguriert - Basis-KI-Features aktiv")
    
    bot.run(TOKEN)
else:
    print("❌ FEHLER: Bot-Token nicht gefunden!")
    print("Bitte stelle sicher, dass DISCORD_TOKEN in der .env-Datei gesetzt ist.")

