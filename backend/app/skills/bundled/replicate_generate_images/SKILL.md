---
name: replicate_generate_images
description: "Multiple style-consistent images sharing one character/aesthetic — use for storyboards, story scenes, comic panels. Format the prompt as '<shared style + character>. Scene 1: ...\\nScene 2: ...'. For one-off images use generate_image."
timeout: 300
parameters:
  type: object
  properties:
    prompt:
      type: string
      description: "Single combined prompt. Recommended shape: '<style + character description>. Maintain consistent character design, art style, and color palette across all images.\\nScene 1: ...\\nScene 2: ...\\n...'"
    max_images:
      type: integer
      default: 4
    aspect_ratio:
      type: string
      default: "2:3"
    size:
      type: string
      default: "2K"
    output_format:
      type: string
      default: png
    sequential_image_generation:
      type: string
      default: auto
    model:
      type: string
      default: "bytedance/seedream-5-lite"
    vault_project:
      type: string
      default: bedtime-stories
    filename_prefix:
      type: string
      default: ""
  required: [prompt]
---

Saves images to `<vault>/<vault_project>/assets/<prefix>-scene-N.<ext>`.
