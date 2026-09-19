"""
NovaDownloader — backend (FastAPI + yt-dlp)
Despliega esto en Render como "Web Service" (entorno Python).

requirements.txt necesario:
  fastapi
  uvicorn
  yt-dlp

Start command en Render:
  uvicorn server:app --host 0.0.0.0 --port 10000
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from yt_dlp.networking.impersonate import ImpersonateTarget
import yt_dlp
import tempfile
import os
import glob
import shutil

IMPERSONATE_TARGET = ImpersonateTarget.from_str("chrome")

app = FastAPI()

# En producción, cambia "*" por el dominio real de tu frontend en Vercel
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def label_for_format(f):
    height = f.get("height")
    if height:
        return f"{height}p"
    abr = f.get("abr")
    if abr:
        return f"Audio {int(abr)}kbps"
    return f.get("format_note") or f.get("ext", "?")


@app.get("/api/tiktok/info")
def get_tiktok_info(url: str = Query(..., description="URL del vídeo de TikTok")):
    if "tiktok.com" not in url:
        raise HTTPException(status_code=400, detail="El enlace no parece ser de TikTok")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "impersonate": IMPERSONATE_TARGET,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=422, detail=f"No se pudo procesar el enlace: {str(e)}")

    all_formats = info.get("formats", [])

    # Formatos de vídeo (con altura conocida), ordenados de mayor a menor calidad
    video_formats = [f for f in all_formats if f.get("vcodec") not in (None, "none") and f.get("url")]
    video_formats.sort(key=lambda f: f.get("height") or 0, reverse=True)

    # Deduplicar por altura para no repetir la misma calidad
    seen_heights = set()
    formats_out = []
    for f in video_formats:
        h = f.get("height") or 0
        if h in seen_heights:
            continue
        seen_heights.add(h)
        formats_out.append({
            "quality": label_for_format(f),
            "url": f.get("url"),
            "ext": f.get("ext", "mp4"),
            "height": h,
        })

    if not formats_out and info.get("url"):
        formats_out = [{"quality": "Estándar", "url": info["url"], "ext": "mp4"}]

    # Mejor pista de solo audio disponible
    audio_formats = [f for f in all_formats if f.get("vcodec") in (None, "none") and f.get("url")]
    audio_formats.sort(key=lambda f: f.get("abr") or 0, reverse=True)
    audio_url = audio_formats[0]["url"] if audio_formats else None

    if not formats_out:
        raise HTTPException(status_code=422, detail="No se pudo extraer el vídeo")

    return {
        "videoUrl": formats_out[0]["url"],
        "formats": formats_out,
        "audioUrl": audio_url,
        "title": info.get("title"),
        "author": info.get("uploader"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
    }


@app.get("/api/tiktok/download")
def download_tiktok(
    url: str = Query(..., description="URL del vídeo de TikTok"),
    height: int = Query(None, description="Altura de vídeo deseada, p.ej. 1280"),
    kind: str = Query("video", description="'video' o 'audio'"),
):
    if "tiktok.com" not in url:
        raise HTTPException(status_code=400, detail="El enlace no parece ser de TikTok")

    tmp_dir = tempfile.mkdtemp(prefix="nova_")
    outtmpl = os.path.join(tmp_dir, "%(id)s.%(ext)s")

    if kind == "audio":
        fmt = "bestaudio/best"
        postprocessors = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
    else:
        fmt = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]" if height else "best"
        postprocessors = []

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "impersonate": IMPERSONATE_TARGET,
        "outtmpl": outtmpl,
        "format": fmt,
        "postprocessors": postprocessors,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"No se pudo descargar: {e}")

    files = glob.glob(os.path.join(tmp_dir, "*"))
    if not files:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="No se generó el archivo")

    filepath = files[0]
    ext = "mp3" if kind == "audio" else "mp4"
    filename = f"novadownloader-{info.get('id', 'video')}.{ext}"
    media_type = "audio/mpeg" if kind == "audio" else "video/mp4"

    return FileResponse(
        filepath,
        filename=filename,
        media_type=media_type,
        background=BackgroundTask(lambda: shutil.rmtree(tmp_dir, ignore_errors=True)),
    )


@app.get("/")
def health():
    return {"status": "NovaDownloader backend activo"}