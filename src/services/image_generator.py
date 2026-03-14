import os
import logging
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

class ImageGenerator:
    def __init__(self, font_path: str = "src/assets/fonts/font.ttf"):
        self.font_path = font_path
        self.width = 1080
        self.height = 1080
        self.bg_color = (15, 15, 15)  # Dark Netflix-style bg
        self.accent_color = (229, 9, 20)  # Netflix Red

    def create_quote_card(self, text: str, author: str, output_path: str = "src/assets/temp_quote.png") -> str:
        """
        Generates a 1080x1080 quote card with gradients and styling.
        """
        # Create base image
        img = Image.new('RGB', (self.width, self.height), color=self.bg_color)
        draw = ImageDraw.Draw(img)

        # Add subtle gradient or background decoration
        for i in range(self.height):
            # Very subtle vertical gradient
            r = max(10, 15 - int(i / 100))
            draw.line([(0, i), (self.width, i)], fill=(r, 15, 15))

        # Accent line at the top
        draw.rectangle([0, 0, self.width, 10], fill=self.accent_color)

        # Load fonts
        try:
            quote_font = ImageFont.truetype(self.font_path, 60)
            author_font = ImageFont.truetype(self.font_path, 40)
            logo_font = ImageFont.truetype(self.font_path, 30)
        except OSError:
            logger.warning(f"Font not found at {self.font_path}. Using default font.")
            quote_font = ImageFont.load_default()
            author_font = ImageFont.load_default()
            logo_font = ImageFont.load_default()

        # Wrap text
        wrapped_text = self._wrap_text(text, quote_font, self.width - 200)
        
        # Calculate positions
        # Center quote
        total_text_height = self._get_text_height(wrapped_text, quote_font)
        y_start = (self.height - total_text_height) // 2

        # Draw quote
        current_y = y_start
        for line in wrapped_text:
            # Get line width for centering
            bbox = draw.textbbox((0, 0), line, font=quote_font)
            line_width = bbox[2] - bbox[0]
            draw.text(((self.width - line_width) // 2, current_y), line, font=quote_font, fill=(255, 255, 255))
            current_y += (bbox[3] - bbox[1]) + 20

        # Draw author
        author_text = f"— {author}"
        bbox_author = draw.textbbox((0, 0), author_text, font=author_font)
        author_width = bbox_author[2] - bbox_author[0]
        draw.text(((self.width - author_width) // 2, current_y + 40), author_text, font=author_font, fill=self.accent_color)

        # Draw "Нетик — твій кіногід 🎬" watermark at bottom
        watermark = "Нетик — твій кіногід 🎬"
        bbox_wm = draw.textbbox((0, 0), watermark, font=logo_font)
        wm_width = bbox_wm[2] - bbox_wm[0]
        draw.text(((self.width - wm_width) // 2, self.height - 100), watermark, font=logo_font, fill=(100, 100, 100))

        # Save
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path)
        return output_path

    def _wrap_text(self, text, font, max_width):
        lines = []
        words = text.split()
        current_line = []

        for word in words:
            test_line = " ".join(current_line + [word])
            # Use textbbox instead of textsize (deprecated in Pillow 10)
            temp_img = Image.new('RGB', (1, 1))
            temp_draw = ImageDraw.Draw(temp_img)
            bbox = temp_draw.textbbox((0, 0), test_line, font=font)
            width = bbox[2] - bbox[0]
            
            if width <= max_width:
                current_line.append(word)
            else:
                lines.append(" ".join(current_line))
                current_line = [word]
        
        lines.append(" ".join(current_line))
        return lines

    def _get_text_height(self, lines, font):
        total_height = 0
        temp_img = Image.new('RGB', (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)
        for line in lines:
            bbox = temp_draw.textbbox((0, 0), line, font=font)
            total_height += (bbox[3] - bbox[1]) + 20
        return total_height - 20 # Remove last spacing

    async def blur_poster(self, poster_url: str, movie_id: int = 0) -> str:
        """
        Downloads a poster and applies a heavy blur for the "Guess the Movie" game.
        """
        import aiohttp
        import hashlib

        # Use movie_id or URL hash for unique filename to avoid race conditions
        url_hash = hashlib.md5(poster_url.encode()).hexdigest()[:8]
        output_path = f"src/assets/blurred_{movie_id or url_hash}.png"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(poster_url) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        from io import BytesIO
                        img = Image.open(BytesIO(content))

                        # Apply heavy blur
                        blurred = img.filter(ImageFilter.GaussianBlur(radius=25))

                        # Add watermark
                        draw = ImageDraw.Draw(blurred)
                        try:
                            font = ImageFont.truetype(self.font_path, 30)
                        except Exception:
                            font = ImageFont.load_default()

                        watermark = "Вгадай фільм! 🧩"
                        bbox = draw.textbbox((0, 0), watermark, font=font)
                        w, h = blurred.size
                        draw.text(((w - (bbox[2]-bbox[0]))//2, h - 50), watermark, font=font, fill=(255, 255, 255))

                        os.makedirs(os.path.dirname(output_path), exist_ok=True)
                        blurred.save(output_path)
                        return output_path
        except Exception as e:
            logger.error(f"Error blurring poster: {e}")
        return ""

image_generator = ImageGenerator()
