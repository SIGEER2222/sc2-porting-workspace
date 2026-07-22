"""Capture SC2 window screenshot and OCR-extract text using Windows.Media.Ocr API.

Usage: python ocr_sc2_screen.py <hwnd>
"""
import subprocess
import sys
import os
import asyncio

HWND = int(sys.argv[1]) if len(sys.argv) > 1 else 1315932
SHOT = os.path.join(os.environ["TEMP"], "ocr_sc2_shot.png")


def capture():
    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File",
         r"c:\Users\22448\.trae-cn\skills\screenshot\scripts\take_screenshot.ps1",
         "-Mode", "temp", "-WindowHandle", str(HWND)],
        capture_output=True, text=True
    )
    # The script prints the saved path
    output = result.stdout.strip()
    # Find png path
    for line in output.split("\n"):
        line = line.strip()
        if line.endswith(".png"):
            return line
    return None


async def ocr_image(path):
    from Windows.Graphics.Imaging import BitmapDecoder, SoftwareBitmap
    from Windows.Media.Ocr import OcrEngine
    from Windows.Storage import StorageFile, FileAccessMode
    from winrt.windows.storage.streams import InMemoryRandomAccessStream

    # Use synchronous StorageFile API via async
    file_op = StorageFile.get_file_from_path_async(path)
    file = await file_op

    stream_op = file.open_async(FileAccessMode.READ)
    stream = await stream_op

    decoder_op = await BitmapDecoder.create_async(stream)
    bitmap_op = await decoder_op.get_software_bitmap_async()

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        # Fall back to first available language
        langs = OcrEngine.available_recognizer_languages
        if len(langs) > 0:
            engine = OcrEngine.create_async(langs[0])
    if engine is None:
        print("No OCR engine available")
        return

    result = await engine.recognize_async(bitmap_op)
    text = result.text
    print(text)


def ocr_image_sync(path):
    """Synchronous wrapper using asyncio."""
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
        asyncio.run(ocr_image(path))
    except Exception as e:
        print(f"OCR failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    shot = capture()
    if shot:
        print(f"Screenshot: {shot}")
        ocr_image_sync(shot)
    else:
        print("Capture failed")
        sys.exit(1)
