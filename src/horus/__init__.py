from horus.display.window import DisplayWindow

char_size = 3

#Terminus (TTF) 500.ttf       Px437_IBM_VGA_8x16.ttf


def main() -> None:
    window = DisplayWindow(font_path = "Px437_IBM_VGA_8x16.ttf", height=1080, title="Horus OS", char_width=8*char_size, char_height=16*char_size, margin=8)
    for row in range(window.buffer.rows):
        window.buffer.write_string(0, row,"Hello WorldHello WorldHello WorldHello WorldHello WorldHello WorldHello WorldHello WorldHello World")
    window.run()
