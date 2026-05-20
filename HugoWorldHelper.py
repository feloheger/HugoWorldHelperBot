import discord
from discord.ext import commands
import os

# ============================================================
#  CONFIG – nur über Umgebungsvariablen (Railway)
# ============================================================

BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
TICKET_KEYWORD = os.environ.get("TICKET_KEYWORD", "ticket")
FREE_MESSAGE   = os.environ.get("FREE_MESSAGE", "📁 Hier sind deine Dateien!")
ALLOWED_ROLES  = [r.strip() for r in os.environ.get("ALLOWED_ROLES", "").split(",") if r.strip()]
FILES_TO_SEND  = [f.strip() for f in os.environ.get("FILES_TO_SEND", "").split(",") if f.strip()]

# TicketTool Bot-IDs (weiße & Premium Version)
TICKETTOOL_BOT_IDS = [557628352828014614, 903654348561137665]

# ============================================================

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)


async def is_matching_ticket(channel: discord.TextChannel) -> bool:
    keyword = TICKET_KEYWORD.lower()

    async for message in channel.history(limit=20, oldest_first=True):
        if message.author.id not in TICKETTOOL_BOT_IDS:
            continue

        if keyword in message.content.lower():
            return True

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

    missing = [f for f in FILES_TO_SEND if not os.path.isfile(f)]
    if missing:
        await ctx.send(
            f"⚠️ Folgende Dateien wurden nicht gefunden: `{'`, `'.join(missing)}`",
            delete_after=15
        )
        return

    try:
        files = [discord.File(f) for f in FILES_TO_SEND]
        await ctx.send(FREE_MESSAGE, files=files)
        print(f"📤 {FILES_TO_SEND} gesendet in #{ctx.channel.name} von {ctx.author}")
    except Exception as e:
        await ctx.send("❌ Beim Senden der Dateien ist ein Fehler aufgetreten.")
        print(f"❌ Fehler: {e}")


@free_command.error
async def free_error(ctx: commands.Context, error):
    print(f"Fehler bei !free: {error}")


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ Kein BOT_TOKEN gefunden! Setze die Umgebungsvariable auf Railway.")
    else:
        bot.run(BOT_TOKEN)
