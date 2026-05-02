---
name: liblib_generate_image
description: Image generation with LoRA support (Flux / SDXL via LibLibAI). Use only when you need a specific LoRA style or fine model control; for plain image generation prefer generate_image (simpler, faster).
timeout: 240
parameters:
  type: object
  properties:
    prompt:
      type: string
      description: Positive prompt. Detailed visual description.
    negative_prompt:
      type: string
      default: ""
    checkpoint_id:
      type: string
      description: LibLib model version UUID.
    lora_ids:
      type: string
      default: ""
      description: "Comma-separated LoRA UUIDs. Use uuid:weight to set weight (default 0.8)."
    width:
      type: integer
      default: 1024
    height:
      type: integer
      default: 1024
    steps:
      type: integer
      default: 20
    cfg_scale:
      type: number
      default: 3.5
    seed:
      type: integer
      default: -1
    template_uuid:
      type: string
      default: ""
    submit_path:
      type: string
      default: ""
    extra_params_json:
      type: string
      default: ""
    vault_project:
      type: string
      default: bedtime-stories
    filename:
      type: string
      default: ""
  required: [prompt, checkpoint_id]
---

Submit-and-poll workflow. Saves the image to `<vault>/<vault_project>/assets/`.
