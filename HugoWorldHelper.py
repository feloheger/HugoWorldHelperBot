import discord
from discord.ext import commands
import os
import json

# ============================================================
#  CONFIG LADEN
# ============================================================

CONFIG_FILE = "config.json"

def load_config() -> dict:
    if not os.path.isfile(CONFIG_FILE):
        print(f"❌ '{CONFIG_FILE}' nicht gefunden! Bitte erstelle die Datei.")
        exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()

BOT_TOKEN = os.environ.get("BOT_TOKEN") or config.get("bot_token")
TICKET_KEYWORD   = config["ticket_keyword"]
FREE_MESSAGE     = config["free_message"]
ALLOWED_ROLES    = config.get("allowed_roles", [])

# file_to_send kann jetzt ein String ODER eine Liste sein
def load_files(cfg: dict) -> list:
    val = cfg.get("file_to_send", [])
    if isinstance(val, str):
        return [val]
    return val

FILES_TO_SEND: list = load_files(config)

# TicketTool Bot-IDs (weiße & Premium Version)
TICKETTOOL_BOT_IDS = [557628352828014614, 903654348561137665]

# ============================================================

intents = discord.Intents.all()

bot = commands.Bot(command_prefix="!", intents=intents)


async def is_matching_ticket(channel: discord.TextChannel) -> bool:
    """
    Liest die ersten 20 Nachrichten und sucht nach der TicketTool-Eröffnungsnachricht.
    Prüft: normaler Text + Embed-Titel + Embed-Beschreibung + Embed-Felder + Footer.
    """
    keyword = TICKET_KEYWORD.lower()

    async for message in channel.history(limit=20, oldest_first=True):
        if message.author.id not in TICKETTOOL_BOT_IDS:
            continue

        # Normaler Nachrichtentext
        if keyword in message.content.lower():
            return True

        # Embeds als Fallback
        for embed in message.embeds:
            if embed.title and keyword in embed.title.lower():
                return True
            if embed.description and keyword in embed.description.lower():
                return True
            if embed.footer and embed.footer.text and keyword in embed.footer.text.lower():
                return True
            for field in embed.fields:
                if keyword in field.name.lower() or keyword in field.value.lower():
                    return True

    return False


def has_allowed_role(member: discord.Member) -> bool:
    if not ALLOWED_ROLES:
        return True
    return any(role.name in ALLOWED_ROLES for role in member.roles)


@bot.event
async def on_ready():
    print(f"✅ Bot ist online als: {bot.user}")
    print(f"   Keyword : '{TICKET_KEYWORD}'")
    print(f"   Dateien : {FILES_TO_SEND}")
    print(f"   Rollen  : {ALLOWED_ROLES if ALLOWED_ROLES else 'Alle'}")


@bot.command(name="free")
async def free_command(ctx: commands.Context):
    """Sendet die Dateien wenn !free im passenden Ticket geschrieben wird."""

    if not isinstance(ctx.channel, discord.TextChannel):
        return

    if not has_allowed_role(ctx.author):
        await ctx.send("❌ Du hast keine Berechtigung für diesen Befehl.", delete_after=10)
        return

    async with ctx.typing():
        ticket_match = await is_matching_ticket(ctx.channel)

    if not ticket_match:
        await ctx.send(
            f"❌ Dieser Befehl funktioniert nur in **{TICKET_KEYWORD.capitalize()}-Tickets**.",
            delete_after=10
        )
        return

    # Prüfen ob alle Dateien existieren
    missing = [f for f in FILES_TO_SEND if not os.path.isfile(f.strip())]
    if missing:
        await ctx.send(
            f"⚠️ Folgende Dateien wurden nicht gefunden: `{'`, `'.join(missing)}`\n"
            "Bitte lege sie in denselben Ordner wie den Bot.",
            delete_after=15
        )
        return

    try:
        files = [discord.File(f.strip()) for f in FILES_TO_SEND]
        await ctx.send(FREE_MESSAGE, files=files)
        print(f"📤 {FILES_TO_SEND} gesendet in #{ctx.channel.name} von {ctx.author}")
    except Exception as e:
        await ctx.send("❌ Beim Senden der Dateien ist ein Fehler aufgetreten.")
        print(f"❌ Fehler: {e}")


