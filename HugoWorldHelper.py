import discord
from discord.ext import commands
import aiohttp
import os
from datetime import datetime, timedelta, timezone

# ============================================================
#  CONFIG – nur über Umgebungsvariablen (Railway)
# ============================================================

BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
TICKET_KEYWORD = os.environ.get("TICKET_KEYWORD", "ticket")
FREE_MESSAGE   = os.environ.get("FREE_MESSAGE", "📁 Hier sind deine Dateien!")
ALLOWED_ROLES  = [r.strip() for r in os.environ.get("ALLOWED_ROLES", "").split(",") if r.strip()]
FILES_TO_SEND  = [f.strip() for f in os.environ.get("FILES_TO_SEND", "").split(",") if f.strip()]

# !buy spezifisch
BUY_TICKET_KEYWORD      = os.environ.get("BUY_TICKET_KEYWORD", "buy")
TARGET_MINECRAFT_PLAYER = os.environ.get("TARGET_MINECRAFT_PLAYER", "")
LOG_CHANNEL_ID          = int(os.environ.get("LOG_CHANNEL_ID", "0"))

# Produkte als Env-Var im Format:
#   BUY_PRODUCTS=Name1|Preis1|Datei1|Beschreibung1,Name2|Preis2|Datei2|Beschreibung2
# Beispiel:
#   BUY_PRODUCTS=Starter|5000|files/starter.txt|Das Einsteiger-Paket,VIP|50000|files/vip.zip|Exklusive Inhalte
def _parse_products() -> list[dict]:
    raw = os.environ.get("BUY_PRODUCTS", "")
    products = []
    for entry in raw.split(","):
        parts = entry.strip().split("|")
        if len(parts) >= 3:
            products.append({
                "name":  parts[0].strip(),
                "price": int(parts[1].strip()),
                "file":  parts[2].strip(),
                "desc":  parts[3].strip() if len(parts) >= 4 else "",
            })
    return products

PRODUCTS = _parse_products()

# TicketTool Bot-IDs (weiße & Premium Version)
TICKETTOOL_BOT_IDS = [557628352828014614, 903654348561137665]

# ============================================================

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)


# ============================================================
#  SHARED HELPERS
# ============================================================

async def is_matching_ticket(channel: discord.TextChannel, keyword: str) -> bool:
    kw = keyword.lower()
    async for message in channel.history(limit=20, oldest_first=True):
        if message.author.id not in TICKETTOOL_BOT_IDS:
            continue
        if kw in message.content.lower():
            return True
        for embed in message.embeds:
            if embed.title       and kw in embed.title.lower():       return True
            if embed.description and kw in embed.description.lower(): return True
            if embed.footer and embed.footer.text and kw in embed.footer.text.lower(): return True
            for field in embed.fields:
                if kw in field.name.lower() or kw in field.value.lower():
                    return True
    return False


def has_allowed_role(member: discord.Member) -> bool:
    if not ALLOWED_ROLES:
        return True
    return any(role.name in ALLOWED_ROLES for role in member.roles)


async def get_minecraft_uuid(username: str) -> str | None:
    url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("id")
    except Exception as e:
        print(f"[UUID-Fehler] {e}")
    return None


async def check_hugosmp_payments(username: str) -> float:
    """
    Prüft Zahlungen auf HugoSMP in den letzten 24h.
    Passe die URL an sobald du den echten API-Endpunkt kennst.
    """
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    endpoints = [
        f"https://hugosmp.net/api/payments?player={username}&to={TARGET_MINECRAFT_PLAYER}&since={since}",
        f"https://api.hugosmp.net/economy/transactions?from={username}&to={TARGET_MINECRAFT_PLAYER}",
    ]
    async with aiohttp.ClientSession() as session:
        for url in endpoints:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        data = await r.json()
                        total = 0.0
                        if isinstance(data, list):
                            for tx in data:
                                total += float(tx.get("amount", tx.get("money", 0)))
                        elif isinstance(data, dict):
                            total = float(data.get("total", data.get("amount", data.get("sum", 0))))
                        if total > 0:
                            return total
            except Exception as e:
                print(f"[HugoSMP API Fehler] {url}: {e}")
    print(f"[WARN] Kein HugoSMP-Endpunkt erreichbar für {username}")
    return 0.0


