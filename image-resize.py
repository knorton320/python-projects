from PIL import Image

def resize_png(input_path, output_path, max_width, max_height):
    # Open the image
    img = Image.open(input_path)
    
    # Calculate aspect ratio
    img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    
    # Save the resized image
    img.save(output_path, "PNG")

# Example usage:
resize_png("input.png", "output.png", 800, 800)
