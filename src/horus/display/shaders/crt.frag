#version 330 core

uniform sampler2D screen_texture;
uniform vec2 resolution;

in vec2 uv;
out vec4 frag_color;

void main() {
    // barrel distortion: warp outward from center to mimic a curved CRT tube
    vec2 centered = uv * 2.0 - 1.0;
    float distortion = 0.035;
    vec2 warped = centered * (1.0 + distortion * dot(centered, centered));
    vec2 warped_uv = warped * 0.5 + 0.5;

    if (warped_uv.x < 0.0 || warped_uv.x > 1.0 || warped_uv.y < 0.0 || warped_uv.y > 1.0) {
        frag_color = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    vec4 color = texture(screen_texture, warped_uv);

    // scanlines: darken alternating rows at native screen resolution
    float scanline = sin(warped_uv.y * resolution.y * 3.14159265) * 0.5 + 0.5;
    color.rgb *= mix(0.75, 1.0, scanline);

    // vignette: darken toward the corners for a rounded-glass look
    float vignette = 1.0 - dot(centered, centered) * 0.35;
    color.rgb *= clamp(vignette, 0.0, 1.0);

    frag_color = color;
}
