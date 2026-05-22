import discord
from discord.ext import commands
import aiohttp
import os
from datetime import datetime, timezone
import asyncio

@bot.event
async def on_ready():
    print(f"✅ {bot.user} online")
   print(f"✅ {bot.user} online")
    print(f"   API-URL         : {API_URL}")
    print(f"   !free Keyword   : {TICKET_KEYWORD}")
    print(f"   !buy  Keyword   : {BUY_TICKET_KEYWORD}")
    print(f"   Empfänger       : {TARGET_MINECRAFT_PLAYER}")
    print(f"   Produkte        : {len(PRODUCTS)}")
    for p in PRODUCTS:
        ok = "✅" if os.path.exists(p["file"]) else "⚠️  FEHLT"
        print(f"      • {p['name']} ${p['price']:,} → {p['file']} {ok}")

    bot.loop.create_task(keep_alive_ping())

async def keep_alive_ping():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(API_URL + "/", timeout=aiohttp.ClientTimeout(total=10)) as r:
                    print(f"[KeepAlive] Ping → {r.status}")
        except Exception as e:
            print(f"[KeepAlive] Fehler: {e}")
        await asyncio.sleep(600)  # alle 10 Minuten
# ============================================================
#  CONFIG – Umgebungsvariablen (Railway)
# ============================================================

BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
TICKET_KEYWORD = os.environ.get("TICKET_KEYWORD", "ticket")
FREE_MESSAGE   = os.environ.get("FREE_MESSAGE", "📁 Hier sind deine Dateien!")
ALLOWED_ROLES  = [r.strip() for r in os.environ.get("ALLOWED_ROLES", "").split(",") if r.strip()]
FILES_TO_SEND  = [f.strip() for f in os.environ.get("FILES_TO_SEND", "").split(",") if f.strip()]

BUY_TICKET_KEYWORD      = os.environ.get("BUY_TICKET_KEYWORD", "buy")
TARGET_MINECRAFT_PLAYER = os.environ.get("TARGET_MINECRAFT_PLAYER", "")
LOG_CHANNEL_ID          = int(os.environ.get("LOG_CHANNEL_ID", "0"))
API_URL                 = os.environ.get("API_URL", "https://hugoworldhelperapi.onrender.com").rstrip("/")
WEBHOOK_SECRET          = os.environ.get("WEBHOOK_SECRET", "geheim")

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
                if kw in field.name.lower() or kw in field.value.lower(): return True
    return False


def has_allowed_role(member: discord.Member) -> bool:
    if not ALLOWED_ROLES:
        return True
    return any(role.name in ALLOWED_ROLES for role in member.roles)


async def get_minecraft_uuid(username: str) -> str | None:
    url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return (await r.json()).get("id")
    except Exception as e:
        print(f"[UUID-Fehler] {e}")
    return None


async def api_query(sender: str) -> float:
    headers = {"X-Secret": WEBHOOK_SECRET}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{API_URL}/query",
                json={"sender": sender},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return float(data.get("total", 0))
                print(f"[API query] HTTP {r.status}: {await r.text()}")
    except Exception as e:
        print(f"[API query Fehler] {e}")
    return 0.0