@free_command.error
async def free_error(ctx: commands.Context, error):
    print(f"Fehler bei !free: {error}")


# ============================================================
#  !config Befehl – Keyword direkt per Discord ändern
# ============================================================

@bot.command(name="config")
@commands.has_permissions(administrator=True)
async def config_command(ctx: commands.Context, setting: str = None, *, value: str = None):
    """
    Ändert Einstellungen direkt über Discord (nur Admins).
    Verwendung:
      !config keyword schematics
      !config addfile  meinedatei.pdf
      !config removefile meinedatei.pdf
      !config clearfiles
      !config message 📁 Deine neue Nachricht!
      !config show
    """
    global TICKET_KEYWORD, FILES_TO_SEND, FREE_MESSAGE

    if setting is None or setting.lower() == "show":
        embed = discord.Embed(title="⚙️ Bot Konfiguration", color=discord.Color.blue())
        embed.add_field(name="keyword", value=f"`{TICKET_KEYWORD}`", inline=False)
        embed.add_field(name="files",   value="\n".join(f"`{f}`" for f in FILES_TO_SEND) or "Keine", inline=False)
        embed.add_field(name="message", value=FREE_MESSAGE,          inline=False)
        embed.add_field(name="roles",   value=str(ALLOWED_ROLES) if ALLOWED_ROLES else "Alle", inline=False)
        await ctx.send(embed=embed)
        return

    if value is None and setting.lower() != "clearfiles":
        await ctx.send("❌ Bitte einen Wert angeben. Beispiel: `!config addfile meinedatei.pdf`", delete_after=10)
        return

    cfg = load_config()

    if setting.lower() == "keyword":
        cfg["ticket_keyword"] = value
        TICKET_KEYWORD = value
        await ctx.send(f"✅ Keyword geändert zu: `{value}`")

    elif setting.lower() == "addfile":
        files = load_files(cfg)
        if value in files:
            await ctx.send(f"⚠️ `{value}` ist bereits in der Liste.", delete_after=10)
            return
        files.append(value)
        cfg["file_to_send"] = files
        FILES_TO_SEND = files
        await ctx.send(f"✅ Datei hinzugefügt: `{value}`\nAktuelle Liste: {FILES_TO_SEND}")

    elif setting.lower() == "removefile":
        files = load_files(cfg)
        if value not in files:
            await ctx.send(f"⚠️ `{value}` ist nicht in der Liste.", delete_after=10)
            return
        files.remove(value)
        cfg["file_to_send"] = files
        FILES_TO_SEND = files
        await ctx.send(f"✅ Datei entfernt: `{value}`\nAktuelle Liste: {FILES_TO_SEND}")

    elif setting.lower() == "clearfiles":
        cfg["file_to_send"] = []
        FILES_TO_SEND = []
        await ctx.send("✅ Alle Dateien aus der Liste entfernt.")

    elif setting.lower() == "message":
        cfg["free_message"] = value
        FREE_MESSAGE = value
        await ctx.send(f"✅ Nachricht geändert zu: {value}")

    else:
        await ctx.send(
            "❌ Unbekannte Einstellung. Verfügbar: `keyword`, `addfile`, `removefile`, `clearfiles`, `message`, `show`",
            delete_after=10
        )
        return

    # In config.json speichern
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
    print(f"💾 Config gespeichert: {setting} = {value}")


@config_command.error
async def config_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Nur Admins können die Config ändern.", delete_after=10)


if __name__ == "__main__":
    if BOT_TOKEN == "DEIN_BOT_TOKEN_HIER":
        print("❌ Bitte trage deinen Bot-Token in config.json ein!")
    else:
        bot.run(BOT_TOKEN)