async def send_log(guild: discord.Guild, mc_name: str, amount: float,
                   success: bool, product_name: str = ""):
    if not LOG_CHANNEL_ID:
        return
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return
    color  = discord.Color.green() if success else discord.Color.red()
    status = "✅ Bestätigt" if success else "❌ Abgelehnt"
    label  = f"Buy ({product_name})" if product_name else "Free"
    embed  = discord.Embed(
        title=f"{label} Log — {status}",
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Minecraft Name",  value=mc_name,              inline=True)
    embed.add_field(name="Gezahlter Betrag",value=f"${amount:,.0f}",    inline=True)
    if product_name:
        embed.add_field(name="Produkt",     value=product_name,         inline=True)
    embed.add_field(name="Empfänger",       value=TARGET_MINECRAFT_PLAYER, inline=True)
    await channel.send(embed=embed)


# ============================================================
#  !free
# ============================================================

@bot.command(name="free")
async def free_command(ctx: commands.Context):
    if not isinstance(ctx.channel, discord.TextChannel):
        return

    if not has_allowed_role(ctx.author):
        await ctx.send("❌ Du hast keine Berechtigung für diesen Befehl.", delete_after=10)
        return

    async with ctx.typing():
        ticket_match = await is_matching_ticket(ctx.channel, TICKET_KEYWORD)

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


# ============================================================
#  !buy  —  Embed mit MC-Name, Produkt-Dropdown & Prüfen-Button
# ============================================================

class MCNameModal(discord.ui.Modal, title="✏️ Minecraft-Name eingeben"):
    mc_name = discord.ui.TextInput(
        label="Dein Minecraft Username",
        placeholder="z.B. Notch",
        min_length=3,
        max_length=16,
        required=True,
    )

    def __init__(self, parent_view: "BuyView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.mc_username = self.mc_name.value.strip()
        await interaction.response.send_message(
            f"✅ Minecraft-Name gesetzt: **`{self.parent_view.mc_username}`**\n"
            f"Wähle jetzt ein Produkt und klicke auf **✅ Prüfen**.",
            ephemeral=True
        )


class BuyView(discord.ui.View):
    def __init__(self, channel: discord.TextChannel):
        super().__init__(timeout=600)
        self.channel      = channel
        self.mc_username  = ""
        self.selected_product: dict | None = None

        # Dropdown aus PRODUCTS bauen
        if PRODUCTS:
            options = [
                discord.SelectOption(
                    label=p["name"],
                    value=str(i),
                    description=f"${p['price']:,}" + (f" — {p['desc'][:40]}" if p["desc"] else "")
                )
                for i, p in enumerate(PRODUCTS)
            ]
            select = discord.ui.Select(
                placeholder="📦 Produkt auswählen...",
                options=options,
                row=1
            )
            select.callback = self._product_selected
            self.add_item(select)

    # ── MC-Name Button ──
    @discord.ui.button(label="✏️ Minecraft-Name eingeben", style=discord.ButtonStyle.secondary, row=2)
    async def enter_name_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MCNameModal(self))

    # ── Dropdown Callback ──
    async def _product_selected(self, interaction: discord.Interaction):
        idx = int(interaction.data["values"][0])
        self.selected_product = PRODUCTS[idx]
        await interaction.response.defer()

    # ── Prüfen Button ──
    @discord.ui.button(label="✅ Prüfen", style=discord.ButtonStyle.green, row=3)
    async def check_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.mc_username:
            await interaction.response.send_message(
                "❌ Bitte gib zuerst deinen Minecraft-Namen ein.", ephemeral=True
            )
            return
        if not self.selected_product:
            await interaction.response.send_message(
                "❌ Bitte wähle zuerst ein Produkt aus.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        username = self.mc_username
        product  = self.selected_product

        # UUID prüfen
        uuid = await get_minecraft_uuid(username)
        if not uuid:
            await interaction.followup.send(
                f"❌ Minecraft-Name **`{username}`** nicht gefunden. Bitte überprüfe die Schreibweise.",
                ephemeral=True
            )
            return

        # Warte-Nachricht
        wait_embed = discord.Embed(
            title="🔍 Überprüfe Zahlung...",
            description=(
                f"Prüfe ob **{username}** mindestens **${product['price']:,}** "
                f"an **{TARGET_MINECRAFT_PLAYER}** in den letzten 24h gezahlt hat..."
            ),
            color=discord.Color.yellow()
        )
        wait_msg = await self.channel.send(embed=wait_embed)
        total_paid = await check_hugosmp_payments(username)
        await wait_msg.delete()

        if total_paid >= product["price"]:
            # ── Erfolg ──
            embed = discord.Embed(
                title="✅ Zahlung bestätigt!",
                description=(
                    f"**{username}** hat **${total_paid:,.0f}** an "
                    f"**{TARGET_MINECRAFT_PLAYER}** gezahlt.\n"
                    f"Mindestbetrag für **{product['name']}**: **${product['price']:,}** ✅\n\n"
                    f"Hier ist deine Datei:"
                ),
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Produkt", value=product["name"],          inline=True)
            embed.add_field(name="Preis",   value=f"${product['price']:,}", inline=True)
            embed.add_field(name="Gezahlt", value=f"${total_paid:,.0f}",    inline=True)
            embed.set_footer(text=f"Verifiziert für: {username}")

            file_path = product["file"]
            if os.path.exists(file_path):
                await self.channel.send(embed=embed, file=discord.File(file_path))
            else:
                await self.channel.send(embed=embed)
                await self.channel.send(
                    f"⚠️ Produktdatei `{file_path}` nicht gefunden. Bitte Admin kontaktieren."
                )

            await send_log(interaction.guild, username, total_paid, True, product["name"])
            await interaction.followup.send("✅ Kauf erfolgreich verifiziert!", ephemeral=True)

            # Alle Buttons deaktivieren
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

        else:
            # ── Nicht genug gezahlt ──
            embed = discord.Embed(
                title="❌ Zahlung nicht ausreichend",
                description=(
                    f"**{username}** hat nur **${total_paid:,.0f}** von "
                    f"**${product['price']:,}** für **{product['name']}** gezahlt.\n"
                    f"Bitte zahle den korrekten Betrag an **{TARGET_MINECRAFT_PLAYER}** und versuche es erneut."
                ),
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"Geprüft für: {username}")
            await self.channel.send(embed=embed)
            await send_log(interaction.guild, username, total_paid, False, product["name"])
            await interaction.followup.send("❌ Betrag nicht ausreichend.", ephemeral=True)


@bot.command(name="buy")
async def buy_command(ctx: commands.Context):
    if not isinstance(ctx.channel, discord.TextChannel):
        return

    if not has_allowed_role(ctx.author):
        await ctx.send("❌ Du hast keine Berechtigung für diesen Befehl.", delete_after=10)
        return

    async with ctx.typing():
        ticket_match = await is_matching_ticket(ctx.channel, BUY_TICKET_KEYWORD)

    if not ticket_match:
        await ctx.send(
            f"❌ Dieser Befehl funktioniert nur in **{BUY_TICKET_KEYWORD.capitalize()}-Tickets**.",
            delete_after=10
        )
        return

    if not PRODUCTS:
        await ctx.send(
            "⚠️ Keine Produkte konfiguriert. Bitte setze die `BUY_PRODUCTS` Umgebungsvariable.",
            delete_after=15
        )
        return

    if not TARGET_MINECRAFT_PLAYER:
        await ctx.send(
            "⚠️ Kein Zahlungsempfänger konfiguriert. Bitte setze `TARGET_MINECRAFT_PLAYER`.",
            delete_after=15
        )
        return

    # Produktliste für Embed
    product_lines = "\n".join(
        f"**{p['name']}** — ${p['price']:,}" + (f"\n> {p['desc']}" if p["desc"] else "")
        for p in PRODUCTS
    )

    embed = discord.Embed(
        title="🛒 Shop",
        description=(
            f"**1.** Klicke auf **✏️ Minecraft-Name eingeben** und gib deinen Namen ein.\n"
            f"**2.** Wähle ein Produkt aus dem Dropdown.\n"
            f"**3.** Klicke auf **✅ Prüfen** — der Bot prüft ob du in den letzten 24h "
            f"den Produktpreis an **{TARGET_MINECRAFT_PLAYER}** gezahlt hast.\n\n"
            f"**Verfügbare Produkte:**\n{product_lines}"
        ),
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="Shop System")

    view = BuyView(ctx.channel)
    await ctx.send(embed=embed, view=view)


@buy_command.error
async def buy_error(ctx: commands.Context, error):
    print(f"Fehler bei !buy: {error}")


# ============================================================
#  on_ready
# ============================================================

@bot.event
async def on_ready():
    print(f"✅ Bot ist online als: {bot.user}")
    print(f"   !free Keyword  : '{TICKET_KEYWORD}'")
    print(f"   !free Dateien  : {FILES_TO_SEND}")
    print(f"   !free Rollen   : {ALLOWED_ROLES if ALLOWED_ROLES else 'Alle'}")
    print(f"   !buy  Keyword  : '{BUY_TICKET_KEYWORD}'")
    print(f"   !buy  Empfänger: '{TARGET_MINECRAFT_PLAYER}'")
    print(f"   !buy  Produkte : {len(PRODUCTS)}")
    for p in PRODUCTS:
        exists = "✅" if os.path.exists(p["file"]) else "⚠️  DATEI FEHLT"
        print(f"      • {p['name']} (${p['price']:,}) → {p['file']} {exists}")


# ============================================================
#  Start
# ============================================================

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ Kein BOT_TOKEN gefunden! Setze die Umgebungsvariable auf Railway.")
    else:
        bot.run(BOT_TOKEN)
