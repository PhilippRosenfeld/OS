#version 330 core

uniform sampler2D screen_texture;
uniform vec2 resolution;
uniform float char_height;  // on-screen character height in pixels -- lets
                             // the scanlines below scale with the window/
                             // zoom level instead of staying a fixed pixel
                             // width that would look thinner (relative to
                             // the text) the bigger the window gets

in vec2 uv;
out vec4 frag_color;

void main() {
    // barrel distortion: warp outward from center to mimic a curved CRT tube
    vec2 centered = uv * 2.0 - 1.0;
    float distortion = 0.04;
    vec2 warped = centered * (1.0 + distortion * dot(centered, centered));
    vec2 warped_uv = warped * 0.5 + 0.5;

    if (warped_uv.x < 0.0 || warped_uv.x > 1.0 || warped_uv.y < 0.0 || warped_uv.y > 1.0) {
        frag_color = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    vec4 color = texture(screen_texture, warped_uv);

    // scanlines: darken alternating bands, SCANLINE_WIDTH pixels each --
    // divides the per-pixel frequency down so every band spans that many
    // pixels instead of just one.
    const float SCANLINES_PER_CHAR = 16.0;  // number of scanlines per character height
    float SCANLINE_WIDTH = char_height / SCANLINES_PER_CHAR;
    float scanline = sin(warped_uv.y * resolution.y * 3.14159265 / SCANLINE_WIDTH) * 1.5 + 0.5;
    color.rgb *= mix(0.85, 1.0, scanline);

    // vignette: darken toward the corners for a rounded-glass look
    float vignette = 1.0 - dot(centered, centered) * 0.2;
    color.rgb *= clamp(vignette, 0.0, 1.0);

    frag_color = color;
}