async def api_claim(sender: str, min_amount: float) -> bool:
    headers = {"X-Secret": WEBHOOK_SECRET}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{API_URL}/claim",
                json={"sender": sender, "min_amount": min_amount},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status != 200:
                    print(f"[API claim] HTTP {r.status}: {await r.text()}")
                return r.status == 200
    except Exception as e:
        print(f"[API claim Fehler] {e}")
    return False

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
    embed  = discord.Embed(title=f"{label} Log — {status}", color=color,
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Minecraft Name",   value=mc_name,           inline=True)
    embed.add_field(name="Gezahlter Betrag", value=f"${amount:,.0f}", inline=True)
    if product_name:
        embed.add_field(name="Produkt", value=product_name, inline=True)
    embed.add_field(name="Empfänger", value=TARGET_MINECRAFT_PLAYER,  inline=True)
    await channel.send(embed=embed)


# ============================================================
#  !free
# ============================================================

@bot.command(name="free")
async def free_command(ctx: commands.Context):
    if not isinstance(ctx.channel, discord.TextChannel): return
    if not has_allowed_role(ctx.author):
        await ctx.send("❌ Du hast keine Berechtigung.", delete_after=10); return
    async with ctx.typing():
        match = await is_matching_ticket(ctx.channel, TICKET_KEYWORD)
    if not match:
        await ctx.send(f"❌ Nur in **{TICKET_KEYWORD}-Tickets** nutzbar.", delete_after=10); return
    missing = [f for f in FILES_TO_SEND if not os.path.isfile(f)]
    if missing:
        await ctx.send(f"⚠️ Dateien fehlen: `{'`, `'.join(missing)}`", delete_after=15); return
    try:
        files = [discord.File(f) for f in FILES_TO_SEND]
        await ctx.send(FREE_MESSAGE, files=files)
    except Exception as e:
        await ctx.send("❌ Fehler beim Senden."); print(f"!free Fehler: {e}")


@free_command.error
async def free_error(ctx, error): print(f"!free error: {error}")


# ============================================================
#  !buy — Embed mit MC-Name, Dropdown, Prüfen-Button
# ============================================================

class MCNameModal(discord.ui.Modal, title="✏️ Minecraft-Name eingeben"):
    mc_name = discord.ui.TextInput(
        label="Dein Minecraft Username",
        placeholder="z.B. Notch",
        min_length=3, max_length=16, required=True,
    )

    def __init__(self, parent: "BuyView"):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        self.parent.mc_username = self.mc_name.value.strip()
        await interaction.response.send_message(
            f"✅ Name gesetzt: **`{self.parent.mc_username}`** — wähle jetzt ein Produkt und klicke **✅ Prüfen**.",
            ephemeral=True
        )


class BuyView(discord.ui.View):
    def __init__(self, channel: discord.TextChannel):
        super().__init__(timeout=600)
        self.channel          = channel
        self.mc_username      = ""
        self.selected_product: dict | None = None

        if PRODUCTS:
            options = [
                discord.SelectOption(
                    label=p["name"],
                    value=str(i),
                    description=f"${p['price']:,}" + (f" — {p['desc'][:40]}" if p["desc"] else "")
                )
                for i, p in enumerate(PRODUCTS)
            ]
            sel = discord.ui.Select(placeholder="📦 Produkt auswählen...", options=options, row=1)
            sel.callback = self._on_select
            self.add_item(sel)

    @discord.ui.button(label="✏️ Minecraft-Name eingeben", style=discord.ButtonStyle.secondary, row=2)
    async def name_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MCNameModal(self))

    async def _on_select(self, interaction: discord.Interaction):
        self.selected_product = PRODUCTS[int(interaction.data["values"][0])]
        await interaction.response.defer()

    @discord.ui.button(label="✅ Prüfen", style=discord.ButtonStyle.green, row=3)
    async def check_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.mc_username:
            await interaction.response.send_message("❌ Bitte zuerst Minecraft-Namen eingeben.", ephemeral=True); return
        if not self.selected_product:
            await interaction.response.send_message("❌ Bitte zuerst ein Produkt auswählen.", ephemeral=True); return

        await interaction.response.defer(ephemeral=True)
        username = self.mc_username
        product  = self.selected_product

        # UUID prüfen
        uuid = await get_minecraft_uuid(username)
        if not uuid:
            await interaction.followup.send(f"❌ **`{username}`** nicht gefunden.", ephemeral=True); return

        # Warte-Embed
        wait = await self.channel.send(embed=discord.Embed(
            title="🔍 Überprüfe Zahlung...",
            description=f"Prüfe ob **{username}** mindestens **${product['price']:,}** an **{TARGET_MINECRAFT_PLAYER}** gezahlt hat...",
            color=discord.Color.yellow()
        ))

        total = await api_query(username)
        await wait.delete()

        if total >= product["price"]:
            # Zahlung als verbraucht markieren
            await api_claim(username, product["price"])

            embed = discord.Embed(
                title="✅ Zahlung bestätigt!",
                description=(
                    f"**{username}** hat **${total:,.0f}** an **{TARGET_MINECRAFT_PLAYER}** gezahlt.\n"
                    f"Mindestbetrag: **${product['price']:,}** ✅\n\nHier ist deine Datei:"
                ),
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Produkt", value=product["name"],           inline=True)
            embed.add_field(name="Preis",   value=f"${product['price']:,}",  inline=True)
            embed.add_field(name="Gezahlt", value=f"${total:,.0f}",          inline=True)
            embed.set_footer(text=f"Verifiziert für: {username}")

            if os.path.exists(product["file"]):
                await self.channel.send(embed=embed, file=discord.File(product["file"]))
            else:
                await self.channel.send(embed=embed)
                await self.channel.send(f"⚠️ Datei `{product['file']}` fehlt — Admin kontaktieren.")

            await send_log(interaction.guild, username, total, True, product["name"])
            await interaction.followup.send("✅ Erfolgreich verifiziert!", ephemeral=True)

            for child in self.children: child.disabled = True
            try: await interaction.message.edit(view=self)
            except Exception: pass

        else:
            embed = discord.Embed(
                title="❌ Zahlung nicht ausreichend",
                description=(
                    f"**{username}** hat nur **${total:,.0f}** von **${product['price']:,}** gezahlt.\n"
                    f"Bitte zahle den Betrag an **{TARGET_MINECRAFT_PLAYER}** und versuche es erneut."
                ),
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"Geprüft für: {username}")
            await self.channel.send(embed=embed)
            await send_log(interaction.guild, username, total, False, product["name"])
            await interaction.followup.send("❌ Nicht genug gezahlt.", ephemeral=True)


@bot.command(name="buy")
async def buy_command(ctx: commands.Context):
    if not isinstance(ctx.channel, discord.TextChannel): return
    if not has_allowed_role(ctx.author):
        await ctx.send("❌ Du hast keine Berechtigung.", delete_after=10); return
    async with ctx.typing():
        match = await is_matching_ticket(ctx.channel, BUY_TICKET_KEYWORD)
    if not match:
        await ctx.send(f"❌ Nur in **{BUY_TICKET_KEYWORD}-Tickets** nutzbar.", delete_after=10); return
    if not PRODUCTS:
        await ctx.send("⚠️ Keine Produkte konfiguriert (`BUY_PRODUCTS`).", delete_after=15); return
    if not TARGET_MINECRAFT_PLAYER:
        await ctx.send("⚠️ `TARGET_MINECRAFT_PLAYER` nicht gesetzt.", delete_after=15); return

    product_lines = "\n".join(
        f"**{p['name']}** — ${p['price']:,}" + (f"\n> {p['desc']}" if p["desc"] else "")
        for p in PRODUCTS
    )
    embed = discord.Embed(
        title="🛒 Shop",
        description=(
            f"**1.** Klicke **✏️ Minecraft-Name eingeben**\n"
            f"**2.** Wähle ein Produkt\n"
            f"**3.** Klicke **✅ Prüfen** — der Bot prüft ob du den Betrag an "
            f"**{TARGET_MINECRAFT_PLAYER}** gezahlt hast.\n\n"
            f"**Produkte:**\n{product_lines}"
        ),
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="Shop System")
    await ctx.send(embed=embed, view=BuyView(ctx.channel))


@buy_command.error
async def buy_error(ctx, error): print(f"!buy error: {error}")


# ============================================================
#  on_ready
# ============================================================

@bot.event
async def on_ready():
    print(f"✅ {bot.user} online")
    print(f"   API-URL         : {API_URL}")
    print(f"   !free Keyword   : {TICKET_KEYWORD}")
    print(f"   !buy  Keyword   : {BUY_TICKET_KEYWORD}")
    print(f"   Empfänger       : {TARGET_MINECRAFT_PLAYER}")
    print(f"   Produkte        : {len(PRODUCTS)}")
    for p in PRODUCTS:
        ok = "✅" if os.path.exists(p["file"]) else "⚠️  FEHLT"
        print(f"      • {p['name']} ${p['price']:,} → {p['file']} {ok}")


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN fehlt!")
    else:
        bot.run(BOT_TOKEN)
