---
name: generate_image
description: Single image from a text prompt — the simplest image skill. Use for one-off visuals. For a series of style-consistent scenes use replicate_generate_images; for LoRA/Flux/SDXL control use liblib_generate_image.
timeout: 120
parameters:
  type: object
  properties:
    prompt:
      type: string
      description: Detailed description of the image to generate.
    size:
      type: string
      enum: ["1024x1024", "1024x1792", "1792x1024"]
      default: "1024x1024"
    provider:
      type: string
      enum: [openai, openrouter]
      default: openai
  required: [prompt]
---

Returns a JSON content block: {"type": "image", "url": "...", "alt": "..."}.
