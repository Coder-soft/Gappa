import discord
from discord.ext import commands
import yt_dlp
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
INTENTS = discord.Intents.default()
INTENTS.message_content = True

# Bot setup
bot = commands.Bot(command_prefix="!", intents=INTENTS)

# Temporary directory for downloads
DOWNLOAD_DIR = "downloads"

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

@bot.event
async def on_ready():
    print(f"{bot.user} is online and ready to go!")

@bot.command(name="download", help="Download music from YouTube Music by link or name.")
async def download(ctx, *, query):
    await ctx.send(f"Processing your request: `{query}`...")
    try:
        # YT-DLP options
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }

        # Download audio
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=True)
            file_path = ydl.prepare_filename(info).replace(".webm", ".mp3")
            file_name = os.path.basename(file_path)

        # Send the file to Discord
        await ctx.send(file=discord.File(file_path))
        os.remove(file_path)  # Delete file locally after sending
        await ctx.send("✅ Music sent successfully!")

    except Exception as e:
        await ctx.send(f"⚠️ Error occurred: {e}")

# Run the bot
bot.run(TOKEN)
