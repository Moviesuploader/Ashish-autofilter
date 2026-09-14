import re
import aiohttp
import asyncio
from io import BytesIO
from PIL import Image
from info import DEENDAYAL_IMAGE_FETCH
from imdb import Cinemagoer


ia = Cinemagoer()
LONG_IMDB_DESCRIPTION = False

def list_to_str(lst):
    if lst:
        return ", ".join(map(str, lst))
    return ""

async def fetch_image(url, size=(720, 720)):
    if not DEENDAYAL_IMAGE_FETCH:
        print("Image fetching is disabled.")
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    content = await response.read()
                    img = Image.open(BytesIO(content))
                    img = img.resize(size, Image.LANCZOS)
                    img_byte_arr = BytesIO()
                    img.save(img_byte_arr, format='JPEG')
                    img_byte_arr.seek(0)
                    return img_byte_arr
                else:
                    print(f"Failed to fetch image: {response.status}")
    except aiohttp.ClientError as e:
        print(f"HTTP request error in fetch_image: {e}")
    except IOError as e:
        print(f"IO error in fetch_image: {e}")
    except Exception as e:
        print(f"Unexpected error in fetch_image: {e}")
    return None

def _get_movie_details_sync(query, id=False, file=None):
    try:
        if not id:
            query = query.strip().lower()
            title = query
            year = re.findall(r'[1-2]\d{3}$', query, re.IGNORECASE)
            if year:
                year = list_to_str(year[:1])
                title = query.replace(year, "").strip()
            elif file is not None:
                year = re.findall(r'[1-2]\d{3}', file, re.IGNORECASE)
                if year:
                    year = list_to_str(year[:1])
            else:
                year = None

            movieid = ia.search_movie(title.lower(), results=10)
            if not movieid:
                return None

            if year:
                filtered = list(filter(lambda k: str(k.get('year')) == str(year), movieid))
                if not filtered:
                    filtered = movieid
            else:
                filtered = movieid

            movieid = list(filter(lambda k: k.get('kind') in ['movie', 'tv series'], filtered))
            if not movieid:
                movieid = filtered

            movieid = movieid[0].movieID
        else:
            movieid = query

        movie = ia.get_movie(movieid)
        if movie.get("original air date"):
            date = movie["original air date"]
        elif movie.get("year"):
            date = movie.get("year")
        else:
            date = "N/A"

        plot = movie.get('plot')
        if plot and len(plot) > 0:
            plot = plot[0]
        else:
            plot = movie.get('plot outline')

        if plot and len(plot) > 800:
            plot = plot[:800] + "..."

        poster_url = movie.get('full-size cover url')

        return {
            'title': movie.get('title'),
            'votes': movie.get('votes'),
            "aka": list_to_str(movie.get("akas")),
            "seasons": movie.get("number of seasons"),
            "box_office": movie.get('box office'),
            'localized_title': movie.get('localized title'),
            'kind': movie.get("kind"),
            "imdb_id": f"tt{movie.get('imdbID')}",
            "cast": list_to_str(movie.get("cast")),
            "runtime": list_to_str(movie.get("runtimes")),
            "countries": list_to_str(movie.get("countries")),
            "certificates": list_to_str(movie.get("certificates")),
            "languages": list_to_str(movie.get("languages")),
            "director": list_to_str(movie.get("director")),
            "writer": list_to_str(movie.get("writer")),
            "producer": list_to_str(movie.get("producer")),
            "composer": list_to_str(movie.get("composer")),
            "cinematographer": list_to_str(movie.get("cinematographer")),
            "music_team": list_to_str(movie.get("music department")),
            "distributors": list_to_str(movie.get("distributors")),
            'release_date': date,
            'year': movie.get('year'),
            'genres': list_to_str(movie.get("genres")),
            'poster_url': poster_url,
            'plot': plot,
            'rating': str(movie.get("rating")),
            'url': f'https://www.imdb.com/title/tt{movieid}'
        }

    except Exception as e:
        print(f"An error occurred in _get_movie_details_sync: {e}")
        return None


async def get_movie_details(query, id=False, file=None):
    """Run Cinemagoer's blocking HTTP work off the bot event loop."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_get_movie_details_sync, query, id, file),
            timeout=15,
        )
    except asyncio.TimeoutError:
        print(f"IMDb lookup timed out: {query}")
        return None
    except Exception as e:
        print(f"An error occurred in get_movie_details: {e}")
        return None
