import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
from yt_dlp import YoutubeDL
import asyncio
import spotipy
import json
from spotipy.oauth2 import SpotifyClientCredentials
from googleapiclient.discovery import build
import re
from discord.ui import Button, View
load_dotenv()
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
youtube_client = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
YOUTUBE_URL_PATTERN = r'(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([a-zA-Z0-9_-]{11})'
class CopyrightChecker(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'extract_flat': 'in_playlist',
            'quiet': True,
            'no_warnings': True,
            'force_generic_extractor': False,
            'cookies': 'cookies.txt'
        }
        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        self.spotify = spotipy.Spotify(client_credentials_manager=SpotifyClientCredentials(client_id, client_secret))
    async def setup_hook(self):
        await self.add_cog(MusicCommands(self))
    async def on_ready(self):
        print(f"Bot is ready! Logged in as {self.user}")
        await self.change_presence(activity=discord.Game(name="!help for commands"))
class MusicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cache_file = 'video_cache.json'
        
        # Load cached data from the file (if it exists)
        self.cached_info = self.load_cache()
        
    def load_cache(self):
        """Load the cached video info from a file."""
        try:
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save_cache(self):
        """Save the cached video info to a file."""
        with open(self.cache_file, 'w') as f:
            json.dump(self.cached_info, f)
        
    @commands.command(name='check')
    async def check_copyright(self, ctx, *, query):
        """Check copyright status of a song by title or YouTube URL"""
        async with ctx.typing():
            try:
                if 'youtube.com' in query or 'youtu.be' in query:
                    info = await self.get_youtube_info(query)
                    if info:
                        embed = await self.create_youtube_embed(info)
                        await ctx.send(embed=embed)
                    else:
                        await ctx.send("❌ Couldn't fetch video information. Please make sure the URL is valid.")
                else:
                    results = await self.search_spotify_info(query)
                    if results:
                        embed = await self.create_spotify_embed(results)
                        await ctx.send(embed=embed)
                    else:
                        await ctx.send("❌ No information found for this song on Spotify.")
            except Exception as e:
                error_msg = f"❌ An error occurred: {str(e)}"
                if "HTTP Error 429" in str(e):
                    error_msg = "❌ Rate limit reached. Please try again later."
                elif "This video is unavailable" in str(e):
                    error_msg = "❌ This video is unavailable or private."
                await ctx.send(error_msg)
    async def get_youtube_info(self, url):
        """Get copyright information from YouTube video, using cache if available."""
        if url in self.cached_info:
            #print(f"Cache hit for {url}")
            return self.cached_info[url]

        with YoutubeDL(self.bot.ydl_opts) as ydl:
            try:
                info = await asyncio.to_thread(ydl.extract_info, url, download=False)
                if not info:
                    return None

                license_info = info.get('license', 'Standard YouTube License')
                title = info.get('title', '').lower()
                description = info.get('description', '').lower()
                is_creative_commons = (
                    'creative commons' in description or
                    license_info.lower() == 'creative commons'
                )
                no_copyright_terms = ['no copyright', 'free to use', 'royalty-free', 'copyright free', 'public domain','royalty free music']
                contains_no_copyright = any(term in title or term in description for term in no_copyright_terms)
                copyrighted = not (is_creative_commons or contains_no_copyright)

                video_info = {
                    'title': info.get('title', 'Unknown'),
                    'channel': info.get('uploader', 'Unknown'),
                    'license': license_info,
                    'is_copyrighted': copyrighted,
                    'description': info.get('description', 'No description available'),
                    'thumbnail': info.get('thumbnail', None),
                    'duration': info.get('duration', 0),
                    'view_count': info.get('view_count', 0),
                    'upload_date': info.get('upload_date', 'Unknown'),
                    'url': info.get('webpage_url', url)
                }

                self.cached_info[url] = video_info
                self.save_cache()
                return video_info

            except Exception as e:
                print(f"Error extracting video info: {str(e)}")
                return None
    async def search_spotify_info(self, query):
        """Search for song information using Spotify"""
        try:
            results = self.bot.spotify.search(q=query, type='track', limit=1)
            if results['tracks']['items']:
                track = results['tracks']['items'][0]
                album = self.bot.spotify.album(track['album']['id'])
                copyrighted = True
                if 'copyrights' in album:
                    copyright_text = ' '.join([c['text'].lower() for c in album['copyrights']])
                    if any(term in copyright_text for term in ['creative commons', 'public domain', 'cc0']):
                        copyrighted = False
                return {
                    'title': track['name'],
                    'artist': ", ".join(artist['name'] for artist in track['artists']),
                    'album': track['album']['name'],
                    'release_date': track['album']['release_date'],
                    'spotify_url': track['external_urls']['spotify'],
                    'thumbnail': track['album']['images'][0]['url'] if track['album']['images'] else None,
                    'is_copyrighted': copyrighted,
                    'copyright_text': album.get('copyrights', [{'text': 'No copyright information available'}])[0]['text']
                }
            return None
        except Exception as e:
            print(f"Error fetching song info from Spotify: {str(e)}")
            return None
    async def create_spotify_embed(self, info):
        """Create Discord embed for Spotify track info"""
        copyright_status = "🔒 Likely Copyrighted" if info['is_copyrighted'] else "⚠️ Potentially Not Copyrighted"
        embed = discord.Embed(
            title="Spotify Track Information",
            description=f"[Listen on Spotify]({info['spotify_url']})",
            color=discord.Color.green()
        )
        embed.add_field(name="Title", value=info['title'], inline=False)
        embed.add_field(name="Artist(s)", value=info['artist'], inline=True)
        embed.add_field(name="Album", value=info['album'], inline=True)
        embed.add_field(name="Release Date", value=info['release_date'], inline=True)
        embed.add_field(name="Estimated Status", value=copyright_status, inline=False)
        embed.add_field(name="Copyright Info", value=info['copyright_text'], inline=False)
        embed.add_field(name="⚠️ Important Note", value=(
            "Spotify Search Results Are Not Accurate! Use YouTube Search Instead."
        ), inline=False)
        if info['thumbnail']:
            embed.set_thumbnail(url=info['thumbnail'])
        return embed
    async def create_youtube_embed(self, info):
        """Create Discord embed for YouTube video info"""
        copyright_status = "🔒 Copyrighted" if info['is_copyrighted'] else "✔️ Public Domain / Creative Commons"
        embed = discord.Embed(
            title="YouTube Video Information",
            description=f"[Watch on YouTube]({info.get('url')})",
            color=discord.Color.red()
        )
        embed.add_field(name="Title", value=info['title'], inline=False)
        embed.add_field(name="Channel", value=info['channel'], inline=True)
        embed.add_field(name="License", value=info['license'], inline=True)
        embed.add_field(name="Status", value=copyright_status, inline=True)
        embed.add_field(name="Note", value="This check is based on video license information, title, and description analysis.", inline=True)
        embed.add_field(name="Note For Epidemic Music", value="If you are checking a music Epidemic Music Which Says That It is Royalty Free, That Does Not Mean You Can Use it you have to buy a subscription from Epidemic.", inline=True)
        embed.set_footer(text="Learn About Copyright,types,symbols and much more. Visit Gappa Wiki Now!")

        view = discord.ui.View()
        button = discord.ui.Button(style=discord.ButtonStyle.green, label="Learn About Copyright", url="https://gappa-web.pages.dev/wiki/wiki")
        view.add_item(button)
        if info['thumbnail']:
            embed.set_thumbnail(url=info['thumbnail'])
        return embed
    @commands.command(name="fetch")
    async def fetch_video_info(self, ctx, yt_link):
        try:
            video_info = self.get_video_info(yt_link)
            embed = discord.Embed(
                title=video_info['title'],
                description=video_info['description'][:200] + "..." if len(video_info['description']) > 200 else video_info['description'],
                color=discord.Color.red(),
                url=yt_link
            )
            embed.set_author(name=video_info['channel_title'])
            embed.add_field(name="Published on", value=video_info['publish_date'], inline=True)
            embed.add_field(name="Views", value=f"{int(video_info['views']):,}", inline=True)
            embed.add_field(name="Likes", value=f"{int(video_info['likes']):,}", inline=True)
            embed.add_field(name="Comments", value=f"{int(video_info['comments']):,}", inline=True)
            embed.add_field(name="Duration", value=self.format_duration(video_info['duration']), inline=True)
            embed.add_field(name="Channel Subscribers", value=f"{int(video_info['channel_subscribers']):,}", inline=True)
            embed.add_field(name="Total Videos", value=f"{int(video_info['channel_videos']):,}", inline=True)
            if 'thumbnail' in video_info and video_info['thumbnail']:
                embed.set_thumbnail(url=video_info['thumbnail'])
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}")
    def format_duration(self, duration):
        """Convert ISO 8601 duration to a more readable format"""
        duration = duration.replace('PT', '')
        hours = 0
        minutes = 0
        seconds = 0
        if 'H' in duration:
            hours, duration = duration.split('H')
            hours = int(hours)
        if 'M' in duration:
            minutes, duration = duration.split('M')
            minutes = int(minutes)
        if 'S' in duration:
            seconds = int(duration.replace('S', ''))
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"
    def get_video_info(self, video_url):
        video_id = video_url.split('v=')[-1]  
        video_request = youtube_client.videos().list(
            part="snippet,contentDetails,statistics",
            id=video_id
        )
        video_response = video_request.execute()
        if not video_response['items']:
            raise Exception("Invalid YouTube video link or video not found.")
        video_data = video_response["items"][0]
        channel_id = video_data["snippet"]["channelId"]
        channel_request = youtube_client.channels().list(
            part="snippet,statistics",
            id=channel_id
        )
        channel_response = channel_request.execute()
        channel_data = channel_response["items"][0]
        thumbnail = video_data["snippet"]["thumbnails"]["high"]["url"] if "thumbnails" in video_data["snippet"] else None
        return {
            "title": video_data["snippet"]["title"],
            "description": video_data["snippet"]["description"],
            "channel_title": video_data["snippet"]["channelTitle"],
            "publish_date": video_data["snippet"]["publishedAt"],
            "views": video_data["statistics"].get("viewCount", "N/A"),
            "likes": video_data["statistics"].get("likeCount", "N/A"),
            "comments": video_data["statistics"].get("commentCount", "N/A"),
            "duration": video_data["contentDetails"]["duration"],
            "channel_subscribers": channel_data["statistics"].get("subscriberCount", "N/A"),
            "channel_videos": channel_data["statistics"]["videoCount"],
            "thumbnail": thumbnail
        }
    @commands.command(name='youtube')
    async def youtube_stats(self, ctx, channel_id):
        stats = self.get_channel_details(channel_id)
        latest_video = self.get_latest_video(channel_id)
        top_video = self.get_top_video(channel_id)
        if stats:
            embed = discord.Embed(
                title=f"{stats['title']} - YouTube Channel Stats",
                description=stats['description'],
                color=discord.Color.red()
            )
            embed.set_thumbnail(url=stats["profile_pic"])
            if stats["banner_url"]:
                embed.set_image(url=stats["banner_url"])
            embed.add_field(name="Subscribers", value=stats['subscribers'], inline=True)
            embed.add_field(name="Total Views", value=stats['views'], inline=True)
            embed.add_field(name="Total Videos", value=stats['videos'], inline=True)
            embed.add_field(name="Watch Hours (estimated)", value=stats['watch_hours'], inline=True)
            embed.add_field(name="Channel Created", value=stats['created_at'], inline=True)
            if latest_video:
                embed.add_field(
                    name="Latest Video",
                    value=f"[{latest_video['title']}](https://www.youtube.com/watch?v={latest_video['video_id']})"
                )
            if top_video:
                embed.add_field(
                    name="Top Video",
                    value=f"[{top_video['title']}](https://www.youtube.com/watch?v={top_video['video_id']})"
                )
            await ctx.send(embed=embed)
        else:
            await ctx.send("Channel not found!")
    def get_channel_details(self, channel_id):
        request = youtube_client.channels().list(
            part="snippet,statistics,brandingSettings,contentDetails",
            id=channel_id
        )
        response = request.execute()
        if "items" in response and len(response["items"]) > 0:
            channel = response["items"][0]
            statistics = channel["statistics"]
            snippet = channel["snippet"]
            branding = channel["brandingSettings"]
            return {
                "title": snippet["title"],
                "description": snippet.get("description", "No description"),
                "subscribers": statistics.get("subscriberCount", "N/A"),
                "views": statistics.get("viewCount", "N/A"),
                "videos": statistics.get("videoCount", "N/A"),
                "watch_hours": round(int(statistics.get("viewCount", 0)) / 1000, 2),  # rough estimate
                "created_at": snippet["publishedAt"],
                "profile_pic": snippet["thumbnails"]["high"]["url"],
                "banner_url": branding["image"]["bannerExternalUrl"] if "image" in branding else None,
            }
        else:
            return None
    def get_latest_video(self, channel_id):
        request = youtube_client.search().list(
            part="snippet",
            channelId=channel_id,
            order="date",
            maxResults=1
        )
        response = request.execute()

        if response["items"]:
            video = response["items"][0]
            return {
                "title": video["snippet"]["title"],
                "video_id": video["id"]["videoId"],
                "published_at": video["snippet"]["publishedAt"]
            }
        return None

    def get_top_video(self, channel_id):
        request = youtube_client.search().list(
            part="snippet",
            channelId=channel_id,
            order="viewCount",
            maxResults=1
        )
        response = request.execute()

        if response["items"]:
            video = response["items"][0]
            return {
                "title": video["snippet"]["title"],
                "video_id": video["id"]["videoId"]
            }
        return None

    @commands.command()
    async def getid(self, ctx, *, handle: str):
        """Fetches the YouTube channel ID from a given handle"""
        try:
            handle = handle.lstrip('@')
            
            request = youtube_client.channels().list(
                part="id,snippet",
                forUsername=handle
            )
            response = request.execute()
            if not response.get("items"):
                search_request = youtube_client.search().list(
                    part="id,snippet",
                    q=handle,
                    type="channel",
                    maxResults=1
                )
                search_response = search_request.execute()
                if search_response.get("items"):
                    channel_id = search_response["items"][0]["id"]["channelId"]
                    channel_name = search_response["items"][0]["snippet"]["title"]
                else:
                    await ctx.send(f"No channel found for `{handle}`. The handle might be incorrect or the channel might not exist.")
                    return
            else:
                channel_id = response["items"][0]["id"]
                channel_name = response["items"][0]["snippet"]["title"]
            embed = discord.Embed(
                title="YouTube Channel ID",
                description=f"Channel ID for `{handle}`",
                color=discord.Color.red()
            )
            embed.add_field(name="Channel Name", value=channel_name, inline=False)
            embed.add_field(name="Channel ID", value=channel_id, inline=False)
            embed.add_field(name="Note", value="The searches may sometimes be inaccurate. Please verify the results.", inline=False)
            button = Button(style=discord.ButtonStyle.green, label="Get Channel Stats", custom_id=f"youtube_{channel_id}")
            async def button_callback(interaction):
                await interaction.response.defer()
                await self.youtube_stats(ctx, channel_id)
            button.callback = button_callback
            view = View()
            view.add_item(button)
            await ctx.send(embed=embed, view=view)
        except Exception as e:
            error_message = f"An error occurred: {str(e)}"
            if "quota" in str(e).lower():
                error_message += "\nIt seems the YouTube API quota has been exceeded. Please try again later."
            await ctx.send(error_message)
    @commands.command(name='help', help="Show this help message.")
    async def help_command(self, ctx):
        embed = discord.Embed(
            title="Music Copyright Bot Help",
            description="Here are the available commands:",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="!check [song title or YouTube URL]",
            value="Check the copyright status of a song or YouTube video.",
            inline=False
        )
        embed.add_field(
            name="!fetch [YouTube URL]",
            value="Fetch detailed information about a YouTube video.",
            inline=False
        )
        embed.add_field(
            name="!thumb [YouTube URL]",
            value="Get the HD thumbnail of a YouTube video.",
            inline=False
        )
        embed.add_field(
            name="!youtube [channel ID]",
            value="Get detailed statistics for a YouTube channel.",
            inline=False
        )
        embed.add_field(
            name="!getid [YouTube handle]",
            value="Get the channel ID for a given YouTube handle (with or without '@') and provide a quick option to view channel stats.",
            inline=False
        )
        embed.add_field(
            name="!help",
            value="Show this help message.",
            inline=False
        )
        embed.add_field(
            name="!extract [YouTube URL]",
            value="Extract audio from a YouTube video and send it as an MP3 file.",
            inline=False
        )
        embed.add_field(
            name="!info",
            value="Show information about the bot.",
            inline=False
        )
        embed.set_footer(text="Learn About Copyright,types,symbols and much more. Click the Button Below To Start Learning!")
        view = discord.ui.View()
        button = discord.ui.Button(style=discord.ButtonStyle.green, label="Learn About Copyright", url="https://gappa-web.pages.dev/wiki/wiki")
        view.add_item(button)
        await ctx.send(embed=embed, view=view)

    @commands.command(name='thumb')
    async def thumb(self, ctx, url: str):
        match = re.match(YOUTUBE_URL_PATTERN, url)
        if match:
            video_id = match.group(1)
            thumbnail_url = f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg'

            embed = discord.Embed(
                title='YouTube Thumbnail',
                description='Here is the HD thumbnail of the provided video:',
                color=discord.Color.blue()
            )
            embed.set_image(url=thumbnail_url)
            embed.set_footer(text='Requested by ' + ctx.author.name)

            await ctx.send(embed=embed)
        else:
            await ctx.send('Please provide a valid YouTube link!')

    @commands.command(name='info')
    async def show_bot_info(self, ctx):
        embed = discord.Embed(
            title="Gappa Bot Info",
            description="I'm a bot designed to help The Creator Community With Free Tools! FREE FOR ALL!",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Version",
            value="0.7",
            inline=True
        )
        embed.add_field(
            name="Library",
            value=f"discord.py {discord.__version__}",
            inline=True
        )
        embed.add_field(
            name="Creator",
            value="Coder-Soft",
            inline=True
        )
        embed.add_field(
            name="Credits",
            value="Skeptical",
            inline=True
        )
        embed.add_field(
            name="Commands",
            value="Use !help to see available commands",
            inline=False
        )
        embed.set_footer(text="Learn About Copyright,types,symbols and much more. Click the Button Below To Start Learning!")

        view = discord.ui.View()
        button = discord.ui.Button(style=discord.ButtonStyle.green, label="Learn About Copyright", url="https://gappa-web.pages.dev/wiki/wiki")
        view.add_item(button)
        
        await ctx.send(embed=embed, view=view)
    
    @commands.command(name='extract')
    async def extract(self, ctx, url=None):
        """Extract audio from a YouTube video"""
        if not url:
            await ctx.send("Please provide a YouTube link after the command.")
            return
        if "youtube.com" not in url and "youtu.be" not in url:
            await ctx.send("Please provide a valid YouTube link after the command.")
            return
        try:
            await ctx.send("Downloading audio...")
            output_filename = "downloaded_audio.mp3"
            ydl_opts = {
                'format': 'bestaudio',
                'outtmpl': 'downloaded_audio.%(ext)s', 
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192'
                }]
            }
            with YoutubeDL(ydl_opts) as ydl:
                await asyncio.to_thread(ydl.extract_info, url, download=True)
            await ctx.send("Audio extracted successfully!", file=discord.File(output_filename))
            os.remove(output_filename)
        except Exception as e:
            await ctx.send("An error occurred while extracting audio.")
            print(f"Error: {e}")
bot = CopyrightChecker()
bot.run(os.getenv("DISCORD_TOKEN"))

